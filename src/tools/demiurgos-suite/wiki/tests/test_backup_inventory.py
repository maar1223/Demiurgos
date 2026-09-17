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
    match_exclusion,
)
from backup.staging import stage_inventory  # noqa: E402

#: A folder no rule knows and no test helper creates by name elsewhere.
EXOTIC = "zzq-lumen-grotto-9f3"

#: Tooling / dependency / cache names that must be refused by basename ANYWHERE.
TOOLING_NAMES = (
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "demo.egg-info",
    "venv",
    ".DS_Store",
    "Thumbs.db",
)

#: Generic directory names that must stay INCLUDED: each can legitimately hold
#: author content, so refusing one would be a silent loss.
GENERIC_NAMES = ("dist", "build", "target", "out", "output", "cache")


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
        ("data", "data/*", False),
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
    """A ruled subtree is taken recursively; ``data/`` takes its databases too."""
    _make(tmp_path / "ideas" / "nota.md")
    _make(tmp_path / "data" / "idea-capture.sqlite3")
    _make(tmp_path / "data" / "methodology" / "library.json")

    inventory = build_inventory(tmp_path)

    assert "ideas/nota.md" in inventory.included
    assert "data/idea-capture.sqlite3" in inventory.included
    # ``data/methodology/`` is author content and is NOT a sqlite file, so a
    # narrow sqlite-only walk would have dropped it. It must survive.
    assert "data/methodology/library.json" in inventory.included


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


def test_data_secrets_are_excluded_by_rule_and_the_databases_survive(
    tmp_path: Path,
) -> None:
    """WARNING-2 fix: ``data/`` keeps its databases and refuses its secrets.

    ``data/`` mixes the four databases the backup owns with auth/session
    material, local machine state and lock files. The old ``estado`` rule never
    matched, so ``data/`` was walked in full and ``data/sessions.json`` (auth
    session hashes), ``data/local-state.json`` and ``data/idea-capture.lock``
    were staged into the cloud-synced folder. Each is now refused BY RULE with a
    recorded reason, while all four owned databases are still staged and the two
    operational ones stay out.

    NOTE for the archive phase: spec #3350 / design #3351 / tasks #3352 describe
    the stores as living in ``estado/``. The real layout is ``data/`` and this
    test locks the corrected behavior; the artifacts must be updated to match.
    """
    owned = (
        "idea-capture",
        "world-checkpoints",
        "co-creation-sessions",
        "guided-sessions",
    )
    for name in owned:
        _make(tmp_path / "data" / f"{name}.sqlite3")
    for name in ("conversation-memory", "import-jobs"):
        _make(tmp_path / "data" / f"{name}.sqlite3")
    _make(tmp_path / "data" / "sessions.json")
    _make(tmp_path / "data" / "local-state.json")
    _make(tmp_path / "data" / "idea-capture.lock")
    _make(tmp_path / "data" / "methodology" / "library.json")

    inventory = build_inventory(tmp_path)

    recorded = {entry.path: entry.reason for entry in inventory.excluded}
    for secret in (
        "data/sessions.json",
        "data/local-state.json",
        "data/idea-capture.lock",
    ):
        assert secret not in inventory.included, f"{secret} leaked into the backup"
        assert secret in recorded, f"{secret} is not recorded as excluded"
        assert recorded[secret].strip(), f"{secret} has an empty exclusion reason"

    for name in owned:
        assert f"data/{name}.sqlite3" in inventory.included, f"{name} was lost"
    for name in ("conversation-memory", "import-jobs"):
        assert f"data/{name}.sqlite3" not in inventory.included

    # Author content under data/ must survive the recursive walk.
    assert "data/methodology/library.json" in inventory.included


def test_data_secret_class_catches_an_equivalent_new_file(tmp_path: Path) -> None:
    """The ``data/`` class matches a ROLE, not three filenames.

    An equivalent new file — a future ``telegram-sessions.json``, a
    ``machine-state.json`` or a new ``*.lock`` — is caught by the same rule, and
    a same-named file OUTSIDE ``data/`` is never touched by the scoped class.
    """
    _make(tmp_path / "data" / "telegram-sessions.json")
    _make(tmp_path / "data" / "machine-state.json")
    _make(tmp_path / "data" / "world-checkpoints.lock")
    _make(tmp_path / "config" / "sessions.json")  # same name, different subtree

    inventory = build_inventory(tmp_path)

    for secret in (
        "data/telegram-sessions.json",
        "data/machine-state.json",
        "data/world-checkpoints.lock",
    ):
        assert secret not in inventory.included
    recorded = {entry.path: entry.reason for entry in inventory.excluded}
    assert recorded["data/telegram-sessions.json"] == "excluded:auth-session-material"
    assert recorded["data/machine-state.json"] == "excluded:local-machine-state"
    assert recorded["data/world-checkpoints.lock"] == "excluded:process-lock-file"
    # The class is scoped to data/: a same-named file elsewhere is untouched.
    assert "config/sessions.json" in inventory.included


