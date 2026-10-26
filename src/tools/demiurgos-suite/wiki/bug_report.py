# -*- coding: utf-8 -*-
"""Bug-report REST router — ``/api/bugreport`` (S1b assemble + S1c submit + S3b fallback).

This module ships four endpoints:

* ``GET /api/bugreport/assemble`` — build the default, sanitized report bundle:
  the app version, a fixed set of allow-listed platform facts, content-scanned
  logs (default-on), the optional-contact slot flag, and the allow-list itself.
* ``POST /api/bugreport/submit`` — re-validate the raw payload against the same
  allow-list, enforce the size caps and the per-principal rate limit, then
  deliver the bundle through a separately-deployable relay. Accepts JSON, or
  ``multipart/form-data`` carrying the bundle in a ``report`` part plus up to
  two screenshots as ``attachments`` file parts (delivered as documents). The submit is
  STATELESS: nothing about the report, a copy or a derived record is persisted.
* ``POST /api/bugreport/link/start|status|revoke`` — the Telegram linking
  surface. These proxy the relay's ``/link/*`` routes with the shared
  ``x-relay-key``, so the browser never talks to the relay and never sees the
  ``install_token`` that signs later reports (S7, S15).
* ``POST /api/bugreport/fallback`` — the STRICT fallback: render the reviewed
  bundle as a copy-paste GitHub issue body, privacy-scrub it with
  :func:`content_scan.scrub_all` (BOTH the shared secret rules and the
  report-specific PII rules), and return ``{body, issue_url, findings}``.
  ``issue_url`` defaults to :data:`DEFAULT_ISSUE_URL` (the
  ``maar1223/Demiurgos`` issue form), overridable at wiring time via
  ``DEMIURGOS_BUGREPORT_ISSUE_URL``.

Default-DENY posture
--------------------
The bundle carries ONLY fields on :data:`ALLOWED_FIELDS`; platform facts are
restricted to :data:`ALLOWED_PLATFORM_KEYS`. World data (the world-data root),
``.env`` and the local account username are excluded **by construction**: the
assemble handler opens nothing but ``install_root/logs`` — there is no post-hoc
filtering to bypass. Logs are scanned with
:func:`content_scan.redact_secrets` before they can be previewed, so a matching
secret line is replaced by ``[redacted: <rule>]`` and the raw value never
reaches the bundle.

Submit re-validation is a **raw-dict** check (``set(body) <= ALLOWED_FIELDS``):
a Pydantic model with default config would silently DROP unknown keys and let a
disallowed-field payload through, so the endpoint reads the raw JSON body and
rejects any key outside the allow-list with ``bugreport.not_allowlisted``.
The fallback endpoint re-validates the same way.

Privacy notes on the fallback body
----------------------------------
:func:`content_scan.scrub_all` applies BOTH rule sets to the rendered body:
the report-specific PII rules (local paths, usernames, hostnames, private
network addresses, e-mails, extra secret shapes) and the SHARED secret rules
(``bot-token``, ``openai-key``, ``google-api-key``, ``author-path`` — the same
set ``scripts/secret_scan.sh`` declares). A credential typed into the
free-text ``description`` therefore never survives into the copy-paste body.
Logs reaching the fallback were already redacted at assemble time against the
same shared set, so the body cannot re-expose what logs never carried. The one
deliberate exception is the explicitly-provided contact: it is the follow-up
datum the user chose to make public (owner decision 5) and survives the scrub.
"""

from __future__ import annotations

import json
import platform as _platform
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Tuple

from fastapi import APIRouter, HTTPException, Request

import bugreport_identity
import content_scan
from error_codes import problem
from local_state import LocalState

#: The only fields a report bundle may ever carry (default-DENY).
ALLOWED_FIELDS = frozenset(
    {"app_version", "platform", "description", "contact", "logs", "context"}
)

#: Where in the app a report came from. App-generated, bounded, secret-scanned.
CONTEXT_KEYS = frozenset({"route", "view", "ui_area", "world_id"})

#: The only platform/environment facts that may be assembled.
ALLOWED_PLATFORM_KEYS = frozenset(
    {"os", "os_version", "arch", "python_version"}
)

