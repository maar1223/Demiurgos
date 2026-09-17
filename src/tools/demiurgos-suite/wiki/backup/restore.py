# -*- coding: utf-8 -*-
"""Restore — rebuild the data root from a COMPLETE snapshot (WU-13).

Restore is *state recovery*, not content import (IM9): the call path is
``restore.py → BackupTransport.fetch → staging → validate → per-member swap →
SQLite copy-back → index regeneration``, and nothing here imports
``import_router``/``import_intake`` or calls the ``ImportService`` pipeline.
Routing recovery through the importer would re-analyse already-analysed
content, demand approvals, and refuse the assets a restore exists to bring back
(``import_intake.SYSTEM_DIRS`` excludes ``.history``/``.papelera``).

**Order of operations (13.1 → 13.6).** ``list`` → ``fetch`` into
``<data_root.parent>/.demiurgos-restore-<run_id>/`` → ``validate`` → ``preview``
→ ``quiesce`` → per-member swap → SQLite copy-back, index regeneration, config
revalidation → ``resume``. Validation is complete before the FIRST byte lands in
the data root: staging sits outside the root on the same volume, so a refused
snapshot is deleted without touching the author's tree, and the swap's renames
never cross a filesystem (SC-RS-3.3 explicitly allows a failure during staging
or validation to leave the data root byte-identical).

**The data-root preservation invariant.** Restore can never erase the data root,
structurally:

* members are MOVED with ``os.rename``; nothing ever ``os.replace``s a non-empty
  directory, and nothing ever ``rmtree``s the data root. The only removal sites
  are guarded by :func:`_assert_not_data_root` (the park directory), restricted
  to the staging directory (outside the root), or keyed to a name carrying the
  park prefix, which cannot equal the data root's name;
* members the exclusion table refuses (``.git``, ``.codegraph``, ``.venv``,
  ``_archivo_produccion``, secrets, SQLite sidecars) are never parked and never
  restored — they were never in the snapshot, so restore leaves them in place
  instead of deleting data it deliberately never backed up;
* the maintenance marker and every park/staging/temp name are reserved and never
  swapped, so the marker survives the swap it guards.

**Rollback.** A rename failure moves the staged-in members back to staging and
the parked members home, then retries ONCE. A second failure raises
:class:`RestoreSwapError` naming exactly which members swapped and which did
not, records it in ``last-write.json.error``, and keeps the maintenance marker —
a failure never pretends success. ``rename`` is injectable, so a mid-swap
failure is simulatable on Linux (the tasks artifact records that Windows
directory swaps cannot be exercised in this environment).
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from backup.engine import (
    MAINTENANCE_SCHEMA_VERSION,
    QUIESCE_MARKER_NAME,
    notify_data_changed,
)
from backup.inventory import build_inventory, match_exclusion
from backup.manifest import (
    ChecksumMismatchError,
    EntryRecord,
    LastWriteRecord,
    Manifest,
    ManifestEntryMissingError,
    ManifestError,
    digest_file,
    read_manifest,
    verify_manifest,
)
from backup.snapshotter import LAST_WRITE_META_NAME, SNAPSHOT_MANIFEST_PATH
from backup.sqlite_snapshot import INTEGRITY_OK
from backup.staging import is_temp_name
from backup.transport.base import (
    BackupTransport,
    SnapshotIncompleteError,
    SnapshotInfo,
    SnapshotRef,
    TransportError,
)
from backup.transport.folder import _normalize_staged_path

#: The snapshot's own metadata member; reserved, never restored into the root.
SNAPSHOT_META_DIRNAME = "meta"
#: Restore staging lives BESIDE the data root: same volume, outside the root.
RESTORE_STAGING_PREFIX = ".demiurgos-restore-"
#: Where a swap parks the root's existing members before renaming the staged
#: ones in. Inside the root, so every rename stays same-volume.
PARK_DIR_PREFIX = ".demiurgos-old-"
#: The data-root member holding the worlds.
MUNDOS_DIRNAME = "mundos"
#: The data-root member holding non-secret author configuration.
CONFIG_DIRNAME = "config"
#: The two real per-world media bases (``api_server._get_media_bases``). The
#: gallery/media index is directory-derived, so regeneration RESCANS these bases
#: instead of rebuilding a persisted index that does not exist.
GALLERY_MEDIA_BASES: tuple[str, ...] = (
    "wiki/media",
    "referencias/visuales/imagenes",
)
#: ``examples`` in a conflict report never exceeds this many entries.
CONFLICT_EXAMPLE_LIMIT = 20
#: ``last-write.json`` warning prefixes (the design's non-fatal notices).
RESTORE_LEFTOVER_WARNING = "restore_leftover"
RESTORE_LEFTOVER_PENDING_WARNING = "restore_leftover_pending"
#: One retry after the first failed swap attempt (13.4).
SWAP_ATTEMPTS = 2


class RestoreError(RuntimeError):
    """A restore could not be completed; the data-root state is named."""


class SnapshotValidationError(RestoreError):
    """A snapshot failed validation BEFORE any write to the data root.

    ``path`` is the offending path relative to the staged snapshot, so an abort
    names the entry instead of reporting a bare failure (SC-RS-2.1/2.2).
    """

    def __init__(self, path: str | None, message: str) -> None:
        self.path = path
        super().__init__(message if path is None else f"{path}: {message}")


class RestoreBlockedError(RestoreError):
    """A conflict blocker forbids the restore; nothing was written."""

    def __init__(self, blockers: tuple[str, ...]) -> None:
        self.blockers = blockers
        super().__init__(
            "restore blocked by conflict blocker(s): " + "; ".join(blockers)
        )


class RestoreSwapError(RestoreError):
    """The atomic swap failed twice; every member's state is recorded exactly.

    ``swapped`` names the staged members that had reached the data root in the
    failed attempt, ``not_swapped`` the staged members that had not, ``parked``
    the members still in a park directory, and ``rollback_failures`` any member
    the rollback could not move back — the case that keeps the maintenance
    marker in place instead of pretending success.
    """

    def __init__(
        self,
        message: str,
        *,
        failure: str | None = None,
        swapped: tuple[str, ...] = (),
        not_swapped: tuple[str, ...] = (),
        parked: tuple[str, ...] = (),
        park_dirs: tuple[Path, ...] = (),
        staging_dir: Path | None = None,
        rollback_failures: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.failure = failure
        self.swapped = swapped
        self.not_swapped = not_swapped
        self.parked = parked
        self.park_dirs = park_dirs
        self.staging_dir = staging_dir
        self.rollback_failures = rollback_failures
        super().__init__(message)


@dataclass(frozen=True)
class RestoreValidation:
    """What validation proved about a staged snapshot before the first write."""

    manifest: Manifest
    entries_verified: int
    bytes_verified: int
    databases: tuple[str, ...]
    okf_documents: int
    worlds: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """The validation summary a status payload can carry (never bytes)."""
        return {
            "snapshot_id": self.manifest.snapshot_id,
            "schema_version": self.manifest.schema_version,
            "complete": self.manifest.complete,
            "entries": self.entries_verified,
            "bytes": self.bytes_verified,
            "databases": list(self.databases),
            "okf_documents": self.okf_documents,
            "worlds": list(self.worlds),
        }


@dataclass(frozen=True)
class ConflictExample:
    """One path the restore would add, modify or remove."""

    path: str
    change: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "change": self.change}


@dataclass(frozen=True)
class ConflictCounts:
    """How many paths each conflict kind covers."""

    added: int
    modified: int
    removed: int

    def to_dict(self) -> dict[str, int]:
        return {
            "added": self.added,
            "modified": self.modified,
            "removed": self.removed,
        }


@dataclass(frozen=True)
class ConflictReport:
    """What restoring ``snapshot_id`` would change, and what forbids it.

    Divergence is REPORTED, never fatal: restoring is supposed to change the
    tree. ``blockers`` is the narrow set that makes the operation unsafe — a
    type mismatch at a member boundary, and a path the restore would delete
    because it is not inside a restored member.
    """

    snapshot_id: str
    counts: ConflictCounts
    examples: tuple[ConflictExample, ...]
    blockers: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        """Whether a blocker forbids the restore."""
        return bool(self.blockers)

    def to_dict(self) -> dict[str, Any]:
        """The ``/api/backup/restore/preview`` payload, examples capped."""
        return {
            "snapshot_id": self.snapshot_id,
            "counts": self.counts.to_dict(),
            "examples": [
                example.to_dict()
                for example in self.examples[:CONFLICT_EXAMPLE_LIMIT]
            ],
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class SwapOutcome:
    """A successful per-member swap: what moved in, where the old tree sits.

    ``earlier_park_dirs`` holds the park directories of attempts that failed and
    rolled back before the successful one. Their contents were moved home, so
    they are empty residue — and they are still reported as ``restore_leftover``
    if emptying them did not succeed, never deleted while they hold a member.
    """

    swapped: tuple[str, ...]
    park_dir: Path
    attempts: int
    earlier_park_dirs: tuple[Path, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"swapped": list(self.swapped), "attempts": self.attempts}


@dataclass(frozen=True)
class RollbackOutcome:
    """What a rollback moved back, and what it could not move back."""

    reverted: tuple[str, ...]
    failures: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class IndexRebuildReport:
    """Indexes regenerated from the restored tree (13.5)."""

    worlds: tuple[str, ...]
    graph_entities: Mapping[str, int]
    gallery_assets: int
    gallery_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "worlds": list(self.worlds),
            "graph_entities": dict(self.graph_entities),
            "gallery_assets": self.gallery_assets,
            "gallery_bytes": self.gallery_bytes,
        }


@dataclass(frozen=True)
class LeftoverSweep:
    """Park directories swept at start-up, and the ones deliberately kept.

    A park directory is swept only once the restore that created it is resolved.
    While the maintenance marker is present the parked members may be the last
    copy of author data, so they are reported and KEPT — never deleted under an
    unresolved failure.
    """

    swept: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()

    def warnings(self) -> tuple[str, ...]:
        """``last-write.json`` warnings: swept and pending park directories."""
        return tuple(
            f"{RESTORE_LEFTOVER_WARNING}:{name}" for name in self.swept
        ) + tuple(
            f"{RESTORE_LEFTOVER_PENDING_WARNING}:{name}" for name in self.blocked
        )


@dataclass(frozen=True)
class RestoreResult:
    """What a completed restore did, in the order it happened."""

    snapshot_id: str
    staging_dir: Path
    validation: RestoreValidation
    conflicts: ConflictReport
    swap: SwapOutcome
    databases: tuple[str, ...]
    indexes: IndexRebuildReport
    config_files: tuple[str, ...]
    status: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """The ``/api/backup/restore`` payload."""
        return {
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "swapped": list(self.swap.swapped),
            "databases": list(self.databases),
            "worlds": list(self.indexes.worlds),
            "config_files": list(self.config_files),
            "conflicts": self.conflicts.to_dict(),
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Paths, reserved names and the maintenance marker
# ---------------------------------------------------------------------------


def staging_directory(data_root: Path, run_id: str) -> Path:
    """``<data_root.parent>/.demiurgos-restore-<run_id>/`` — same volume, outside.

    Staging is deliberately not under the data root, so a refused snapshot can be
    discarded without any risk to the author's tree, and because it is the root's
    sibling the swap's renames never cross a filesystem boundary.
    """
    return Path(data_root).parent / f"{RESTORE_STAGING_PREFIX}{run_id}"


def maintenance_marker_path(data_root: Path) -> Path:
    """``<data_root>/.demiurgos-maintenance.json`` — the quiesce marker."""
    return Path(data_root) / QUIESCE_MARKER_NAME


def is_restore_pending(data_root: Path) -> bool:
    """Whether a restore marker is present and still unresolved (SC-RS-3.2)."""
    return maintenance_marker_path(data_root).exists()


def write_maintenance_marker(
    data_root: Path,
    *,
    run_id: str | None = None,
    snapshot_id: str | None = None,
) -> Path:
    """Write the maintenance marker atomically, BEFORE the swap (SC-RS-3.2).

    The marker is the crash witness: it survives a mid-swap crash, so the next
    start keeps the API read-only until it is explicitly resolved. Same
    temp+``os.replace`` discipline the backup engine uses for the same file.
    """
    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    path = maintenance_marker_path(root)
    payload = json.dumps(
        {
            "schema_version": MAINTENANCE_SCHEMA_VERSION,
            "quiesced_at": _utc_stamp(),
            "reason": "restore",
            "run_id": run_id,
            "snapshot_id": snapshot_id,
        },
        sort_keys=True,
    )
    temp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, path)
    finally:
        _unlink_quietly(temp)
    return path


def clear_maintenance_marker(data_root: Path) -> None:
    """Remove the maintenance marker, resolving the restore (SC-RS-3.2)."""
    _unlink_quietly(maintenance_marker_path(data_root))


def find_restore_leftovers(data_root: Path) -> tuple[Path, ...]:
    """Every park directory still present under *data_root* (13.4)."""
    root = Path(data_root)
    if not root.is_dir():
        return ()
    return tuple(sorted(
        (
            entry
            for entry in root.iterdir()
            if entry.is_dir() and entry.name.startswith(PARK_DIR_PREFIX)
        ),
        key=lambda entry: entry.name,
    ))


def sweep_restore_leftovers(
    data_root: Path, *, resolved: bool = False
) -> LeftoverSweep:
    """Sweep park directories left by a previous restore, reporting each (13.4).

    This is the LAST step of a successful restore and the start-up recovery
    otherwise. A park directory is removed only when the restore is ``resolved``:
    while the maintenance marker is present the parked members can be the last
    copy of author data, so the sweep reports and keeps them (strengthening the
    design, which sweeps unconditionally).
    """
    root = Path(data_root)
    leftovers = find_restore_leftovers(root)
    if not leftovers:
        return LeftoverSweep()
    if maintenance_marker_path(root).exists() and not resolved:
        return LeftoverSweep(blocked=tuple(entry.name for entry in leftovers))
    swept: list[str] = []
    blocked: list[str] = []
    for entry in leftovers:
        _assert_not_data_root(entry, root)
        _rmtree_best_effort(entry)
        (swept if not entry.exists() else blocked).append(entry.name)
    return LeftoverSweep(swept=tuple(swept), blocked=tuple(blocked))


def _is_reserved_member(name: str) -> bool:
    """Whether *name* is restore infrastructure rather than author data (13.4).

    The snapshot's own ``meta/`` member carries the manifest that validates the
    snapshot; the marker, park directories, staging directories and every
    transport temp name are restore bookkeeping.
    """
    return (
        name == SNAPSHOT_META_DIRNAME
        or name == QUIESCE_MARKER_NAME
        or name.startswith(PARK_DIR_PREFIX)
        or name.startswith(RESTORE_STAGING_PREFIX)
        or is_temp_name(name)
    )


def _swap_members(directory: Path) -> tuple[str, ...]:
    """The members a swap may move: not reserved, not excluded (13.4).

    An excluded member was deliberately never backed up, so restore leaves it in
    place: parking it would delete data the snapshot was never meant to hold.
    """
    root = Path(directory)
    if not root.is_dir():
        return ()
    return tuple(sorted(
        entry.name
        for entry in root.iterdir()
        if not _is_reserved_member(entry.name)
        and match_exclusion(entry.name) is None
    ))


def _assert_not_data_root(path: Path, data_root: Path) -> None:
    """Refuse any operation that would treat the data root as disposable."""
    if Path(path).resolve() == Path(data_root).resolve():
        raise RestoreError(f"refusing to remove {path}: it is the data root")


# ---------------------------------------------------------------------------
# 13.1 — Listing
# ---------------------------------------------------------------------------


def list_restore_snapshots(transport: BackupTransport) -> list[SnapshotInfo]:
    """List the snapshots present in the destination folder (13.1, SC-RS-1.1).

    The listing is ``transport.list_snapshots()``, derived from the real
    directory listing, so a snapshot missing its manifest is reported as
    ``complete=False``. An incomplete snapshot is LISTED AS INCOMPLETE — never
    hidden, because hiding it is how a user concludes their backup vanished.
    """
    return sorted(transport.list_snapshots(), key=lambda info: info.snapshot_id)


# ---------------------------------------------------------------------------
# 13.2 — Validation before any write
# ---------------------------------------------------------------------------


def _utc_stamp() -> str:
    """The wall-clock stamp for restore bookkeeping (observability only)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _offending_entry(message: str, manifest: Manifest) -> str | None:
    """The manifest entry a verifier's message names, when it names one.

    ``backup.manifest.verify_manifest`` reports ``{entry.path!r}``; mapping that
    back gives an abort a structural ``path`` without re-implementing the
    verification.
    """
    for entry in manifest.entries:
        if f"'{entry.path}'" in message:
            return entry.path
    return None


