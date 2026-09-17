# -*- coding: utf-8 -*-
"""SQLite snapshot tests for WU-9a (REQ-BE-5, SC-BE-5.1/5.2).

Centerpiece: the 428-of-430 case. A WAL database holds committed rows in its
``-wal`` that a plain ``<db>``-only copy silently loses. The concurrency test
rebuilds that state deterministically (a TRUNCATE checkpoint leaves 428 rows in
the main file, then a concurrent writer commits two more that stay in the WAL),
proves a naive copy still sees 428, and proves the online backup sees the
committed 430. ``threading.Event`` coordinates the writer, so the test never
sleeps and never guesses which side of the cut a commit landed on.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.sqlite_snapshot import (  # noqa: E402
    ABSENT_FINDING_KIND,
    EXCLUDED_DATABASES,
    INCLUDED_DATABASES,
    MissingDatabaseError,
    snapshot_db,
    snapshot_databases,
    source_path,
    staged_relative_path,
)

#: The 428-of-430 scenario, in numbers (SC-BE-5.1).
ROWS_IN_MAIN_FILE = 428
COMMITTED_ROWS = 430
ROWS_AFTER_THE_CUT = 432


def _wal_database(path: Path) -> sqlite3.Connection:
    """A WAL database with autocheckpoint OFF, so commits stay in the ``-wal``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, payload TEXT)")
    conn.commit()
    return conn


def _insert(conn: sqlite3.Connection, first: int, last: int) -> None:
    """Commit one ``entries`` row per index in ``[first, last)``."""
    conn.executemany(
        "INSERT INTO entries (payload) VALUES (?)",
        [(f"row-{index}",) for index in range(first, last)],
    )
    conn.commit()


def _count(path: Path, *, read_only: bool = False) -> int:
    """The committed ``entries`` count of *path*, read through the WAL normally."""
    target = f"file:{path}?mode=ro" if read_only else str(path)
    conn = sqlite3.connect(target, uri=read_only)
    try:
        return conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    finally:
        conn.close()


def _rows_a_plain_file_copy_would_see(src: Path) -> int:
    """What a naive ``<db>``-only copy sees: the last CHECKPOINTED state.

    Reproducing the forbidden copy here is the point — it is the baseline the
    428/430 assertion rests on. Only the main file's bytes are read.
    """
    naive = src.parent / "naive-main-file-only.sqlite3"
    naive.write_bytes(src.read_bytes())
    return _count(naive, read_only=True)


def test_snapshot_under_a_concurrent_writer_matches_the_committed_state(
    tmp_path: Path,
) -> None:
    """SC-BE-5.1: the snapshot is ``ok`` and holds every COMMITTED row."""
    src = tmp_path / "data" / "idea-capture.sqlite3"
    writer = _wal_database(src)
    writer.execute("CREATE TABLE marks (id INTEGER PRIMARY KEY, note TEXT)")
    writer.executemany("INSERT INTO marks (note) VALUES (?)", [("a",), ("b",)])
    writer.commit()
    _insert(writer, 0, ROWS_IN_MAIN_FILE)
    # Empty the WAL: the main file holds exactly 428 rows, all a copy would see.
    writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert _rows_a_plain_file_copy_would_see(src) == ROWS_IN_MAIN_FILE

    committed = threading.Event()
    more_committed = threading.Event()
    release = threading.Event()

    def concurrent_writer() -> None:
        conn = sqlite3.connect(str(src))
        try:
            _insert(conn, ROWS_IN_MAIN_FILE, COMMITTED_ROWS)
            committed.set()
            release.wait(5)
            _insert(conn, COMMITTED_ROWS, ROWS_AFTER_THE_CUT)
            more_committed.set()
        finally:
            conn.close()

    thread = threading.Thread(target=concurrent_writer, daemon=True)
    thread.start()
    try:
        # The writer COMMITTED and parked; an Event, never a sleep, fixes the cut.
        assert committed.wait(5), "the concurrent writer never committed its rows"
        wal = src.parent / "idea-capture.sqlite3-wal"
        assert wal.is_file() and wal.stat().st_size > 0, "committed rows are not in the WAL"
        assert _rows_a_plain_file_copy_would_see(src) == ROWS_IN_MAIN_FILE, (
            "the 428/430 baseline did not reproduce"
        )

        snapshot = snapshot_db(
            src, tmp_path / "staging" / "data" / "idea-capture.sqlite3"
        )

        assert snapshot.integrity == "ok"
        assert dict(snapshot.rows) == {"entries": COMMITTED_ROWS, "marks": 2}
    finally:
        release.set()
        thread.join(5)

    assert not thread.is_alive()
    # The writer moved on AFTER the cut; the snapshot is a cut, not a view.
    assert more_committed.is_set()
    assert _count(src) == ROWS_AFTER_THE_CUT
    assert dict(snapshot.rows) == {"entries": COMMITTED_ROWS, "marks": 2}
    writer.close()


