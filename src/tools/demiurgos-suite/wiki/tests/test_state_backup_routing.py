# -*- coding: utf-8 -*-
"""The backup follows the state base across the content/state split (2b).

S5c: "la semántica de backup sigue intacta". The four databases the backup owns
are machine state, so the SQLite cut must read them where the stores open them
and the copy-back must put them back there — while the manifest keeps its
``data/<name>.sqlite3`` labels, the gating rules and the integrity check.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backup import restore as R  # noqa: E402
from backup.snapshotter import BackupSnapshotter  # noqa: E402
from backup.transport.folder import FolderTransport  # noqa: E402
from state_root_support import state_file  # noqa: E402

DB_NAME = "idea-capture.sqlite3"
MANIFEST_PATH = "data/idea-capture.sqlite3"


def _database(path: Path, rows: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS t (a TEXT)")
        connection.execute("DELETE FROM t")
        for index in range(rows):
            connection.execute("INSERT INTO t VALUES (?)", (f"row-{index}",))
        connection.commit()
    finally:
        connection.close()
    return path


def _row_count(path: Path) -> int:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return connection.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        connection.close()


def _content_root(tmp_path: Path, *, inert_rows: int | None = 99) -> Path:
    """A content root: author data, plus (optionally) the inert legacy copy."""
    root = tmp_path / "content"
    (root / "mundos" / "ekkor" / "lore").mkdir(parents=True)
    (root / "mundos" / "ekkor" / "lore" / "Rhyz.md").write_text(
        "---\ntype: lore\ntitle: Rhyz\n---\n# Rhyz\n", encoding="utf-8"
    )
    (root / "data" / "methodology").mkdir(parents=True)
    (root / "data" / "methodology" / "library.json").write_text("{}", encoding="utf-8")
    if inert_rows is not None:
        _database(root / "data" / DB_NAME, inert_rows)
    return root


def _snapshot(root: Path, destination: Path, **snapshotter_kwargs):
    transport = FolderTransport(destination, data_root=root)
    transport.ensure_layout()
    result = BackupSnapshotter(transport, **snapshotter_kwargs).run(root)
    return transport, result.snapshot_id


def _staged_db(destination: Path, snapshot_id: str) -> Path:
    return destination / "Demiurgos" / "snapshots" / snapshot_id / MANIFEST_PATH


def test_the_cut_reads_the_live_database_not_the_inert_copy(tmp_path: Path):
    root = _content_root(tmp_path, inert_rows=99)
    live = _database(state_file(DB_NAME), 2)

    transport, snapshot_id = _snapshot(root, tmp_path / "dest")

    staged = _staged_db(tmp_path / "dest", snapshot_id)
    assert _row_count(staged) == 2
    assert _row_count(live) == 2
    manifest = R.read_manifest(
        tmp_path / "dest" / "Demiurgos" / "snapshots" / snapshot_id
        / R.SNAPSHOT_MANIFEST_PATH
    )
    assert [record.path for record in manifest.sqlite] == [MANIFEST_PATH]
    # The inert copy is refused as content, never uploaded under the same label.
    excluded = {entry.path: entry.reason for entry in manifest.excluded}
    assert excluded["data/idea-capture.sqlite3"] == "excluded:state-root-artifact"
    assert [entry.path for entry in manifest.entries].count(MANIFEST_PATH) == 1


def test_the_restore_copies_the_database_back_to_the_state_base(tmp_path: Path):
    root = _content_root(tmp_path)
    live = _database(state_file(DB_NAME), 1)
    transport, snapshot_id = _snapshot(root, tmp_path / "dest")
    _database(live, 5)  # local drift after the snapshot

    result = R.restore_snapshot(
        transport=transport,
        data_root=root,
        snapshot_id=snapshot_id,
        reindex=lambda _root: None,
        config_revalidator=lambda _root: (),
    )

    assert result.status == "ok"
    assert result.databases == (MANIFEST_PATH,)
    assert _row_count(live) == 1
    # The swap deposits the snapshot's copy in the content root; the restore
    # retires it so machine state never stays in the author's folder (2b).
    assert not (root / "data" / DB_NAME).exists()


def test_an_absent_live_database_is_never_taken_from_the_inert_copy(tmp_path: Path):
    root = _content_root(tmp_path, inert_rows=42)

    _transport, snapshot_id = _snapshot(root, tmp_path / "dest")

    manifest = R.read_manifest(
        tmp_path / "dest" / "Demiurgos" / "snapshots" / snapshot_id
        / R.SNAPSHOT_MANIFEST_PATH
    )
    assert manifest.sqlite == ()
    findings = {finding.kind: finding.paths for finding in manifest.findings}
    assert "idea-capture" in findings["sqlite_db_absent"]
    assert not _staged_db(tmp_path / "dest", snapshot_id).exists()


def test_the_state_base_is_an_explicit_seam(tmp_path: Path):
    root = _content_root(tmp_path, inert_rows=None)
    alternate = tmp_path / "alternate"
    _database(alternate / "data" / DB_NAME, 3)

    _transport, snapshot_id = _snapshot(
        root, tmp_path / "dest", state_base=lambda: alternate
    )

    assert _row_count(_staged_db(tmp_path / "dest", snapshot_id)) == 3


def test_the_copy_back_keeps_its_containment_gate(tmp_path: Path):
    state_base = tmp_path / "state"
    state_base.mkdir()

    with pytest.raises(Exception) as failure:
        R.restore_databases(
            tmp_path / "content",
            {"../../escape.sqlite3": b"SQLite format 3\x00"},
            state_base=state_base,
        )

    assert "escape" in str(failure.value) or "path" in str(failure.value)
    assert not (tmp_path / "escape.sqlite3").exists()


def test_the_backup_run_forwards_the_state_base(tmp_path: Path):
    """The engine path and the manual path share one runner; both accept the seam."""
    from backup import runner
    from backup.transport.base import TargetCapabilities

    root = _content_root(tmp_path, inert_rows=None)
    destination = tmp_path / "dest"
    alternate = tmp_path / "alternate"
    _database(alternate / "data" / DB_NAME, 4)

    outcome = runner.run_backup(
        data_root=root,
        destination=runner.BackupDestination(
            path=str(destination),
            provider="folder",
            source="test",
            confidence="exact",
            mode_hint="folder",
        ),
        quiesce_check=lambda: False,
        evaluate=lambda path: runner.TargetDecision(
            accepted=True,
            capabilities=TargetCapabilities(
                kind="folder",
                path=str(path),
                writable=True,
                same_volume_as_data_root=False,
                mode_hint="mirrored",
            ),
            reason="ok",
        ),
        state_base=alternate,
    )

    assert outcome.status in {runner.STATUS_OK, runner.STATUS_OK_WITH_WARNINGS}
    staged = _staged_db(destination, outcome.snapshot_id)
    assert _row_count(staged) == 4