def _first_missing_or_sized(manifest: Manifest, staged: Path) -> str | None:
    """The first entry absent or size-mismatched, so an abort names it exactly.

    A diagnostics locator only: the digest verification stays with the REAL
    :func:`backup.manifest.verify_manifest` called afterwards.
    """
    for entry in manifest.entries:
        absolute = staged / entry.path
        if not absolute.is_file():
            return entry.path
        if absolute.stat().st_size != entry.size:
            return entry.path
    return None


def _gate_manifest_path(path: Any) -> str:
    """Run ONE manifest-supplied path through the transport's own name gate.

    A snapshot's manifest is attacker-influenced input: it lives in the user's
    chosen sync folder and a tampered one can name ``../../evil.sqlite3``. The
    transport already refuses exactly that shape for every path it writes
    (:func:`backup.transport.folder._normalize_staged_path`, the SAME gate the
    publish path uses), so restore reuses that gate instead of inventing a
    second validation scheme. The gate runs BEFORE any read or write, and a
    rejection is surfaced as a :class:`SnapshotValidationError` naming the
    offending path.
    """
    try:
        return _normalize_staged_path(path)
    except TransportError as exc:
        raise SnapshotValidationError(path, f"unsafe manifest path: {exc}") from exc


def _contained_path(root: Path, relative: str) -> Path:
    """Resolve *relative* under *root*, refusing anything that escapes it.

    Defence in depth beside :func:`_gate_manifest_path`: even though the name
    gate already rejects ``..`` and absolute components, the resolved path is
    proved to stay under *root* before it is ever used, so a future gate
    relaxation cannot silently re-open the hole. ``resolve()`` collapses symlinks
    too, so a symlinked escape is refused as well.
    """
    resolved_root = Path(root).resolve()
    resolved = (resolved_root / relative).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise SnapshotValidationError(
            relative, f"path escapes the expected root {resolved_root}"
        )
    return resolved


