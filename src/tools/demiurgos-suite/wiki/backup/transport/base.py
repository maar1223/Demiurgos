# -*- coding: utf-8 -*-
"""Transport seam for the backup engine (REQ-BE-8).

This module defines the CONTRACT only: the result dataclasses, the two typed
errors, and the :class:`BackupTransport` protocol the engine drives. It holds no
implementation and no path logic — ``FolderTransport`` (WU-5/WU-6) supplies the
local-folder implementation, and a later transport can be added without
reworking the engine.

**Deliberate structural absence (REQ-BE-10.1).** The protocol has no
delete-at-destination verb and no ``sync``/``mirror`` verb. The engine's
non-destructiveness is a property of this SHAPE, not of a caller's discipline:
a future transport cannot reintroduce the retired destructive ``rclone sync``
mirror without changing this contract. The only deletion in the system is
:meth:`BackupTransport.prune`, which removes policy-expired snapshots from the
destination and never touches ``current/``.

**Payload typing.** :meth:`BackupTransport.publish_current` and
:meth:`BackupTransport.publish_snapshot` receive the staged payload defined by
``backup/staging.py`` (WU-8). That module lands after this contract, so the
payload is typed opaquely as :data:`typing.Any` here. This keeps the contract
module free of dependencies on later slices; the staging slice tightens the
annotation when it exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class TargetCapabilities:
    """What ``probe()`` learned about a destination BEFORE any byte is written.

    ``mode_hint`` is the sync-folder classification consumed by the write gate
    (REQ-SF-3, WU-12): ``"mirrored"``, ``"streaming"`` or ``"unknown"``. A
    verified streaming target reports ``writable=False`` so no run publishes
    into a cache that may be cleared or corrupted.
    """

    kind: str
    path: str
    writable: bool
    same_volume_as_data_root: bool
    mode_hint: str


@dataclass(frozen=True)
class SnapshotInfo:
    """One destination snapshot as ``list_snapshots()`` reports it.

    Derived from the real directory listing, never from a manifest, so a
    partially synced snapshot is visible as ``complete=False``.
    """

    snapshot_id: str
    complete: bool
    entries: int
    bytes: int


@dataclass(frozen=True)
class PublishResult:
    """Outcome of a publish: entries written, entries skipped and bytes written."""

    published: int
    skipped: int
    bytes: int


@dataclass(frozen=True)
class PruneResult:
    """Outcome of a prune: ids removed, and ``(id, error)`` pairs that were not.

    A failed deletion is never reported as pruned — its id stays on the
    destination and the error is surfaced (REQ-BE-7).
    """

    deleted: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FetchResult:
    """Where a restore staged a snapshot and what it copied."""

    dest_dir: Path
    entries: int
    bytes: int


@dataclass(frozen=True)
class SnapshotRef:
    """Opaque handle to a snapshot the caller wants to fetch."""

    snapshot_id: str


class TransportError(RuntimeError):
    """A transport operation failed (I/O, lock, layout, or an unsafe name)."""


class SnapshotIncompleteError(TransportError):
    """A snapshot is missing entries or fails validation.

    Raised before any write, so an incomplete snapshot — for example one from a
    partially synced folder — aborts a restore without touching the data root.
    """


@runtime_checkable
class BackupTransport(Protocol):
    """The only surface the engine may drive (REQ-BE-8).

    Exactly nine verbs. There is no delete-at-destination verb and no ``sync``
    verb by design (REQ-BE-10.1). ``@runtime_checkable`` lets a conformance
    check prove a class exposes every verb, so a transport missing one fails at
    the seam instead of at the first call.
    """

    def probe(self) -> TargetCapabilities:
        """Capabilities and the write gate for the destination. Writes no bytes."""
        ...

    def ensure_layout(self) -> None:
        """Create the backup tree idempotently; safe to call on every run."""
        ...

    def publish_current(
        self, staged: Any, *, manifest: Mapping[str, Any]
    ) -> PublishResult:
        """Add or overwrite ``current/`` entries. Never deletes, never mirrors."""
        ...

    def publish_snapshot(self, snapshot_id: str, staged: Any) -> PublishResult:
        """Publish an immutable snapshot. Fails if ``snapshot_id`` already exists."""
        ...

    def prune(self, snapshot_ids: Sequence[str]) -> PruneResult:
        """Delete policy-expired snapshots. The only deletion verb (REQ-BE-7)."""
        ...

    def list_snapshots(self) -> list[SnapshotInfo]:
        """List the snapshots actually present, with their completion status."""
        ...

    def read_meta(self, name: str) -> Mapping[str, Any] | None:
        """Read a ``meta/`` document, or ``None`` when it does not exist yet."""
        ...

    def write_meta(self, name: str, payload: Mapping[str, Any]) -> None:
        """Write a ``meta/`` document atomically."""
        ...

    def fetch(self, snapshot_ref: SnapshotRef, dest_dir: Path) -> FetchResult:
        """Stage a snapshot into ``dest_dir`` for restore. Never writes the data root."""
        ...
