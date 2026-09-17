# -*- coding: utf-8 -*-
"""``/api/backup/*`` router — destination, runs, snapshots and restore (WU-14).

Eight routes, and no more (REQ-BUI-1):

========================================  ==================================
``GET  /api/backup/status``               the honest card state + local write
``GET  /api/backup/candidates``           suggested folders; the picker is always offered
``POST /api/backup/destination``          persist the chosen folder (author config)
``POST /api/backup/run``                  one run now, into the chosen folder
``GET  /api/backup/snapshots``            the snapshots actually present
``POST /api/backup/restore/preview``      diff counts + blockers, nothing written
``POST /api/backup/restore``              whole-root restore (explicit confirm)
``GET  /api/backup/restore/status``       maintenance marker + last restore outcome
========================================  ==================================

**Auth posture.** Every route runs behind ``require_principal`` and fails
CLOSED: a resolver that returns ``None`` maps to 401 before any state is read
(SC-BUI-1.3). The factory never trusts a request regardless of the resolver
injected, mirroring the sibling routers (``create_ideas_bank_router``).

**Honesty posture.** ``GET /status`` composes
:func:`backup.sync_folder.build_local_write_status` and then runs the WU-12 gate
over the LIVE payload: :func:`~backup.sync_folder.find_dishonest_status_keys`
walks every nesting level for an ``upload*``/``cloud*``/``sync_state`` key, and
:func:`~backup.sync_folder.assert_honest_copy` scans every string leaf in both
es-ES and en. That closes the half of SC-SF-4.2 WU-12 deliberately deferred to
this slice.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backup import runner as backup_runner
from backup.restore import (
    RestoreBlockedError,
    RestoreError,
    SnapshotIncompleteError,
    SnapshotRef,
    SnapshotValidationError,
    find_restore_leftovers,
    is_restore_pending,
    list_restore_snapshots,
    preview_conflicts,
    restore_snapshot,
    staging_directory,
    validate_staged_snapshot,
)
from backup.state import (
    BackupDestination,
    backup_state,
    destination_from_candidate,
    read_destination,
    read_last_write,
    write_destination,
)
from backup.sync_folder import (
    MODE_STREAMING,
    MIRRORING_REMEDY,
    Candidate,
    DishonestCopyError,
    TargetDecision,
    assert_honest_copy,
    build_local_write_status,
    discover_candidates,
    evaluate_target,
    find_dishonest_status_keys,
    local_write_copy,
    manual_candidate,
)
from backup.transport.base import TransportError
from backup.transport.folder import FolderTransport

_AUTH_REQUIRED_DETAIL = "Autenticación requerida"

#: The status payload's honest copy in both languages the feature ships (SC-SF-4.2).
_COPY_LANGUAGES = ("en", "es")


class DestinationRequest(BaseModel):
    """``POST /api/backup/destination`` payload — the user-chosen folder."""

    path: str


class SnapshotRequest(BaseModel):
    """Snapshot selection for preview / restore."""

    snapshot_id: str


class RestoreRequest(BaseModel):
    """``POST /api/backup/restore`` payload — explicit confirmation required."""

    snapshot_id: str
    confirm: bool = False


def _string_leaves(value: Any) -> Iterable[str]:
    """Every string leaf of a JSON-style payload, at any nesting depth."""
    if isinstance(value, Mapping):
        for nested in value.values():
            yield from _string_leaves(nested)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _string_leaves(item)
    elif isinstance(value, str):
        yield value


def _assert_honest_payload(payload: Mapping[str, Any]) -> None:
    """Refuse a status payload that exposes a delivery key or claim (SC-SF-4.1-4.2).

    Reuses the WU-12 helpers rather than re-implementing the vocabulary: the key
    walk is recursive, and every string leaf is scanned in es-ES and en.
    """
    findings = find_dishonest_status_keys(payload)
    if findings:
        raise DishonestCopyError(
            "status payload exposes delivery keys: " + ", ".join(findings)
        )
    for text in _string_leaves(payload):
        assert_honest_copy(text)


def _default_preview(
    transport: Any, data_root: Path, snapshot_id: str
) -> Mapping[str, Any]:
    """Fetch + validate + diff a snapshot WITHOUT writing the data root.

    The fetch lands in the same-volume staging directory restore uses, and the
    staging is removed whatever the outcome: a preview leaves nothing behind.
    """
    staging = staging_directory(data_root, f"preview-{uuid.uuid4().hex[:12]}")
    transport.fetch(SnapshotRef(snapshot_id=snapshot_id), staging)
    try:
        validation = validate_staged_snapshot(staging)
        conflicts = preview_conflicts(
            snapshot_id=snapshot_id,
            staged_dir=staging,
            data_root=data_root,
            manifest=validation.manifest,
        )
        return {
            "validation": validation.to_dict(),
            "conflicts": conflicts.to_dict(),
            "blocked": conflicts.blocked,
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _snapshot_payload(info: Any) -> dict[str, Any]:
    """One snapshot listing entry, completeness included (SC-RS-1.1)."""
    return {
        "snapshot_id": info.snapshot_id,
        "complete": bool(info.complete),
        "entries": int(info.entries),
        "bytes": int(info.bytes),
    }


def create_backup_router(
    require_principal: Callable[[Request], Any],
    *,
    data_root: Path | Callable[[], Path] | None = None,
    transport_factory: Callable[[Path], Any] | None = None,
    discover: Callable[[], list[Candidate]] | None = None,
    evaluate: Callable[[Path], TargetDecision] | None = None,
    run_backup: Callable[[Path, BackupDestination | None], backup_runner.RunOutcome]
    | None = None,
    preview: Callable[[Any, Path, str], Mapping[str, Any]] | None = None,
    restore: Callable[..., Any] | None = None,
    engine: Callable[[], Any] | None = None,
) -> APIRouter:
    """Build the ``/api/backup`` router.

    ``require_principal`` must return a trusted principal for the request or
    ``None``; ``None`` maps to 401. Every other argument is an injectable seam
    with a real default, so the suite drives the routes without a real sync
    folder and without starting a backup engine.
    """
    router = APIRouter(prefix="/api/backup", tags=["backup"])

    def _guard(request: Request) -> None:
        if require_principal(request) is None:
            raise HTTPException(status_code=401, detail=_AUTH_REQUIRED_DETAIL)

    def _root() -> Path:
        if data_root is None:
            import data_root as resolver  # flat sibling module (REQ-DR-1)

            return resolver.resolve_data_root()
        return Path(data_root()) if callable(data_root) else Path(data_root)

    def _transport(destination: BackupDestination) -> Any:
        factory = transport_factory or (lambda root: FolderTransport(root))
        return factory(Path(destination.path))

    def _persisted(root: Path) -> BackupDestination | None:
        try:
            return read_destination(root)
        except Exception as exc:  # noqa: BLE001 — a corrupt record never 500s the card
            raise HTTPException(
                status_code=500, detail=f"backup config is not usable: {exc}"
            ) from exc

    def _default_run(
        data_root: Path, destination: BackupDestination | None
    ) -> backup_runner.RunOutcome:
        """One run into the chosen folder — the ONE run implementation.

        Delegates to :func:`backup.runner.run_backup`, so ``POST /run`` and the
        engine's runner are the same code path: preconditions -> transport ->
        snapshot -> retention -> last-write. The route maps a refusal to the
        honest HTTP status.
        """
        return backup_runner.run_backup(
            data_root=data_root,
            destination=destination,
            evaluate=evaluate,
            transport_factory=transport_factory,
        )

    def _status_payload(
        root: Path,
        destination: BackupDestination | None = None,
        record: Any = None,
        **extra: Any,
    ) -> dict[str, Any]:
        if destination is None:
            destination = _persisted(root)
        if record is None and destination is not None:
            record = read_last_write(destination)
        state = backup_state(
            None, data_root=root, destination=destination, last_write=record
        )
        written = bool(
            record is not None
            and record.status in ("ok", "ok_with_warnings")
            and record.last_run_at
        )
        payload: dict[str, Any] = {
            "state": state,
            "destination": destination.to_dict() if destination else None,
            "mode": destination.mode_hint if destination else None,
            "blocked": bool(destination and destination.mode_hint == MODE_STREAMING),
            "warning": (
                MIRRORING_REMEDY
                if destination and destination.mode_hint == MODE_STREAMING
                else None
            ),
            "last_write": (
                build_local_write_status(
                    destination=str(record.destination or destination.path),
                    written_at=str(record.last_run_at),
                    status=str(record.status),
                    current_entries=int(record.current_entries),
                )
                if written
                else None
            ),
            "copy": (
                {
                    language: local_write_copy(
                        str(record.destination or destination.path),
                        written_at=str(record.last_run_at),
                        language=language,
                    )
                    for language in _COPY_LANGUAGES
                }
                if written and destination is not None
                else None
            ),
        }
        payload.update(extra)
        _assert_honest_payload(payload)
        return payload

    # -- status ------------------------------------------------------------
    @router.get("/status")
    def get_status(request: Request) -> dict[str, Any]:
        """The honest card state, the chosen folder and the last LOCAL write.

        No quota, no account, no connection state and no upload field: the
        payload is asserted cloud-free and vocabulary-clean before it leaves
        (SC-SF-4.1, SC-SF-4.2, SC-BUI-1.2).
        """
        _guard(request)
        return _status_payload(_root())

    # -- candidates --------------------------------------------------------
    @router.get("/candidates")
    def get_candidates(request: Request) -> dict[str, Any]:
        """Suggested folders plus the always-available picker (REQ-SF-1).

        A suggestion is never auto-selected: ``confirmed`` is false for every
        candidate and the picker is offered on every platform.
        """
        _guard(request)
        finder = discover or discover_candidates
        return {
            "candidates": [
                {**candidate.to_dict(), "confirmed": False}
                for candidate in finder()
            ],
            "picker": True,
        }

    # -- destination -------------------------------------------------------
    @router.post("/destination")
    def set_destination(request: Request, body: DestinationRequest) -> dict[str, Any]:
        """Persist the chosen folder and report the resulting honest state.

        A verified streaming target is persisted WITH its verdict so the card
        shows the Mirroring remedy and ``error`` — no run publishes into a cache
        that can be cleared (REQ-SF-3). A missing/unwritable target is rejected
        and nothing is written.
        """
        _guard(request)
        root = _root()
        classifier = evaluate or evaluate_target
        target = Path(body.path)
        decision = classifier(target)
        # The ONLY rejected-yet-persisted case is a verified streaming target:
        # it is recorded with its verdict so the card shows the remedy, and every
        # run refuses. Any other rejection writes nothing.
        streaming = decision.capabilities.mode_hint == MODE_STREAMING
        if not decision.accepted and not streaming:
            raise HTTPException(
                status_code=400,
                detail=decision.reason or "the chosen folder is not usable",
            )
        candidate = manual_candidate(target)
        destination = destination_from_candidate(
            candidate, mode_hint=decision.capabilities.mode_hint
        )
        persisted = write_destination(root, destination)
        return _status_payload(
            root,
            destination=persisted,
            accepted=decision.accepted,
            remedy=decision.remedy,
        )

    # -- run ---------------------------------------------------------------
    @router.post("/run")
    def run_backup_now(request: Request) -> dict[str, Any]:
        """Run one backup into the chosen folder (the "backup now" action).

        Drives the ONE run implementation (:func:`backup.runner.run_backup`),
        which refuses before writing any byte when there is no destination or
        the target is a verified streaming one — the reason (and the Mirroring
        remedy) is surfaced here; no bytes are written.
        """
        _guard(request)
        root = _root()
        destination = _persisted(root)
        outcome = (run_backup or _default_run)(root, destination)
        if getattr(outcome, "refused", False):
            raise HTTPException(
                status_code=409,
                detail=outcome.remedy
                or outcome.error
                or "the backup run was refused",
            )
        return _status_payload(root)

    # -- snapshots ---------------------------------------------------------
    @router.get("/snapshots")
    def get_snapshots(request: Request) -> dict[str, Any]:
        """The snapshots present in the chosen folder, incomplete ones included."""
        _guard(request)
        root = _root()
        destination = _persisted(root)
        if destination is None:
            return {"snapshots": []}
        infos = list_restore_snapshots(_transport(destination))
        return {"snapshots": [_snapshot_payload(info) for info in infos]}

    # -- restore: preview --------------------------------------------------
    @router.post("/restore/preview")
    def preview_restore(request: Request, body: SnapshotRequest) -> dict[str, Any]:
        """Validate + diff a snapshot before any write; blockers disable confirm."""
        _guard(request)
        root = _root()
        destination = _persisted(root)
        if destination is None:
            raise HTTPException(status_code=409, detail="no backup destination configured")
        describe = preview or _default_preview
        try:
            return dict(describe(_transport(destination), root, body.snapshot_id))
        except SnapshotValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (SnapshotIncompleteError, TransportError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    # -- restore: execute --------------------------------------------------
    @router.post("/restore")
    def execute_restore(request: Request, body: RestoreRequest) -> dict[str, Any]:
        """Whole-root restore from a COMPLETE snapshot; requires ``confirm``.

        Restore aborts before the swap on any validation failure, so a refused
        snapshot leaves the data root untouched (SC-RS-2.1/2.2).
        """
        _guard(request)
        if not body.confirm:
            raise HTTPException(
                status_code=400,
                detail="restore requires explicit confirmation",
            )
        root = _root()
        destination = _persisted(root)
        if destination is None:
            raise HTTPException(status_code=409, detail="no backup destination configured")
        runner = restore or restore_snapshot
        try:
            result = runner(
                transport=_transport(destination),
                data_root=root,
                snapshot_id=body.snapshot_id,
                engine=engine() if engine is not None else None,
            )
        except RestoreBlockedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SnapshotValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (RestoreError, SnapshotIncompleteError, TransportError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return result.to_dict()

    # -- restore: status ---------------------------------------------------
    @router.get("/restore/status")
    def restore_status(request: Request) -> dict[str, Any]:
        """Whether a restore is unresolved, plus its last recorded outcome."""
        _guard(request)
        root = _root()
        destination = _persisted(root)
        record = read_last_write(destination) if destination is not None else None
        return {
            "pending": is_restore_pending(root),
            "leftovers": [path.name for path in find_restore_leftovers(root)],
            "last_write": (
                build_local_write_status(
                    destination=str(record.destination or destination.path),
                    written_at=str(record.last_run_at or ""),
                    status=str(record.status),
                    current_entries=int(record.current_entries),
                )
                if record is not None
                else None
            ),
        }

    return router
