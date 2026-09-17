# -*- coding: utf-8 -*-
"""Run-wiring tests: one run means preconditions -> transport -> snapshot ->
retention -> last-write (REQ-BE-1/3/6/7, REQ-SF-3, REQ-BE-8).

The gap this suite closes: the engine's runner used to be a placeholder that
returned ``None``, so a debounced trigger published nothing and ``prune_snapshots``
was never called. Every proof here runs on ``tmp_path`` with an INJECTED clock,
so a real snapshot is produced without a real clock and without a sleep.

Proofs:

* a debounced trigger (``notify_data_changed`` -> debounce -> run) produces a REAL
  snapshot in the destination — directory + manifest exist and ``current/`` was
  published;
* retention ACTUALLY runs: policy-expired snapshots are pruned and the keep set
  survives, and a failed prune is folded into ``ok_with_warnings``;
* a quiesced engine refuses, records why and writes nothing;
* a verified streaming destination refuses, records why and writes no bytes;
* no destination configured refuses and records why;
* the engine's runner and ``POST /api/backup/run`` are ONE implementation, and
  both record the same ``last-write.json`` shape.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import backup.runner as backup_runner  # noqa: E402
from backup.engine import (  # noqa: E402
    DEFAULT_DEBOUNCE_SECONDS,
    BackupEngine,
    NoopObserver,
    notify_data_changed,
    set_active_engine,
)
from backup.router import create_backup_router  # noqa: E402
from backup.state import (  # noqa: E402
    BackupDestination,
    read_last_write,
    write_destination,
)
from backup.sync_folder import (  # noqa: E402
    MIRRORING_REMEDY,
    MODE_STREAMING,
    REASON_STREAMING,
    TargetCapabilities,
    TargetDecision,
)
from backup.transport.base import PruneResult, TransportError  # noqa: E402
from backup.transport.folder import FolderTransport  # noqa: E402

#: A fixed, aware moment: the run's ``created_at`` and default snapshot id.
FIXED = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
#: The snapshot id ``FIXED`` yields through the real id source.
FIXED_ID = "2026-09-16T120000Z"
#: The debounce the debounced-trigger proof pins.
DEBOUNCE = DEFAULT_DEBOUNCE_SECONDS
#: The destination's tree root under the chosen folder.
TREE = ("Demiurgos",)
#: Old snapshots spanning more than the GFS window. ``now`` is Sep 2026; with one
#: snapshot per month the 7-most-recent-distinct-days rule keeps the 7 newest
#: months, so the two oldest (Jan/Feb) fall outside every keep rule and MUST be
#: pruned, while Mar..Aug survive.
PRUNABLE_IDS = (
    "2026-01-15T000000Z",
    "2026-02-15T000000Z",
)
SURVIVING_IDS = (
    "2026-03-15T000000Z",
    "2026-04-15T000000Z",
    "2026-05-15T000000Z",
    "2026-06-15T000000Z",
    "2026-07-15T000000Z",
    "2026-08-15T000000Z",
)


class VirtualClock:
    """A monotonic-clock stand-in the test moves by hand. Never reads real time."""

    def __init__(self, start: float = 1000.0) -> None:
        self._lock = threading.Lock()
        self._now = start

    def __call__(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> float:
        with self._lock:
            self._now += seconds
            return self._now


@pytest.fixture(autouse=True)
def _reset_active_engine():
    """Never leak the process-wide hook between tests."""
    set_active_engine(None)
    yield
    set_active_engine(None)


def _data_root(tmp_path: Path) -> Path:
    """A real data root with one world/idea file, never the suite's root."""
    root = tmp_path / "data-root"
    (root / "ideas").mkdir(parents=True)
    (root / "ideas" / "alpha.md").write_bytes(b"alpha\n")
    return root


def _destination_folder(tmp_path: Path) -> Path:
    dest = tmp_path / "sync-folder"
    dest.mkdir()
    return dest


