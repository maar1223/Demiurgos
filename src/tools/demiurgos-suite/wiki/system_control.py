"""System-control REST router — ``/api/system`` endpoints.

Exposes UI-driven platform restart/shutdown over FastAPI: ``POST
/api/system/restart`` and ``POST /api/system/shutdown``. Both dispatch the
Demiurgos launcher script DETACHED (``subprocess.Popen`` with
``start_new_session=True``) and answer 200 immediately — shutdown kills this
very uvicorn process, so the response MUST flush before the launcher's
``stop`` lands; a blocking ``subprocess.run`` would race the self-kill.

The launcher's stderr is redirected to a FILE, never ``subprocess.PIPE``. A
pipe's read end is owned by this process, and ``restart`` deliberately stops
the stack — including this API — before starting it again. With a pipe, the
launcher's first stderr write after that point raises EPIPE and SIGPIPE kills
it mid-sequence: the API is already stopped and never comes back, so the
platform is left half down. A file cannot EPIPE, and it doubles as the
launcher's diagnostic log.

Auth mirrors the sibling routers (``create_ideas_bank_router``): every route
requires a trusted local principal resolved at call time via
``require_principal``; None maps to 401. The production wiring passes
``api_server._resolve_principal``, which fails closed unless
``DEMIURGOS_AUTH_MODE=local-dev`` AND the request is loopback AND carries a
server-issued session cookie — so outside local-dev auth every route here
fails closed with 401 (S-2.1). The factory itself never trusts an
unauthenticated request regardless of which resolver is injected.

Session logout ordering (S-2.5/S-3.4) is deliberately the CLIENT's job: the
UI logs the local session out BEFORE calling this endpoint. The server never
clears the session itself, because the launcher may kill this process before
any post-dispatch cleanup could flush — the ordering must be decided before
the request leaves the browser.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

#: How long to give an instantly-failing launcher (bad path, permission
#: denied, missing Hermes) before reporting its exit code. A pragma for this
#: single-user local tool: brief enough to never feel blocking, long enough
#: to catch immediate failures. Only *immediate* exits are reported; a
#: launcher that fails later is out of reach of this request.
_PEEK_WINDOW_SECONDS = 0.5

#: stderr excerpt cap for the 500 early-failure report.
_STDERR_EXCERPT_LIMIT = 2048

#: Default launcher stderr log (see the module docstring for why it is a file
#: and not a pipe). Kept beside the launcher's own ``/tmp/demiurgos-*.log``
#: family so every stack log is found in one place.
_LAUNCHER_LOG = Path(tempfile.gettempdir()) / "demiurgos-launcher.log"

_AUTH_REQUIRED_DETAIL = "Autenticación requerida"


def _stderr_excerpt(log_path: Path | None, exit_code: int) -> str:
    """Read up to 2KB of the launcher's stderr log for an immediate failure.

    Only called after ``proc.poll()`` returned a non-None exit code, so the
    launcher has already exited and the log holds whatever it managed to write.

    ``log_path`` is ``None`` when this run could not open its log. Reading the
    path anyway would report a PREVIOUS run's stderr as this run's failure, so
    an unavailable log reports no output instead of someone else's output.
    """
    excerpt = ""
    if log_path is not None:
        try:
            raw = log_path.read_bytes()
            excerpt = raw[-_STDERR_EXCERPT_LIMIT:].decode("utf-8", errors="replace").strip()
        except OSError:  # pragma: no cover - defensive; the log may be absent
            excerpt = ""
    if excerpt:
        return f"script exited with code {exit_code}: {excerpt}"
    return f"script exited with code {exit_code} (no stderr output)"


def create_system_control_router(
    require_principal: Callable[[Request], Any],
    launcher_path: Path,
    launcher_log: Path | None = None,
    launcher_available: bool | None = None,
) -> APIRouter:
    """Build the /api/system router.

    ``require_principal`` must return a trusted principal for the request or
    None; None maps to 401 (fail closed). The production resolver is
    ``_resolve_principal``, which itself requires local-dev auth mode +
    loopback peer + session cookie; the factory never trusts an
    unauthenticated request regardless of what resolver is injected.

    ``launcher_path`` is the Demiurgos launcher script. Only the hardcoded
    actions ``restart`` (POST /restart) and ``stop`` (POST /shutdown) are ever
    dispatched — no user input reaches the shell.

    ``launcher_log`` is where the detached launcher's stderr is captured. It
    MUST NOT be a pipe (see the module docstring); the default is
    ``_LAUNCHER_LOG``.

    ``launcher_available`` is the boot-time existence verdict for
    ``launcher_path`` (S2-7). When it is False, dispatch is refused with a
    clear error instead of spawning a stale path; ``None`` keeps the legacy
    behavior (spawn, and let a spawn failure surface).
    """
    router = APIRouter(prefix="/api/system", tags=["system-control"])
    log_path = Path(launcher_log) if launcher_log is not None else _LAUNCHER_LOG

    def _guard(request: Request) -> None:
        if require_principal(request) is None:
            raise HTTPException(status_code=401, detail=_AUTH_REQUIRED_DETAIL)

    def _dispatch(api_action: str, launcher_arg: str) -> JSONResponse:
        if launcher_available is False:
            return JSONResponse(status_code=503, content={
                "action": api_action,
                "accepted": False,
                "error": f"launcher not available at {launcher_path}",
            })
        # Detached dispatch: the launcher outlives this request. The server
        # answers BEFORE the launcher stops/restarts the stack (shutdown kills
        # this very process), so subprocess.run is never an option here.
        #
        # stderr is a FILE, never a PIPE: the launcher keeps writing after this
        # process is gone, and a pipe whose reader died would kill it with
        # SIGPIPE mid-sequence (see the module docstring).
        try:
            stderr_target = open(log_path, "wb")
        except OSError:
            # Losing the early-failure excerpt must never block the operation.
            stderr_target = None

        try:
            proc = subprocess.Popen(
                [str(launcher_path), launcher_arg],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=stderr_target if stderr_target is not None else subprocess.DEVNULL,
            )
        except OSError as exc:
            # The spawn itself failed (bad path, permission denied): surface it
            # instead of returning a misleading "accepted".
            return JSONResponse(status_code=500, content={
                "action": api_action,
                "accepted": False,
                "error": f"failed to spawn launcher: {exc}",
            })
        finally:
            # The child holds its own descriptor: closing ours keeps this
            # process free of a leaked fd and never affects the launcher.
            if stderr_target is not None:
                stderr_target.close()

        # Non-blocking early-failure peek: give an instantly-failing launcher
        # (bad path, permission, missing Hermes) a brief window to exit, then
        # report its stderr/exit code. This is a bounded 0.5s wait — it never
        # waits for the operation to complete (start/restart runs for the
        # whole stack lifetime).
        time.sleep(_PEEK_WINDOW_SECONDS)
        exit_code = proc.poll()
        if exit_code is not None and exit_code != 0:
            return JSONResponse(status_code=500, content={
                "action": api_action,
                "accepted": False,
                "error": _stderr_excerpt(
                    log_path if stderr_target is not None else None, exit_code
                ),
            })
        return JSONResponse(status_code=200, content={
            "action": api_action,
            "accepted": True,
        })

    @router.post("/restart")
    def restart(request: Request) -> JSONResponse:
        """Restart the platform (launcher ``restart``) — S-2.2.

        The client MUST log the local session out before calling this endpoint
        (S-2.5/S-3.4); the server intentionally does not clear the session.
        """
        _guard(request)
        return _dispatch(api_action="restart", launcher_arg="restart")

    @router.post("/shutdown")
    def shutdown(request: Request) -> JSONResponse:
        """Shut the platform down (launcher ``stop``) — S-2.3.

        Returns 200 BEFORE the launcher kills this uvicorn process. The client
        MUST log the local session out before calling this endpoint
        (S-2.5/S-3.4); the server intentionally does not clear the session.
        """
        _guard(request)
        return _dispatch(api_action="shutdown", launcher_arg="stop")

    return router


__all__ = ["create_system_control_router"]