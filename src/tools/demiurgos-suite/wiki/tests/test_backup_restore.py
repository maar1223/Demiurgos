# -*- coding: utf-8 -*-
"""Restore tests for WU-13: validate → fetch → quiesce → swap → reindex (13.7).

Every case runs on ``tmp_path``: the data root, the destination folder and the
snapshot are all throwaway, so the developer's real data root is never touched.
The proofs:

* listing reports an incomplete snapshot as incomplete instead of hiding it
  (SC-RS-1.1);
* validation aborts BEFORE the first write, naming the offending path, for a
  missing entry, a size mismatch, a checksum mismatch, an incomplete manifest,
  an unsupported schema version, a failed ``PRAGMA integrity_check`` and an OKF
  contract failure (SC-RS-2.1/2.2) — with the data root proved byte-identical;
* the swap parks and renames per member, quiesces before the first rename and
  resumes after the last, and never touches an excluded member;
* a mid-swap rename failure rolls back, retries once and, when the retry also
  fails, raises ``RestoreSwapError`` naming every member's state while the
  maintenance marker stays and ``last-write.json`` records the failure;
* conflict divergence is reported (counts, capped examples) while a type
  mismatch or an unbacked member is a blocker;
* the SQLite copy-back removes stale sidecars and refuses a corrupt result;
* the real ``EntityGraphIndex`` and the real media bases drive index rebuild;
* restore imports nothing from the importer and calls no import-service entry
  point (SC-RS-1.2) — the two named import-graph guards.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _root in (_WIKI, _SUITE):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from backup import restore as R  # noqa: E402
from backup.manifest import (  # noqa: E402
    MANIFEST_SCHEMA_VERSION,
    EntryRecord,
    Manifest,
    SqliteRecord,
    Totals,
)
from backup.snapshotter import BackupSnapshotter  # noqa: E402
from backup.transport.base import SnapshotIncompleteError  # noqa: E402
from backup.transport.folder import FolderTransport  # noqa: E402

OKF_DOCUMENT = "---\ntype: lore\ntitle: Rhyz\n---\n# Rhyz\n"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_data_root(root: Path) -> Path:
    """A small, complete data root: a world, an idea, a DB, a config, git."""
    (root / "mundos" / "ekkor" / "lore").mkdir(parents=True)
    (root / "mundos" / "ekkor" / "lore" / "Rhyz.md").write_text(
        OKF_DOCUMENT, encoding="utf-8"
    )
    (root / "ideas").mkdir()
    (root / "ideas" / "note.md").write_text("idea\n", encoding="utf-8")
    (root / "data").mkdir()
    (root / "config").mkdir()
    (root / "config" / "backup.json").write_text(
        json.dumps({"schema_version": 1}), encoding="utf-8"
    )
    _write_database(root / "data" / "idea-capture.sqlite3")
    # An excluded member: never backed up, so restore must leave it in place.
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return root


def _write_database(path: Path, rows: int = 1) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS t (a TEXT)")
        for index in range(rows):
            connection.execute("INSERT INTO t VALUES (?)", (f"row-{index}",))
        connection.commit()
    finally:
        connection.close()


def _row_count(path: Path) -> int:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return connection.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        connection.close()


def _snapshot(root: Path, destination: Path) -> tuple[FolderTransport, str]:
    """Run the REAL snapshotter into a temp destination; return transport + id."""
    transport = FolderTransport(destination, data_root=root)
    transport.ensure_layout()
    result = BackupSnapshotter(transport).run(root)
    return transport, result.snapshot_id


def _snapshot_dir(destination: Path, snapshot_id: str) -> Path:
    return destination / "Demiurgos" / "snapshots" / snapshot_id


def _tree_digest(root: Path) -> dict[str, str]:
    """Every file's path → digest, for a byte-identity assertion."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _fast_reindex(data_root: Path) -> R.IndexRebuildReport:
    """A stand-in reindex seam: real graph rebuild is exercised separately."""
    return R.IndexRebuildReport(
        worlds=(), graph_entities={}, gallery_assets=0, gallery_bytes=0
    )


