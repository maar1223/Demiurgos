# -*- coding: utf-8 -*-
"""``/api/data-root`` — read and change where the author's content lives (step 4).

Two routes, both behind ``require_principal``:

* ``GET`` reports the folder the running app is USING, how it was resolved, the
  disk facts a picker needs, and whether a pointer written meanwhile still needs
  a restart to take effect.
* ``POST`` writes the pointer atomically, refusing the cases that would leave the
  author's content unreachable or put it inside the machine state.

Nothing here moves, copies or deletes author content: pointing the pointer at a
folder moves no bytes, and the route never touches the old tree.

**A saved choice needs a restart to take effect.** Modules across the process
resolve the data root once and cache it (``api_server.PROJECT_ROOT`` and every
store built from it), so rewriting the pointer mid-flight cannot rebind them
safely. :func:`set_content_root` says so in ``restart_required`` instead of
pretending the running process switched folders.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import data_root as resolver
import state_paths
from backup.sync_folder import TargetDecision, evaluate_target

_AUTH_REQUIRED_DETAIL = "Autenticación requerida"

ORIGIN_ENV = "env"
ORIGIN_POINTER = "pointer"
ORIGIN_UNCONFIGURED = "unconfigured"

#: Author content lives under this member; a folder that holds no world in it
#: carries no content worth protecting.
WORLDS_DIRNAME = "mundos"

REFUSAL_RELATIVE = "the content folder must be an absolute path"
REFUSAL_NOT_A_DIRECTORY = "the content folder must be an existing directory: {path}"
REFUSAL_STATE_OVERLAP = (
    "the content folder cannot be the machine-state folder or overlap it: "
    "{path} overlaps {state_dir}"
)
REFUSAL_ENV_WINS = (
    "the content folder is fixed by {env} for this install; unset it to choose "
    "another folder"
)
REFUSAL_LOSES_WORLDS = (
    "refusing to switch to {target}: it holds no worlds while {current} holds "
    "{count}. Choose a folder that already holds your content."
)


class ContentRootRequest(BaseModel):
    """``POST /api/data-root`` payload — the folder the author picked."""

    path: str


def _absolute(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def count_worlds(root: Path) -> int:
    """Worlds under ``<root>/mundos``; a missing folder counts zero."""
    worlds = Path(root) / WORLDS_DIRNAME
    if not worlds.is_dir():
        return 0
    try:
        return sum(1 for entry in worlds.iterdir() if entry.is_dir())
    except OSError:
        return 0


def disk_facts(path: Path) -> dict[str, Any]:
    """Free/total bytes and the volume, or ``None`` fields when unreadable.

    Never guesses: a filesystem name is not reported because the portable API
    does not have one.
    """
    facts: dict[str, Any] = {"free_bytes": None, "total_bytes": None, "volume": None}
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return facts
    facts["free_bytes"] = int(usage.free)
    facts["total_bytes"] = int(usage.total)
    facts["volume"] = Path(path).drive or None
    return facts


def create_content_root_router(
    require_principal: Callable[[Request], Any],
    *,
    env: Mapping[str, str] | None = None,
    config_dir: Path | None = None,
    state_dir: Path | None = None,
    current_root: Callable[[], Path] | None = None,
    classify: Callable[[Path], TargetDecision] | None = None,
    write: Callable[[Path], None] | None = None,
) -> APIRouter:
    """Build the ``/api/data-root`` router.

    Every argument is an injectable seam with a real default, so the suite drives
    both routes without a real pointer, a real state dir or a real disk probe.
    """
    router = APIRouter(prefix="/api/data-root", tags=["data-root"])
    environ = os.environ if env is None else env

    def _guard(request: Request) -> None:
        if require_principal(request) is None:
            raise HTTPException(status_code=401, detail=_AUTH_REQUIRED_DETAIL)

    def _in_use() -> tuple[Path | None, str]:
        """The root the RUNNING process uses, plus how it was resolved."""
        override = (environ.get(resolver.ENV_VAR) or "").strip()
        try:
            if current_root is not None:
                return _absolute(current_root()), (
                    ORIGIN_ENV if override else ORIGIN_POINTER
                )
            return resolver.resolve_data_root(
                environ=environ, config_dir=config_dir
            ), (ORIGIN_ENV if override else ORIGIN_POINTER)
        except resolver.DataRootNotConfigured:
            return None, ORIGIN_UNCONFIGURED

    def _recorded() -> Path | None:
        try:
            return resolver.read_pointer(config_dir=config_dir)
        except resolver.DataRootNotConfigured:
            return None

    def _payload() -> dict[str, Any]:
        root, origin = _in_use()
        recorded = _recorded()
        payload: dict[str, Any] = {
            "path": None if root is None else str(root),
            "origin": origin,
            "configured": root is not None,
            "recorded_path": None if recorded is None else str(recorded),
            "pending_restart": bool(
                root is not None and recorded is not None and recorded != root
            ),
            "usable": False,
            "worlds": 0,
            "disk": {"free_bytes": None, "total_bytes": None, "volume": None},
            "mode": "unknown",
            "warning": None,
            "reason": None,
        }
        if root is None:
            return payload
        decision = (classify or evaluate_target)(Path(root))
        payload.update(
            usable=bool(decision.accepted),
            worlds=count_worlds(root),
            disk=disk_facts(Path(root)),
            mode=decision.capabilities.mode_hint,
            warning=decision.remedy,
            reason=decision.reason,
        )
        return payload

    @router.get("")
    def get_content_root(request: Request) -> dict[str, Any]:
        """Where the content lives (the folder IN USE), and whether it is usable."""
        _guard(request)
        return _payload()

    @router.post("")
    def set_content_root(
        request: Request, body: ContentRootRequest
    ) -> dict[str, Any]:
        """Record the chosen folder, or refuse with a reason that names both paths.

        Refused: a relative path, something that is not an existing directory, a
        folder that overlaps the machine state, a folder that would hide existing
        worlds behind an empty one, and any change while the environment pins the
        root. An accepted write moves NO bytes; the running process keeps the
        folder it booted with until it restarts.
        """
        _guard(request)
        root, origin = _in_use()
        if origin == ORIGIN_ENV and root is not None:
            raise HTTPException(
                status_code=409,
                detail=REFUSAL_ENV_WINS.format(env=resolver.ENV_VAR),
            )

        target = _absolute(body.path)
        if not Path(body.path).expanduser().is_absolute():
            raise HTTPException(status_code=400, detail=REFUSAL_RELATIVE)
        if not target.is_dir():
            raise HTTPException(
                status_code=400,
                detail=REFUSAL_NOT_A_DIRECTORY.format(path=target),
            )

        state = state_paths.resolve_state_dir(
            environ=environ, state_dir=state_dir, config_dir=config_dir
        )
        if (
            target == state
            or target.is_relative_to(state)
            or state.is_relative_to(target)
        ):
            raise HTTPException(
                status_code=400,
                detail=REFUSAL_STATE_OVERLAP.format(path=target, state_dir=state),
            )

        if root is not None and target != root:
            held = count_worlds(root)
            if held and not count_worlds(target):
                raise HTTPException(
                    status_code=409,
                    detail=REFUSAL_LOSES_WORLDS.format(
                        target=target, current=root, count=held
                    ),
                )

        writer = write or (
            lambda chosen: resolver.write_pointer(chosen, config_dir=config_dir)
        )
        writer(target)
        return {**_payload(), "restart_required": True}

    return router
