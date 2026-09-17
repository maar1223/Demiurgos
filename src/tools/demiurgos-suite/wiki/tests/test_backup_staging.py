# -*- coding: utf-8 -*-
"""Staging tests for WU-8b: staged set, temp naming, and the start-up sweep.

Covers REQ-BE-3 / SC-BE-3.3 (a temp name is never a final name), REQ-BE-4 /
SC-BE-4.1 (a published snapshot is never modified), and REQ-BE-2 / SC-BE-2.1
(the staged set comes from the inventory, never a second disk scan). Hermetic:
every case builds its own ``tmp_path`` data root and backup tree; the real data
root is never read and no pointer is consulted. The sweep's clock is injected,
so the 24 h boundary is exercised without a single real sleep.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.inventory import build_inventory  # noqa: E402
from backup.staging import (  # noqa: E402
    STALE_REPORT_SECONDS,
    is_temp_name,
    snapshot_temp_name,
    stage_inventory,
    sweep_stale_temps,
    temp_name,
)
from backup.transport.folder import (  # noqa: E402
    SNAPSHOT_ID_PATTERN,
    FolderTransport,
)

#: A fixed UUID-style token so the expected names are exact and deterministic.
TOKEN = "0123456789abcdef0123456789abcdef"
SNAPSHOT_ID = "2026-09-16T120530Z"
#: The files the fixture data root holds; directories are implied, not entries.
STAGED = ("ideas/alpha.md", "skills/seeds/seed.bin", "zzq-unruled/note.md")


def _data_root(tmp_path: Path) -> Path:
    """A data root with a ruled member, a nested member and an exclusion."""
    root = tmp_path / "data-root"
    (root / "ideas").mkdir(parents=True, exist_ok=True)
    (root / "ideas" / "alpha.md").write_bytes(b"alpha\n")
    (root / "skills" / "seeds").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "seeds" / "seed.bin").write_bytes(b"\x00\x01\x02")
    (root / "zzq-unruled").mkdir(exist_ok=True)
    (root / "zzq-unruled" / "note.md").write_text("note", encoding="utf-8")
    (root / "data" / "world-trash").mkdir(parents=True, exist_ok=True)
    (root / "data" / "world-trash" / "junk.bin").write_bytes(b"junk")
    return root


def _tree(tmp_path: Path) -> Path:
    """The backup tree ``<root>/Demiurgos/`` with its four subdirectories."""
    tree = tmp_path / "Demiurgos"
    for name in ("current", "snapshots", "meta", "world-trash-index"):
        (tree / name).mkdir(parents=True, exist_ok=True)
    return tree


def test_staged_set_matches_the_inventory_and_never_rescans(tmp_path: Path) -> None:
    """The set is the inventory's files, at their selected relative paths."""
    root = _data_root(tmp_path)
    inventory = build_inventory(root)
    (root / "ideas" / "added-after-inventory.md").write_bytes(b"late")

    staged = stage_inventory(inventory)

    assert set(staged.paths()) == set(STAGED)
    assert len(staged.entries) == len(STAGED)
    # A directory is implied by its files, never an entry of its own.
    assert "ideas" not in staged.paths()
    assert "skills/seeds" not in staged.paths()
    for entry in staged.entries:
        assert entry.source == root / entry.path


def test_temp_names_are_invisible_to_the_transport(tmp_path: Path) -> None:
    """Both helpers produce names the transport's OWN rule never shows."""
    file_temp = temp_name("alpha.md", token=TOKEN)
    dir_temp = snapshot_temp_name(SNAPSHOT_ID, token=TOKEN)

    assert file_temp == f"alpha.md.tmp-{TOKEN}"
    assert dir_temp == f".{SNAPSHOT_ID}.tmp-{TOKEN}"
    assert is_temp_name(file_temp) and is_temp_name(dir_temp)

    # The ACTUAL rule, imported not copied: a temp name is never a final name.
    assert SNAPSHOT_ID_PATTERN.match(file_temp) is None
    assert SNAPSHOT_ID_PATTERN.match(dir_temp) is None
    assert SNAPSHOT_ID_PATTERN.match(SNAPSHOT_ID) is not None

    # And the real listing agrees: only the final snapshot directory is seen.
    tree = _tree(tmp_path)
    transport = FolderTransport(tmp_path)
    (tree / "snapshots" / dir_temp).mkdir()
    (tree / "snapshots" / SNAPSHOT_ID).mkdir()
    assert [info.snapshot_id for info in transport.list_snapshots()] == [SNAPSHOT_ID]