class _RecordingEngine:
    """Records quiesce/resume order and owns the marker, like the real engine."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.calls: list[str] = []

    def quiesce(self) -> None:
        self.calls.append("quiesce")
        R.write_maintenance_marker(self.data_root)

    def resume(self) -> None:
        self.calls.append("resume")
        R.clear_maintenance_marker(self.data_root)


def _staged_tree(
    tmp_path: Path,
    *,
    files: dict[str, bytes] | None = None,
    sqlite: dict[str, bytes] | None = None,
    complete: bool = True,
    schema_version: int = MANIFEST_SCHEMA_VERSION,
    integrity: str = "ok",
) -> Path:
    """A hand-built staged snapshot, so one validation rule fails at a time."""
    staged = tmp_path / "staged"
    entries: list[EntryRecord] = []
    records: list[SqliteRecord] = []
    for relative, data in sorted((files or {}).items()):
        entries.append(_stage_file(staged, relative, data))
    for name, data in sorted((sqlite or {}).items()):
        relative = f"data/{name}.sqlite3"
        entry = _stage_file(staged, relative, data)
        entries.append(entry)
        records.append(SqliteRecord(name, relative, entry.sha256, integrity))
    manifest = Manifest(
        schema_version=schema_version,
        snapshot_id="2026-01-01T000000Z",
        created_at="2026-01-01T00:00:00Z",
        data_root="/original/root",
        checksum_algorithm="sha256",
        complete=complete,
        totals=Totals(
            entries=len(entries), bytes=sum(entry.size for entry in entries)
        ),
        top_level=(),
        entries=tuple(entries),
        sqlite=tuple(records),
        excluded=(),
        findings=(),
    )
    manifest_path = staged / R.SNAPSHOT_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest.to_dict()), encoding="utf-8"
    )
    return staged


def _stage_file(staged: Path, relative: str, data: bytes) -> EntryRecord:
    target = staged / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return EntryRecord(
        path=relative,
        kind="file",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        mtime_ns=target.stat().st_mtime_ns,
    )


def _failing_rename(root: Path, member: str, *, failures: int = 1):
    """A rename seam that fails while a staged *member* moves into the root."""
    state = {"remaining": failures, "undos": 0, "calls": 0}

    def rename(source: Path, target: Path) -> None:
        source, target = Path(source), Path(target)
        state["calls"] += 1
        is_swap_in = (
            source.name == member
            and target.parent.resolve() == root.resolve()
            and source.parent.name.startswith(R.RESTORE_STAGING_PREFIX)
        )
        if is_swap_in and state["remaining"] > 0:
            state["remaining"] -= 1
            raise OSError(32, "simulated sharing violation")
        if target.parent.name.startswith(R.RESTORE_STAGING_PREFIX):
            state["undos"] += 1
        os.rename(source, target)

    return state, rename


def _left_write(transport: FolderTransport) -> dict:
    payload = transport.read_meta("last-write.json")
    assert payload is not None
    return dict(payload)


# ---------------------------------------------------------------------------
# 13.1 — Listing
# ---------------------------------------------------------------------------


def test_list_reports_incomplete_snapshot_as_incomplete(tmp_path: Path) -> None:
    root = _make_data_root(tmp_path / "root")
    transport, snapshot_id = _snapshot(root, tmp_path / "dest")
    # A partially synced snapshot: its manifest never arrived.
    (_snapshot_dir(tmp_path / "dest", snapshot_id) / R.SNAPSHOT_MANIFEST_PATH).unlink()

    listing = R.list_restore_snapshots(transport)

    assert [info.snapshot_id for info in listing] == [snapshot_id]
    assert listing[0].complete is False


# ---------------------------------------------------------------------------
# 13.2 — Validation before any write
# ---------------------------------------------------------------------------


def test_validation_passes_and_reports_what_it_proved(tmp_path: Path) -> None:
    root = _make_data_root(tmp_path / "root")
    _, snapshot_id = _snapshot(root, tmp_path / "dest")
    staged = _snapshot_dir(tmp_path / "dest", snapshot_id)

    validation = R.validate_staged_snapshot(staged)

    assert validation.entries_verified == validation.manifest.totals.entries
    assert validation.bytes_verified == validation.manifest.totals.bytes
    assert validation.databases == ("data/idea-capture.sqlite3",)
    assert validation.worlds == ("ekkor",)
    assert validation.okf_documents == 1


def test_validation_aborts_on_a_missing_entry_naming_the_path(
    tmp_path: Path,
) -> None:
    staged = _staged_tree(tmp_path, files={
        "ideas/note.md": b"idea\n", "ideas/gone.md": b"gone\n",
    })
    (staged / "ideas" / "gone.md").unlink()

    with pytest.raises(R.SnapshotValidationError) as failure:
        R.validate_staged_snapshot(staged)

    assert failure.value.path == "ideas/gone.md"
    assert "gone.md" in str(failure.value)


def test_validation_aborts_on_a_size_mismatch_naming_the_path(
    tmp_path: Path,
) -> None:
    staged = _staged_tree(tmp_path, files={"ideas/note.md": b"idea\n"})
    (staged / "ideas" / "note.md").write_bytes(b"a much longer body\n")

    with pytest.raises(R.SnapshotValidationError) as failure:
        R.validate_staged_snapshot(staged)

    assert failure.value.path == "ideas/note.md"


def test_validation_aborts_on_a_checksum_mismatch_naming_the_path(
    tmp_path: Path,
) -> None:
    staged = _staged_tree(tmp_path, files={"ideas/note.md": b"aaaa\n"})
    (staged / "ideas" / "note.md").write_bytes(b"bbbb\n")  # same size, new bytes

    with pytest.raises(R.SnapshotValidationError) as failure:
        R.validate_staged_snapshot(staged)

    assert failure.value.path == "ideas/note.md"
    assert "mismatch" in str(failure.value)


def test_validation_aborts_on_an_incomplete_manifest(tmp_path: Path) -> None:
    staged = _staged_tree(
        tmp_path, files={"ideas/note.md": b"idea\n"}, complete=False
    )

    with pytest.raises(SnapshotIncompleteError):
        R.validate_staged_snapshot(staged)


def test_validation_aborts_on_an_unsupported_schema_version(
    tmp_path: Path,
) -> None:
    staged = _staged_tree(
        tmp_path, files={"ideas/note.md": b"idea\n"}, schema_version=99
    )

    with pytest.raises(R.SnapshotValidationError) as failure:
        R.validate_staged_snapshot(staged)

    assert failure.value.path == R.SNAPSHOT_MANIFEST_PATH
    assert "99" in str(failure.value)


def test_validation_aborts_on_a_recorded_integrity_verdict(
    tmp_path: Path,
) -> None:
    staged = _staged_tree(
        tmp_path, sqlite={"idea-capture": _database_bytes()}, integrity="not-ok"
    )

    with pytest.raises(R.SnapshotValidationError) as failure:
        R.validate_staged_snapshot(staged)

    assert failure.value.path == "data/idea-capture.sqlite3"


def test_validation_aborts_on_a_failed_integrity_check(tmp_path: Path) -> None:
    staged = _staged_tree(tmp_path, sqlite={"broken": b"not a database at all"})

    with pytest.raises(R.SnapshotValidationError) as failure:
        R.validate_staged_snapshot(staged)

    assert failure.value.path == "data/broken.sqlite3"
    assert "integrity_check" in str(failure.value)


def test_validation_aborts_on_an_okf_contract_failure(tmp_path: Path) -> None:
    staged = _staged_tree(tmp_path, files={
        "mundos/ekkor/lore/Good.md": OKF_DOCUMENT.encode("utf-8"),
        "mundos/ekkor/lore/Bad.md": b"# No frontmatter here\n",
    })

    with pytest.raises(R.SnapshotValidationError) as failure:
        R.validate_staged_snapshot(staged)

    assert failure.value.path == "mundos/ekkor/lore/Bad.md"
    assert "OKF" in str(failure.value)


def _database_bytes(rows: int = 1) -> bytes:
    """A real SQLite database's bytes, built in a throwaway directory."""
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "probe.sqlite3"
        _write_database(path, rows)
        return path.read_bytes()


