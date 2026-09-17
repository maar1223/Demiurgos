# -*- coding: utf-8 -*-
"""Staging — the staged set, the transport's temp names, and the start-up sweep.

Three responsibilities, one module (WU-8b):

* :func:`stage_inventory` turns an :class:`~backup.inventory.Inventory` into the
  set the transport publishes: the destination-relative path of every selected
  FILE. The inventory is the ONLY source of the set (REQ-BE-2, SC-BE-2.1) — this
  function iterates ``inventory.included`` and never walks the data root again.
  Paths pass through unchanged, because the transport owns NFC normalization and
  collision refusal (REQ-BE-9); staging never invents a spelling (REQ-CDL-2).
  A directory is not an entry — it is implied by the files beneath it, exactly
  as the manifest treats it.
* :func:`temp_name` / :func:`snapshot_temp_name` are the ONE pair of helpers for
  the transport's temp convention, so its shape lives in a single place and can
  never drift between the write path and the sweep. They reproduce
  ``FolderTransport``'s existing names exactly: ``<final>.tmp-<uuid>`` for a file
  written beside its destination, and ``.<id>.tmp-<uuid>`` for a snapshot's
  sibling temp directory. Neither is ever a final name (SC-BE-3.3, REQ-BE-4).
* :func:`sweep_stale_temps` removes the residue an interrupted run leaves —
  temp-named files anywhere in the tree, temp-named snapshot directories under
  ``snapshots/`` — and REPORTS residue older than 24 h through
  :meth:`SweepReport.warnings`, which the run records in ``last-write.json``.
  The clock is injected, so the 24 h boundary is testable without waiting.

**Final names are never swept.** A published file, and a published
``snapshots/<id>/`` directory, carry no temp marker; on top of that the sweep
never descends into a published snapshot, so immutability holds even if the
data itself contained a ``*.tmp-*`` name (REQ-BE-4, SC-BE-4.1).
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backup.inventory import Inventory

#: The tree's snapshot directory (REQ-BE-1). Temp snapshot directories are its
#: direct ``.<id>.tmp-<uuid>`` children.
SNAPSHOTS_DIRNAME = "snapshots"

#: The marker every transport temp name carries, immediately before its UUID.
TEMP_MARKER = ".tmp-"

#: Residue at least this old is REPORTED in ``last-write.json``, never swept
#: silently (design §3: "a sweep older than 24 h is reported").
STALE_REPORT_SECONDS = 24 * 60 * 60


def is_temp_name(name: str) -> bool:
    """True when *name* is a transport temp name — ``*.tmp-<uuid>`` (SC-BE-3.3).

    The suffix after the marker must be non-empty, mirroring the ``*.tmp-*``
    glob: a name that merely ends in ``.tmp-`` is not a temp.
    """
    _, marker, suffix = name.rpartition(TEMP_MARKER)
    return bool(marker) and bool(suffix)


def temp_name(final_name: str, *, token: str | None = None) -> str:
    """``<final_name>.tmp-<uuid>`` — the file temp written beside its destination.

    ``token`` is injectable so a test can assert the exact name; it defaults to
    the same ``uuid4().hex`` style ``FolderTransport`` already uses.
    """
    return f"{final_name}{TEMP_MARKER}{token or uuid.uuid4().hex}"


def snapshot_temp_name(snapshot_id: str, *, token: str | None = None) -> str:
    """``.<snapshot_id>.tmp-<uuid>`` — the snapshot's sibling temp directory.

    The leading dot and the same UUID suffix are ``FolderTransport``'s existing
    conventions; this helper exists so the shape is never re-typed.
    """
    return f".{snapshot_id}{TEMP_MARKER}{token or uuid.uuid4().hex}"


@dataclass(frozen=True)
class StagedEntry:
    """One staged FILE: its destination-relative path and its source on disk."""

    path: str
    source: Path


@dataclass(frozen=True)
class StagedSet:
    """The files the transport publishes, at their inventory-selected paths."""

    entries: tuple[StagedEntry, ...]

    def paths(self) -> tuple[str, ...]:
        """Every destination-relative path in the set, in inventory order."""
        return tuple(entry.path for entry in self.entries)


def stage_inventory(inventory: Inventory) -> StagedSet:
    """The staged set for *inventory* — exactly the files it selected.

    The inventory is the only source (REQ-BE-2, SC-BE-2.1): the data root is not
    re-scanned, so a file created after the inventory was built cannot appear
    here. A selected directory is skipped — it is implied by the files beneath
    it. A path is never rewritten: the transport NFC-normalizes and refuses
    collisions (REQ-BE-9, SC-BE-9.1).
    """
    entries: list[StagedEntry] = []
    for relative in inventory.included:
        source = inventory.root / relative
        if source.is_dir():
            continue
        entries.append(StagedEntry(path=relative, source=source))
    return StagedSet(tuple(entries))


@dataclass(frozen=True)
class SweptTemp:
    """One removed piece of residue: its tree-relative path, kind and age."""

    path: str
    kind: str
    age_seconds: float


@dataclass(frozen=True)
class SweepReport:
    """What the start-up sweep removed, and which of it must be reported."""

    swept: tuple[SweptTemp, ...] = ()

    def warnings(self) -> tuple[str, ...]:
        """``last-write.json`` warnings for residue older than 24 h (design §3).

        Younger residue is still removed — the sweep's job is to clear what an
        interrupted run left; its age is only what makes it noteworthy.
        """
        return tuple(
            f"sweep-stale-tmp:{entry.path}"
            for entry in self.swept
            if entry.age_seconds >= STALE_REPORT_SECONDS
        )


def sweep_stale_temps(
    tree_root: Path, *, now: Callable[[], float] = time.time
) -> SweepReport:
    """Remove temp residue under *tree_root*, reporting residue older than 24 h.

    *tree_root* is the backup tree root (``<chosen folder>/Demiurgos/``). Files
    whose name carries the temp marker are removed wherever they sit — they are
    written beside their destination, so they can be nested inside ``current/``.
    Temp-named directories are removed recursively, but only as direct children
    of ``snapshots/``, which is where the transport creates them; the sweep
    never descends into a published snapshot, so immutability is untouched
    (REQ-BE-4, SC-BE-4.1). Removal is best-effort: a locked residue is left for
    the next start rather than aborting the run, and it is not reported as swept.

    ``now`` is injected (epoch seconds) so the 24 h boundary is exercised
    without real waiting; it is never read from the system clock inside.
    """
    root = Path(tree_root)
    if not root.is_dir():
        return SweepReport()
    snapshots_dir = root / SNAPSHOTS_DIRNAME
    swept: list[SweptTemp] = []

    if snapshots_dir.is_dir():
        for entry in sorted(snapshots_dir.iterdir()):
            if entry.is_dir() and is_temp_name(entry.name):
                removed = _sweep_dir(entry, root, now)
                if removed is not None:
                    swept.append(removed)

    for current, dirnames, filenames in os.walk(root):
        if Path(current) == snapshots_dir:
            # Published snapshots are immutable, and temp dirs are done above.
            dirnames[:] = []
        else:
            dirnames[:] = [name for name in dirnames if not is_temp_name(name)]
        for name in filenames:
            if not is_temp_name(name):
                continue
            removed = _sweep_file(Path(current) / name, root, now)
            if removed is not None:
                swept.append(removed)

    return SweepReport(tuple(sorted(swept, key=lambda entry: entry.path)))


def _age_seconds(path: Path, now: Callable[[], float]) -> float:
    """The age of *path* from its mtime; 0.0 when the stat is unreadable."""
    try:
        return now() - path.stat().st_mtime
    except OSError:
        return 0.0


def _relative(path: Path, root: Path) -> str:
    """*path* relative to *root*, as a POSIX string for the report."""
    return path.relative_to(root).as_posix()


def _sweep_file(path: Path, root: Path, now: Callable[[], float]) -> SweptTemp | None:
    """Remove one temp file, or ``None`` when it could not be removed."""
    age = _age_seconds(path, now)
    try:
        path.unlink()
    except OSError:
        return None
    return SweptTemp(_relative(path, root), "file", age)


def _sweep_dir(path: Path, root: Path, now: Callable[[], float]) -> SweptTemp | None:
    """Remove one temp directory recursively, or ``None`` when it survived."""
    age = _age_seconds(path, now)
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        return None
    return SweptTemp(_relative(path, root), "snapshot_dir", age)
