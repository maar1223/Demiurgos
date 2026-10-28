# -*- coding: utf-8 -*-
"""One backup run, wired end to end: preconditions -> transport -> snapshot
-> retention -> last-write.

This module is the SINGLE run implementation. Two entry points drive it and
neither forks it:

* the engine's runner (``api_server._run_backup_once``) — reached by
  ``notify_data_changed()`` -> debounce -> the worker thread;
* ``POST /api/backup/run`` — the manual "backup now" action, through
  :func:`backup.router._default_run`.

Both build the same :func:`run_backup` call, so a debounced trigger and a manual
run publish exactly the same tree and record exactly the same status.

**Run order.** Design #3351 §10 places ``prune`` LAST in the snapshotter's
orchestration (``inventory -> sqlite -> stage -> publish -> meta -> prune``), so
this runner composes:

1. **preconditions** — quiesce, destination, target acceptance. A refused run
   writes NOTHING: the run order puts ``last-write`` last, and REQ-SF-3 forbids
   putting bytes into a target that is not verified safe. The reason is returned
   in the :class:`RunOutcome` — never swallowed.
2. **transport** — ``FolderTransport`` over the persisted destination's
   ``Demiurgos/`` layout.
3. **snapshot** — ``BackupSnapshotter`` with the real clock/id source, so a
   trigger produces an ACTUAL snapshot (``current/`` published, ``snapshots/<id>``
   immutable, ``meta/`` last).
4. **retention** — ``prune_snapshots`` with the GFS policy. Its outcome is folded
   into the run: a failed prune downgrades the status to ``ok_with_warnings`` and
   its warnings are recorded; the pruned / ``keep_failed`` ids are surfaced.
5. **last-write** — the FINAL ``meta/last-write.json`` through the shared
   ``write_meta`` seam, carrying the real status (``ok`` / ``ok_with_warnings`` /
   ``failed``) and the destination. The snapshotter writes an interim ``ok``; this
   runner overwrites it once retention has run, which is the only way the status
   can reflect the prune (see the task's step 5).

``clock`` is injected (an aware ``datetime`` per call) and serves both the
snapshotter and retention, so a run is deterministic under test and never reads
the system clock inside the algorithm.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from backup.engine import is_write_quiesced
from backup.manifest import (
    GFS_DAILY_7_WEEKLY_4_MONTHLY_6,
    GfsPolicy,
    LastWriteRecord,
)
from backup.retention import prune_snapshots
from backup.snapshotter import LAST_WRITE_META_NAME, BackupSnapshotter
from backup.state import BackupDestination, BackupStateError, read_destination
from backup.sync_folder import TargetDecision, evaluate_target
from backup.transport.folder import FolderTransport

logger = logging.getLogger("demiurgos-backup")

#: The real statuses ``last-write.json`` may carry (REQ-BE-1, REQ-SF-4).
STATUS_OK = "ok"
STATUS_OK_WITH_WARNINGS = "ok_with_warnings"
STATUS_FAILED = "failed"

#: The refusal reasons, surfaced by the outcome and never swallowed.
REASON_QUIESCED = "backup engine is quiesced: maintenance in progress"
REASON_NO_DESTINATION = "no backup destination configured"
REASON_UNUSABLE = "the chosen folder is not usable"


@dataclass(frozen=True)
class RunOutcome:
    """What one run did — the snapshot it made, the status and the reasons.

    ``refused`` is ``True`` when a precondition stopped the run before any byte
    was written; ``error`` then names the reason. A completed run carries the
    snapshot identity, the local write count and retention's warnings.
    """

    status: str
    refused: bool = False
    snapshot_id: str | None = None
    created_at: str | None = None
    destination: str | None = None
    current_entries: int = 0
    error: str | None = None
    remedy: str | None = None
    warnings: tuple[str, ...] = ()
    pruned: tuple[str, ...] = ()
    keep_failed: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        """Whether the run completed (cleanly or with warnings)."""
        return self.status in (STATUS_OK, STATUS_OK_WITH_WARNINGS)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready report of the run, refusal reason included."""
        return {
            "status": self.status,
            "refused": self.refused,
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "destination": self.destination,
            "current_entries": self.current_entries,
            "error": self.error,
            "remedy": self.remedy,
            "warnings": list(self.warnings),
            "pruned": list(self.pruned),
            "keep_failed": [list(pair) for pair in self.keep_failed],
        }