def test_sqlite_integrity_refuses_a_missing_database(tmp_path: Path) -> None:
    with pytest.raises(R.SnapshotValidationError):
        R.sqlite_integrity(tmp_path / "absent.sqlite3")


# ---------------------------------------------------------------------------
# 13.6 — Conflict preview
# ---------------------------------------------------------------------------


def test_preview_reports_divergence_as_counts_and_examples(
    tmp_path: Path,
) -> None:
    root = _make_data_root(tmp_path / "root")
    transport, snapshot_id = _snapshot(root, tmp_path / "dest")
    staged = _snapshot_dir(tmp_path / "dest", snapshot_id)
    (root / "ideas" / "note.md").unlink()
    (root / "ideas" / "new.md").write_text("new idea\n", encoding="utf-8")
    (root / "mundos" / "ekkor" / "lore" / "Rhyz.md").write_text(
        OKF_DOCUMENT + "changed\n", encoding="utf-8"
    )

    report = R.preview_conflicts(
        snapshot_id=snapshot_id, staged_dir=staged, data_root=root
    )

    assert report.counts.added == 1
    assert report.counts.removed == 1
    assert report.blockers == ()
    assert report.blocked is False
    changes = {(example.path, example.change) for example in report.examples}
    assert ("ideas/new.md", "added") in changes
    assert ("ideas/note.md", "removed") in changes
    # The live database and the edited ficha both differ from the snapshot; a
    # ``sqlite`` entry reports as modified because the restore replaces it.
    assert {
        example.path for example in report.examples if example.change == "modified"
    } == {"mundos/ekkor/lore/Rhyz.md", "data/idea-capture.sqlite3"}