def _gated_and_contained(root: Path, relative: Any) -> str:
    """Gate a manifest path with the transport's rules, then prove containment."""
    safe = _gate_manifest_path(relative)
    _contained_path(root, safe)
    return safe


def sqlite_integrity(path: Path) -> str:
    """``PRAGMA integrity_check`` of *path*, read-only, refusing a missing file.

    A file that is not a database at all is reported as a non-``ok`` verdict with
    SQLite's own message, so the caller aborts on it exactly like a failed check
    instead of leaking a :class:`sqlite3.DatabaseError`.
    """
    target = Path(path)
    if not target.is_file():
        raise SnapshotValidationError(str(target), "SQLite database is missing")
    connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    except sqlite3.Error as exc:
        return f"error: {exc}"
    finally:
        connection.close()


def _default_okf_validator() -> Callable[[str], Any]:
    """The REAL ``okf_contract.validate``, imported lazily.

    ``api_server`` imports it as ``okf_contract`` and ``graph_indexer`` as
    ``wiki.okf_contract`` depending on how the process bootstrapped ``sys.path``,
    so both spellings are tried. Nothing here re-implements the contract.
    """
    try:
        from wiki.okf_contract import validate as real_validate  # type: ignore[import-untyped]
    except ImportError:
        from okf_contract import validate as real_validate  # type: ignore[import-untyped]
    return real_validate


