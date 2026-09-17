# -*- coding: utf-8 -*-
"""Snapshotter — one backup run: SQLite cut, file cut, publish, meta last (WU-9).

The run's ORDER is a property of the code, not a comment:

1. :func:`_cut_databases` captures the four included databases through the online
   backup API and returns a :class:`DatabaseCut`. It runs FIRST so the DB cut is
   never OLDER than the file cut: a file written during the run is newer than any
   row that could reference it (a ficha present but unreferenced), which is
   recoverable; a DB-last order would let rows reference files the snapshot never
   captured.
2. :func:`_cut_files` REQUIRES that :class:`DatabaseCut` as a parameter, so the
   file cut cannot be expressed — let alone run — before the DB cut exists. It
   also skips the paths the DB cut claimed, so a live ``*.sqlite3`` is never
   copied file-wise (REQ-BE-5). This is a data dependency, not a convention.
3. Payloads go through :class:`BackupTransport` only — ``probe``,
   ``ensure_layout``, ``read_meta``, ``publish_current``, ``publish_snapshot``,
   ``write_meta``. The engine holds no path or transport special case
   (REQ-BE-8, SC-BE-8.1).
4. ``meta/`` documents are written LAST, ``last-write.json`` with ``status: ok``
   at the very end, so a reader never sees a complete-looking snapshot whose
   bytes are still landing (REQ-BE-1).

**Incremental staging (REQ-BE-3).** Each candidate is compared with its entry in
the PREVIOUS manifest (read through the transport) by ``size`` and ``mtime_ns``;
only a candidate whose size or modification time differs is hashed. An unchanged
tree is never re-hashed, and ``current/`` receives only the entries whose digest
changed — it is add/overwrite only, so a file deleted locally stays recoverable
(SC-BE-3.1/3.2). A snapshot stays COMPLETE (every file) because a restore
validates it standalone.

**Injection.** ``clock`` and ``snapshot_id_source`` are injected, so ``created_at``
and the snapshot id never come from the system clock read inside ``run``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from backup.inventory import Inventory, build_inventory
from backup.manifest import (
    DEFAULT_CHECKSUM_ALGORITHM,
    MANIFEST_SCHEMA_VERSION,
    EntryRecord,
    ExcludedRecord,
    FindingRecord,
    LastWriteRecord,
    Manifest,
    ManifestError,
    SqliteRecord,
    TopLevelRecord,
    Totals,
)
from backup.sqlite_snapshot import snapshot_databases, staged_relative_path
from backup.transport.base import BackupTransport, PublishResult, TargetCapabilities

#: The ``meta/`` documents this run owns; retention is WU-10.
MANIFEST_META_NAME = "manifest.json"
LAST_WRITE_META_NAME = "last-write.json"
#: The manifest a snapshot carries so it validates standalone (REQ-BE-4).
SNAPSHOT_MANIFEST_PATH = "meta/manifest.json"


def _digest(data: bytes) -> str:
    """The recorded algorithm's digest of *data* (REQ-BE-4)."""
    hasher = hashlib.new(DEFAULT_CHECKSUM_ALGORITHM)
    hasher.update(data)
    return hasher.hexdigest()


def _utc_stamp(moment: datetime) -> str:
    """*moment* as ``YYYY-MM-DDTHH:MM:SSZ`` (the manifest's ``created_at``)."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_snapshot_id(moment: datetime) -> str:
    """``YYYY-MM-DDTHHMMSSZ`` — the REQ-BE-1 snapshot name, derived from *moment*."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


