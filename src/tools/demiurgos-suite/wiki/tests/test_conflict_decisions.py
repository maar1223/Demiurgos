"""Unit tests for conflict decisions (S2 — W11 records)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from conflict_decisions import (
    DECISIONS,
    apply_decisions,
    clear_decision,
    load_decisions,
    record_decision,
)


def _conflict(
    conflict_id: str = "unresolved-reference:lore/alfa.md:Fantasma",
    *,
    code: str = "unresolved-reference",
    severity: str = "error",
    path: str = "lore/alfa.md",
    name: str = "Alfa",
    reference: str | None = "Fantasma",
    field: str | None = None,
) -> dict:
    return {
        "id": conflict_id,
        "code": code,
        "severity": severity,
        "path": path,
        "name": name,
        "message": "diagnostic",
        "field": field,
        "reference": reference,
    }


def _world(tmp_path: Path) -> Path:
    world = tmp_path / "mundos" / "mundo"
    world.mkdir(parents=True)
    return world


def test_load_decisions_without_folder_is_empty(tmp_path: Path) -> None:
    assert load_decisions(_world(tmp_path)) == {}


def test_record_decision_writes_a_readable_markdown_record(tmp_path: Path) -> None:
    world = _world(tmp_path)

    decision = record_decision(
        world, _conflict(), "intentional", note="Planned but not written yet."
    )

    record = world / decision.file
    assert record.is_file()
    text = record.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = yaml.safe_load(text.split("---\n")[1])
    assert frontmatter["conflict_id"] == "unresolved-reference:lore/alfa.md:Fantasma"
    assert frontmatter["code"] == "unresolved-reference"
    assert frontmatter["decision"] == "intentional"
    assert frontmatter["path"] == "lore/alfa.md"
    assert frontmatter["reference"] == "Fantasma"
    assert frontmatter["decided_at"]
    assert "Planned but not written yet." in text


def test_record_decision_is_an_upsert(tmp_path: Path) -> None:
    world = _world(tmp_path)
    first = record_decision(world, _conflict(), "intentional")
    second = record_decision(world, _conflict(), "muted", note="Changed my mind.")

    assert first.file == second.file
    records = list((world / "conflictos").glob("*.md"))
    assert len(records) == 1
    decisions = load_decisions(world)
    assert decisions[first.conflict_id].decision == "muted"


def test_load_decisions_round_trips(tmp_path: Path) -> None:
    world = _world(tmp_path)
    record_decision(world, _conflict(), "structural", note="Foundational rule.")

    decisions = load_decisions(world)

    decision = decisions["unresolved-reference:lore/alfa.md:Fantasma"]
    assert decision.decision == "structural"
    assert decision.note == "Foundational rule."
    assert decision.code == "unresolved-reference"


def test_clear_decision_removes_the_record(tmp_path: Path) -> None:
    world = _world(tmp_path)
    record_decision(world, _conflict(), "intentional")

    assert clear_decision(world, "unresolved-reference:lore/alfa.md:Fantasma") is True
    assert load_decisions(world) == {}
    assert (
        clear_decision(world, "unresolved-reference:lore/alfa.md:Fantasma") is False
    )


def test_invalid_decision_is_rejected(tmp_path: Path) -> None:
    world = _world(tmp_path)

    with pytest.raises(ValueError):
        record_decision(world, _conflict(), "resolved-by-magic")


def test_decision_set_is_closed() -> None:
    assert DECISIONS == ("intentional", "muted", "structural")


def test_apply_decisions_marks_known_and_hides_muted(tmp_path: Path) -> None:
    world = _world(tmp_path)
    intentional = _conflict("unresolved-reference:lore/a.md:X")
    muted = _conflict("dangling-relation:lore/b.md:Y", code="dangling-relation", path="lore/b.md")
    structural = _conflict("duplicate-id:lore/c.md:Z", code="duplicate-id", path="lore/c.md")
    undecided = _conflict("self-relation:lore/d.md:W", code="self-relation", path="lore/d.md")
    record_decision(world, intentional, "intentional")
    record_decision(world, muted, "muted")
    record_decision(world, structural, "structural")

    payload, summary = apply_decisions(
        [intentional, muted, structural, undecided], load_decisions(world)
    )

    by_id = {item["id"]: item for item in payload}
    assert set(by_id) == {intentional["id"], structural["id"], undecided["id"]}
    assert by_id[intentional["id"]]["decision"] == "intentional"
    assert by_id[structural["id"]]["decision"] == "structural"
    assert by_id[undecided["id"]]["decision"] is None
    assert summary["total"] == 3
    assert summary["known"] == 1
    assert summary["muted"] == 1
    assert summary["errors"] == 2
    assert summary["warnings"] == 0


def test_apply_decisions_without_any_record_is_identity(tmp_path: Path) -> None:
    payload, summary = apply_decisions([_conflict()], {})

    assert payload[0]["decision"] is None
    assert summary == {
        "total": 1,
        "errors": 1,
        "warnings": 0,
        "known": 0,
        "muted": 0,
        "by_code": {"unresolved-reference": 1},
    }