#: Fallback destination: the public main repo's GitHub issue form.
DEFAULT_ISSUE_URL = (
    "https://github.com/maar1223/Demiurgos/issues/new?template=bug_report.yml"
)

_AUTH_REQUIRED_DETAIL = "Autenticación requerida"

#: Logs are dropped (``included=false``) once the redacted text exceeds this cap.
_LOGS_MAX_BYTES = 65536

def _utf16_units(text: str) -> int:
    """Length in UTF-16 code units — the unit the relay (JavaScript) enforces.

    ``len()`` counts code points, so 200 emoji pass here and fail there. A cap
    that disagrees with the other side of the contract is a cap that rejects
    valid reports at the last hop.

    A lone surrogate (hand-crafted JSON, never a real route) cannot be encoded;
    it is reported as over the cap so the caller refuses it like any other
    unusable value instead of raising a 500.
    """
    try:
        return len(text.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return _CONTEXT_VALUE_MAX_CHARS + 1


#: Stable ordering for the assembled platform facts.
_PLATFORM_FACT_ORDER: Tuple[str, ...] = ("os", "os_version", "arch", "python_version")

# --- Submit caps (report-submission) --------------------------------------
#: Screenshot attachments (S5): at most two, 5 MB each, images only, and they
#: travel as multipart file parts — never inside the 98 KB JSON bundle.
_ATTACHMENTS_MAX = 2
_ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024
_ATTACHMENT_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_ATTACHMENT_NAME_MAX = 64

#: Per-field character caps and the total serialized-byte cap.
_DESCRIPTION_MAX_CHARS = 4000
_CONTACT_MAX_CHARS = 200
_LOGS_MAX_CHARS = 65536
_CONTEXT_VALUE_MAX_CHARS = 200
_PAYLOAD_MAX_BYTES = 98304

#: Per-principal rate limit: at most ``_RATE_LIMIT_MAX`` submits per window.
_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW_SECONDS = 600.0

#: Vendor-neutral relay contract version that carries ``context``.
_RELAY_SCHEMA = 2

#: The version a client without context still speaks, so a relay that predates
#: schema 2 keeps delivering instead of rejecting the whole report. A dropped
#: report is worse than a report without context.
_LEGACY_RELAY_SCHEMA = 1

#: Production relay timeout (seconds).
_RELAY_TIMEOUT_SECONDS = 10.0


def _platform_facts() -> Dict[str, str]:
    """The allow-listed platform facts, restricted to :data:`ALLOWED_PLATFORM_KEYS`."""
    raw = {
        "os": _platform.system(),
        "os_version": _platform.release(),
        "arch": _platform.machine(),
        "python_version": _platform.python_version(),
    }
    return {
        key: str(raw.get(key, "") or "")
        for key in _PLATFORM_FACT_ORDER
        if key in ALLOWED_PLATFORM_KEYS
    }


def _safe_attachment_name(raw: str | None, index: int, mime: str) -> str:
    """A filename safe to hand downstream: no paths, no control characters."""
    base = (raw or "").replace("\\", "/").split("/")[-1]
    cleaned = "".join(ch for ch in base if ord(ch) >= 32 and ord(ch) != 127).strip()
    if cleaned:
        return cleaned[:_ATTACHMENT_NAME_MAX]
    extension = "jpg" if mime == "image/jpeg" else mime.split("/")[-1] or "png"
    return "screenshot-%d.%s" % (index + 1, extension)


def _attachment_parts(
    uploads: List[Any],
) -> List[Tuple[str, bytes, str]]:
    """Validate the uploaded screenshots; return ``(name, bytes, mime)`` parts."""
    if len(uploads) > _ATTACHMENTS_MAX:
        raise problem("bugreport.too_large", field="attachments")
    parts: List[Tuple[str, bytes, str]] = []
    for index, upload in enumerate(uploads):
        mime = (getattr(upload, "content_type", "") or "").split(";")[0].strip().lower()
        if mime not in _ATTACHMENT_TYPES:
            raise problem("bugreport.invalid_attachment")
        data = upload.file.read() if hasattr(upload, "file") else b""
        if not data:
            raise problem("bugreport.invalid_attachment")
        if len(data) > _ATTACHMENT_MAX_BYTES:
            raise problem("bugreport.too_large", field="attachments")
        name = _safe_attachment_name(getattr(upload, "filename", None), index, mime)
        parts.append((name, data, mime))
    return parts


def _default_relay_post(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str] | None = None,
    attachments: List[Tuple[str, bytes, str]] | None = None,
) -> Tuple[int, Dict[str, Any]]:
    """Production relay invocation: ``POST`` the bundle to ``url`` via httpx.

    Returns ``(status_code, json_body)``; a body that is not a JSON object is
    reported as ``{}``. The provider credential/owner inbox live ONLY in the
    relay, never here. ``headers`` carries the shared relay key on the linking
    routes and the ``install_token`` that signs a report — both stay server-side.
    """
    import httpx  # local import keeps the module import surface light

    if attachments:
        resp = httpx.post(
            url,
            data={"report": json.dumps(payload, ensure_ascii=False)},
            files=[("attachments", part) for part in attachments],
            headers=headers or {},
            timeout=_RELAY_TIMEOUT_SECONDS,
        )
    else:
        resp = httpx.post(
            url, json=payload, headers=headers or {}, timeout=_RELAY_TIMEOUT_SECONDS
        )
    try:
        data = resp.json()
    except ValueError:
        data = {}
    return resp.status_code, data if isinstance(data, dict) else {}