@dataclass(frozen=True)
class DatabaseCut:
    """The SQLite cut: staged bytes, manifest records and absent-DB findings."""

    payload: Mapping[str, bytes]
    entries: tuple[EntryRecord, ...]
    records: tuple[SqliteRecord, ...]
    findings: tuple[FindingRecord, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        """Every staged database path — what the file cut must not re-stage."""
        return tuple(entry.path for entry in self.entries)


@dataclass(frozen=True)
class FileCut:
    """The file-tree cut: every staged file, the changed subset, and entries."""

    payload: Mapping[str, bytes]
    changed: Mapping[str, bytes]
    entries: tuple[EntryRecord, ...]
    hashed: int


@dataclass(frozen=True)
class RunResult:
    """What one run did, including the phase order it actually executed."""

    snapshot_id: str
    created_at: str
    stages: tuple[str, ...]
    databases: DatabaseCut
    files: FileCut
    current: PublishResult
    snapshot: PublishResult


def _cut_databases(data_root: Path) -> DatabaseCut:
    """Capture the included databases with ``Connection.backup()``, FIRST.

    Stages into a throwaway directory, then reads the staged bytes so the caller
    gets an in-memory payload. An included database with no live file is recorded
    as a finding, never dropped (REQ-BE-5, SC-BE-5.1/5.2).
    """
    staging = Path(tempfile.mkdtemp(prefix="demiurgos-backup-sqlite-"))
    try:
        captured = snapshot_databases(Path(data_root), staging)
        payload: dict[str, bytes] = {}
        entries: list[EntryRecord] = []
        records: list[SqliteRecord] = []
        for snapshot in captured.snapshots:
            relative = staged_relative_path(snapshot.name)
            staged = staging / relative
            data = staged.read_bytes()
            digest = _digest(data)
            payload[relative] = data
            entries.append(EntryRecord(
                path=relative,
                kind="file",
                size=len(data),
                sha256=digest,
                mtime_ns=staged.stat().st_mtime_ns,
            ))
            records.append(SqliteRecord(
                name=snapshot.name,
                path=relative,
                sha256=digest,
                integrity=snapshot.integrity,
            ))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    findings = tuple(
        FindingRecord(kind, paths) for kind, paths in captured.findings()
    )
    return DatabaseCut(
        payload=payload,
        entries=tuple(entries),
        records=tuple(records),
        findings=findings,
    )


def _cut_files(
    inventory: Inventory,
    previous: Mapping[str, EntryRecord],
    databases: DatabaseCut,
) -> FileCut:
    """Cut the file tree AFTER the DB cut — *databases* is a required input.

    The signature encodes the order: files cannot be cut without the already-made
    :class:`DatabaseCut` (REQ-BE-3). Paths the DB cut claimed are skipped, so a
    live database is never copied file-wise (REQ-BE-5). A candidate whose size and
    ``mtime_ns`` both match the previous manifest reuses that digest; only a
    differing candidate is hashed.
    """
    payload: dict[str, bytes] = {}
    changed: dict[str, bytes] = {}
    entries: list[EntryRecord] = []
    hashed = 0
    for relative in inventory.included:
        if relative in databases.paths:
            continue
        source = inventory.root / relative
        if source.is_dir():
            continue
        stat = source.stat()
        data = source.read_bytes()
        prior = previous.get(relative)
        unchanged = (
            prior is not None
            and prior.size == len(data)
            and prior.mtime_ns == stat.st_mtime_ns
        )
        if unchanged:
            digest = prior.sha256
        else:
            digest = _digest(data)
            hashed += 1
        entries.append(EntryRecord(
            path=relative,
            kind="file",
            size=len(data),
            sha256=digest,
            mtime_ns=stat.st_mtime_ns,
        ))
        payload[relative] = data
        if prior is None or prior.sha256 != digest:
            changed[relative] = data
    return FileCut(
        payload=payload, changed=changed, entries=tuple(entries), hashed=hashed,
    )


def _previous_entries(transport: BackupTransport) -> dict[str, EntryRecord]:
    """The previous run's entries by path; ``{}`` when none is readable.

    Read through the transport (``read_meta``) — the engine holds no path of its
    own. An unsupported or unreadable document degrades to "no previous run", so
    the next run hashes everything instead of trusting a document it cannot parse.
    """
    payload = transport.read_meta(MANIFEST_META_NAME)
    if payload is None:
        return {}
    try:
        manifest = Manifest.from_dict(payload)
    except (ManifestError, KeyError, TypeError, ValueError):
        return {}
    return {entry.path: entry for entry in manifest.entries}


def _build_manifest(
    inventory: Inventory,
    *,
    snapshot_id: str,
    created_at: str,
    databases: DatabaseCut,
    files: FileCut,
) -> Manifest:
    """The manifest for this run, from the cuts — never a second disk walk."""
    entries = tuple(sorted(
        (*files.entries, *databases.entries), key=lambda entry: entry.path
    ))
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        created_at=created_at,
        data_root=str(inventory.root),
        checksum_algorithm=DEFAULT_CHECKSUM_ALGORITHM,
        complete=True,
        totals=Totals(entries=len(entries), bytes=sum(e.size for e in entries)),
        top_level=tuple(
            TopLevelRecord(member.name, member.canonical_case, member.kind)
            for member in inventory.top_level
        ),
        entries=entries,
        sqlite=databases.records,
        excluded=tuple(
            ExcludedRecord(entry.path, entry.reason) for entry in inventory.excluded
        ),
        findings=tuple(
            FindingRecord(finding.kind, finding.paths)
            for finding in inventory.findings
        ) + databases.findings,
    )