def test_sweep_removes_temp_files_and_snapshot_temp_dirs(tmp_path: Path) -> None:
    """Residue left by an interrupted run is removed, and reported as removed."""
    tree = _tree(tmp_path)
    (tree / "current" / "ideas").mkdir(parents=True, exist_ok=True)
    file_temp = tree / "current" / "ideas" / temp_name("alpha.md", token=TOKEN)
    file_temp.write_bytes(b"partial")
    dir_temp = tree / "snapshots" / snapshot_temp_name(SNAPSHOT_ID, token=TOKEN)
    (dir_temp / "meta").mkdir(parents=True)
    (dir_temp / "meta" / "manifest.json").write_text("{}", encoding="utf-8")

    report = sweep_stale_temps(tree)

    assert not file_temp.exists()
    assert not dir_temp.exists()
    assert {entry.kind for entry in report.swept} == {"file", "snapshot_dir"}
    assert {entry.path for entry in report.swept} == {
        f"current/ideas/alpha.md.tmp-{TOKEN}",
        f"snapshots/.{SNAPSHOT_ID}.tmp-{TOKEN}",
    }
    assert report.warnings() == ()  # fresh residue is swept, not reported


def test_sweep_never_touches_final_names(tmp_path: Path) -> None:
    """A published file and a published snapshot directory always survive."""
    tree = _tree(tmp_path)
    published = tree / "current" / "ideas" / "alpha.md"
    published.parent.mkdir(parents=True, exist_ok=True)
    published.write_bytes(b"alpha\n")
    snapshot = tree / "snapshots" / SNAPSHOT_ID
    snapshot.mkdir()
    inside = snapshot / "notes.md"
    inside.write_bytes(b"published")
    # Immutability (REQ-BE-4): the sweep never descends into a published
    # snapshot, so even a data file that looks like a temp is left alone.
    lookalike = snapshot / temp_name("notes.md", token=TOKEN)
    lookalike.write_bytes(b"author data")

    report = sweep_stale_temps(tree)

    assert report.swept == ()
    assert published.read_bytes() == b"alpha\n"
    assert snapshot.is_dir()
    assert inside.read_bytes() == b"published"
    assert lookalike.read_bytes() == b"author data"


@pytest.mark.parametrize(
    ("age_seconds", "expected_warnings"),
    [
        (STALE_REPORT_SECONDS - 1, ()),
        (STALE_REPORT_SECONDS, (f"current/old.md.tmp-{TOKEN}",)),
        (STALE_REPORT_SECONDS + 1, (f"current/old.md.tmp-{TOKEN}",)),
    ],
)
def test_sweep_reports_residue_at_the_24h_boundary(
    tmp_path: Path, age_seconds: float, expected_warnings: tuple[str, ...]
) -> None:
    """Just-under is swept silently; at/over 24 h the sweep is reported."""
    tree = _tree(tmp_path)
    frozen = 1_700_000_000.0
    residue = tree / "current" / temp_name("old.md", token=TOKEN)
    residue.write_bytes(b"stale")
    os.utime(residue, (frozen - age_seconds, frozen - age_seconds))

    report = sweep_stale_temps(tree, now=lambda: frozen)

    assert not residue.exists()  # the sweep still removes the residue
    assert report.warnings() == tuple(
        f"sweep-stale-tmp:{path}" for path in expected_warnings
    )
