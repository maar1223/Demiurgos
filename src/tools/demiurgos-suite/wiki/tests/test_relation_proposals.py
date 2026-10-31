"""Unit tests for the pending proposal queue (P3)."""

from __future__ import annotations

import json
from pathlib import Path

from relation_proposals import (
    Proposal,
    add_proposals,
    load_proposals,
    proposal_id,
    remove_proposal,
)


def _proposal(target: str = "lore::beta", rel_type: str = "aliado-de") -> Proposal:
    return Proposal(
        id=proposal_id("lore::alpha", target, rel_type),
        source_path="lore/alpha.md",
        source_key="lore::alpha",
        target_id=target,
        relationship_type=rel_type,
        confidence=0.8,
        evidence="Alpha served Beta.",
        created_at="2026-10-31T20:00:00",
    )


def test_add_then_load_roundtrip(tmp_path: Path) -> None:
    world = tmp_path / "world"

    added = add_proposals(world, [_proposal()])

    assert len(added) == 1
    stored = load_proposals(world)
    assert len(stored) == 1
    assert stored[0].target_id == "lore::beta"
    assert stored[0].relationship_type == "aliado-de"
    assert stored[0].confidence == 0.8


def test_add_is_deduped_by_id(tmp_path: Path) -> None:
    world = tmp_path / "world"

    assert len(add_proposals(world, [_proposal()])) == 1
    assert add_proposals(world, [_proposal()]) == []
    assert len(load_proposals(world)) == 1


def test_different_type_is_a_different_proposal(tmp_path: Path) -> None:
    world = tmp_path / "world"

    add_proposals(world, [_proposal(rel_type="aliado-de")])
    add_proposals(world, [_proposal(rel_type="rival-de")])

    assert len(load_proposals(world)) == 2


def test_remove_returns_the_proposal(tmp_path: Path) -> None:
    world = tmp_path / "world"
    proposal = _proposal()
    add_proposals(world, [proposal])

    removed = remove_proposal(world, proposal.id)

    assert removed is not None
    assert removed.target_id == "lore::beta"
    assert load_proposals(world) == []
    assert remove_proposal(world, proposal.id) is None


def test_corrupt_store_is_ignored(tmp_path: Path) -> None:
    world = tmp_path / "world"
    path = world / ".relations" / "proposals.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert load_proposals(world) == []
    assert len(add_proposals(world, [_proposal()])) == 1


def test_file_is_sorted_by_id(tmp_path: Path) -> None:
    world = tmp_path / "world"
    add_proposals(
        world,
        [
            _proposal(target="lore::zeta"),
            _proposal(target="lore::beta"),
            _proposal(target="lore::gamma"),
        ],
    )

    payload = json.loads(
        (world / ".relations" / "proposals.json").read_text(encoding="utf-8")
    )
    ids = [entry["id"] for entry in payload["proposals"]]

    assert ids == sorted(ids)
