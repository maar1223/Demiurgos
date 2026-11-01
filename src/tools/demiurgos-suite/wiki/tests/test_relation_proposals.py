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


def _directional(
    source_key: str,
    target_id: str,
    *,
    confidence: float = 0.8,
    rel_type: str = "aliado-de",
    evidence: str = "Alpha served Beta.",
) -> Proposal:
    source_path = source_key.replace("::", "/") + ".md"
    return Proposal(
        id=proposal_id(source_key, target_id, rel_type),
        source_path=source_path,
        source_key=source_key,
        target_id=target_id,
        relationship_type=rel_type,
        confidence=confidence,
        evidence=evidence,
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


def test_opposite_directions_collapse_to_one_entry(tmp_path: Path) -> None:
    """S4: A->B and B->A are the same queue entry."""
    world = tmp_path / "world"

    assert len(add_proposals(world, [_directional("lore::alpha", "lore::beta")])) == 1
    assert add_proposals(world, [_directional("lore::beta", "lore::alpha")]) == []

    stored = load_proposals(world)
    assert len(stored) == 1
    assert stored[0].id == proposal_id("lore::beta", "lore::alpha", "aliado-de")


def test_the_stored_side_is_independent_of_arrival_order(tmp_path: Path) -> None:
    """The deterministic winner keeps its own side, whichever batch saw it first."""
    first = tmp_path / "first"
    second = tmp_path / "second"

    add_proposals(first, [_directional("lore::beta", "lore::alpha")])
    add_proposals(first, [_directional("lore::alpha", "lore::beta")])

    add_proposals(second, [_directional("lore::alpha", "lore::beta")])
    add_proposals(second, [_directional("lore::beta", "lore::alpha")])

    alpha_first = load_proposals(first)[0]
    beta_first = load_proposals(second)[0]
    assert (alpha_first.source_key, alpha_first.target_id) == (
        "lore::alpha",
        "lore::beta",
    )
    assert (beta_first.source_key, beta_first.target_id) == (
        "lore::alpha",
        "lore::beta",
    )


def test_higher_confidence_wins_the_pair_in_either_order(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    add_proposals(first, [_directional("lore::alpha", "lore::beta", confidence=0.3)])
    add_proposals(first, [_directional("lore::beta", "lore::alpha", confidence=0.9)])

    add_proposals(second, [_directional("lore::beta", "lore::alpha", confidence=0.9)])
    add_proposals(second, [_directional("lore::alpha", "lore::beta", confidence=0.3)])

    for world in (first, second):
        stored = load_proposals(world)
        assert len(stored) == 1
        assert stored[0].source_key == "lore::beta"
        assert stored[0].confidence == 0.9


def test_a_legacy_directional_store_is_rekeyed_on_load(tmp_path: Path) -> None:
    """A pre-S4 proposals.json still loads, collapsed onto the deterministic side."""
    world = tmp_path / "world"
    path = world / ".relations" / "proposals.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposals": [
                    {
                        "id": "legacy-alpha",
                        "source_path": "lore/alpha.md",
                        "source_key": "lore::alpha",
                        "target_id": "lore::beta",
                        "relationship_type": "aliado-de",
                        "confidence": 0.4,
                        "evidence": "Alpha served Beta.",
                        "created_at": "",
                    },
                    {
                        "id": "legacy-beta",
                        "source_path": "lore/beta.md",
                        "source_key": "lore::beta",
                        "target_id": "lore::alpha",
                        "relationship_type": "aliado-de",
                        "confidence": 0.9,
                        "evidence": "Beta served Alpha.",
                        "created_at": "",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    stored = load_proposals(world)

    assert len(stored) == 1
    # The pre-S4 id is preserved so an in-flight verdict still addresses it.
    assert stored[0].id == "legacy-beta"
    assert stored[0].source_key == "lore::beta"
    assert stored[0].target_id == "lore::alpha"
    assert stored[0].evidence == "Beta served Alpha."

    # And the queue still accepts the canonical pair identity for new work.
    assert proposal_id("lore::alpha", "lore::beta", "aliado-de") == proposal_id(
        "lore::beta", "lore::alpha", "aliado-de"
    )
    assert remove_proposal(world, "legacy-beta") is not None
    assert load_proposals(world) == []