def _world_directories(staged: Path) -> tuple[Path, ...]:
    """Every ``mundos/<World>`` directory in the staged snapshot, discovered."""
    mundos = Path(staged) / MUNDOS_DIRNAME
    if not mundos.is_dir():
        return ()
    return tuple(sorted(
        (entry for entry in mundos.iterdir() if entry.is_dir()),
        key=lambda entry: entry.name,
    ))


def validate_staged_snapshot(
    staged_dir: Path,
    *,
    okf_validator: Callable[[str], Any] | None = None,
) -> RestoreValidation:
    """Validate a staged snapshot completely, BEFORE the first data-root write.

    In this exact order (13.2, SC-RS-2.1/2.2): the manifest is readable and its
    ``schema_version`` and ``checksum_algorithm`` are supported (both gated by
    the REAL ``Manifest.from_dict``); ``complete is True``; every entry is
    present with a matching size, then every digest is verified by the REAL
    ``verify_manifest`` using the manifest's own algorithm; every ``sqlite``
    entry passes ``PRAGMA integrity_check == "ok"`` and records ``ok``; and the
    OKF contract over ``mundos/<World>/**/*.md`` passes through the real
    ``okf_contract.validate``. Every failure names the offending path.
    """
    staged = Path(staged_dir)
    manifest_path = staged / SNAPSHOT_MANIFEST_PATH
    if not manifest_path.is_file():
        raise SnapshotIncompleteError(
            f"snapshot at {staged} has no {SNAPSHOT_MANIFEST_PATH}; "
            "an incomplete snapshot cannot be restored"
        )
    try:
        manifest = read_manifest(manifest_path)
    except ManifestError as exc:
        raise SnapshotValidationError(
            SNAPSHOT_MANIFEST_PATH, f"manifest is not usable: {exc}"
        ) from exc
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SnapshotValidationError(
            SNAPSHOT_MANIFEST_PATH, f"manifest cannot be read: {exc}"
        ) from exc

    if not manifest.complete:
        raise SnapshotIncompleteError(
            f"snapshot {manifest.snapshot_id!r} is marked incomplete; restore "
            "requires a COMPLETE snapshot"
        )

    # WARNING-1 fix: every manifest-supplied path is gated FIRST, before any read
    # or write. The manifest is attacker-influenced input; a crafted
    # ``sqlite[].path = "../../evil.sqlite3"`` used to pass validation, be read
    # from outside staging and written outside the data root. Both entry paths
    # (read by ``_first_missing_or_sized``/``verify_manifest`` and by the SQLite
    # copy-back) and sqlite paths are gated with the transport's own name rules,
    # then proved contained. Nothing outside the staging root is ever touched.
    for entry in manifest.entries:
        _gated_and_contained(staged, entry.path)
    for record in manifest.sqlite:
        _gated_and_contained(staged, record.path)

    broken = _first_missing_or_sized(manifest, staged)
    if broken is not None:
        raise SnapshotValidationError(
            broken, "manifest entry is missing or its size no longer matches"
        )
    try:
        bytes_verified = verify_manifest(manifest, root=staged)
    except (ManifestEntryMissingError, ChecksumMismatchError) as exc:
        raise SnapshotValidationError(
            _offending_entry(str(exc), manifest), str(exc)
        ) from exc
    except ManifestError as exc:
        raise SnapshotValidationError(None, str(exc)) from exc

    databases: list[str] = []
    for record in manifest.sqlite:
        if record.integrity != INTEGRITY_OK:
            raise SnapshotValidationError(
                record.path,
                f"manifest records integrity {record.integrity!r}, not "
                f"{INTEGRITY_OK!r}",
            )
        integrity = sqlite_integrity(_contained_path(staged, record.path))
        if integrity != INTEGRITY_OK:
            raise SnapshotValidationError(
                record.path, f"PRAGMA integrity_check returned {integrity!r}"
            )
        databases.append(record.path)

    validator = okf_validator or _default_okf_validator()
    okf_documents = 0
    worlds: list[str] = []
    for world_dir in _world_directories(staged):
        worlds.append(world_dir.name)
        for document in sorted(world_dir.rglob("*.md")):
            try:
                text = document.read_text(encoding="utf-8")
            except OSError as exc:
                raise SnapshotValidationError(
                    document.relative_to(staged).as_posix(),
                    f"OKF document is unreadable: {exc}",
                ) from exc
            result = validator(text)
            okf_documents += 1
            if not getattr(result, "ok", False):
                codes = ",".join(
                    str(getattr(issue, "code", "unknown"))
                    for issue in getattr(result, "issues", ())
                )
                raise SnapshotValidationError(
                    document.relative_to(staged).as_posix(),
                    f"OKF contract failure ({codes or 'not-an-okf-document'})",
                )

    return RestoreValidation(
        manifest=manifest,
        entries_verified=len(manifest.entries),
        bytes_verified=bytes_verified,
        databases=tuple(databases),
        okf_documents=okf_documents,
        worlds=tuple(worlds),
    )