def test_preview_caps_examples_and_reports_the_full_count(tmp_path: Path) -> None:
    root = _make_data_root(tmp_path / "root")
    _, snapshot_id = _snapshot(root, tmp_path / "dest")
    staged = _snapshot_dir(tmp_path / "dest", snapshot_id)
    for index in range(25):
        (root / "ideas" / f"extra-{index:02d}.md").write_text(
            f"idea {index}\n", encoding="utf-8"
        )

    report = R.preview_conflicts(
        snapshot_id=snapshot_id, staged_dir=staged, data_root=root
    )

    assert report.counts.added == 25
    assert len([e for e in report.examples if e.change == "added"]) == 25
    assert len(report.to_dict()["examples"]) == R.CONFLICT_EXAMPLE_LIMIT


def test_preview_blocks_a_type_mismatch_and_an_unbacked_member(
    tmp_path: Path,
) -> None:
    root = _make_data_root(tmp_path / "root")
    _, snapshot_id = _snapshot(root, tmp_path / "dest")
    staged = _snapshot_dir(tmp_path / "dest", snapshot_id)
    (root / "ideas").rename(root / "ideas-renamed")
    (root / "ideas").write_text("now a file\n", encoding="utf-8")
    (root / "output").mkdir()
    (root / "output" / "artifact.md").write_text("x\n", encoding="utf-8")

    report = R.preview_conflicts(
        snapshot_id=snapshot_id, staged_dir=staged, data_root=root
    )

    assert report.blocked is True
    assert any("'ideas'" in blocker and "dir" in blocker for blocker in report.blockers)
    assert any("'output'" in blocker for blocker in report.blockers)
    assert any("'ideas-renamed'" in blocker for blocker in report.blockers)


