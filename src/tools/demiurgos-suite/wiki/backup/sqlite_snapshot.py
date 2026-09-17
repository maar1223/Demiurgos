# -*- coding: utf-8 -*-
"""SQLite online snapshots — a consistent cut through ``Connection.backup()``.

A WAL-mode database keeps committed rows in ``<db>-wal`` until a checkpoint
folds them back, so copying only ``<db>`` silently loses them — the 428-of-430
loss this project already suffered. This module never copies a file:
:func:`snapshot_db` opens the source READ-ONLY (``file:<src>?mode=ro``) and
drives ``Connection.backup()``, which reads through the WAL, so committed rows
are included, the live database is never written, and no ``-wal``/``-shm`` is
ever staged.

The destination must pass ``PRAGMA integrity_check`` (``ok``) before its
per-table row counts are recorded. Included/excluded databases live in ONE
place, and each snapshot is staged at the SAME relative path it has in the data
root (``estado/<name>.sqlite3``), so a restore is a plain copy-back. An absent
INCLUDED database is recorded on :attr:`SnapshotSet.absent` and never dropped
silently — a fresh install legitimately lacks databases never opened.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

#: The data-root member that holds the operational SQLite databases (REQ-BE-2).
DATABASE_DIRNAME = "estado"

#: Every operational database carries this suffix (REQ-BE-1).
DATABASE_SUFFIX = ".sqlite3"

#: The four databases a snapshot MUST include (REQ-BE-5, SC-BE-5.2).
INCLUDED_DATABASES: tuple[str, ...] = (
    "idea-capture",
    "world-checkpoints",
    "co-creation-sessions",
    "guided-sessions",
)

#: The two databases a snapshot MUST NEVER include (REQ-BE-5, SC-BE-5.2):
#: ``conversation-memory`` is 24 h TTL state and ``import-jobs`` is regenerable.
EXCLUDED_DATABASES: tuple[str, ...] = (
    "conversation-memory",
    "import-jobs",
)

#: ``PRAGMA integrity_check``'s single healthy verdict (SC-BE-5.1).
INTEGRITY_OK = "ok"

#: The finding kind recorded when an included database has no source file.
ABSENT_FINDING_KIND = "sqlite_db_absent"


class SqliteSnapshotError(RuntimeError):
    """A database could not be snapshotted into a trusted copy."""


class MissingDatabaseError(SqliteSnapshotError):
    """The requested source database does not exist."""


class SqliteIntegrityError(SqliteSnapshotError):
    """The destination failed ``PRAGMA integrity_check`` — never trust it."""


@dataclass(frozen=True)
class SqliteSnapshot:
    """One database's cut: its ``ok`` verdict and COMMITTED per-table row counts.

    ``rows`` comes from the destination, so it can prove the committed state.
    """

    name: str
    integrity: str
    rows: Mapping[str, int]


@dataclass(frozen=True)
class SnapshotSet:
    """Every included database staged in one pass, plus the absent ones."""

    snapshots: tuple[SqliteSnapshot, ...]
    absent: tuple[str, ...]

    def findings(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """The manifest-shaped finding for every absent database, if any."""
        if not self.absent:
            return ()
        return ((ABSENT_FINDING_KIND, self.absent),)


def database_filename(name: str) -> str:
    """``<name>.sqlite3`` — the on-disk file name of database *name*."""
    return f"{name}{DATABASE_SUFFIX}"


def staged_relative_path(name: str) -> str:
    """The staged path of *name* — its own data-root-relative path (REQ-BE-5).

    Keeping the source's path is what makes a restore a plain copy-back.
    """
    return f"{DATABASE_DIRNAME}/{database_filename(name)}"


def source_path(data_root: Path, name: str) -> Path:
    """The live database *name* under *data_root*."""
    return Path(data_root) / DATABASE_DIRNAME / database_filename(name)


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """The committed row count of every user table of *conn*; internal ones skipped."""
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {
        table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        for table in tables
    }


def snapshot_db(src: Path, dest: Path) -> SqliteSnapshot:
    """Snapshot *src* into *dest* through SQLite's online backup API (REQ-BE-5).

    The source is opened read-only and copied with ``Connection.backup()``, so
    committed rows still in the ``-wal`` are included and the live database is
    never modified or copied file-wise. The destination is verified with
    ``PRAGMA integrity_check``; a verdict other than ``ok`` raises rather than
    returning a copy nobody should trust. A missing source raises
    :class:`MissingDatabaseError` instead of creating an empty database.
    """
    source = Path(src)
    if not source.is_file():
        raise MissingDatabaseError(f"SQLite database {source} does not exist")
    destination = Path(dest)
    destination.parent.mkdir(parents=True, exist_ok=True)

    src_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(str(destination))
        try:
            src_conn.backup(dst_conn)
            integrity = dst_conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != INTEGRITY_OK:
                raise SqliteIntegrityError(
                    f"snapshot of {source} failed integrity_check: {integrity!r}"
                )
            rows = _row_counts(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    return SqliteSnapshot(name=source.stem, integrity=integrity, rows=rows)


def snapshot_databases(data_root: Path, dest_root: Path) -> SnapshotSet:
    """Snapshot every INCLUDED database present under *data_root* (SC-BE-5.2).

    Each database is staged at the same relative path it occupies in the data
    root, under *dest_root*. The excluded set is never read, so a sidecar can
    never reach staging. An included database with no source file is recorded
    in :attr:`SnapshotSet.absent`.
    """
    root = Path(data_root)
    staging = Path(dest_root)
    snapshots: list[SqliteSnapshot] = []
    absent: list[str] = []
    for name in INCLUDED_DATABASES:
        source = source_path(root, name)
        if not source.is_file():
            absent.append(name)
            continue
        snapshots.append(snapshot_db(source, staging / staged_relative_path(name)))
    return SnapshotSet(tuple(snapshots), tuple(absent))