# ---------------------------------------------------------------------------
# 13.6 — Conflict preview
# ---------------------------------------------------------------------------


def _inventory_files(data_root: Path) -> dict[str, EntryRecord]:
    """The current root's files as manifest-shaped records, cheaply.

    The inventory's own selection drives the set (never a literal list), and the
    engine's change rule is reused: a candidate is only hashed when its ``size``
    or ``mtime_ns`` differs, so a preview over a large root is not a full re-hash.
    """
    inventory = build_inventory(Path(data_root))
    records: dict[str, EntryRecord] = {}
    for relative in inventory.included:
        absolute = inventory.root / relative
        if absolute.is_dir():
            continue
        try:
            stat = absolute.stat()
        except OSError:
            continue
        records[relative] = EntryRecord(
            path=relative,
            kind="file",
            size=stat.st_size,
            sha256="",
            mtime_ns=stat.st_mtime_ns,
        )
    return records


def preview_conflicts(
    *,
    snapshot_id: str,
    staged_dir: Path,
    data_root: Path,
    manifest: Manifest | None = None,
) -> ConflictReport:
    """Compare the staged manifest against the current inventory (13.6).

    Divergence is REPORTED, never fatal — restoring is supposed to change the
    tree. ``counts`` covers added/modified/removed paths, ``examples`` caps at
    :data:`CONFLICT_EXAMPLE_LIMIT`, and ``blockers`` carries the two conditions
    that forbid the swap: a type mismatch at a member boundary, and a top-level
    member the restore would delete because it is not inside a restored member.

    A ``sqlite`` entry normally reports as ``modified``: the live database's
    bytes differ from the ``backup()`` copy the snapshot carries (that copy is a
    consistent cut, not a byte copy), and the restore does replace it.
    """
    staged = Path(staged_dir)
    root = Path(data_root)
    staged_manifest = manifest or read_manifest(staged / SNAPSHOT_MANIFEST_PATH)
    staged_entries = {entry.path: entry for entry in staged_manifest.entries}
    current = _inventory_files(root)

    added = sorted(set(current) - set(staged_entries))
    removed = sorted(set(staged_entries) - set(current))
    modified: list[str] = []
    for path in sorted(set(current) & set(staged_entries)):
        live = current[path]
        recorded = staged_entries[path]
        if live.size == recorded.size and live.mtime_ns == recorded.mtime_ns:
            continue  # unchanged by the engine's own size+mtime rule
        try:
            actual = digest_file(root / path, staged_manifest.checksum_algorithm)
        except OSError:
            modified.append(path)
            continue
        if actual != recorded.sha256:
            modified.append(path)

    examples = (
        tuple(ConflictExample(path, "added") for path in added)
        + tuple(ConflictExample(path, "modified") for path in modified)
        + tuple(ConflictExample(path, "removed") for path in removed)
    )

    staged_members = dict(_member_kinds(staged))
    current_members = dict(_member_kinds(root))
    blockers: list[str] = []
    for name in sorted(set(staged_members) & set(current_members)):
        if staged_members[name] != current_members[name]:
            blockers.append(
                f"member {name!r} is a {current_members[name]} in the data root "
                f"and a {staged_members[name]} in the snapshot"
            )
    for name in sorted(set(current_members) - set(staged_members)):
        blockers.append(
            f"member {name!r} would be deleted by the restore but is not "
            "inside a restored member"
        )

    return ConflictReport(
        snapshot_id=snapshot_id,
        counts=ConflictCounts(
            added=len(added), modified=len(modified), removed=len(removed)
        ),
        examples=examples,
        blockers=tuple(blockers),
    )


def _member_kinds(directory: Path) -> tuple[tuple[str, str], ...]:
    """``(name, kind)`` for the swap-eligible members of *directory*."""
    root = Path(directory)
    return tuple(
        (name, "dir" if (root / name).is_dir() else "file")
        for name in _swap_members(root)
    )


# ---------------------------------------------------------------------------
# 13.4 — Per-top-level-member atomic swap + rollback
# ---------------------------------------------------------------------------


def _present(path: Path) -> bool:
    """Existence test that also sees a broken symlink."""
    return path.exists() or path.is_symlink()


def _park_dir_for(data_root: Path, run_id: str, attempt: int) -> Path:
    """The park directory for *attempt* — inside the root, same volume."""
    suffix = "" if attempt <= 1 else f"-retry{attempt - 1}"
    return Path(data_root) / f"{PARK_DIR_PREFIX}{run_id}{suffix}"