def _destination_record(dest: Path) -> BackupDestination:
    return BackupDestination(
        path=str(dest),
        provider="unknown",
        source="user",
        confidence="heuristic",
        mode_hint="mirrored",
    )


def _tree(dest: Path) -> Path:
    return dest.joinpath(*TREE)


def _last_write(dest: Path) -> dict:
    return json.loads((_tree(dest) / "meta" / "last-write.json").read_text("utf-8"))


def _seed_snapshot(dest: Path, snapshot_id: str) -> Path:
    snapshot = _tree(dest) / "snapshots" / snapshot_id
    snapshot.mkdir(parents=True)
    (snapshot / "payload.txt").write_bytes(b"seed\n")
    return snapshot


def _streaming_decision(path: Path) -> TargetDecision:
    return TargetDecision(
        False,
        TargetCapabilities(
            kind="folder",
            path=str(path),
            writable=False,
            same_volume_as_data_root=False,
            mode_hint=MODE_STREAMING,
        ),
        remedy=MIRRORING_REMEDY,
        reason=REASON_STREAMING,
    )


class _FailingPruneTransport(FolderTransport):
    """A transport whose prune always fails, to prove the ``ok_with_warnings`` fold."""

    def prune(self, snapshot_ids):  # type: ignore[override]
        return PruneResult(
            deleted=(),
            failed=tuple((str(snapshot_id), "destination locked")
                         for snapshot_id in snapshot_ids),
        )


class _BrokenPublishTransport(FolderTransport):
    """A transport whose snapshot publish fails, to prove the ``failed`` status."""

    def publish_snapshot(self, snapshot_id, staged):  # type: ignore[override]
        raise TransportError("snapshot publish exploded")


# ---------------------------------------------------------------------------
# The end-to-end gap: a debounced trigger produces a REAL snapshot
# ---------------------------------------------------------------------------


def test_a_debounced_trigger_produces_a_real_snapshot(tmp_path: Path) -> None:
    """The whole point: notify -> debounce -> actual snapshot + published current/."""
    root = _data_root(tmp_path)
    dest = _destination_folder(tmp_path)
    write_destination(root, _destination_record(dest))

    clock = VirtualClock()
    engine = BackupEngine(
        lambda: backup_runner.run_backup(data_root=root, clock=lambda: FIXED),
        data_root=root,
        clock=clock,
        debounce_seconds=DEBOUNCE,
        reconcile_interval=None,
        observer_factory=lambda _root, _on_change: NoopObserver(),
    )
    set_active_engine(engine)
    try:
        notify_data_changed("ideas/alpha.md")
        assert engine.pending_deadline == clock() + DEBOUNCE
        clock.advance(DEBOUNCE)
        assert engine.pump() is True, "the debounced deadline must start the run"
    finally:
        engine.stop(timeout=2.0)

    outcome = engine.last_result
    assert outcome.status == backup_runner.STATUS_OK
    assert outcome.snapshot_id == FIXED_ID

    # The snapshot directory AND its standalone manifest exist.
    snapshot = _tree(dest) / "snapshots" / FIXED_ID
    assert snapshot.is_dir()
    assert (snapshot / "meta" / "manifest.json").is_file()

    # current/ was published with the real file.
    assert (_tree(dest) / "current" / "ideas" / "alpha.md").read_bytes() == b"alpha\n"

    # last-write.json records the local write, honestly.
    record = _last_write(dest)
    assert record["status"] == "ok"
    assert record["destination"] == str(dest)
    assert record["current_entries"] >= 1