def _utc_stamp(moment: datetime) -> str:
    """*moment* as ``YYYY-MM-DDTHH:MM:SSZ``; a naive value is read as UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _refused(
    reason: str,
    *,
    destination: BackupDestination | None = None,
    remedy: str | None = None,
) -> RunOutcome:
    """A refusal: nothing was written, and the reason travels with the outcome."""
    return RunOutcome(
        status=STATUS_FAILED,
        refused=True,
        destination=None if destination is None else str(destination.path),
        error=reason,
        remedy=remedy,
    )


def _write_last_write(transport: Any, record: LastWriteRecord) -> None:
    """Record ``last-write.json`` best-effort: a write failure never masks a run."""
    try:
        transport.write_meta(LAST_WRITE_META_NAME, record.to_dict())
    except Exception:  # noqa: BLE001 — the outcome is still returned
        logger.exception("could not record %s", LAST_WRITE_META_NAME)


def run_backup(
    *,
    data_root: Path,
    destination: BackupDestination | None = None,
    quiesce_check: Callable[[], bool] | None = None,
    evaluate: Callable[[Path], TargetDecision] | None = None,
    transport_factory: Callable[[Path], Any] | None = None,
    clock: Callable[[], datetime] | None = None,
    snapshot_id_source: Callable[[datetime], str] | None = None,
    policy: GfsPolicy = GFS_DAILY_7_WEEKLY_4_MONTHLY_6,
    protected: Sequence[str] = (),
    state_base: Path | None = None,
) -> RunOutcome:
    """Run one backup: preconditions, transport, snapshot, retention, last-write.

    Every seam is injectable so the suite drives the whole run hermetically. The
    destination is read from ``config/backup.json`` when not supplied, so the
    engine path (which only knows the data root) and the router path share this
    one function.

    ``state_base`` overrides the base whose ``data/`` holds the live databases;
    the snapshotter resolves it through the state layer by default (2b).
    """
    root = Path(data_root)
    moment_clock = clock or (lambda: datetime.now(timezone.utc))

    # -- 1. Preconditions: before writing ANYTHING -------------------------
    is_quiesced = quiesce_check or is_write_quiesced
    try:
        quiesced = bool(is_quiesced())
    except Exception:  # noqa: BLE001 — an unreadable probe never blocks a run
        quiesced = False
    if quiesced:
        return _refused(REASON_QUIESCED)

    if destination is None:
        try:
            destination = read_destination(root)
        except BackupStateError as exc:
            return _refused(str(exc))
    if destination is None:
        return _refused(REASON_NO_DESTINATION)

    classifier = evaluate or evaluate_target
    try:
        decision = classifier(Path(destination.path))
    except Exception as exc:  # noqa: BLE001 — an unevaluable target is refused
        return _refused(f"{REASON_UNUSABLE}: {exc}", destination=destination)
    if not decision.accepted:
        return _refused(
            decision.remedy or decision.reason or REASON_UNUSABLE,
            destination=destination,
            remedy=decision.remedy,
        )

    # -- 2. The real transport over the persisted destination --------------
    build_transport = transport_factory or (
        lambda dest: FolderTransport(dest, data_root=root)
    )
    transport = build_transport(Path(destination.path))

    # -- 3. The real snapshot ---------------------------------------------
    # ``snapshot_id_source`` keeps ``BackupSnapshotter``'s own default when the
    # caller does not inject one (the real ``YYYY-MM-DDTHHMMSSZ`` id source).
    snapshotter_kwargs: dict[str, Any] = {"clock": moment_clock}
    if snapshot_id_source is not None:
        snapshotter_kwargs["snapshot_id_source"] = snapshot_id_source
    if state_base is not None:
        snapshotter_kwargs["state_base"] = lambda: Path(state_base)
    snapshotter = BackupSnapshotter(transport, **snapshotter_kwargs)
    try:
        result = snapshotter.run(root)
    except Exception as exc:  # noqa: BLE001 — a failed run is recorded, not raised
        error = str(exc) or exc.__class__.__name__
        record = LastWriteRecord(
            last_run_at=_utc_stamp(moment_clock()),
            status=STATUS_FAILED,
            destination=str(destination.path),
            current_entries=0,
            error=error,
        )
        _write_last_write(transport, record)
        return RunOutcome(
            status=STATUS_FAILED,
            destination=str(destination.path),
            error=error,
        )

    # -- 4. Retention: the GFS policy ACTUALLY runs ------------------------
    retention = prune_snapshots(
        transport, now=moment_clock, policy=policy, protected=protected
    )

    # -- 5. The final last-write, with the real folded status --------------
    warnings = tuple(retention.warnings)
    status = retention.status
    record = LastWriteRecord(
        last_run_at=result.created_at,
        status=status,
        destination=str(destination.path),
        current_entries=int(result.current.published),
        warnings=warnings,
    )
    _write_last_write(transport, record)
    return RunOutcome(
        status=status,
        snapshot_id=result.snapshot_id,
        created_at=result.created_at,
        destination=str(destination.path),
        current_entries=int(result.current.published),
        warnings=warnings,
        pruned=tuple(retention.pruned),
        keep_failed=tuple(retention.failed),
    )