class BackupSnapshotter:
    """One backup run over a :class:`BackupTransport`, with an injected clock.

    ``clock`` returns an aware ``datetime``; ``snapshot_id_source`` maps that
    moment to the snapshot directory name. Both are injectable so a run is
    deterministic under test.
    """

    def __init__(
        self,
        transport: BackupTransport,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        snapshot_id_source: Callable[[datetime], str] = _default_snapshot_id,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._snapshot_id_source = snapshot_id_source

    def run(self, data_root: Path) -> RunResult:
        """Run one backup: SQLite FIRST, then files, publish, and meta LAST."""
        root = Path(data_root)
        moment = self._clock()
        created_at = _utc_stamp(moment)
        snapshot_id = self._snapshot_id_source(moment)
        transport = self._transport
        capabilities: TargetCapabilities = transport.probe()
        transport.ensure_layout()
        previous = _previous_entries(transport)

        stages: list[str] = ["sqlite"]
        databases = _cut_databases(root)
        inventory = build_inventory(root)
        stages.append("files")
        files = _cut_files(inventory, previous, databases)

        manifest = _build_manifest(
            inventory,
            snapshot_id=snapshot_id,
            created_at=created_at,
            databases=databases,
            files=files,
        )
        manifest_payload = manifest.to_dict()

        stages.append("current")
        current_payload = dict(files.changed)
        for entry in databases.entries:
            prior = previous.get(entry.path)
            if prior is None or prior.sha256 != entry.sha256:
                current_payload[entry.path] = databases.payload[entry.path]
        current = transport.publish_current(
            current_payload, manifest=manifest_payload
        )

        stages.append("snapshot")
        snapshot_payload = {
            **files.payload,
            **databases.payload,
            SNAPSHOT_MANIFEST_PATH: json.dumps(
                manifest_payload, indent=2, sort_keys=True
            ).encode("utf-8"),
        }
        snapshot = transport.publish_snapshot(snapshot_id, snapshot_payload)

        stages.append("meta")
        transport.write_meta(MANIFEST_META_NAME, manifest_payload)
        transport.write_meta(
            LAST_WRITE_META_NAME,
            LastWriteRecord(
                last_run_at=created_at,
                status="ok",
                destination=capabilities.path,
                current_entries=len(current_payload),
            ).to_dict(),
        )
        return RunResult(
            snapshot_id=snapshot_id,
            created_at=created_at,
            stages=tuple(stages),
            databases=databases,
            files=files,
            current=current,
            snapshot=snapshot,
        )
