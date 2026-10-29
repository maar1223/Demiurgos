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
from backup.state import BackupStateError, read_destination
from backup.sync_folder import TargetDecision, evaluate_target
import folder_dialog
from content_mover import MoveError, destination_candidates
from content_move_service import (
    ContentMoveService,
    read_pointer_change,
    record_pointer_change,
)

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


class MoveRequest(BaseModel):
    """``POST /api/data-root/move`` payload — the destination for the content."""

    target: str


class PickFolderRequest(BaseModel):
    """``POST /api/data-root/pick-folder`` payload — where the dialog starts."""

    initial: str | None = None


class CleanupRequest(BaseModel):
    """``POST /api/data-root/cleanup`` payload — the typed confirmation."""

    confirm: str


def _absolute(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def env_pins_root(override: str, recorded: Path | None) -> bool:
    """Whether the environment really pins the root.

    The shipped launchers export ``DEMIURGOS_DATA_ROOT`` from the pointer they
    just read (``scripts/start-demiurgos.sh``, ``start-demiurgos.ps1``,
    ``start-api.ps1``, ``start-gateway.ps1``), so ``env == pointer`` is the
    normal case in production and must NOT freeze the folder. A real override is
    a value that DISAGREES with the record — or one that exists with no record
    at all, where only the environment knows where the content is.
    """
    if not override:
        return False
    if recorded is None:
        return True
    return _absolute(override) != recorded


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
    move_service: ContentMoveService | None = None,
    pick_folder: Callable[..., Path | None] | None = None,
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

    def _override() -> str:
        return (environ.get(resolver.ENV_VAR) or "").strip()

    def _in_use() -> tuple[Path | None, str]:
        """The root the RUNNING process uses, plus how it was resolved."""
        override = _override()
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
        pinned = _pinned(recorded)
        payload: dict[str, Any] = {
            "path": None if root is None else str(root),
            "origin": origin,
            "configured": root is not None,
            "recorded_path": None if recorded is None else str(recorded),
            # A restart can only help when nothing pins the root: with a real
            # override the next start re-reads the same environment.
            "pinned": pinned,
            "pending_restart": bool(
                root is not None
                and recorded is not None
                and recorded != root
                and not pinned
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

    #: ONE service per router. Building it per request made a background job
    #: unreadable to the next request (progress and cancel answered 404) and let
    #: two moves run at once — the whole feature was dead in production.
    service_cache: list[ContentMoveService] = []

    def _pointer() -> Path | None:
        try:
            return resolver.read_pointer(config_dir=config_dir)
        except resolver.DataRootNotConfigured:
            return None

    def _state_base() -> Path:
        """The machine-state base, never ``resolve_state_dir()``.

        Policy (ii) can answer ``<content root>/data``; a record written there
        would modify the source of the move it describes and be lost with it.
        """
        return resolver.resolve_state_root(environ=environ, state_dir=state_dir)

    def _record_dir() -> Path:
        return _state_base() / "move"

    def _pinned(recorded: Path | None) -> bool:
        """Whether the environment really outranks the record.

        After the APP writes the pointer, a launcher's boot-time
        ``DEMIURGOS_DATA_ROOT`` echo disagrees with the record until the next
        start. That is a pending restart, not an author override, and the app must
        not claim the folder is "fixed by the variable" right after moving it.
        """
        if not env_pins_root(_override(), recorded):
            return False
        change = read_pointer_change(_state_base())
        if change is None or recorded is None:
            return True
        return _absolute(str(change.get("path"))) != recorded

    def _service() -> ContentMoveService:
        if move_service is not None:
            return move_service
        if not service_cache:
            service_cache.append(
                ContentMoveService(record_dir=_record_dir(), pointer=_pointer)
            )
        return service_cache[0]

    def _state_dir() -> Path:
        return state_paths.resolve_state_dir(
            environ=environ, state_dir=state_dir, config_dir=config_dir
        )

    def _forbidden(root: Path) -> list[Path]:
        """What a destination must never overlap, and a delete must never touch."""
        blocked = [_state_dir()]
        try:
            record = read_destination(root)
        except BackupStateError:
            record = None
        if record is not None:
            blocked.append(Path(record.path))
        return blocked

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
        root, _origin = _in_use()
        if _pinned(_recorded()):
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
        record_pointer_change(_state_base(), target)
        # Rewriting the same folder changes nothing: no restart to ask for.
        changed = root is None or target != root
        return {**_payload(), "restart_required": changed}

    # -- candidates --------------------------------------------------------
    @router.get("/candidates")
    def get_destinations(request: Request) -> dict[str, Any]:
        """Folders worth offering as a destination, best first.

        A browser cannot browse the server's disk, so the honest equivalent is a
        list of where a destination usually is: mounted disks, home, Documents
        and siblings of the current folder. The manual path stays as fallback.
        """
        _guard(request)
        root, _origin = _in_use()
        blocked = _forbidden(root) if root is not None else []

        def clashes(candidate: Path) -> bool:
            path = _absolute(candidate)
            return any(
                path == other
                or path.is_relative_to(other)
                or other.is_relative_to(path)
                for other in ( _absolute(item) for item in blocked )
            )

        items = destination_candidates(current=root)
        kept = [item for item in items if not clashes(Path(str(item["path"])))]
        return {
            "candidates": kept,
            "picker": True,
            # The browser cannot browse the server's disk, but the SERVER can open
            # the system dialog. Tell the UI whether that is possible here.
            "native_dialog": folder_dialog.is_available(),
        }

    # -- native picker -----------------------------------------------------
    @router.post("/pick-folder")
    def pick_destination(body: PickFolderRequest, request: Request) -> dict[str, Any]:
        """Open the OS folder dialog on this machine and return the choice.

        A browser cannot name a server folder; the server is running where the
        author sits, so it opens the dialog itself. ``cancelled`` is not an error,
        and a host without a dialog answers 501 so the UI can fall back to the
        suggestions list.
        """
        _guard(request)
        picker = pick_folder or folder_dialog.pick_directory
        try:
            chosen = picker(initial=body.initial)
        except folder_dialog.DialogUnavailable as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except folder_dialog.DialogFailed as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        if chosen is None:
            return {"cancelled": True, "path": None}
        return {"cancelled": False, "path": str(chosen)}

    def _decorate_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
        """Add what the cleanup needs to know about the recorded source.

        Computed live, not only stored: a record written before the field existed
        (or edited by hand) must still tell the UI that the old folder is a code
        checkout and cannot be deleted. The server refuses it either way; this is
        what stops the UI from asking for a confirmation that can only fail.
        """
        if record is None:
            return None
        source = record.get("source")
        enriched = dict(record)
        enriched["source_exists"] = bool(source) and Path(str(source)).is_dir()
        enriched["source_is_checkout"] = bool(source) and (
            Path(str(source)) / ".git"
        ).exists()
        return enriched

    # -- move --------------------------------------------------------------
    # NOT "/move": `POST /api/{mundo}/move` (moving a file inside a world) is
    # registered earlier and matches `{mundo}="data-root"`, so a route named
    # "/move" here was never reached — the app answered "from/to required".
    @router.post("/move-content", status_code=202)
    def start_move(request: Request, body: MoveRequest) -> dict[str, Any]:
        """Copy, verify and only then publish the new content folder.

        The plan is validated here, synchronously, so a refusal never starts a
        job; the copy itself runs in the background because gigabytes do not fit
        in a request.
        """
        _guard(request)
        root, _origin = _in_use()
        if root is None:
            raise HTTPException(
                status_code=409,
                detail="no content folder configured; set one before moving",
            )
        if _pinned(_recorded()):
            raise HTTPException(
                status_code=409,
                detail=REFUSAL_ENV_WINS.format(env=resolver.ENV_VAR),
            )
        service = _service()
        try:
            job = service.start(
                source=root, target=body.target, forbidden=_forbidden(root)
            )
        except MoveError as exc:
            busy = "already running" in str(exc)
            raise HTTPException(
                status_code=409 if busy else 400, detail=str(exc)
            ) from exc
        return {"job": job.to_dict()}

    @router.get("/move-content/{job_id}")
    def get_move(request: Request, job_id: str) -> dict[str, Any]:
        """The job's state, counters and failure reason."""
        _guard(request)
        job = _service().get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown move")
        return {
            "job": job.to_dict(),
            "last_move": _decorate_record(_service().last_move()),
        }

    @router.post("/move-content/{job_id}/cancel")
    def cancel_move(request: Request, job_id: str) -> dict[str, Any]:
        """Ask the running job to stop; nothing is published if it does."""
        _guard(request)
        job = _service().cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown move")
        return {"job": job.to_dict()}

    @router.get("/last-move")
    def get_last_move(request: Request) -> dict[str, Any]:
        """The record of the last terminal move, which gates the cleanup."""
        _guard(request)
        return {"last_move": _decorate_record(_service().last_move())}

    # -- cleanup -----------------------------------------------------------
    @router.post("/cleanup")
    def cleanup_source(request: Request, body: CleanupRequest) -> dict[str, Any]:
        """Delete the old copy: the recorded folder, typed back exactly.

        Only a completed move that published the pointer authorises it, and the
        typed value must equal the recorded source. Never automatic.
        """
        _guard(request)
        root, _origin = _in_use()
        forbidden = [p for p in [_state_dir(), root] if p is not None]
        try:
            removed = _service().delete_source(typed=body.confirm, forbidden=forbidden)
        except MoveError as exc:
            message = str(exc)
            status = 400 if "type the folder exactly" in message else 409
            raise HTTPException(status_code=status, detail=message) from exc
        return {"removed": removed, "last_move": _decorate_record(_service().last_move())}

    return router
