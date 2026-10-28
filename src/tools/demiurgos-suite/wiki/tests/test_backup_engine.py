# -*- coding: utf-8 -*-
"""Engine tests for WU-9b: one run through the transport seam (REQ-BE-1/3/5/8).

Every case builds its own ``tmp_path`` data root and backup tree, so the real
data root is never read. The proofs:

* layout appears under ``<folder>/Demiurgos/`` (SC-BE-1.1);
* incremental staging hashes only changed candidates, and ``current/`` is
  add/overwrite only (SC-BE-3.1/3.2);
* a published snapshot is immutable across runs (SC-BE-4.1);
* the run is drivable through a ``FakeTransport`` with protocol verbs only
  (SC-BE-8.1) — the fake raises if the engine touches any other member;
* ``meta/`` is written after the payload, ``last-write.json`` last with
  ``status: ok`` (REQ-BE-1);
* the SQLite cut precedes the file cut and the DB is never copied file-wise;
* clock and snapshot-id source are injected, so a run is deterministic.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.snapshotter import BackupSnapshotter  # noqa: E402
from backup.transport.base import (  # noqa: E402
    BackupTransport,
    FetchResult,
    PruneResult,
    PublishResult,
    SnapshotInfo,
    TargetCapabilities,
)
from backup.transport.folder import FolderTransport  # noqa: E402
from state_root_support import state_file  # noqa: E402

#: A fixed, aware moment so ``created_at`` and the default id never drift.
FIXED = datetime(2026, 9, 16, 12, 5, 30, tzinfo=timezone.utc)
IDEAS = ("ideas/alpha.md", "ideas/beta.md")


class _SnapshotIds:
    """Deterministic, pattern-safe snapshot ids: one distinct id per run."""

    def __init__(self) -> None:
        self._n = 0

    def __call__(self, moment: datetime) -> str:
        self._n += 1
        return f"2026-09-16T1205{self._n:02d}Z"


def _engine(transport: object, ids: object | None = None) -> BackupSnapshotter:
    return BackupSnapshotter(
        transport,  # type: ignore[arg-type]
        clock=lambda: FIXED,
        snapshot_id_source=ids or _SnapshotIds(),  # type: ignore[arg-type]
    )


def _data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data-root"
    (root / "ideas").mkdir(parents=True)
    (root / "ideas" / "alpha.md").write_bytes(b"alpha\n")
    (root / "ideas" / "beta.md").write_bytes(b"beta\n")
    return root


def _database(path: Path, *, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY)")
        conn.executemany("INSERT INTO entries DEFAULT VALUES", [()] * rows)
        conn.commit()
    finally:
        conn.close()


def _count(path: Path) -> int:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    finally:
        conn.close()


def test_layout_exists_after_a_run(tmp_path: Path) -> None:
    """SC-BE-1.1: the four subdirectories and the snapshot appear."""
    result = _engine(FolderTransport(tmp_path / "dest")).run(_data_root(tmp_path))

    tree = tmp_path / "dest" / "Demiurgos"
    assert (tree / "current").is_dir()
    assert (tree / "snapshots" / result.snapshot_id).is_dir()
    assert (tree / "meta").is_dir()
    assert (tree / "world-trash-index").is_dir()
    assert (tree / "current" / "ideas" / "alpha.md").read_bytes() == b"alpha\n"


def test_changed_files_only_are_rehashed(tmp_path: Path) -> None:
    """SC-BE-3.1: unchanged candidates are not re-hashed; one edit re-hashes one."""
    root = _data_root(tmp_path)
    engine = _engine(FolderTransport(tmp_path / "dest"))

    first = engine.run(root)
    assert first.files.hashed == 2
    assert [entry.path for entry in first.files.entries] == list(IDEAS)

    second = engine.run(root)
    assert second.files.hashed == 0          # unchanged tree: nothing re-hashed
    assert dict(second.files.changed) == {}

    target = root / "ideas" / "beta.md"
    target.write_bytes(b"beta changed\n")
    os.utime(target, ns=(1, 1))              # size AND mtime_ns now differ
    third = engine.run(root)

    assert third.files.hashed == 1
    assert list(third.files.changed) == ["ideas/beta.md"]


def test_removing_a_source_file_does_not_remove_it_from_current(
    tmp_path: Path,
) -> None:
    """SC-BE-3.2: ``current/`` is add/overwrite only — a local delete stays."""
    root = _data_root(tmp_path)
    engine = _engine(FolderTransport(tmp_path / "dest"))
    engine.run(root)
    (root / "ideas" / "beta.md").unlink()

    engine.run(root)

    recoverable = tmp_path / "dest" / "Demiurgos" / "current" / "ideas" / "beta.md"
    assert recoverable.read_bytes() == b"beta\n"


def test_a_published_snapshot_is_immutable_across_runs(tmp_path: Path) -> None:
    """SC-BE-4.1: a later run selects a new id and never touches the old bytes."""
    root = _data_root(tmp_path)
    engine = _engine(FolderTransport(tmp_path / "dest"))
    first = engine.run(root)
    published = (
        tmp_path / "dest" / "Demiurgos" / "snapshots"
        / first.snapshot_id / "ideas" / "alpha.md"
    )
    before = (published.read_bytes(), published.stat().st_mtime_ns)

    (root / "ideas" / "alpha.md").write_bytes(b"alpha changed\n")
    second = engine.run(root)

    assert second.snapshot_id != first.snapshot_id
    assert (published.read_bytes(), published.stat().st_mtime_ns) == before
    snapshots = tmp_path / "dest" / "Demiurgos" / "snapshots"
    assert (snapshots / first.snapshot_id / "ideas" / "alpha.md").read_bytes() == b"alpha\n"
    assert (snapshots / second.snapshot_id / "ideas" / "alpha.md").read_bytes() == (
        b"alpha changed\n"
    )


class FakeTransport:
    """An in-memory transport that records the exact protocol calls it receives.

    ``__getattr__`` refuses any member outside :data:`VERBS`, so an engine that
    reached for a transport-specific attribute (say ``.root``) fails the test
    loudly instead of passing on a coincidence (SC-BE-8.1).
    """

    VERBS = frozenset({
        "probe", "ensure_layout", "publish_current", "publish_snapshot",
        "prune", "list_snapshots", "read_meta", "write_meta", "fetch",
    })

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.meta: dict[str, dict] = {}
        self.current: dict[str, bytes] = {}
        self.snapshots: dict[str, dict[str, bytes]] = {}

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"engine touched a non-protocol transport member: {name!r}")

    def probe(self) -> TargetCapabilities:
        self.calls.append("probe")
        return TargetCapabilities("folder", "/dest", True, False, "unknown")

    def ensure_layout(self) -> None:
        self.calls.append("ensure_layout")

    def publish_current(self, staged, *, manifest) -> PublishResult:
        self.calls.append("publish_current")
        self.current.update(staged)
        return PublishResult(len(staged), 0, sum(len(d) for d in staged.values()))

    def publish_snapshot(self, snapshot_id, staged) -> PublishResult:
        self.calls.append("publish_snapshot")
        self.snapshots[snapshot_id] = dict(staged)
        return PublishResult(len(staged), 0, sum(len(d) for d in staged.values()))

    def prune(self, snapshot_ids) -> PruneResult:
        self.calls.append("prune")
        return PruneResult((), ())

    def list_snapshots(self) -> list[SnapshotInfo]:
        self.calls.append("list_snapshots")
        return [
            SnapshotInfo(sid, True, len(files), sum(len(d) for d in files.values()))
            for sid, files in self.snapshots.items()
        ]

    def read_meta(self, name):
        self.calls.append("read_meta")
        return self.meta.get(name)

    def write_meta(self, name, payload) -> None:
        self.calls.append("write_meta")
        self.meta[name] = dict(payload)

    def fetch(self, snapshot_ref, dest_dir) -> FetchResult:
        self.calls.append("fetch")
        return FetchResult(Path(dest_dir), 0, 0)


def test_the_run_drives_the_transport_protocol_only(tmp_path: Path) -> None:
    """SC-BE-8.1: every call arrives through the protocol; no special case."""
    fake = FakeTransport()

    result = _engine(fake).run(_data_root(tmp_path))

    assert isinstance(fake, BackupTransport)
    assert set(fake.calls) <= FakeTransport.VERBS
    assert result.snapshot_id in fake.snapshots
    assert fake.current["ideas/alpha.md"] == b"alpha\n"
    assert "meta/manifest.json" in fake.snapshots[result.snapshot_id]


def test_meta_is_written_after_the_payload(tmp_path: Path) -> None:
    """REQ-BE-1: ``write_meta`` follows the publishes; last-write says ``ok``."""
    fake = FakeTransport()

    _engine(fake).run(_data_root(tmp_path))

    publishes = [
        index for index, call in enumerate(fake.calls)
        if call in ("publish_current", "publish_snapshot")
    ]
    metas = [index for index, call in enumerate(fake.calls) if call == "write_meta"]
    assert publishes and metas
    assert max(publishes) < min(metas)
    assert fake.calls[-1] == "write_meta"
    assert fake.meta["last-write.json"]["status"] == "ok"
    assert "upload" not in json.dumps(fake.meta["last-write.json"]).lower()


def test_the_sqlite_cut_precedes_the_file_cut(tmp_path: Path) -> None:
    """REQ-BE-3/5: the DB cut runs first and the DB is never file-copied."""
    root = _data_root(tmp_path)
    # The live database is machine state (2b): it lives in the state directory,
    # and the cut reads it there whatever the content root holds.
    live = state_file("idea-capture.sqlite3")
    live.parent.mkdir(parents=True, exist_ok=True)
    _database(live, rows=5)
    _database(root / "data" / "idea-capture.sqlite3", rows=99)  # inert legacy copy

    result = _engine(FolderTransport(tmp_path / "dest")).run(root)

    assert result.stages == ("sqlite", "files", "current", "snapshot", "meta")
    # The DB path belongs to the SQLite cut, so the file cut never staged any
    # copy of it (a file-wise copy would also lose committed WAL rows).
    assert "data/idea-capture.sqlite3" not in result.files.payload
    assert [record.name for record in result.databases.records] == ["idea-capture"]
    assert result.databases.records[0].integrity == "ok"
    staged = (
        tmp_path / "dest" / "Demiurgos" / "snapshots" / result.snapshot_id
        / "data" / "idea-capture.sqlite3"
    )
    assert _count(staged) == 5