def test_tooling_directories_are_excluded_anywhere_and_never_staged(
    tmp_path: Path,
) -> None:
    """An installed dependency tree stays out of the staged set (REQ-BE-1).

    The real deployment's data root IS the checkout, so ``frontend/node_modules``
    (and any nested ``node_modules`` deeper in the tree) was being staged into
    the synced backup folder — thousands of files and hundreds of MB of tool
    output. The class refuses such a directory by its unambiguous NAME anywhere
    in the tree. This asserts on the STAGED set, not merely on the rule table:
    a rule that matched but was not consulted by the walk would still let the
    files through.
    """
    _make(tmp_path / "frontend" / "node_modules" / "pkg" / "index.js")
    _make(tmp_path / "frontend" / "packages" / "app" / "node_modules" / "dep" / "index.js")
    _make(tmp_path / "frontend" / "src" / "app.ts")
    _make(tmp_path / "ideas" / "nota.md")

    inventory = build_inventory(tmp_path)
    recorded = {entry.path: entry.reason for entry in inventory.excluded}

    for dependency_dir in (
        "frontend/node_modules",
        "frontend/packages/app/node_modules",  # nested, not only top-level
    ):
        assert dependency_dir in recorded, f"{dependency_dir} is not excluded"
        assert recorded[dependency_dir].strip(), f"{dependency_dir} has no reason"
        assert dependency_dir not in inventory.included

    staged = set(stage_inventory(inventory).paths())
    assert not any("node_modules" in path.split("/") for path in staged), (
        "a node_modules file reached the staged set"
    )
    # Author data and the surrounding frontend source are untouched.
    assert "ideas/nota.md" in staged
    assert "frontend/src/app.ts" in staged


def test_every_tooling_exclusion_carries_a_non_empty_reason() -> None:
    """Every tooling name is refused, anywhere, with a non-empty reason."""
    for name in TOOLING_NAMES:
        reason = match_exclusion(f"deep/nested/{name}")
        assert reason is not None, f"{name} is not excluded anywhere in the tree"
        assert reason.strip(), f"{name} has an empty exclusion reason"

    # And no row in the whole table is allowed to carry an empty reason.
    for rule in inventory_module.EXCLUSION_RULES:
        assert rule.reason.strip(), f"rule {rule.pattern!r} has an empty reason"


def test_generic_tooling_names_stay_included(tmp_path: Path) -> None:
    """``dist``/``build``/``output``/... are NOT excluded (no silent loss).

    A folder with a generic name can legitimately hold author content. Refusing
    it by name would silently drop a world from the backup, which the design
    forbids, so the guarantee is locked here by a test.
    """
    for name in GENERIC_NAMES:
        _make(tmp_path / name / "author-content.md")

    inventory = build_inventory(tmp_path)
    excluded = {entry.path for entry in inventory.excluded}
    staged = set(stage_inventory(inventory).paths())

    for name in GENERIC_NAMES:
        relative = f"{name}/author-content.md"
        assert relative in inventory.included, f"{relative} was dropped"
        assert relative in staged, f"{relative} was not staged"
        assert name not in excluded, f"{name} was excluded by a rule"


def test_author_folder_merely_containing_a_cache_entry_is_unaffected(
    tmp_path: Path,
) -> None:
    """A legitimate author folder is not dropped because it nests a cache entry.

    The refusal matches the tooling DIRECTORY (and OS metadata files) by exact
    basename. An author world that happens to contain a ``__pycache__`` or a file
    whose name merely RESEMBLES a tooling name keeps every other file: only the
    cache entry itself is left out, and the folder survives.
    """
    _make(tmp_path / "mundos" / "MyWorld" / "ficha.md")
    _make(tmp_path / "mundos" / "MyWorld" / "node_modules-notes.md")  # near-miss
    _make(tmp_path / "mundos" / "MyWorld" / "cache")  # generic file name
    _make(tmp_path / "mundos" / "MyWorld" / "__pycache__" / "world.pyc")

    inventory = build_inventory(tmp_path)
    staged = set(stage_inventory(inventory).paths())

    assert "mundos/MyWorld/ficha.md" in staged
    assert "mundos/MyWorld/node_modules-notes.md" in staged
    assert "mundos/MyWorld/cache" in staged
    assert "mundos/MyWorld/__pycache__/world.pyc" not in staged
    assert "mundos/MyWorld" in inventory.included


def test_inventory_surfaces_the_excluded_listing_and_count(tmp_path: Path) -> None:
    """What was left out is recorded with its reason AND summarizable.

    The manifest copies ``Inventory.excluded`` verbatim, so the author can SEE
    what the run left out instead of trusting it; ``excluded_count`` is the
    one-number summary a report or UI can show. No I/O and no new document.
    """
    _make(tmp_path / "frontend" / "node_modules" / "pkg" / "index.js")
    _make(tmp_path / "ideas" / "nota.md")

    inventory = build_inventory(tmp_path)

    assert inventory.excluded_count == len(inventory.excluded)
    assert inventory.excluded_count == 1
    entry = inventory.excluded[0]
    assert entry.path == "frontend/node_modules"
    assert entry.reason == "excluded:dependency-tree"