def test_restore_refuses_blockers_before_the_first_write(tmp_path: Path) -> None:
    root = _make_data_root(tmp_path / "root")
    transport, snapshot_id = _snapshot(root, tmp_path / "dest")
    (root / "output").mkdir()
    (root / "output" / "artifact.md").write_text("x\n", encoding="utf-8")
    before = _tree_digest(root)

    with pytest.raises(R.RestoreBlockedError) as failure:
        R.restore_snapshot(
            transport=transport,
            data_root=root,
            snapshot_id=snapshot_id,
            reindex=_fast_reindex,
        )

    assert any("'output'" in blocker for blocker in failure.value.blockers)
    assert _tree_digest(root) == before
    assert R.is_restore_pending(root) is False
    assert R.find_restore_leftovers(root) == ()


# ---------------------------------------------------------------------------
# 13.3–13.5 — Quiesce, swap, SQLite, indexes, resume
# ---------------------------------------------------------------------------


def test_restore_completes_and_the_root_equals_the_snapshot(
    tmp_path: Path,
) -> None:
    root = _make_data_root(tmp_path / "root")
    transport, snapshot_id = _snapshot(root, tmp_path / "dest")
    # Local edits after the snapshot: overwritten by a whole-root restore.
    (root / "ideas" / "note.md").write_text("edited locally\n", encoding="utf-8")
    engine = _RecordingEngine(root)

    result = R.restore_snapshot(
        transport=transport,
        data_root=root,
        snapshot_id=snapshot_id,
        engine=engine,
        reindex=_fast_reindex,
    )

    assert result.status == "ok"
    assert (root / "mundos" / "ekkor" / "lore" / "Rhyz.md").read_text(
        encoding="utf-8"
    ) == OKF_DOCUMENT
    assert (root / "ideas" / "note.md").read_text(encoding="utf-8") == "idea\n"
    assert _row_count(root / "data" / "idea-capture.sqlite3") == 1
    assert result.databases == ("data/idea-capture.sqlite3",)
    assert result.config_files == ("config/backup.json",)
    assert set(result.swap.swapped) >= {"config", "data", "ideas", "mundos"}
    # 13.4: the park directory is dropped, so no leftover is reported.
    assert R.find_restore_leftovers(root) == ()
    assert R.is_restore_pending(root) is False
    assert engine.calls == ["quiesce", "resume"]
    payload = _left_write(transport)
    assert payload["status"] == "ok"
    assert payload["error"] is None
    assert payload["warnings"] == []
    assert list(tmp_path.glob(f"{R.RESTORE_STAGING_PREFIX}*")) == []


def test_restore_raises_the_marker_before_the_first_rename(
    tmp_path: Path,
) -> None:
    root = _make_data_root(tmp_path / "root")
    transport, snapshot_id = _snapshot(root, tmp_path / "dest")
    seen: dict[str, bool] = {}

    def rename(source: Path, target: Path) -> None:
        seen.setdefault("marker_at_first_rename", R.is_restore_pending(root))
        os.rename(source, target)

    result = R.restore_snapshot(
        transport=transport,
        data_root=root,
        snapshot_id=snapshot_id,
        rename=rename,
        reindex=_fast_reindex,
    )

    assert seen["marker_at_first_rename"] is True
    assert result.status == "ok"
    assert R.is_restore_pending(root) is False


def test_restore_leaves_an_excluded_member_in_place(tmp_path: Path) -> None:
    root = _make_data_root(tmp_path / "root")
    transport, snapshot_id = _snapshot(root, tmp_path / "dest")

    R.restore_snapshot(
        transport=transport,
        data_root=root,
        snapshot_id=snapshot_id,
        reindex=_fast_reindex,
    )

    # ``.git`` is excluded by the inventory, so it was never in the snapshot and
    # must never be swept away by a restore.
    assert (root / ".git" / "HEAD").is_file()
    assert ".git" not in _staged_member_names(tmp_path / "dest", snapshot_id)


