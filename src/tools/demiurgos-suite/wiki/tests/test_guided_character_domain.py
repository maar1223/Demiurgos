"""Focused PR2 tests for routing, candidate evidence, graph discipline, and ficha proposals."""

from __future__ import annotations

from pathlib import Path
import sys
import yaml

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from guided_character_domain import (  # noqa: E402
    FichaValidationError,
    GraphEvidence,
    apply_delta,
    collect_graph_evidence,
    retain_graph_evidence,
    route_new_character_intent,
    serialize_ficha,
)
from guided_character_protocol import CandidateState  # noqa: E402


def test_new_character_routing_is_focused_and_compact() -> None:
    result = route_new_character_intent("I need a new character")
    assert result.is_new_character
    assert result.question and result.question.count("?") == 1
    assert len(result.response) < 80
    assert not route_new_character_intent("Tell me about the existing character Aria").is_new_character
    for edit_request in (
        "I want to edit an existing character Aria",
        "quiero modificar el personaje existente Aria",
        "update the character Aria",
    ):
        assert not route_new_character_intent(edit_request).is_new_character


def test_proposals_are_separate_until_explicit_acceptance_or_rejection() -> None:
    candidate = CandidateState()
    apply_delta(candidate, {"origin": "storm coast", "rumor": "unverified"}, ("hermes:run-1",))
    assert "origin" not in candidate.accepted_canon
    assert candidate.proposals["origin"]["certainty"] == "proposed"
    from guided_character_domain import accept_proposal, reject_proposal
    accept_proposal(candidate, "origin")
    reject_proposal(candidate, "rumor")
    assert candidate.accepted_canon["origin"]["certainty"] == "accepted"
    assert "rumor" not in candidate.accepted_canon
    assert "rejected:rumor" in candidate.provenance


class FakeGraph:
    def __init__(self, matches: list[dict]) -> None:
        self.matches = matches
        self.calls: list[tuple[str, str]] = []

    def search(self, query: str) -> list[dict]:
        self.calls.append(("search", query))
        return self.matches

    def read(self, entity_path: str) -> dict:
        self.calls.append(("read", entity_path))
        return {"path": entity_path, "title": "Known"}

    def links(self, entity_path: str, kind: str) -> list[dict]:
        self.calls.append(("links", kind))
        return [{"kind": kind}]


def test_graph_order_is_search_read_then_forward_and_backlinks() -> None:
    graph = FakeGraph([{"path": "lore/known.md"}])
    evidence = collect_graph_evidence(graph, "known")
    assert [call[0] for call in graph.calls] == ["search", "read", "links", "links"]
    assert evidence.forward and evidence.backlinks


def test_unresolved_and_conflict_evidence_is_retained() -> None:
    candidate = CandidateState()
    unresolved = collect_graph_evidence(FakeGraph([]), "missing")
    retain_graph_evidence(candidate, unresolved)
    retain_graph_evidence(candidate, GraphEvidence(provenance=["source:a"]), {"a": "one", "b": "two"})
    assert candidate.unresolved_references[0]["certainty"] == "unknown"
    assert candidate.conflicts[0]["certainty"] == "conflicted"
    assert "graph:search:missing" in candidate.provenance


def test_ficha_is_additive_v1_and_validates_slug_collisions() -> None:
    candidate = CandidateState(
        accepted_canon={"desire": {"value": "freedom", "certainty": "accepted"}},
        proposals={"fear": {"value": "the sea", "certainty": "proposed"}},
        conflicts=[{"value": "two origins", "certainty": "conflicted", "provenance": ["graph:conflict"]}],
        unresolved_references=[{"value": "Unknown Order", "certainty": "unknown", "provenance": ["graph:search:order"]}],
        provenance=["graph:read:lore/a.md"],
    )
    proposal = serialize_ficha(candidate, world="vibrantes", slug="aria-storm", title="Aria Storm")
    assert proposal.target == "personajes/aria-storm.md"
    frontmatter, body = proposal.content.split("---\n", 2)[1:]
    metadata = yaml.safe_load(frontmatter)
    assert metadata == {
        "type": "Personaje",
        "schema_version": 1,
        "id": "aria-storm",
        "title": "Aria Storm",
        "status": "proposed",
        "provenance": ["graph:read:lore/a.md"],
    }
    for section in ("Identity", "Canon Anchors", "Exploratory Friction", "Relationships", "Unresolved References"):
        assert f"## {section}" in body
    assert "Unknown Order" in body
    assert "graph:search:order" in body
    # A legacy ficha remains an untouched collision target; serialization is diskless and additive.
    legacy_target = "personajes/legacy-aria.md"
    assert serialize_ficha(candidate, world="vibrantes", slug="aria-storm", title="Aria Storm", existing_targets={legacy_target}).target == proposal.target
    with pytest.raises(FichaValidationError):
        serialize_ficha(candidate, world="vibrantes", slug="aria_storm", title="Aria Storm")
    with pytest.raises(FichaValidationError):
        serialize_ficha(candidate, world="vibrantes", slug="aria-storm", title="Aria Storm", existing_targets={proposal.target})