def rollback_swap(
    swapped: tuple[str, ...] | list[str],
    parked: tuple[str, ...] | list[str],
    *,
    data_root: Path,
    staging_dir: Path,
    park_dir: Path,
    rename: Callable[[Path, Path], None] = os.rename,
) -> RollbackOutcome:
    """Move the staged-in members back to staging, then the parked ones home.

    Only renames are used — nothing is deleted, so a rollback can never lose a
    member. Undoing ``swapped`` first frees the name before the original is
    moved back. Failures are collected, not raised, because a rollback that stops
    halfway would be worse than one that reports what it could not restore.
    """
    root = Path(data_root)
    staging = Path(staging_dir)
    park = Path(park_dir)
    reverted: list[str] = []
    failures: list[tuple[str, str]] = []
    for name in reversed(tuple(swapped)):
        source = root / name
        if not _present(source):
            continue
        try:
            rename(source, staging / name)
        except OSError as exc:
            failures.append((name, str(exc)))
        else:
            reverted.append(name)
    for name in tuple(parked):
        source = park / name
        if not _present(source):
            continue
        try:
            rename(source, root / name)
        except OSError as exc:
            failures.append((name, str(exc)))
        else:
            reverted.append(name)
    return RollbackOutcome(tuple(reverted), tuple(failures))


def swap_in_staged_tree(
    staging_dir: Path,
    data_root: Path,
    *,
    run_id: str,
    rename: Callable[[Path, Path], None] = os.rename,
) -> SwapOutcome:
    """Swap every top-level member atomically, rolling back and retrying once.

    Park EVERY existing member into ``root/.demiurgos-old-<id>/`` by a
    same-volume ``os.rename`` first, then rename the staged members in. Both
    steps are per-member renames: ``os.replace`` cannot replace a non-empty
    directory on Windows, and the design forbids it for exactly that reason. The
    data root itself is never renamed and never removed.

    On a rename failure the rollback moves the swapped members back to staging
    and the parked members home, then the swap is retried once. A second failure
    raises :class:`RestoreSwapError` naming every member's state, so the caller
    records it and keeps the maintenance marker (SC-RS-3.3).
    """
    root = Path(data_root)
    staging = Path(staging_dir)
    root.mkdir(parents=True, exist_ok=True)
    staged_members = _swap_members(staging)
    existing_members = _swap_members(root)

    failure: RestoreSwapError | None = None
    park_dirs: list[Path] = []
    for attempt in range(1, SWAP_ATTEMPTS + 1):
        park = _park_dir_for(root, run_id, attempt)
        _assert_not_data_root(park, root)
        park.mkdir(parents=True, exist_ok=True)
        park_dirs.append(park)
        swapped: list[str] = []
        parked: list[str] = []
        try:
            for name in existing_members:
                source = root / name
                if _present(source):
                    rename(source, park / name)
                    parked.append(name)
            for name in staged_members:
                source = staging / name
                if _present(source):
                    rename(source, root / name)
                    swapped.append(name)
        except OSError as exc:
            rollback = rollback_swap(
                swapped,
                parked,
                data_root=root,
                staging_dir=staging,
                park_dir=park,
                rename=rename,
            )
            not_swapped = tuple(
                name for name in staged_members if name not in swapped
            )
            failure = RestoreSwapError(
                f"swap attempt {attempt} failed on member {name!r}: {exc}; "
                f"rolled back {len(rollback.reverted)} member(s); "
                f"staged members not swapped: {not_swapped}",
                failure=name,
                swapped=tuple(swapped),
                not_swapped=not_swapped,
                parked=tuple(
                    name for name in parked if _present(park / name)
                ),
                park_dirs=tuple(park_dirs),
                staging_dir=staging,
                rollback_failures=rollback.failures,
            )
            continue
        return SwapOutcome(
            swapped=tuple(swapped),
            park_dir=park,
            attempts=attempt,
            earlier_park_dirs=tuple(park_dirs[:-1]),
        )
    assert failure is not None  # the loop either returns or records a failure
    raise failure


def _rmtree_best_effort(path: Path) -> None:
    """Remove *path* recursively, never raising: a survivor is reported, not fatal."""
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def _drop_empty_park_dir(park: Path) -> str | None:
    """Remove an emptied park directory, or return its name if it survived.

    A park directory from an attempt that already rolled back holds nothing, so
    dropping it is pure cleanup. A NON-empty one may hold a member a rollback
    could not move home — it is never removed here, only reported, so the sweep
    at the next start (and a human) can see it.
    """
    if not park.is_dir():
        return None
    try:
        if any(park.iterdir()):
            return park.name
    except OSError:
        return park.name
    _rmtree_best_effort(park)
    return park.name if park.exists() else None


# ---------------------------------------------------------------------------
# 13.5 — SQLite copy-back, index regeneration, config revalidation
# ---------------------------------------------------------------------------


def capture_staged_databases(
    staged_dir: Path, manifest: Manifest
) -> dict[str, bytes]:
    """Read every staged database's bytes BEFORE the swap moves the member in.

    The swap relocates the ``data/`` member wholesale, so the staged database
    files no longer exist under the staging directory afterwards. Capturing them
    here lets the copy-back still run over the live databases, remove any stale
    sidecar and prove ``integrity_check`` on the restored file. The payload is
    bounded by the four included databases (12 KB–1.4 MB), which the SQLite
    snapshotter already holds in memory in the same way.
    """
    staged = Path(staged_dir)
    payloads: dict[str, bytes] = {}
    for record in manifest.sqlite:
        # Defence in depth: re-gate and re-prove containment on the read path,
        # even though ``validate_staged_snapshot`` already did so — this function
        # is also reachable directly, and nothing outside staging may be read.
        relative = _gated_and_contained(staged, record.path)
        source = _contained_path(staged, relative)
        if not source.is_file():
            raise SnapshotValidationError(
                record.path, "staged SQLite database disappeared before the swap"
            )
        payloads[record.path] = source.read_bytes()
    return payloads