def test_retention_actually_runs_and_keeps_the_policy_set(tmp_path: Path) -> None:
    """REQ-BE-7: the GFS policy runs — expired snapshots go, the keep set stays."""
    root = _data_root(tmp_path)
    dest = _destination_folder(tmp_path)
    write_destination(root, _destination_record(dest))
    for snapshot_id in PRUNABLE_IDS + SURVIVING_IDS:
        _seed_snapshot(dest, snapshot_id)

    outcome = backup_runner.run_backup(data_root=root, clock=lambda: FIXED)

    assert outcome.status == backup_runner.STATUS_OK
    assert set(outcome.pruned) == set(PRUNABLE_IDS), "only policy-expired snapshots"
    for snapshot_id in PRUNABLE_IDS:
        assert not (_tree(dest) / "snapshots" / snapshot_id).exists()
    for snapshot_id in SURVIVING_IDS:
        assert (_tree(dest) / "snapshots" / snapshot_id).is_dir()
    # The new snapshot survives too, and the decision is recorded.
    assert (_tree(dest) / "snapshots" / FIXED_ID).is_dir()
    assert (_tree(dest) / "meta" / "retention.json").is_file()


def test_a_failed_prune_is_folded_into_ok_with_warnings(tmp_path: Path) -> None:
    """The retention outcome reaches the run status and the record's warnings."""
    root = _data_root(tmp_path)
    dest = _destination_folder(tmp_path)
    write_destination(root, _destination_record(dest))
    for snapshot_id in PRUNABLE_IDS + SURVIVING_IDS:
        _seed_snapshot(dest, snapshot_id)

    outcome = backup_runner.run_backup(
        data_root=root,
        clock=lambda: FIXED,
        transport_factory=lambda folder: _FailingPruneTransport(
            folder, data_root=root
        ),
    )

    assert outcome.status == backup_runner.STATUS_OK_WITH_WARNINGS
    assert outcome.warnings, "a failed prune must surface a warning"
    assert outcome.keep_failed, "the failed id is recorded, never reported as pruned"
    record = _last_write(dest)
    assert record["status"] == backup_runner.STATUS_OK_WITH_WARNINGS
    assert record["warnings"], "warnings reach last-write.json"


def test_a_failed_run_records_the_failed_status(tmp_path: Path) -> None:
    """An exception inside the run is recorded as ``failed``, never raised."""
    root = _data_root(tmp_path)
    dest = _destination_folder(tmp_path)
    record = write_destination(root, _destination_record(dest))

    outcome = backup_runner.run_backup(
        data_root=root,
        clock=lambda: FIXED,
        transport_factory=lambda folder: _BrokenPublishTransport(
            folder, data_root=root
        ),
    )

    assert outcome.status == backup_runner.STATUS_FAILED
    assert outcome.error and "exploded" in outcome.error
    assert read_last_write(record).status == backup_runner.STATUS_FAILED


# ---------------------------------------------------------------------------
# The three refusal paths: refuse, record why, write nothing
# ---------------------------------------------------------------------------