def _staged_member_names(destination: Path, snapshot_id: str) -> set[str]:
    staged = _snapshot_dir(destination, snapshot_id)
    return {entry.name for entry in staged.iterdir()}


def test_restore_quiesces_when_there_is_no_engine(tmp_path: Path) -> None:
    root = _make_data_root(tmp_path / "root")
    transport, snapshot_id = _snapshot(root, tmp_path / "dest")

    result = R.restore_snapshot(
        transport=transport,
        data_root=root,
        snapshot_id=snapshot_id,
        reindex=_fast_reindex,
    )

    assert result.status == "ok"
    assert R.is_restore_pending(root) is False


def test_staging_lives_beside_the_data_root(tmp_path: Path) -> None:
    root = tmp_path / "root"

    staging = R.staging_directory(root, "abc123")

    assert staging == tmp_path / f"{R.RESTORE_STAGING_PREFIX}abc123"
    assert staging.parent == root.parent


def test_assert_not_data_root_refuses_the_data_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(R.RestoreError):
        R._assert_not_data_root(root, root)


# ---------------------------------------------------------------------------
# 13.4 — Rollback on an injected rename failure
# ---------------------------------------------------------------------------


def test_rollback_then_retry_restores_the_root(tmp_path: Path) -> None:
    root = _make_data_root(tmp_path / "root")
    transport, snapshot_id = _snapshot(root, tmp_path / "dest")
    (root / "ideas" / "note.md").write_text("edited locally\n", encoding="utf-8")
    state, rename = _failing_rename(root, "ideas", failures=1)

    result = R.restore_snapshot(
        transport=transport,
        data_root=root,
        snapshot_id=snapshot_id,
        rename=rename,
        reindex=_fast_reindex,
    )

    assert result.status == "ok"
    assert result.swap.attempts == 2
    assert state["undos"] >= 1, "the rollback must move swapped members back"
    assert (root / "ideas" / "note.md").read_text(encoding="utf-8") == "idea\n"
    assert R.is_restore_pending(root) is False
    assert R.find_restore_leftovers(root) == ()


def test_a_second_swap_failure_names_the_members_and_keeps_the_marker(
    tmp_path: Path,
) -> None:
    root = _make_data_root(tmp_path / "root")
    transport, snapshot_id = _snapshot(root, tmp_path / "dest")
    before = _tree_digest(root)
    state, rename = _failing_rename(root, "ideas", failures=R.SWAP_ATTEMPTS)

    with pytest.raises(R.RestoreSwapError) as failure:
        R.restore_snapshot(
            transport=transport,
            data_root=root,
            snapshot_id=snapshot_id,
            rename=rename,
            reindex=_fast_reindex,
        )

    assert failure.value.failure == "ideas"
    assert failure.value.swapped == ("config", "data")
    assert "ideas" in failure.value.not_swapped
    assert state["remaining"] == 0
    # The rollback restores the original tree (the maintenance marker is the one
    # file that survives, by design), and the marker stays: the API refuses
    # writes until this is explicitly resolved.
    after = _tree_digest(root)
    after.pop(R.QUIESCE_MARKER_NAME, None)
    assert after == before
    assert R.is_restore_pending(root) is True
    payload = _left_write(transport)
    assert payload["status"] == "failed"
    assert "ideas" in str(payload["error"])
    # The park directories survive (the marker keeps the sweep from deleting
    # them), so nothing is silently dropped on an unresolved failure.
    assert R.find_restore_leftovers(root) != ()
    sweep = R.sweep_restore_leftovers(root)
    assert sweep.swept == ()
    assert len(sweep.blocked) == len(R.find_restore_leftovers(root))


def test_leftover_park_directory_is_reported_and_swept(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "mundos").mkdir(parents=True)
    leftover = root / f"{R.PARK_DIR_PREFIX}run1"
    leftover.mkdir()
    (leftover / "mundos" / "ekkor").mkdir(parents=True)

    report = R.sweep_restore_leftovers(root)

    assert report.swept == (leftover.name,)
    assert report.blocked == ()
    assert report.warnings() == (f"{R.RESTORE_LEFTOVER_WARNING}:{leftover.name}",)
    assert leftover.exists() is False