def remove_sqlite_sidecars(database: Path) -> tuple[str, ...]:
    """Remove ``-wal``/``-shm`` beside *database*, never restoring them (13.5).

    A stale write-ahead log beside a restored database would be replayed on the
    next open and could re-introduce exactly the rows the snapshot does not
    contain. The sidecars are excluded from the inventory too, so they are never
    part of a snapshot in the first place.
    """
    removed: list[str] = []
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{database}{suffix}")
        if sidecar.exists():
            _unlink_quietly(sidecar)
            if not sidecar.exists():
                removed.append(sidecar.name)
    return tuple(removed)


def restore_databases(
    data_root: Path, payloads: Mapping[str, bytes]
) -> tuple[str, ...]:
    """Copy the staged databases over the live ones and verify each (13.5).

    Each file is written through a same-directory temp and ``os.replace``, after
    the stale ``-wal``/``-shm`` beside it are removed. The restored file must
    pass ``PRAGMA integrity_check`` or the restore aborts with the marker still in
    place — a corrupt database is never reported as restored.
    """
    root = Path(data_root)
    restored: list[str] = []
    for relative in sorted(payloads):
        # Defence in depth: the write path is gated with the transport's own
        # rules and proved contained under the data root BEFORE anything is
        # written, so a payload keyed by an escaping path can never write outside.
        safe_relative = _gated_and_contained(root, relative)
        target = _contained_path(root, safe_relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        remove_sqlite_sidecars(target)
        temp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex}")
        try:
            temp.write_bytes(payloads[relative])
            os.replace(temp, target)
        finally:
            _unlink_quietly(temp)
        integrity = sqlite_integrity(target)
        if integrity != INTEGRITY_OK:
            raise RestoreError(
                f"restored database {relative} failed integrity_check: "
                f"{integrity!r}"
            )
        restored.append(relative)
    return tuple(restored)


def _entity_graph_index(mundos_path: Path) -> Any:
    """The REAL ``wiki.graph_indexer.EntityGraphIndex``, imported lazily.

    Lazy for the same reason ``api_server`` does it lazily: the module lives in
    the ``wiki`` package and is reached as ``wiki.graph_indexer`` once the suite
    root is on ``sys.path``.
    """
    try:
        from wiki.graph_indexer import EntityGraphIndex  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RestoreError(
            "index regeneration needs the wiki package on sys.path "
            "(wiki.graph_indexer); import 'wiki' before restoring"
        ) from exc
    return EntityGraphIndex(mundos_path)


def _rescan_gallery(mundos: Path, worlds: tuple[str, ...]) -> tuple[int, int]:
    """Count the media assets under the two REAL per-world media bases.

    The gallery/media index is directory-derived (``api_server._get_media_bases``
    returns ``wiki/media`` and ``referencias/visuales/imagenes``), so regeneration
    is a rescan of exactly those bases — the same contract ``list_images`` reads.
    There is no persisted index to rebuild, and inventing one would create a
    second source of truth for the gallery.
    """
    assets = 0
    total = 0
    for world in worlds:
        for relative in GALLERY_MEDIA_BASES:
            base = mundos / world / relative
            if not base.is_dir():
                continue
            for root_dir, _dirs, names in os.walk(base):
                for name in names:
                    try:
                        total += (Path(root_dir) / name).stat().st_size
                    except OSError:
                        continue
                    assets += 1
    return assets, total


def rebuild_indexes(data_root: Path) -> IndexRebuildReport:
    """Rebuild the entity graph and rescan the gallery for every world (13.5).

    Each world discovered under ``mundos/`` is rebuilt through the real
    ``EntityGraphIndex`` (``build(world)`` is a full, read-only scan), and the
    gallery media bases are rescanned. ``ReindexCoordinator``, the API's
    per-create reconciler, is deliberately not used: it reconciles ONE created
    file against its digest, whereas a restore invalidates every index at once and
    must rebuild from scratch.
    """
    root = Path(data_root)
    mundos = root / MUNDOS_DIRNAME
    worlds = tuple(
        entry.name
        for entry in sorted(mundos.iterdir(), key=lambda item: item.name)
        if entry.is_dir()
    ) if mundos.is_dir() else ()
    graph: dict[str, int] = {}
    if worlds:
        index = _entity_graph_index(mundos)
        for world in worlds:
            graph[world] = int(index.build(world))
    assets, total = _rescan_gallery(mundos, worlds)
    return IndexRebuildReport(
        worlds=worlds,
        graph_entities=graph,
        gallery_assets=assets,
        gallery_bytes=total,
    )


