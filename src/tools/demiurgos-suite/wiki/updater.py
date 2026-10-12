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
    ``channel.json``. ``local_state`` returns the runtime-authoritative
    ``LocalState`` registry. ``install_argv`` / ``install_available`` /
    ``install_log`` are the Slice 3 detached-apply seams, accepted now so the
    factory signature is stable across the change; Slice 2b routes never touch
    them. ``channel_fetch`` defaults to the urllib fetcher (injectable for
    tests).
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