def test_included_databases_are_staged_and_excluded_ones_are_not(tmp_path: Path) -> None:
    """SC-BE-5.2: the four included DBs are staged at their data-root path, the two are not."""
    root = tmp_path / "data-root"
    for name in INCLUDED_DATABASES + EXCLUDED_DATABASES:
        _wal_database(source_path(root, name)).close()

    dest = tmp_path / "staging"
    result = snapshot_databases(root, dest)

    assert tuple(s.name for s in result.snapshots) == INCLUDED_DATABASES
    assert result.absent == ()
    assert set(INCLUDED_DATABASES).isdisjoint(EXCLUDED_DATABASES)
    staged_files = sorted(
        path.relative_to(dest).as_posix() for path in dest.rglob("*") if path.is_file()
    )
    assert staged_files == sorted(staged_relative_path(name) for name in INCLUDED_DATABASES)
    assert staged_relative_path("idea-capture") == "data/idea-capture.sqlite3"


def test_no_sidecar_is_staged_and_no_plain_file_copy_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-BE-5.2: no ``-wal``/``-shm`` is staged, and no live DB is file-copied."""

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a live database was copied file-wise")

    for name in ("copy", "copy2", "copyfile", "move"):
        monkeypatch.setattr(shutil, name, forbidden)

    root = tmp_path / "data-root"
    writer = _wal_database(source_path(root, "idea-capture"))
    _insert(writer, 0, 5)  # committed, and still living in the ``-wal``

    dest = tmp_path / "staging"
    result = snapshot_databases(root, dest)

    assert tuple(s.name for s in result.snapshots) == ("idea-capture",)
    sidecars = sorted(
        path.name for path in dest.rglob("*") if path.name.endswith(("-wal", "-shm"))
    )
    assert sidecars == []
    # The live database keeps its WAL: the snapshot neither copied nor consumed it.
    assert (root / "data" / "idea-capture.sqlite3-wal").is_file()
    writer.close()


def test_uncommitted_rows_are_not_included(tmp_path: Path) -> None:
    """SC-BE-5.2: an open write transaction's rows are not part of the committed cut."""
    src = tmp_path / "data" / "guided-sessions.sqlite3"
    writer = _wal_database(src)
    _insert(writer, 0, 5)
    writer.execute("BEGIN")
    writer.execute("INSERT INTO entries (payload) VALUES ('uncommitted')")

    snapshot = snapshot_db(
        src, tmp_path / "staging" / staged_relative_path("guided-sessions")
    )

    assert dict(snapshot.rows) == {"entries": 5}
    writer.rollback()
    writer.close()


def test_absent_included_database_is_recorded_and_a_missing_source_raises(
    tmp_path: Path,
) -> None:
    """A missing include is recorded, never dropped; a direct missing source raises."""
    root = tmp_path / "data-root"
    _wal_database(source_path(root, "idea-capture")).close()

    result = snapshot_databases(root, tmp_path / "staging")

    assert tuple(s.name for s in result.snapshots) == ("idea-capture",)
    assert result.absent == ("world-checkpoints", "co-creation-sessions", "guided-sessions")
    assert result.findings() == ((ABSENT_FINDING_KIND, result.absent),)
    with pytest.raises(MissingDatabaseError):
        snapshot_db(root / "data" / "gone.sqlite3", tmp_path / "staged.sqlite3")