def revalidate_config_files(data_root: Path) -> tuple[str, ...]:
    """Re-read the non-secret config the snapshot carries, refusing broken JSON.

    ``config/`` is itself backed up because it is author configuration, and the
    exclusion table keeps secrets out of it (``.env``, ``*.key``, ``*.pem``,
    ``credentials*``). A restored ``.json`` document that no longer parses is
    reported naming its path, so a broken configuration is never silently
    accepted.
    """
    config = Path(data_root) / CONFIG_DIRNAME
    if not config.is_dir():
        return ()
    validated: list[str] = []
    for path in sorted(config.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(Path(data_root)).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RestoreError(f"config {relative} is unreadable: {exc}") from exc
        if path.suffix.lower() == ".json":
            try:
                json.loads(text)
            except ValueError as exc:
                raise RestoreError(
                    f"config {relative} is not valid JSON: {exc}"
                ) from exc
        validated.append(relative)
    return tuple(validated)


# ---------------------------------------------------------------------------
# 13.3–13.5 — The restore orchestration
# ---------------------------------------------------------------------------


def _write_last_write(
    transport: BackupTransport,
    *,
    status: str,
    snapshot_id: str,
    current_entries: int,
    error: str | None = None,
    warnings: tuple[str, ...] = (),
) -> None:
    """Record the outcome in ``meta/last-write.json`` (a LOCAL write record).

    Best-effort: when the destination is unreachable the original restore error
    must still surface, so a bookkeeping failure is swallowed here rather than
    replacing the real one. ``snapshot_id`` rides on the error/warning text, since
    ``LastWriteRecord`` deliberately has no field for it.
    """
    try:
        destination = transport.probe().path
    except Exception:  # noqa: BLE001 — bookkeeping never masks the real error
        destination = None
    try:
        transport.write_meta(
            LAST_WRITE_META_NAME,
            LastWriteRecord(
                last_run_at=_utc_stamp(),
                status=status,
                destination=destination,
                current_entries=current_entries,
                error=error,
                warnings=warnings,
            ).to_dict(),
        )
    except (OSError, TransportError):
        pass


def _quiesce(
    engine: Any | None, data_root: Path, *, run_id: str, snapshot_id: str
) -> None:
    """Raise the write barrier BEFORE the swap, marker included (SC-RS-3.2)."""
    if engine is not None and hasattr(engine, "quiesce"):
        engine.quiesce()
    if not maintenance_marker_path(data_root).exists():
        write_maintenance_marker(
            data_root, run_id=run_id, snapshot_id=snapshot_id
        )


def _resume(engine: Any | None, data_root: Path) -> None:
    """Clear the barrier after a successful restore and re-notify the engine."""
    if engine is not None and hasattr(engine, "resume"):
        engine.resume()
    clear_maintenance_marker(data_root)
    try:
        notify_data_changed()
    except Exception:  # noqa: BLE001 — a notification is never fatal
        pass


def restore_snapshot(
    *,
    transport: BackupTransport,
    data_root: Path,
    snapshot_id: str,
    engine: Any | None = None,
    run_id: str | None = None,
    rename: Callable[[Path, Path], None] = os.rename,
    reindex: Callable[[Path], IndexRebuildReport] | None = None,
    config_revalidator: Callable[[Path], tuple[str, ...]] | None = None,
    okf_validator: Callable[[str], Any] | None = None,
    allow_blockers: bool = False,
) -> RestoreResult:
    """Restore the whole data root from one COMPLETE snapshot (13.1–13.6).

    Whole-root restore only: there is no partial-member mode, so the restored root
    equals the snapshot for every member the backup covers, and a member the
    exclusion table refuses is left untouched. The seams (``rename``,
    ``reindex``, ``config_revalidator``, ``okf_validator``, ``engine``) let the
    suite simulate a mid-swap failure and stay hermetic; the defaults are the real
    implementations.
    """
    root = Path(data_root)
    run = run_id or uuid.uuid4().hex[:12]
    staging = staging_directory(root, run)
    _assert_same_volume(staging.parent, root)

    transport.fetch(SnapshotRef(snapshot_id=snapshot_id), staging)
    try:
        validation = validate_staged_snapshot(
            staging, okf_validator=okf_validator
        )
        conflicts = preview_conflicts(
            snapshot_id=snapshot_id,
            staged_dir=staging,
            data_root=root,
            manifest=validation.manifest,
        )
        if conflicts.blocked and not allow_blockers:
            raise RestoreBlockedError(conflicts.blockers)
        payloads = capture_staged_databases(staging, validation.manifest)
    except BaseException:
        # Validation or the conflict gate refused the snapshot: the data root was
        # never written, and staging holds nothing worth keeping.
        shutil.rmtree(staging, ignore_errors=True)
        raise

    _quiesce(engine, root, run_id=run, snapshot_id=snapshot_id)
    swapped: tuple[str, ...] = ()
    try:
        swap = swap_in_staged_tree(staging, root, run_id=run, rename=rename)
        swapped = swap.swapped
        databases = restore_databases(root, payloads)
        indexes = (reindex or rebuild_indexes)(root)
        config_files = (config_revalidator or revalidate_config_files)(root)
    except BaseException as exc:
        # The marker stays: the API is read-only until this is explicitly
        # resolved, and last-write.json records exactly what moved.
        _write_last_write(
            transport,
            status="failed",
            snapshot_id=snapshot_id,
            current_entries=len(swapped),
            error=f"restore {snapshot_id} failed: {exc}",
        )
        raise

    warnings: list[str] = []
    _rmtree_best_effort(swap.park_dir)
    if swap.park_dir.exists():
        warnings.append(f"{RESTORE_LEFTOVER_WARNING}:{swap.park_dir.name}")
    for stale in swap.earlier_park_dirs:
        name = _drop_empty_park_dir(stale)
        if name is not None:
            warnings.append(f"{RESTORE_LEFTOVER_WARNING}:{name}")
    _resume(engine, root)
    status = "ok_with_warnings" if warnings else "ok"
    _write_last_write(
        transport,
        status=status,
        snapshot_id=snapshot_id,
        current_entries=validation.manifest.totals.entries,
        warnings=tuple(warnings),
    )
    shutil.rmtree(staging, ignore_errors=True)
    return RestoreResult(
        snapshot_id=snapshot_id,
        staging_dir=staging,
        validation=validation,
        conflicts=conflicts,
        swap=swap,
        databases=databases,
        indexes=indexes,
        config_files=config_files,
        status=status,
        warnings=tuple(warnings),
    )


def _assert_same_volume(one: Path, other: Path) -> None:
    """Prove two paths share a volume, using the nearest existing ancestor.

    A same-volume rename is what makes the per-member swap atomic; staging on a
    different filesystem would silently degrade the swap into a copy, so it is
    refused before the fetch.
    """
    if _volume_of(Path(one)) != _volume_of(Path(other)):
        raise RestoreError(
            f"restore staging on {one} is not on the same volume as {other}; "
            "a same-volume rename is required for the atomic swap"
        )


def _volume_of(path: Path) -> int:
    """``st_dev`` of *path* or of its nearest existing ancestor."""
    current = Path(path)
    while not current.exists() and current.parent != current:
        current = current.parent
    return current.stat().st_dev


def _unlink_quietly(path: Path) -> None:
    """Remove *path*, tolerating its absence."""
    try:
        Path(path).unlink()
    except OSError:
        pass
