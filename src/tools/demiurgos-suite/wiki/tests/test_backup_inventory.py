# -*- coding: utf-8 -*-
"""Inventory tests for WU-7 (REQ-BE-2, REQ-BE-1, REQ-CDL-2).

Hermetic: every case builds its own ``tmp_path`` root and never touches the real
data root. The first test proves discovery is inventory-driven rather than
list-driven by using a folder name that appears nowhere in the module source —
if a hardcoded top-level list ever drove the walk, that name would vanish.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import backup.inventory as inventory_module  # noqa: E402
from backup.inventory import (  # noqa: E402
    CaseCollisionError,
    build_inventory,
    classify_member,
    detect_case_collisions,
    discover_top_level,
)

#: A folder no rule knows and no test helper creates by name elsewhere.
EXOTIC = "zzq-lumen-grotto-9f3"


def test_discovery_is_not_driven_by_a_hardcoded_list(tmp_path: Path) -> None:
    """An unknown top-level folder is discovered and included, not list-dropped."""
    source = Path(inventory_module.__file__).read_text(encoding="utf-8")
    assert EXOTIC not in source  # no literal list anywhere mentions it
    (tmp_path / EXOTIC / "nested").mkdir(parents=True)
    (tmp_path / EXOTIC / "nested" / "entry.md").write_text("x", encoding="utf-8")

    inventory = build_inventory(tmp_path)

    assert EXOTIC in {member.name for member in inventory.top_level}
    assert EXOTIC in inventory.included
    assert f"{EXOTIC}/nested/entry.md" in inventory.included


def test_unruled_member_recorded_as_unclassified_top_level(tmp_path: Path) -> None:
    """An unrecognized member is flagged; a ruled one is not (SC-CDL-2.2)."""
    (tmp_path / "ideas").mkdir()
    (tmp_path / "mystery-box").mkdir()

    inventory = build_inventory(tmp_path)

    flagged = {
        path
        for finding in inventory.findings
        if finding.kind == "unclassified_top_level"
        for path in finding.paths
    }
    assert "mystery-box" in flagged
    assert "ideas" not in flagged


def test_exclusions_hold_and_are_recorded(tmp_path: Path) -> None:
    """Every sampled exclusion is absent AND carries a non-empty reason."""
    _make(tmp_path / "data" / "world-trash" / "ficha.md")
    _make(tmp_path / "data" / "import-spool" / "job.json")
    _make(tmp_path / ".git" / "config")
    _make(tmp_path / ".venv" / "lib.py")
    _make(tmp_path / "data" / "idea-capture.sqlite3-wal")
    _make(tmp_path / "data" / "conversation-memory.sqlite3")

    inventory = build_inventory(tmp_path)

    recorded = {entry.path: entry.reason for entry in inventory.excluded}
    for path in (
        "data/world-trash",
        "data/import-spool",
        ".git",
        ".venv",
        "data/idea-capture.sqlite3-wal",
        "data/conversation-memory.sqlite3",
    ):
        assert path in recorded, f"{path} is not recorded as excluded"
        assert recorded[path].strip(), f"{path} has an empty exclusion reason"
        assert path not in inventory.included
    assert "data/world-trash/ficha.md" not in inventory.included


@pytest.mark.parametrize(
    ("member", "subtree", "sqlite_only"),
    (
        ("ideas", "ideas/*", False),
        ("mundos", "mundos/<World>/*", False),
        ("estado", "data/*.sqlite3", True),
        ("config", "config/* (no secrets)", False),
    ),
)
def test_rule_table_routes_known_members(
    member: str, subtree: str, sqlite_only: bool
) -> None:
    """A recognized member resolves to its subtree rule; unknown -> ``None``."""
    rule = classify_member(member)
    assert rule is not None
    assert (rule.member, rule.subtree, rule.sqlite_only) == (member, subtree, sqlite_only)


def test_unruled_member_has_no_rule() -> None:
    """An unruled name returns ``None`` and is still included by the walk."""
    assert classify_member("mystery-box") is None


def test_ruled_subtree_is_included_and_sqlite_scope_is_narrow(tmp_path: Path) -> None:
    """A ruled subtree is taken recursively; ``estado/`` takes only SQLite files."""
    _make(tmp_path / "ideas" / "nota.md")
    _make(tmp_path / "estado" / "idea-capture.sqlite3")
    _make(tmp_path / "estado" / "scratch.txt")

    inventory = build_inventory(tmp_path)

    assert "ideas/nota.md" in inventory.included
    assert "estado/idea-capture.sqlite3" in inventory.included
    assert "estado/scratch.txt" not in inventory.included
    recorded = {entry.path: entry.reason for entry in inventory.excluded}
    assert recorded.get("estado/scratch.txt")


def test_case_collision_is_detected_names_both_and_aborts(tmp_path: Path) -> None:
    """A same-level case collision aborts, naming BOTH members (SC-CDL-2.1)."""
    _make(tmp_path / "Ideas" / "a.md")
    _make(tmp_path / "ideas" / "b.md")

    with pytest.raises(CaseCollisionError) as raised:
        build_inventory(tmp_path)

    collisions = raised.value.collisions
    assert len(collisions) == 1
    assert set(collisions[0].members) == {"Ideas", "ideas"}
    assert len(collisions[0].members) == 2, "both members, not one spelling"
    assert collisions[0].key == "ideas"

    findings = raised.value.findings
    assert [finding.kind for finding in findings] == ["case_collision"]
    assert set(findings[0].paths) == {"Ideas", "ideas"}
    for name in ("Ideas", "ideas"):
        assert name in str(raised.value)


def test_nfc_equivalent_names_collide(tmp_path: Path) -> None:
    """Composed vs decomposed spellings collapse after NFC and abort (REQ-CDL-2)."""
    _make(tmp_path / "caf\u00e9" / "a.md")  # composed: é
    _make(tmp_path / "cafe\u0301" / "b.md")  # decomposed: e + combining acute

    collisions = detect_case_collisions(discover_top_level(tmp_path))

    assert len(collisions) == 1
    assert collisions[0].key == "caf\u00e9"
    # Both on-disk spellings are named, even though they normalize identically.
    assert len(collisions[0].members) == 2
    assert collisions[0].members[0] != collisions[0].members[1]

    with pytest.raises(CaseCollisionError):
        build_inventory(tmp_path)


def test_motivating_pair_is_cross_level_and_therefore_not_caught(
    tmp_path: Path,
) -> None:
    """SPEC scope is TOP LEVEL: ``ideas/`` vs ``mundos/Ideas/`` is NOT a collision here.

    REQ-CDL-2 asks for "one canonical case per top-level name" and SC-CDL-2.1
    gives "top-level members differing only by case". The motivating evidence
    sits at DIFFERENT levels (root ``ideas/`` vs ``Ideas`` inside ``mundos/``),
    so the spec's top-level scope does not cover it and no abort happens. This
    test asserts that documented boundary instead of leaving it untested. A
    same-level nested collision is the transport's concern (REQ-BE-9,
    SC-BE-9.1, WU-6).
    """
    _make(tmp_path / "ideas" / "nota.md")
    _make(tmp_path / "mundos" / "Ideas" / "ficha.md")

    inventory = build_inventory(tmp_path)  # no abort: they are not siblings

    assert "ideas/nota.md" in inventory.included
    assert "mundos/Ideas/ficha.md" in inventory.included
    assert not [f for f in inventory.findings if f.kind == "case_collision"]


def test_case_differences_that_cannot_collide_do_not_abort(tmp_path: Path) -> None:
    """No false positive: a case difference that cannot collide never aborts."""
    _make(tmp_path / "ideas" / "nota.md")
    _make(tmp_path / "Mundos" / "ficha.md")
    _make(tmp_path / "IdeasArchive" / "old.md")

    inventory = build_inventory(tmp_path)

    assert {"ideas", "Mundos", "IdeasArchive"} <= {
        member.name for member in inventory.top_level
    }
    assert not [f for f in inventory.findings if f.kind == "case_collision"]


def _make(path: Path) -> None:
    """Create *path* (and parents) as a small text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