def create_bug_report_router(
    require_principal: Callable[[Request], Any],
    *,
    app_version: Callable[[], str],
    install_root: Path | None,
    relay_url: str | None = None,
    issue_url: str = DEFAULT_ISSUE_URL,
    relay_post: Callable[[str, dict, dict, list], Tuple[int, dict]] | None = None,
    relay_key: str | None = None,
    bot_username: str | None = None,
    local_state: Callable[[], LocalState] | None = None,
    vault_active: Callable[[], bool] | None = None,
    log_source: Callable[[], List[Tuple[str, str]]] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> APIRouter:
    """Build the ``/api/bugreport`` router (Slice S1b: assemble only).

    ``require_principal`` must return a trusted principal for the request or
    ``None``; ``None`` maps to 401 (fail closed). ``app_version`` returns the
    running version (injected callable, mirroring ``updater``). ``install_root``
    is the install root when running the installed layout, else ``None`` (dev
    checkout) — it locates the ONLY log source (``install_root/logs``).

    ``log_source`` is injectable for tests; the default reads every ``*.log``
    under ``install_root/logs`` and returns ``[(name, text), ...]``.

    ``relay_url`` is the operational kill-switch for submit: unset or empty
    means delivery is unavailable and the endpoint fails closed with
    ``bugreport.relay_unavailable``. ``relay_post`` injects the relay invocation
    (tests); the production default is an ``httpx`` ``POST`` to ``relay_url``.
    ``clock`` injects the time source for the rate limit (tests). ``issue_url``
    is the fallback destination; production wiring reads
    ``DEMIURGOS_BUGREPORT_ISSUE_URL`` from the environment, defaulting to
    :data:`DEFAULT_ISSUE_URL`.
    """
    router = APIRouter(prefix="/api/bugreport", tags=["bug-report"])

    # In-memory per-principal rate-limit buckets, lazily pruned via ``clock``.
    # Ephemeral operational state, never persisted — a restart resets it, which
    # is acceptable for the Alpha bound (relay applies a durable limit too).
    _rate: Dict[str, Deque[float]] = {}

    def _guard(request: Request) -> Any:
        principal = require_principal(request)
        if principal is None:
            raise HTTPException(status_code=401, detail=_AUTH_REQUIRED_DETAIL)
        return principal

    def _check_rate_limit(principal_id: str) -> None:
        """Record one attempt for ``principal_id``; reject beyond the window cap.

        Entries older than :data:`_RATE_LIMIT_WINDOW_SECONDS` are dropped on the
        next access (lazy pruning). At most :data:`_RATE_LIMIT_MAX` attempts per
        window per principal.
        """
        now = clock()
        bucket = _rate.get(principal_id)
        if bucket is None:
            bucket = deque()
            _rate[principal_id] = bucket
        while bucket and (now - bucket[0]) > _RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT_MAX:
            raise problem("bugreport.rate_limited")
        bucket.append(now)

    def _validate_and_cap(body: Any) -> Dict[str, Any]:
        """Raw-dict re-validation against the allow-list, then the size caps.

        Returns the normalized bundle. ``body`` must be a JSON object whose keys
        are a subset of :data:`ALLOWED_FIELDS` and whose ``platform`` (when
        present) is a JSON object with keys within
        :data:`ALLOWED_PLATFORM_KEYS`; anything else maps to
        ``bugreport.not_allowlisted``. Per-field and total caps map to
        ``bugreport.too_large``.
        """
        if not isinstance(body, dict):
            raise problem("bugreport.not_allowlisted")
        if not set(body).issubset(ALLOWED_FIELDS):
            raise problem("bugreport.not_allowlisted")
        platform = body.get("platform", {})
        if platform is None:
            platform = {}
        if not isinstance(platform, dict) or not set(platform).issubset(
            ALLOWED_PLATFORM_KEYS
        ):
            raise problem("bugreport.not_allowlisted")

        context_raw = body.get("context", {})
        if context_raw is None:
            context_raw = {}
        if not isinstance(context_raw, dict) or not set(context_raw).issubset(CONTEXT_KEYS):
            raise problem("bugreport.not_allowlisted")
        context: Dict[str, str] = {}
        for key, value in context_raw.items():
            if not isinstance(value, str):
                raise problem("bugreport.not_allowlisted")
            if _utf16_units(value) > _CONTEXT_VALUE_MAX_CHARS:
                raise problem("bugreport.too_large", field="context")
            # App-generated, but a pasted credential must still not survive.
            redacted, _hits = content_scan.redact_secrets(value)
            if redacted.strip():
                context[key] = redacted

        description = body.get("description", "") or ""
        contact = body.get("contact")
        logs = body.get("logs")
        if not isinstance(description, str) or (
            contact is not None and not isinstance(contact, str)
        ) or (logs is not None and not isinstance(logs, str)):
            raise problem("bugreport.not_allowlisted")
        if len(description) > _DESCRIPTION_MAX_CHARS:
            raise problem("bugreport.too_large", field="description")
        if contact is not None and len(contact) > _CONTACT_MAX_CHARS:
            raise problem("bugreport.too_large", field="contact")
        if logs is not None and len(logs) > _LOGS_MAX_CHARS:
            raise problem("bugreport.too_large", field="logs")
        try:
            serialized = json.dumps(body, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            raise problem("bugreport.not_allowlisted")
        if len(serialized) > _PAYLOAD_MAX_BYTES:
            raise problem("bugreport.too_large", field="total")
        return {
            "app_version": str(body.get("app_version", "") or ""),
            "platform": {key: str(value) for key, value in platform.items()},
            "description": description,
            "contact": contact or None,
            "logs": logs or None,
            "context": context,
        }

    def _local() -> LocalState:
        if local_state is None:
            raise problem("bugreport.storage_unavailable")
        return local_state()

    def _current_install_token() -> str | None:
        if local_state is None:
            return None
        try:
            return bugreport_identity.read_install_token(local_state())
        except Exception:  # noqa: BLE001 - an unreadable slot signs nothing
            return None

    def _store_install_token(token: str) -> None:
        try:
            bugreport_identity.store_install_token(_local(), token)
        except Exception:  # noqa: BLE001 - never a 500 with a credential in it
            raise problem("bugreport.storage_unavailable")

    def _clear_install_token() -> None:
        try:
            bugreport_identity.clear_install_token(_local())
        except Exception:  # noqa: BLE001
            raise problem("bugreport.storage_unavailable")

    def _stable_account_key() -> str:
        try:
            vault_on = bool(vault_active()) if vault_active is not None else False
            return bugreport_identity.account_key(_local(), vault_on)
        except Exception:  # noqa: BLE001
            raise problem("bugreport.storage_unavailable")

    def _relay_sender() -> Callable[[str, dict, dict], Tuple[int, dict]]:
        return relay_post if relay_post is not None else _default_relay_post

    def _link_call(path: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Call one relay identity route with the shared key."""
        if not relay_url or not relay_key:
            raise problem("bugreport.relay_unavailable")
        try:
            status, data = _relay_sender()(
                relay_url.rstrip("/") + path, payload, {"x-relay-key": relay_key}, []
            )
        except Exception:  # noqa: BLE001 - network/config failure fails closed
            raise problem("bugreport.relay_unavailable")
        return int(status), data if isinstance(data, dict) else {}

    def _raise_link_failure(status: int, data: Dict[str, Any]) -> None:
        """Map a relay identity failure onto a stable backend code."""
        if status == 429:
            raise problem("bugreport.rate_limited")
        if status in (401, 403):
            raise problem("bugreport.relay_unavailable")
        raise problem("bugreport.delivery_failed")

    def _deliver(
        bundle: Dict[str, Any],
        attachments: List[Tuple[str, bytes, str]] | None = None,
    ) -> Dict[str, Any]:
        """Forward the validated bundle to the relay; fail closed on any failure.

        The contract is vendor-neutral: ``{schema, app_version, platform,
        description, contact, logs}``. A success maps to ``{ok: True,
        delivery_id}``; an unreachable/misconfigured relay maps to
        ``bugreport.relay_unavailable``; a relay-reported failure maps to
        ``bugreport.delivery_failed``. No credential or traceback is ever
        included in a response.
        """
        if not relay_url:
            raise problem("bugreport.relay_unavailable")
        payload = {
            "schema": _RELAY_SCHEMA,
            "app_version": bundle["app_version"],
            "platform": bundle["platform"],
            "description": bundle["description"],
            "contact": bundle["contact"],
            "logs": bundle["logs"],
            "context": bundle["context"],
        }
        if not bundle["context"]:
            # A relay that predates schema 2 rejects the unknown key, so a
            # contextless client keeps speaking the older contract until the
            # relay is rolled out. A dropped report is worse than no context.
            payload["schema"] = _LEGACY_RELAY_SCHEMA
            payload.pop("context")
        headers: Dict[str, str] = {}
        token = _current_install_token()
        if token:
            headers["x-install-token"] = token
        try:
            status, data = _relay_sender()(relay_url, payload, headers, attachments or [])
        except Exception:  # noqa: BLE001 - network/config failure fails closed
            raise problem("bugreport.relay_unavailable")
        if not isinstance(data, dict):
            data = {}
        if 200 <= int(status) < 300 and data.get("ok") is True:
            return {"ok": True, "delivery_id": str(data.get("delivery_id") or "")}
        raise problem("bugreport.delivery_failed")

    def _render_fallback_body(bundle: Dict[str, Any]) -> str:
        """Render the reviewed bundle as a copy-paste GitHub issue body.

        Neutral-Spanish section labels mirror the profile panel copy
        (``profile.bugreport.*`` in ``frontend/src/i18n/messages.ts``). The
        explicitly-provided contact is deliberately NOT part of this prefix:
        it is appended verbatim by the fallback handler after the privacy scrub
        (the contact is the follow-up datum the user chose to make public).
        """
        platform = bundle["platform"]
        context = bundle.get("context") or {}
        where = (
            ["## Dónde", *[f"- **{key}:** {value}" for key, value in context.items()], ""]
            if context
            else []
        )
        lines = [
            "## Descripción",
            bundle["description"] or "_(sin descripción)_",
            "",
            *where,
            "## Información del sistema",
            "- **Versión de la aplicación:** %s" % bundle["app_version"],
            "- **Sistema operativo:** %s" % platform.get("os", ""),
            "- **Versión del sistema:** %s" % platform.get("os_version", ""),
            "- **Arquitectura:** %s" % platform.get("arch", ""),
            "- **Versión de Python:** %s" % platform.get("python_version", ""),
            "",
            "## Registros",
            bundle["logs"] or "_(sin registros)_",
        ]
        return "\n".join(lines)

    def _default_log_source() -> List[Tuple[str, str]]:
        """Read every ``*.log`` under ``install_root/logs`` — the ONLY source.

        Never touches the world-data root, ``.env`` or any user identity file.
        A missing install root or log directory yields no logs.
        """
        if install_root is None:
            return []
        logs_dir = Path(install_root) / "logs"
        if not logs_dir.is_dir():
            return []
        pairs: List[Tuple[str, str]] = []
        for path in sorted(logs_dir.glob("*.log")):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            pairs.append((path.name, text))
        return pairs

    def _assemble_logs() -> Dict[str, Any]:
        """Redact-and-count logs, dropping them with a non-secret reason.

        Logs are default-on. Each source line is scanned; a matching line is
        replaced by ``[redacted: <rule>]`` (the raw value is never read). If the
        source is unavailable or the redacted text exceeds the cap, logs are
        dropped and ``included`` is ``False`` with a non-secret ``reason``.
        """
        source = log_source if log_source is not None else _default_log_source
        try:
            pairs = source()
        except Exception:  # noqa: BLE001 - a bad source drops logs, never 500s
            return {
                "included": False,
                "content": "",
                "redacted_lines": 0,
                "reason": "log source unavailable",
            }
        if not pairs:
            return {
                "included": False,
                "content": "",
                "redacted_lines": 0,
                "reason": "no logs available",
            }
        redacted_total = 0
        chunks: List[str] = []
        for _name, text in pairs:
            redacted_text, hits = content_scan.redact_secrets(text or "")
            redacted_total += hits
            chunks.append(redacted_text)
        content = "\n".join(chunks)
        if len(content.encode("utf-8")) > _LOGS_MAX_BYTES:
            return {
                "included": False,
                "content": "",
                "redacted_lines": redacted_total,
                "reason": "logs exceed the size cap",
            }
        return {
            "included": True,
            "content": content,
            "redacted_lines": redacted_total,
            "reason": "",
        }

    @router.get("/assemble")
    def assemble(request: Request) -> Dict[str, Any]:
        """Assemble the default, allow-listed, content-scanned report bundle.

        Returns exactly :data:`ALLOWED_FIELDS`-bounded content. World data,
        ``.env`` and the account username are absent by construction.
        """
        _guard(request)
        return {
            "app_version": app_version(),
            "platform": _platform_facts(),
            "logs": _assemble_logs(),
            "allow_list": sorted(ALLOWED_FIELDS),
            "contact_slot": True,
        }

    @router.post("/submit")
    async def submit(request: Request) -> Dict[str, Any]:
        """Re-validate, rate-limit and relay-deliver a report bundle.

        Stateless: no report, copy or derived record is persisted. Order:
        principal gate (401) -> per-principal rate limit (429) -> raw allow-list
        re-validation and caps (400/413) -> relay delivery (502 on failure).
        """
        principal = _guard(request)
        principal_id = str(getattr(principal, "id", None) or id(principal))
        _check_rate_limit(principal_id)
        content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        attachments: List[Tuple[str, bytes, str]] = []
        if content_type == "multipart/form-data":
            # The JSON bundle travels in the `report` part; binaries never enter
            # the bundle, so the 98 KB contract and the preview gate both hold.
            try:
                form = await request.form()
            except Exception:  # noqa: BLE001
                raise problem("bugreport.not_allowlisted")
            report_raw = form.get("report")
            if not isinstance(report_raw, str):
                raise problem("bugreport.not_allowlisted")
            try:
                body = json.loads(report_raw)
            except Exception:  # noqa: BLE001
                raise problem("bugreport.not_allowlisted")
            uploads = [value for key, value in form.multi_items() if key == "attachments"]
            attachments = _attachment_parts(uploads)
        else:
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001 - unparsable body is not allow-listed
                raise problem("bugreport.not_allowlisted")
        bundle = _validate_and_cap(body)
        return _deliver(bundle, attachments)

    def _link_body_status() -> None:
        raise problem("bugreport.not_allowlisted")

    @router.post("/link/start")
    async def link_start(request: Request) -> Dict[str, Any]:
        """Mint (or reuse) the linking ticket for this install's stable key.

        The browser never talks to the relay and never sees the account key: the
        key is resolved server-side. The two permission flags are forwarded only
        when the client states them as booleans, so an omitted flag stays
        unstated instead of being coerced into ``true``.
        """
        _guard(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - an empty body is a valid request
            body = {}
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise problem("bugreport.not_allowlisted")
        flags: Dict[str, bool] = {}
        for flag in ("report_identity", "notify_releases"):
            value = body.get(flag)
            if isinstance(value, bool):
                flags[flag] = value
            elif value is not None:
                raise problem("bugreport.not_allowlisted")

        account = _stable_account_key()
        status, data = _link_call("/link/start", {"account_key": account, **flags})
        if not (200 <= status < 300) or data.get("ok") is not True:
            _raise_link_failure(status, data)
        ticket = data.get("ticket")
        if not isinstance(ticket, str) or not ticket:
            raise problem("bugreport.delivery_failed")
        telegram_url = (
            "https://t.me/%s?start=%s" % (bot_username, ticket)
            if bot_username
            else None
        )
        return {
            "ticket": ticket,
            "expires_at": data.get("expires_at"),
            "reused": data.get("reused") is True,
            "telegram_url": telegram_url,
        }

    @router.post("/link/status")
    async def link_status(request: Request) -> Dict[str, Any]:
        """Poll the ticket; on completion, keep the token server-side.

        The ``install_token`` the relay hands over exactly once is persisted and
        NEVER returned to the browser: it signs later reports and nothing else
        needs it (S15).
        """
        _guard(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            _link_body_status()
        if not isinstance(body, dict):
            _link_body_status()
        ticket = body.get("ticket")
        if not isinstance(ticket, str) or not ticket:
            _link_body_status()

        status, data = _link_call("/link/status", {"ticket": ticket})
        if not (200 <= status < 300) or data.get("ok") is not True:
            _raise_link_failure(status, data)

        state = data.get("state")
        if state == "pending":
            return {"state": "pending", "expires_at": data.get("expires_at")}
        if state == "expired":
            return {"state": "expired"}
        if state != "linked":
            raise problem("bugreport.delivery_failed")

        token = data.get("install_token")
        if isinstance(token, str) and token:
            _store_install_token(token)
        elif _current_install_token() is None:
            # The relay hands the token exactly once. If it is gone — a failed
            # store, a wiped state file, another poll that won the race — the
            # link cannot sign reports, so "connected" would be a lie.
            raise problem("bugreport.link_incomplete")
        identity = data.get("identity")
        identity = identity if isinstance(identity, dict) else {}
        permissions = identity.get("permissions")
        permissions = permissions if isinstance(permissions, dict) else {}
        return {
            "state": "linked",
            "username": identity.get("username"),
            "display_name": identity.get("display_name"),
            "permissions": {
                "report_identity": permissions.get("report_identity") is True,
                "notify_releases": permissions.get("notify_releases") is True,
            },
        }

    @router.post("/link/revoke")
    async def link_revoke(request: Request) -> Dict[str, Any]:
        """Unlink this install: the relay drops the binding and blocks the token."""
        _guard(request)
        account = _stable_account_key()
        status, data = _link_call("/link/revoke", {"account_key": account})
        if not (200 <= status < 300) or data.get("ok") is not True:
            _raise_link_failure(status, data)
        _clear_install_token()
        return {"revoked": data.get("revoked") is True}

    @router.post("/fallback")
    async def fallback(request: Request) -> Dict[str, Any]:
        """Return the STRICT fallback: a copy-paste issue body and the form link.

        The endpoint takes the same reviewed-bundle shape as submit
        (``require_principal`` gate + raw allow-list re-validation, so the body
        is always built from a bundle the user reviewed). The body is rendered
        from the bundle and privacy-scrubbed with
        :func:`content_scan.scrub_all` — the report-specific PII rules
        (paths/usernames/hostnames/private IPs/e-mails/extra secrets become
        placeholders) AND the shared secret rules (bot-token/openai-key/
        google-api-key/author-path), structure preserved — then returned
        together with ``issue_url`` — :data:`DEFAULT_ISSUE_URL` unless
        overridden at wiring time — and the ``findings`` count. The
        explicitly-provided contact survives the scrub as the deliberate
        follow-up datum. Nothing is delivered and nothing is persisted.
        """
        _guard(request)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - unparsable body is not allow-listed
            raise problem("bugreport.not_allowlisted")
        bundle = _validate_and_cap(body)
        scrubbed, findings = content_scan.scrub_all(_render_fallback_body(bundle))
        contact = bundle["contact"]
        if contact:
            scrubbed = "%s\n\n## Contacto\n%s" % (scrubbed, contact)
        else:
            scrubbed = "%s\n\n## Contacto\n_(no proporcionado)_" % scrubbed
        return {"body": scrubbed, "issue_url": issue_url, "findings": findings}

    return router


__all__ = [
    "ALLOWED_FIELDS",
    "ALLOWED_PLATFORM_KEYS",
    "DEFAULT_ISSUE_URL",
    "create_bug_report_router",
]