def test_a_quiesced_engine_refuses_and_writes_nothing(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    dest = _destination_folder(tmp_path)
    write_destination(root, _destination_record(dest))

    engine = BackupEngine(
        lambda: backup_runner.run_backup(data_root=root),
        data_root=root,
        reconcile_interval=None,
        observer_factory=lambda _root, _on_change: NoopObserver(),
    )
    set_active_engine(engine)
    try:
        engine.quiesce()
        outcome = backup_runner.run_backup(data_root=root)
    finally:
        engine.resume()
        engine.stop(timeout=2.0)

    assert outcome.refused is True
    assert outcome.error and "quies" in outcome.error.lower(), "the reason is recorded"
    assert list(dest.rglob("*")) == [], "a refusal writes nothing"


def test_a_streaming_destination_refuses_and_writes_no_bytes(tmp_path: Path) -> None:
    """SC-SF-3.1: a verified streaming target blocks the run, with the remedy."""
    root = _data_root(tmp_path)
    dest = _destination_folder(tmp_path)
    write_destination(root, _destination_record(dest))

    outcome = backup_runner.run_backup(
        data_root=root,
        clock=lambda: FIXED,
        evaluate=lambda path: _streaming_decision(path),
    )

    assert outcome.refused is True
    assert outcome.remedy == MIRRORING_REMEDY
    assert outcome.error == MIRRORING_REMEDY, "the reason is recorded, never swallowed"
    assert list(dest.rglob("*")) == [], "no byte is written into a streaming target"


def test_no_destination_configured_refuses_and_records_why(tmp_path: Path) -> None:
    root = _data_root(tmp_path)

    outcome = backup_runner.run_backup(data_root=root, clock=lambda: FIXED)

    assert outcome.refused is True
    assert outcome.error == backup_runner.REASON_NO_DESTINATION
    assert outcome.destination is None
    assert not (root / "Demiurgos").exists()


def test_a_corrupt_destination_record_refuses_with_its_reason(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    config = root / "config"
    config.mkdir()
    (config / "backup.json").write_text("{not json", encoding="utf-8")

    outcome = backup_runner.run_backup(data_root=root, clock=lambda: FIXED)

    assert outcome.refused is True
    assert outcome.error and "cannot read" in outcome.error


# ---------------------------------------------------------------------------
# One implementation, two entry points
# ---------------------------------------------------------------------------


def test_both_entry_points_call_the_one_run_implementation(
    tmp_path: Path, monkeypatch
) -> None:
    """The engine runner and ``POST /run`` both delegate to ``run_backup``."""
    import api_server  # imported here: the engine's runner lives there

    calls: list[dict] = []

    def spy(**kwargs):
        calls.append(kwargs)
        return backup_runner.RunOutcome(
            status=backup_runner.STATUS_OK, destination=str(kwargs["data_root"])
        )

    monkeypatch.setattr(backup_runner, "run_backup", spy)

    # Entry point A: the engine's runner.
    api_server._run_backup_once()

    # Entry point B: POST /api/backup/run.
    root = _data_root(tmp_path)
    dest = _destination_folder(tmp_path)
    write_destination(root, _destination_record(dest))
    app = FastAPI()
    app.include_router(create_backup_router(lambda _request: "tester", data_root=root))
    response = TestClient(app).post("/api/backup/run")

    assert response.status_code == 200
    assert len(calls) == 2, "both entry points drove the SAME implementation"


def test_both_entry_points_record_the_same_status_shape(tmp_path: Path) -> None:
    """A debounced run and a manual run record the identical ``last-write`` shape."""
    # -- debounced path --
    root_a = _data_root(tmp_path / "a")
    dest_a = tmp_path / "a" / "sync-folder"
    dest_a.mkdir()
    write_destination(root_a, _destination_record(dest_a))
    clock = VirtualClock()
    engine = BackupEngine(
        lambda: backup_runner.run_backup(data_root=root_a, clock=lambda: FIXED),
        data_root=root_a,
        clock=clock,
        debounce_seconds=DEBOUNCE,
        reconcile_interval=None,
        observer_factory=lambda _root, _on_change: NoopObserver(),
    )
    set_active_engine(engine)
    try:
        notify_data_changed("ideas/alpha.md")
        clock.advance(DEBOUNCE)
        assert engine.pump() is True
    finally:
        engine.stop(timeout=2.0)

    # -- manual path --
    root_b = _data_root(tmp_path / "b")
    dest_b = tmp_path / "b" / "sync-folder"
    dest_b.mkdir()
    write_destination(root_b, _destination_record(dest_b))
    app = FastAPI()
    app.include_router(create_backup_router(lambda _request: "tester", data_root=root_b))
    assert TestClient(app).post("/api/backup/run").status_code == 200

    debounced = _last_write(dest_a)
    manual = _last_write(dest_b)
    assert set(debounced) == set(manual), "one recorded status shape"
    assert debounced["status"] == manual["status"] == "ok"
    assert debounced["destination"] == str(dest_a)
    assert manual["destination"] == str(dest_b)