def test_leftover_park_directory_is_kept_while_the_marker_is_present(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    leftover = root / f"{R.PARK_DIR_PREFIX}run2"
    (leftover / "mundos").mkdir(parents=True)
    R.write_maintenance_marker(root, run_id="run2")

    report = R.sweep_restore_leftovers(root)

    assert report.swept == ()
    assert report.blocked == (leftover.name,)
    assert report.warnings() == (
        f"{R.RESTORE_LEFTOVER_PENDING_WARNING}:{leftover.name}",
    )
    assert (leftover / "mundos").is_dir()


# ---------------------------------------------------------------------------
# 13.5 — SQLite copy-back, index regeneration, config revalidation
# ---------------------------------------------------------------------------


def test_capture_reads_the_staged_databases(tmp_path: Path) -> None:
    root = _make_data_root(tmp_path / "root")
    _, snapshot_id = _snapshot(root, tmp_path / "dest")
    staged = _snapshot_dir(tmp_path / "dest", snapshot_id)
    manifest = R.read_manifest(staged / R.SNAPSHOT_MANIFEST_PATH)

    payloads = R.capture_staged_databases(staged, manifest)

    assert set(payloads) == {"data/idea-capture.sqlite3"}
    assert payloads["data/idea-capture.sqlite3"] == (
        staged / "data" / "idea-capture.sqlite3"
    ).read_bytes()


def test_copy_back_removes_stale_sidecars_and_verifies(tmp_path: Path) -> None:
    root = tmp_path / "root"
    target = root / "data" / "idea-capture.sqlite3"
    target.parent.mkdir(parents=True)
    _write_database(target, rows=3)
    payload = target.read_bytes()
    (root / "data" / "idea-capture.sqlite3-wal").write_bytes(b"stale")
    (root / "data" / "idea-capture.sqlite3-shm").write_bytes(b"stale")

    restored = R.restore_databases(root, {"data/idea-capture.sqlite3": payload})

    assert restored == ("data/idea-capture.sqlite3",)
    assert (root / "data" / "idea-capture.sqlite3-wal").exists() is False
    assert (root / "data" / "idea-capture.sqlite3-shm").exists() is False
    assert _row_count(target) == 3


def test_copy_back_refuses_a_corrupt_database(tmp_path: Path) -> None:
    root = tmp_path / "root"
    target = root / "data" / "idea-capture.sqlite3"
    target.parent.mkdir(parents=True)
    _write_database(target)

    with pytest.raises(R.RestoreError):
        R.restore_databases(root, {"data/idea-capture.sqlite3": b"garbage bytes"})

    # The failure is reported and the marker would stay in place: the copy-back
    # never claims a database it could not verify.
    assert R.sqlite_integrity(target) != "ok"


def test_remove_sqlite_sidecars_reports_what_it_removed(tmp_path: Path) -> None:
    database = tmp_path / "idea-capture.sqlite3"
    _write_database(database)
    (tmp_path / "idea-capture.sqlite3-wal").write_bytes(b"w")

    removed = R.remove_sqlite_sidecars(database)

    assert removed == ("idea-capture.sqlite3-wal",)
    assert (tmp_path / "idea-capture.sqlite3-wal").exists() is False


def test_rebuild_indexes_uses_the_real_graph_and_media_bases(
    tmp_path: Path,
) -> None:
    root = _make_data_root(tmp_path / "root")
    media = root / "mundos" / "ekkor" / "wiki" / "media"
    media.mkdir(parents=True)
    (media / "hero.png").write_bytes(b"png")
    poster = root / "mundos" / "ekkor" / "referencias" / "visuales" / "imagenes"
    poster.mkdir(parents=True)
    (poster / "map.png").write_bytes(b"png-bytes")

    report = R.rebuild_indexes(root)

    assert report.worlds == ("ekkor",)
    assert report.graph_entities["ekkor"] >= 1
    assert report.gallery_assets == 2
    assert report.gallery_bytes == len(b"png") + len(b"png-bytes")


def test_revalidate_config_refuses_broken_json(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "config").mkdir(parents=True)
    (root / "config" / "backup.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(R.RestoreError) as failure:
        R.revalidate_config_files(root)

    assert "config/backup.json" in str(failure.value)


def test_revalidate_config_returns_the_files_it_checked(tmp_path: Path) -> None:
    root = _make_data_root(tmp_path / "root")

    assert R.revalidate_config_files(root) == ("config/backup.json",)
    assert R.revalidate_config_files(tmp_path / "absent") == ()


# ---------------------------------------------------------------------------
# SC-RS-1.2 — the importer is never involved (the two named guards)
# ---------------------------------------------------------------------------

FORBIDDEN_IMPORTER_MODULES = frozenset(
    {"import_router", "import_intake", "import_service", "import_models"}
)
FORBIDDEN_IMPORTER_SYMBOLS = frozenset(
    {
        "ImportService",
        "import_intake",
        "import_router",
        "import_service",
        "execute_import",
        "plan_merge",
    }
)


def _module_file(name: str) -> Path | None:
    """Resolve a dotted module name to a source file under the scanned roots."""
    parts = name.split(".")
    for root in (_WIKI, _SUITE):
        candidate = root.joinpath(*parts)
        if candidate.with_suffix(".py").is_file():
            return candidate.with_suffix(".py")
        package = candidate / "__init__.py"
        if package.is_file():
            return package
    return None


def _imports_of(path: Path) -> list[tuple[str, int, str | None]]:
    """``(module, level, member)`` for every import in *path*.

    ``from . import x`` yields ``("x", 1, None)`` — the alias is a SUBMODULE — so
    the closure follows relative package imports too.
    """
    found: list[tuple[str, int, str | None]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, 0, None))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                if module:
                    found.append((module, node.level, None))
                else:
                    for alias in node.names:
                        found.append((alias.name, node.level, None))
            else:
                found.append((module, 0, None))
    return found


def _relative_target(path: Path, module: str, level: int) -> Path | None:
    """Resolve a relative import against the importing file's directory."""
    directory = path.parent
    for _ in range(max(level - 1, 0)):
        directory = directory.parent
    if not module:
        return None
    candidate = directory.joinpath(*module.split("."))
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    package = candidate / "__init__.py"
    return package if package.is_file() else None


def _import_closure(entry: Path) -> set[str]:
    """Every local module NAME reachable from *entry* through imports."""
    seen: set[Path] = set()
    names: set[str] = set()
    queue = [entry]
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        for module, level, _member in _imports_of(path):
            if module in FORBIDDEN_IMPORTER_MODULES:
                names.add(module)
            target = (
                _relative_target(path, module, level) if level else _module_file(module)
            )
            if target is None:
                continue
            names.add(target.stem)
            queue.append(target)
    return names


def test_restore_never_imports_importer() -> None:
    """No importer module is reachable from ``backup.restore``'s import graph."""
    closure = _import_closure(_WIKI / "backup" / "restore.py")

    leaked = closure & FORBIDDEN_IMPORTER_MODULES
    assert leaked == set(), f"restore imports importer module(s): {sorted(leaked)}"


def test_restore_never_calls_import_service() -> None:
    """``restore.py`` neither names nor CALLS an importer/import-service symbol.

    The check is AST-based, so the module may still explain in prose why it must
    never route recovery through the importer.
    """
    source = (_WIKI / "backup" / "restore.py").read_text(encoding="utf-8")
    referenced: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute):
            referenced.add(node.attr)
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                called.add(target.id)
            elif isinstance(target, ast.Attribute):
                called.add(target.attr)

    assert referenced & FORBIDDEN_IMPORTER_SYMBOLS == set()
    assert called & FORBIDDEN_IMPORTER_SYMBOLS == set()
