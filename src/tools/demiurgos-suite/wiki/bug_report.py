# -*- coding: utf-8 -*-
"""Bug-report REST router — ``/api/bugreport`` (Slice S1b: assemble).

This slice ships a SINGLE read-only endpoint:

* ``GET /api/bugreport/assemble`` — build the default, sanitized report bundle:
  the app version, a fixed set of allow-listed platform facts, content-scanned
  logs (default-on), the optional-contact slot flag, and the allow-list itself.

Default-DENY posture
--------------------
The bundle carries ONLY fields on :data:`ALLOWED_FIELDS`; platform facts are
restricted to :data:`ALLOWED_PLATFORM_KEYS`. World data (the world-data root),
``.env`` and the local account username are excluded **by construction**: the
handler opens nothing but ``install_root/logs`` — there is no post-hoc
filtering to bypass. Logs are scanned with
:func:`content_scan.redact_secrets` before they can be previewed, so a matching
secret line is replaced by ``[redacted: <rule>]`` and the raw value never
reaches the bundle.

Scope
-----
This module intentionally implements ONLY assemble. ``POST /submit`` (caps +
rate limit + relay) and ``POST /fallback`` land in later slices. The
``relay_url`` / ``relay_post`` / ``issue_url`` / ``clock`` parameters are
accepted now so the factory signature is stable across the slices; they are
unused until submit/fallback are added.

Auth mirrors the sibling routers (``updater.create_update_router``,
``system_control.create_system_control_router``): the request is gated through
``require_principal`` resolved at call time; ``None`` maps to 401 (fail closed).
"""

from __future__ import annotations

import platform as _platform
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from fastapi import APIRouter, HTTPException, Request

import content_scan

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
    under ``install_root/logs`` and returns ``[(name, text), ...]``. ``relay_url``
    / ``relay_post`` / ``issue_url`` / ``clock`` are accepted for signature
    stability and used by the submit/fallback slices, not here.
    """
    router = APIRouter(prefix="/api/bugreport", tags=["bug-report"])

    def _guard(request: Request) -> None:
        if require_principal(request) is None:
            raise HTTPException(status_code=401, detail=_AUTH_REQUIRED_DETAIL)

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

    return router


__all__ = [
    "ALLOWED_FIELDS",
    "ALLOWED_PLATFORM_KEYS",
    "DEFAULT_ISSUE_URL",
    "create_bug_report_router",
]
