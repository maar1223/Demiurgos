"""In-app update-check REST router — ``/api/update`` endpoints (Slice 2b).

Exposes two principal-gated, read-mostly endpoints for the in-app updater:

- ``GET /api/update/status`` — the running version, the selected channel
  (Estable/Beta), the resolved channel base URL, and the ADVISORY latest
  version offered on that channel. The advisory value comes from the channel
  pointer (``latest`` for Estable, ``latest-beta`` for Beta), never from
  ``version.json``: the pointer is inherently channel-correct (the release
  gate in ``release.yml`` moves ``latest`` only for stable tags and
  ``latest-beta`` only for prereleases), and ``version.json`` is unsigned.
  Everything here is display-only — the installer core remains the single
  authority that verifies the signed manifest before any install (Slice 3).
- ``PUT /api/update/channel`` — persist the channel preference under
  ``capabilities.update.channel`` in the runtime-authoritative
  ``local-state.json`` via ``LocalState.atomic_commit``, so the choice
  survives version flips and restarts (spec 'Channel type persists across
  restarts').
- ``POST /api/update/apply`` — dispatch the installer DETACHED for the
  server-resolved offered version (the client never supplies a version), with
  the channel base URL and target version passed via environment. The dispatch
  mirrors ``system_control``'s detached pattern: ``start_new_session=True``,
  stdout ``DEVNULL``, stderr a FILE (never a PIPE, so the installer can never
  EPIPE/SIGPIPE on a dead reader after this process is gone), and a 0.5s
  early-failure peek that surfaces an immediate install crash as a 500.
  ``version.json`` is never read on this path — the installer core re-verifies
  the signed manifest (signature BEFORE checksums) and aborts on any failure,
  so an unsigned advisory can never authorize an install (Slice 3).

Auth mirrors the sibling routers (``system_control.create_system_control_router``):
every route requires a trusted local principal resolved at call time via
``require_principal``; None maps to 401 (fail closed). The production wiring
passes ``api_server._resolve_principal``, which itself requires local-dev auth
mode + loopback peer + session cookie, so outside local-dev auth every route
here fails closed with 401. The factory never trusts an unauthenticated
request regardless of which resolver is injected.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from local_state import LocalState
import semver

#: Public release-channel default. Mirrors the installer's channel base and is
#: only a LAST RESORT: the installer-written ``channel.json`` (validated
#: https/file at install time) wins on any real install, with the
#: ``DEMIURGOS_CHANNEL_URL`` env as the operator override.
DEFAULT_CHANNEL_URL = "https://github.com/maar1223/demiurgos-releases"

#: The only channel types the updater understands (spec 'Channel selection').
VALID_CHANNELS = ("Estable", "Beta")

#: URL schemes the advisory fetcher accepts; mirrors the installer scheme gate
#: (https:// and file:// only) so a hostile channel URL can never redirect the
#: runtime into an unexpected protocol.
_ALLOWED_SCHEMES = ("https", "file")

#: ``channel.json`` schema this runtime understands (installer writes 1).
_CHANNEL_CONFIG_SCHEMA = 1

_AUTH_REQUIRED_DETAIL = "Autenticación requerida"

#: Default advisory fetch timeout; brief enough that a dead channel never
#: blocks the status route for long (spec 'Channel fetch failure degrades
#: gracefully').
_FETCH_TIMEOUT_SECONDS = 3

#: How long to give an instantly-failing installer (bad path, permission
#: denied) before reporting its exit code. Mirrors ``system_control``'s
#: ``_PEEK_WINDOW_SECONDS``: brief enough to never feel blocking, long enough
#: to catch immediate failures. Only *immediate* exits are reported; an
#: installer that fails later is out of reach of this request.
_PEEK_WINDOW_SECONDS = 0.5

#: stderr excerpt cap for the 500 early-failure report (mirrors
#: ``system_control``).
_STDERR_EXCERPT_LIMIT = 2048

#: Default installer stderr log (see the module docstring for why it is a file
#: and not a pipe). Kept beside ``system_control``'s ``/tmp/demiurgos-*.log``
#: family so every stack log is found in one place.
_INSTALLER_LOG = Path(tempfile.gettempdir()) / "demiurgos-installer.log"


def _stderr_excerpt(log_path: Path | None, exit_code: int) -> str:
    """Read up to 2KB of the installer's stderr log for an immediate failure.

    Only called after ``proc.poll()`` returned a non-None exit code, so the
    installer has already exited and the log holds whatever it managed to
    write. ``log_path`` is ``None`` when this run could not open its log;
    reading the path anyway would report a PREVIOUS run's stderr as this run's
    failure (mirrors ``system_control._stderr_excerpt``).
    """
    excerpt = ""
    if log_path is not None:
        try:
            raw = log_path.read_bytes()
            excerpt = raw[-_STDERR_EXCERPT_LIMIT:].decode(
                "utf-8", errors="replace"
            ).strip()
        except OSError:  # pragma: no cover - defensive; the log may be absent
            excerpt = ""
    if excerpt:
        return f"script exited with code {exit_code}: {excerpt}"
    return f"script exited with code {exit_code} (no stderr output)"


def _resolve_url_base(cfg_path: Path | None, env: Mapping[str, str]) -> str:
    """Resolve the channel base URL: ``channel.json`` -> env -> public default.

    The installer persists ``<install_root>/channel.json``
    (``{"schema_version": 1, "url_base": "<validated URL>"}``) at install time.
    The ``DEMIURGOS_CHANNEL_URL`` env override applies when no valid
    ``channel.json`` exists; otherwise the hardcoded public default applies.
    Absence of ``channel.json`` never causes a failure — it falls through the
    chain (spec 'Hardcoded default applies when nothing is set').
    """
    if cfg_path is not None:
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if (
            isinstance(data, dict)
            and data.get("schema_version") == _CHANNEL_CONFIG_SCHEMA
        ):
            url = data.get("url_base")
            if isinstance(url, str) and url.strip():
                return url.strip()
    override = env.get("DEMIURGOS_CHANNEL_URL", "").strip()
    if override:
        return override
    return DEFAULT_CHANNEL_URL


def _pointer_for(channel: str) -> str:
    """The release-asset pointer name for a channel (slice 0 gate contract).

    ``Estable`` reads the stable-only ``latest`` pointer; ``Beta`` reads the
    prerelease ``latest-beta`` pointer.
    """
    return "latest-beta" if channel == "Beta" else "latest"


def _read_channel(local_state: LocalState) -> str:
    """The persisted channel preference; ``"Estable"`` on a fresh install.

    Reads ``capabilities.update.channel`` from the runtime-authoritative local
    state (spec 'Default channel on fresh install is Estable'). Unknown or
    absent values fall back to the default — a missing slot must never crash
    the status route.
    """
    try:
        state = local_state.snapshot()
    except Exception:  # defensive: a damaged registry never crashes status
        return VALID_CHANNELS[0]
    capabilities = state.get("capabilities")
    slot = capabilities.get("update", {}) if isinstance(capabilities, dict) else {}
    channel = slot.get("channel") if isinstance(slot, dict) else None
    if isinstance(channel, str) and channel in VALID_CHANNELS:
        return channel
    return VALID_CHANNELS[0]


def _fetch_text(url: str, timeout: int = _FETCH_TIMEOUT_SECONDS) -> str | None:
    """Fetch *url* as text; fail-open ``None``.

    Only ``https`` and ``file`` schemes are accepted (mirrors the installer
    scheme gate); any other scheme is treated as an unavailable channel. Any
    fetch/parse failure degrades to ``None`` so the status route reports the
    advisory as unavailable instead of fabricating a version (spec 'Channel
    fetch failure degrades gracefully').
    """
    try:
        scheme = urllib.parse.urlparse(url).scheme.lower()
    except ValueError:
        return None
    if scheme not in _ALLOWED_SCHEMES:
        return None
    try:
        if scheme == "file":
            path = urllib.request.url2pathname(urllib.parse.urlparse(url).path)
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace").strip()
    except (OSError, ValueError, urllib.error.URLError):
        return None


def create_update_router(
    require_principal: Callable[[Request], Any],
    *,
    app_version: Callable[[], str],
    install_root: Path | None,
    local_state: Callable[[], LocalState],
    install_argv: list[str],                 # POSIX [sh]; Windows [powershell, -NoProfile, -File, ps1]
    install_available: bool | None = None,
    channel_config_path: Path | None = None,  # defaults to <install_root>/channel.json
    channel_fetch: Callable[[str], str | None] | None = None,  # (url) -> text; production uses urllib
    install_log: Path | None = None,
) -> APIRouter:
    """Build the ``/api/update`` router (Slice 2b: status + channel).

    ``require_principal`` must return a trusted principal for the request or
    None; None maps to 401 (fail closed). The production resolver is
    ``api_server._resolve_principal``; the factory never trusts an
    unauthenticated request regardless of which resolver is injected.

    ``app_version`` returns the running version (env -> install layout -> dev
    fallback; Slice 1). ``install_root`` is the install root when running the
    installed layout, else None (dev checkout); it locates the default
    ``channel.json`` and, on apply, tells the installer to operate on the SAME
    root the runtime is running from. ``local_state`` returns the
    runtime-authoritative ``LocalState`` registry. ``install_argv`` is the
    installer command to spawn detached on apply (``[<sh installer>]`` on
    POSIX; ``["powershell", "-NoProfile", "-File", "<ps1 installer>"]`` on
    Windows). ``install_available`` is the boot-time existence verdict for the
    installer: False refuses the apply with 503 instead of spawning a stale
    path. ``install_log`` is where the detached installer's stderr is captured
    (a FILE, never a PIPE); the default is ``_INSTALLER_LOG``. ``channel_fetch``
    defaults to the urllib fetcher (injectable for tests).
    """
    router = APIRouter(prefix="/api/update", tags=["update"])
    cfg_path = channel_config_path
    if cfg_path is None and install_root is not None:
        cfg_path = install_root / "channel.json"
    fetch = channel_fetch if channel_fetch is not None else _fetch_text

    def _guard(request: Request) -> None:
        if require_principal(request) is None:
            raise HTTPException(status_code=401, detail=_AUTH_REQUIRED_DETAIL)

    def _status_payload() -> dict[str, Any]:
        current_version = app_version()
        channel = _read_channel(local_state())
        url_base = _resolve_url_base(cfg_path, os.environ)
        offered = fetch(f"{url_base}/{_pointer_for(channel)}")
        if offered is None or not offered.strip():
            return {
                "current_version": current_version,
                "channel": channel,
                "url_base": url_base,
                "latest": None,
                "update_available": False,
                "advisory_unavailable": True,
            }
        latest = offered.strip()
        try:
            update_available = semver.compare(latest, current_version) > 0
        except semver.SemVerError:
            # Unparseable advisory: never offer on uncertainty. The raw value
            # is still surfaced as display-only advisory. The updater never
            # offers or performs a downgrade (compare > 0 only).
            update_available = False
        return {
            "current_version": current_version,
            "channel": channel,
            "url_base": url_base,
            "latest": latest,
            "update_available": update_available,
            "advisory_unavailable": False,
        }

    @router.get("/status")
    def update_status(request: Request) -> dict[str, Any]:
        """Report the running version, channel and the channel's advisory latest.

        Advisory-only: ``version.json`` is never consulted for the offered
        version and nothing here authorizes an install (spec 'Advisory
        version.json is display-only').
        """
        _guard(request)
        return _status_payload()

    @router.put("/channel")
    def set_channel(request: Request, body: dict = Body(...)) -> JSONResponse:
        """Persist the channel preference (``Estable`` | ``Beta``).

        A valid value is committed to ``capabilities.update.channel`` via
        ``LocalState.atomic_commit`` so the choice survives restarts; an
        invalid value is rejected (``update.invalid_channel``) and the
        persisted value is left unchanged (spec 'Invalid channel value is
        rejected').
        """
        _guard(request)
        raw = body.get("channel") if isinstance(body, dict) else None
        if not isinstance(raw, str) or raw not in VALID_CHANNELS:
            return JSONResponse(status_code=400, content={
                "detail": (
                    f"canal no válido: {raw!r}; opciones: "
                    f"{', '.join(VALID_CHANNELS)}"
                ),
                "code": "update.invalid_channel",
            })
        registry = local_state()
        snapshot = registry.snapshot()
        capabilities = snapshot.setdefault("capabilities", {})
        capabilities["update"] = {"channel": raw}
        registry.atomic_commit(snapshot)
        return JSONResponse(status_code=200, content={"channel": raw})

    @router.post("/apply")
    def apply_update(request: Request) -> JSONResponse:
        """Dispatch the installer detached for the channel's offered version.

        Principal-gated like the sibling routes: an unauthenticated request
        fails closed with 401 before anything is resolved or spawned (spec
        'Unauthenticated apply fails closed'). The offered version is
        SERVER-resolved from the channel pointer — the client never supplies a
        version, so the version stays inside the server trust boundary and the
        updater never downgrades (the same no-downgrade rule the status route
        applies; nothing applicable -> 409 ``update.none_available``).
        ``version.json`` is never read here: the installer core re-verifies
        the signed manifest (signature BEFORE checksums) and aborts on any
        failure, so an unsigned advisory alone can never authorize an install
        (spec 'Signed-manifest re-verification before apply').
        """
        _guard(request)

        channel = _read_channel(local_state())
        url_base = _resolve_url_base(cfg_path, os.environ)
        offered = fetch(f"{url_base}/{_pointer_for(channel)}")
        if offered is None or not offered.strip():
            return JSONResponse(status_code=409, content={
                "detail": (
                    "no hay una actualización disponible para el canal "
                    "seleccionado"
                ),
                "code": "update.none_available",
            })
        offered_version = offered.strip()
        try:
            semver.parse_version(offered_version)
        except semver.SemVerError:
            # Defense in depth: the env version must be SemVer-valid before
            # dispatch (design 'Dispatch'). An unparseable advisory is never
            # offered/applied.
            return JSONResponse(status_code=409, content={
                "detail": f"versión ofrecida no válida: {offered_version!r}",
                "code": "update.none_available",
            })
        # Never downgrade: only dispatch when the offered version is strictly
        # greater than the running version (same rule as the status route).
        try:
            applicable = semver.compare(offered_version, app_version()) > 0
        except semver.SemVerError:
            applicable = False
        if not applicable:
            return JSONResponse(status_code=409, content={
                "detail": (
                    "no hay una actualización disponible para el canal "
                    "seleccionado"
                ),
                "code": "update.none_available",
            })

        if install_available is False:
            return JSONResponse(status_code=503, content={
                "action": "update",
                "accepted": False,
                "error": f"installer not available at {install_argv[-1]}",
            })

        log_path = Path(install_log) if install_log is not None else _INSTALLER_LOG
        # The installer receives the channel base and the target version via
        # environment — never argv (no user text reaches the command line and
        # there is no shell=True). ``DEMIURGOS_HOME`` pins the SAME install
        # root the runtime is running from when the installed layout applies,
        # so the `current` flip (a JUNCTION on Windows) targets the root the
        # running app lives under instead of the installer's default.
        env = os.environ.copy()
        env["DEMIURGOS_URL_BASE"] = url_base
        env["DEMIURGOS_VERSION"] = offered_version
        if install_root is not None:
            env["DEMIURGOS_HOME"] = str(install_root)

        # stderr is a FILE, never a PIPE: the installer keeps writing after
        # this process is gone, and a pipe whose reader died would kill it
        # with SIGPIPE mid-install (mirrors system_control's module docstring).
        try:
            stderr_target = open(log_path, "wb")
        except OSError:
            # Losing the early-failure excerpt must never block the operation.
            stderr_target = None

        try:
            proc = subprocess.Popen(
                install_argv,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=(
                    stderr_target if stderr_target is not None
                    else subprocess.DEVNULL
                ),
                env=env,
            )
        except OSError as exc:
            # The spawn itself failed (bad path, permission denied): surface it
            # instead of returning a misleading "accepted".
            return JSONResponse(status_code=500, content={
                "action": "update",
                "accepted": False,
                "error": f"failed to spawn installer: {exc}",
            })
        finally:
            # The child holds its own descriptor: closing ours keeps this
            # process free of a leaked fd and never affects the installer.
            if stderr_target is not None:
                stderr_target.close()

        # Non-blocking early-failure peek: give an instantly-failing installer
        # a brief window to exit, then report its stderr/exit code. This is a
        # bounded 0.5s wait — it never waits for the install to complete.
        time.sleep(_PEEK_WINDOW_SECONDS)
        exit_code = proc.poll()
        if exit_code is not None and exit_code != 0:
            return JSONResponse(status_code=500, content={
                "action": "update",
                "accepted": False,
                "error": _stderr_excerpt(
                    log_path if stderr_target is not None else None,
                    exit_code,
                ),
            })
        return JSONResponse(status_code=200, content={
            "action": "update",
            "accepted": True,
            "version": offered_version,
            "channel": channel,
        })

    return router


__all__ = [
    "DEFAULT_CHANNEL_URL",
    "VALID_CHANNELS",
    "create_update_router",
    "_resolve_url_base",
    "_pointer_for",
    "_read_channel",
    "_fetch_text",
]