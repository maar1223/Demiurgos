# -*- coding: utf-8 -*-
"""Bug-report REST router — ``/api/bugreport`` (S1b assemble + S1c submit + S3b fallback).

This module ships three endpoints:

* ``GET /api/bugreport/assemble`` — build the default, sanitized report bundle:
  the app version, a fixed set of allow-listed platform facts, content-scanned
  logs (default-on), the optional-contact slot flag, and the allow-list itself.
* ``POST /api/bugreport/submit`` — re-validate the raw payload against the same
  allow-list, enforce the size caps and the per-principal rate limit, then
  deliver the bundle through a separately-deployable relay. The submit is
  STATELESS: nothing about the report, a copy or a derived record is persisted.
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

import content_scan
from error_codes import problem

#: The only fields a report bundle may ever carry (default-DENY).
ALLOWED_FIELDS = frozenset(
    {"app_version", "platform", "description", "contact", "logs"}
)

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

#: Stable ordering for the assembled platform facts.
_PLATFORM_FACT_ORDER: Tuple[str, ...] = ("os", "os_version", "arch", "python_version")

# --- Submit caps (report-submission) --------------------------------------
#: Per-field character caps and the total serialized-byte cap.
_DESCRIPTION_MAX_CHARS = 4000
_CONTACT_MAX_CHARS = 200
_LOGS_MAX_CHARS = 65536
_PAYLOAD_MAX_BYTES = 98304

#: Per-principal rate limit: at most ``_RATE_LIMIT_MAX`` submits per window.
_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW_SECONDS = 600.0

#: Vendor-neutral relay contract version.
_RELAY_SCHEMA = 1

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


def _default_relay_post(url: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """Production relay invocation: ``POST`` the bundle to ``url`` via httpx.

    Returns ``(status_code, json_body)``; a body that is not a JSON object is
    reported as ``{}``. The provider credential/owner inbox live ONLY in the
    relay, never here.
    """
    import httpx  # local import keeps the module import surface light

    resp = httpx.post(url, json=payload, timeout=_RELAY_TIMEOUT_SECONDS)
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
    relay_post: Callable[[str, dict], Tuple[int, dict]] | None = None,
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
        }

    def _deliver(bundle: Dict[str, Any]) -> Dict[str, Any]:
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
        }
        sender = relay_post if relay_post is not None else _default_relay_post
        try:
            status, data = sender(relay_url, payload)
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
        lines = [
            "## Descripción",
            bundle["description"] or "_(sin descripción)_",
            "",
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
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - unparsable body is not allow-listed
            raise problem("bugreport.not_allowlisted")
        bundle = _validate_and_cap(body)
        return _deliver(bundle)

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
