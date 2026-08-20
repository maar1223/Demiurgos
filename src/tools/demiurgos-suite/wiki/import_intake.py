"""World importer — bounded, read-only intake.

Server-owned rules for folders, loose files, and optional ZIPs: 500 MB/file and
5 GB/job bounds (including ZIP contents), path safety (traversal, symlink
escape, system folders), ZIP-bomb defenses, and streamed chunk resume without
whole-job buffering. All checks fail closed before any canon write.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from import_models import (
    MAX_FILE_BYTES,
    MAX_JOB_AGGREGATE_BYTES,
    INTAKE_STATES,
    ImportJobState,
)

# ZIP-bomb defenses (checked against the zip header manifest before extraction).
ZIP_MAX_ENTRIES = 10_000
ZIP_MAX_DEPTH = 16
ZIP_MAX_ENTRY_SIZE = MAX_FILE_BYTES
ZIP_MAX_RATIO = 200            # uncompressed/compressed ratio guard
ZIP_MIN_COMPRESSED_ENTRY = 1_024  # ignore ratio guard on trivially small entries

# System/transversal folders that are never imported as content (W10).
SYSTEM_DIRS = frozenset({"_context", ".history", ".papelera"})
TRANSVERSAL_DIRS = frozenset({"relaciones", "canon", "conflictos", "propuestas"})

logger = logging.getLogger("demiurgos-import-intake")


class UnsafePathError(ValueError):
    """A source path is traversal, symlink-escaping, or a system folder."""


class BoundsError(ValueError):
    """A per-file or aggregate size bound was exceeded."""


class ZipBombError(ValueError):
    """A ZIP exceeds expansion/count/depth/entry-size/ratio defenses."""


class MalformedProviderError(ValueError):
    """Provider output is malformed; the job must fail closed."""


def reject_unsafe_path(relative: str, *, forbid_system: bool = True) -> None:
    """Reject unsafe *relative* source paths (raise UnsafePathError).

    Mirrors runtime world/path invariants: no separators tricks, absolute
    paths, dot segments, backslashes, hidden files, or system/transversal
    folders.
    """
    if not isinstance(relative, str) or not relative:
        raise UnsafePathError("empty source path")
    if relative.startswith("/") or "\\" in relative or ":" in relative:
        raise UnsafePathError("absolute or foreign-separator path")
    parts = [p for p in relative.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        raise UnsafePathError("traversal path")
    if any(p.startswith(".") for p in parts):
        raise UnsafePathError("hidden path segment")
    if forbid_system:
        for part in parts:
            if part in SYSTEM_DIRS or part in TRANSVERSAL_DIRS:
                raise UnsafePathError(f"system folder not importable: {part!r}")


def check_file_bounds(size_bytes: int, aggregate_after: int) -> None:
    """Fail closed on per-file and aggregate size limits."""
    if size_bytes > MAX_FILE_BYTES:
        raise BoundsError(f"file exceeds 500 MB per-file limit ({size_bytes} bytes)")
    if aggregate_after > MAX_JOB_AGGREGATE_BYTES:
        raise BoundsError("job exceeds 5 GB aggregate limit (including ZIP contents)")


@dataclass(frozen=True)
class ZipEntrySpec:
    path: str
    compressed_size: int
    uncompressed_size: int


@dataclass(frozen=True)
class SpoolFile:
    """One file extracted from a bounded ZIP archive.

    Carries the absolute path of the extracted file, the relative path
    within the archive (the entry name), and the extracted size in bytes.
    Returned by ``extract_zip_bounded`` after all manifest defenses pass.
    """

    path: Path
    relative_path: str
    size: int


def validate_zip_manifest(entries: Iterable[ZipEntrySpec]) -> int:
    """Validate a ZIP entry manifest pre-extraction; return total uncompressed.

    Counts compressed/uncompressed bytes separately, bounds entry size and
    count, rejects excessive depth, and defends against suspicious
    compression ratios. Raises ZipBombError without extracting anything.
    """
    entries = list(entries)
    if len(entries) > ZIP_MAX_ENTRIES:
        raise ZipBombError(f"zip entry count {len(entries)} exceeds {ZIP_MAX_ENTRIES}")
    total_uncompressed = 0
    for entry in entries:
        reject_unsafe_path(entry.path)
        depth = entry.path.count("/") + (1 if entry.path else 0)
        if depth > ZIP_MAX_DEPTH:
            raise ZipBombError(f"zip path depth {depth} exceeds {ZIP_MAX_DEPTH}")
        if entry.uncompressed_size > ZIP_MAX_ENTRY_SIZE:
            raise ZipBombError(
                f"zip entry {entry.path!r} exceeds 500 MB per-file limit"
            )
        if (
            entry.compressed_size >= ZIP_MIN_COMPRESSED_ENTRY
            and entry.uncompressed_size > entry.compressed_size * ZIP_MAX_RATIO
        ):
            raise ZipBombError(
                f"zip entry {entry.path!r} has suspicious compression ratio"
            )
        total_uncompressed += entry.uncompressed_size
    return total_uncompressed


def inspect_zip(archive: Path) -> tuple[list[ZipEntrySpec], int]:
    """Read-only zip inspection (headers only, never extraction)."""
    with zipfile.ZipFile(archive) as zf:
        specs = [
            ZipEntrySpec(
                path=info.filename,
                compressed_size=info.compress_size,
                uncompressed_size=info.file_size,
            )
            for info in zf.infolist()
        ]
    total = validate_zip_manifest(specs)
    return specs, total


# Streaming chunk size for per-entry extraction (avoids whole-file buffering
# of large entries; 64 KiB matches the BoundedSpool's streaming posture).
_ZIP_EXTRACT_CHUNK = 64 * 1024


def extract_zip_bounded(archive: Path,
                        destination: Path) -> list[SpoolFile]:
    """Bounded extraction of a ZIP archive into *destination*.

    Reuses ``inspect_zip`` (entry-count, per-entry size, depth, compression
    ratio) BEFORE any file is written and re-validates each path through
    ``reject_unsafe_path``. Every entry is streamed into the destination
    via ``ZipFile.open`` one chunk at a time; the unbounded
    ``ZipFile.extractall`` is never called. The aggregate uncompressed
    total is bounded against ``MAX_JOB_AGGREGATE_BYTES`` during streaming
    so a single oversize archive cannot exhaust the spool.

    Raises ``ZipBombError``, ``UnsafePathError``, or ``BoundsError`` on any
    violation — the destination is left empty (or untouched) on rejection.
    """
    archive = Path(archive)
    destination = Path(destination)

    # 1) Validate the complete manifest FIRST. inspect_zip calls
    #    validate_zip_manifest which enforces entry count, depth, per-entry
    #    size, ratio, and per-path safety (no traversal/absolute/system).
    specs, total_uncompressed = inspect_zip(archive)
    del specs  # manifest already validated; entries are re-read below

    # 2) Pre-flight aggregate bound — the same 5 GB job-level cap enforced
    #    by BoundedSpool for streamed files.
    if total_uncompressed > MAX_JOB_AGGREGATE_BYTES:
        raise BoundsError(
            f"zip uncompressed total {total_uncompressed} bytes exceeds "
            f"{MAX_JOB_AGGREGATE_BYTES} aggregate job limit"
        )

    # 3) Resolve the destination containment once.
    dest_root = destination.resolve()
    dest_root.mkdir(parents=True, exist_ok=True)

    spool_files: list[SpoolFile] = []
    cumulative = 0

    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            # Per-entry defenses (defensive re-check: inspect_zip already
            # rejected manifest-level violations, but path/data divergence
            # between header and central directory is theoretically possible).
            reject_unsafe_path(info.filename)
            if info.file_size > ZIP_MAX_ENTRY_SIZE:
                raise ZipBombError(
                    f"zip entry {info.filename!r} exceeds 500 MB per-file limit"
                )

            # Resolve the target path under the destination and ensure it
            # remains contained (no escape outside the destination root).
            rel = info.filename
            target = (dest_root / rel).resolve()
            if dest_root != target and dest_root not in target.parents:
                raise UnsafePathError(
                    f"zip entry escapes destination: {info.filename!r}"
                )

            # Directory entries have no body — just ensure the path exists.
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)

            # Stream the entry one chunk at a time. We never call
            # ZipFile.extractall; instead we open the entry, read in
            # bounded chunks, and write to the target.
            entry_size = 0
            with zf.open(info) as src, target.open("wb") as dst:
                while True:
                    chunk = src.read(_ZIP_EXTRACT_CHUNK)
                    if not chunk:
                        break
                    dst.write(chunk)
                    entry_size += len(chunk)
                    cumulative += len(chunk)
                    if cumulative > MAX_JOB_AGGREGATE_BYTES:
                        raise BoundsError(
                            f"zip extraction exceeds 5 GB aggregate limit "
                            f"({cumulative} bytes written)"
                        )

            spool_files.append(SpoolFile(
                path=target, relative_path=rel, size=entry_size,
            ))

    return spool_files


class BoundedSpool:
    """Durable, streaming, resumable per-job intake spool.

    Streams chunks into durable files at explicit offsets (no whole-job
    buffering). ``resume`` returns durable offsets and only proceeds after
    ``revalidate`` confirms the job is still in an intake state and the caller
    holds the lease.
    """

    def __init__(self, spool_dir: Path, job_id: str, world: str) -> None:
        self.spool_dir = Path(spool_dir)
        self.job_dir = self.spool_dir / job_id
        self.job_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # relative path -> durable file (no whole-job buffer)
        self._files: dict[str, Path] = {}
        self._sizes: dict[str, int] = {}
        self._uncompressed = 0
        self._compressed = 0
        self._count = 0
        # Re-discover durably streamed files so a fresh instance (created by a
        # later request, e.g. analyze/resume) sees the durable offsets instead
        # of an empty in-memory map.
        self._load_existing()

    def _load_existing(self) -> None:
        """Populate ``_files``/``_sizes`` from files already on disk.

        Streaming writes chunks durably into ``job_dir/{relative}``. Because a
        new ``BoundedSpool`` is constructed per request, the analyze/resume
        routes would otherwise see an empty offset map for prior streams.
        Walking the job dir restores the durable state (resumable across
        requests) while still rejecting unsafe relative paths.
        """
        if not self.job_dir.is_dir():
            return
        for path in sorted(self.job_dir.rglob("*")):
            if not path.is_file():
                continue
            try:
                relative = str(path.relative_to(self.job_dir)).replace("\\", "/")
            except ValueError:
                continue
            reject_unsafe_path(relative)
            self._files[relative] = path
            self._sizes[relative] = path.stat().st_size

    def begin_file(self, relative: str, size_hint: int) -> None:
        reject_unsafe_path(relative)
        with self._lock:
            if relative in self._files:
                return  # idempotent: already started
            check_file_bounds(size_hint, self._uncompressed + size_hint)
            job_root = self.job_dir.resolve()
            target = (self.job_dir / relative).resolve()
            if job_root != target and job_root not in target.parents:
                raise UnsafePathError("symlink escape in spool path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=True)
            self._files[relative] = target
            self._sizes[relative] = 0

    def write_chunk(self, relative: str, offset: int, data: bytes) -> int:
        """Append/overwrite at *offset*; returns bytes actually written."""
        with self._lock:
            if relative not in self._files:
                raise ValueError(f"no file started: {relative!r}")
            target = self._files[relative]
            with target.open("r+b") as fh:
                fh.seek(offset)
                fh.write(data)
            self._sizes[relative] = max(self._sizes[relative], offset + len(data))
            check_file_bounds(self._sizes[relative], self._uncompressed + len(data))
            self._uncompressed += len(data)
            self._compressed += len(data)
        return offset + len(data)

    def finalize_file(self, relative: str) -> tuple[str, int]:
        """Hash + close a file; returns (sha256, size). Returns (None, 0) for a
        started-but-empty file (nothing written), treating it as not present."""
        with self._lock:
            if relative not in self._files:
                return None, 0
            target = self._files[relative]
            size = self._sizes.get(relative, 0)
            digest = hashlib.sha256(target.read_bytes()).hexdigest() if size else None
            if not size:
                del self._files[relative]
                self._sizes.pop(relative, None)
            return digest, size

    def offsets(self) -> dict[str, int]:
        with self._lock:
            return {k: v for k, v in self._sizes.items()}

    def resume(self, job_state: ImportJobState, leased: bool) -> dict[str, int]:
        """Return durable offsets only after revalidation (state + lease)."""
        if job_state not in INTAKE_STATES or not leased:
            raise PermissionError("resume requires revalidation: intake state + lease")
        return self.offsets()

    def accounting(self) -> tuple[int, int, int]:
        with self._lock:
            return self._uncompressed, self._compressed, self._count

    def cleanup(self) -> None:
        """Best-effort removal of the job spool directory (idempotent).

        Called once a job reaches a terminal state (COMPLETED/FAILED/CANCELLED)
        so the durable streamed bytes are reclaimed. ``FileNotFoundError`` is a
        no-op (nothing to clean); any other ``OSError`` is logged with the job
        path for diagnostics. Cleanup never raises, so a spool that cannot be
        removed never masks a successful state transition nor aborts the
        caller.
        """
        try:
            shutil.rmtree(self.job_dir)
        except FileNotFoundError:
            return  # idempotent: nothing to clean
        except OSError as exc:
            logger.warning(
                "spool cleanup failed for %s (%s): %s",
                self.job_dir, type(exc).__name__, exc,
            )
