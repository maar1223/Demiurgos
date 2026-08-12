"""Domain rules for guided creation of a new character.

This module is deliberately diskless. It turns provider deltas into explicit
candidate state, reads graph evidence in a fixed order, and emits a validated
Markdown proposal without persisting it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol

import yaml

from guided_character_protocol import CandidateState, MessageType, SessionState, TypedMessage


_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NEW_CHARACTER_TERMS = ("character", "personaje", "protagonist", "protagonista", "villain", "villano")
_NEW_CHARACTER_VERBS = ("create", "crear", "invent", "inventar", "need", "necesito", "want", "quiero", "design", "diseñar")
_EDIT_CHARACTER_TERMS = ("edit", "editar", "existing", "existente", "modify", "modificar", "update", "actualizar", "change", "cambiar")


@dataclass(frozen=True)
class GuidedTurn:
    """Compact routing result; provider-facing details stay out of the reply."""

    is_new_character: bool
    question: str | None = None
    response: str = ""


def route_new_character_intent(author_input: str) -> GuidedTurn:
    """Admit only clearly new-character intent and ask at most one question."""
    words = set(re.findall(r"[a-záéíóúñ]+", author_input.lower()))
    if words & set(_EDIT_CHARACTER_TERMS):
        return GuidedTurn(False)
    is_new = bool(words & set(_NEW_CHARACTER_TERMS)) and bool(words & set(_NEW_CHARACTER_VERBS))
    if not is_new:
        return GuidedTurn(False)
    if len(words) <= 4:
        return GuidedTurn(True, "What is the character's defining desire?", "Let's define the character one step at a time.")
    return GuidedTurn(True, "What should this character want most?", "I can help shape this new character.")


@dataclass(frozen=True)
class Evidence:
    value: Any
    certainty: str
    provenance: tuple[str, ...]


def _record(value: Any, certainty: str, provenance: tuple[str, ...]) -> dict[str, Any]:
    return {"value": value, "certainty": certainty, "provenance": list(provenance)}


def apply_delta(candidate: CandidateState, delta: Mapping[str, Any], provenance: tuple[str, ...] = ()) -> CandidateState:
    """Apply provider data to non-canon partitions only."""
    for key, value in delta.items():
        # A provider cannot address accepted_canon, even if it supplies that
        # field name; acceptance is exclusively an author transition.
        target = getattr(candidate, key, None) if key != "accepted_canon" else None
        if isinstance(target, dict):
            target[key] = _record(value, "proposed", provenance)
        elif isinstance(target, list):
            target.append(_record(value, "proposed", provenance))
        else:
            candidate.proposals[key] = _record(value, "proposed", provenance)
    candidate.provenance.extend(provenance)
    return candidate


def accept_proposal(candidate: CandidateState, key: str) -> Any:
    """Move one proposal to canon; no implicit acceptance of other values."""
    if key not in candidate.proposals:
        raise KeyError(key)
    item = candidate.proposals.pop(key)
    if isinstance(item, Mapping) and "value" in item:
        accepted = dict(item)
        accepted["certainty"] = "accepted"
        candidate.accepted_canon[key] = accepted
        return accepted
    candidate.accepted_canon[key] = _record(item, "accepted", ())
    return candidate.accepted_canon[key]


def reject_proposal(candidate: CandidateState, key: str) -> Any:
    """Remove one proposal while retaining a rejection record outside canon."""
    if key not in candidate.proposals:
        raise KeyError(key)
    item = candidate.proposals.pop(key)
    candidate.provenance.append(f"rejected:{key}")
    return item


class GraphReader(Protocol):
    def search(self, query: str) -> list[Mapping[str, Any]]: ...
    def read(self, entity_path: str) -> Mapping[str, Any] | None: ...
    def links(self, entity_path: str, kind: str) -> list[Mapping[str, Any]]: ...


@dataclass
class GraphEvidence:
    matches: list[Mapping[str, Any]] = field(default_factory=list)
    entity: Mapping[str, Any] | None = None
    forward: list[Mapping[str, Any]] = field(default_factory=list)
    backlinks: list[Mapping[str, Any]] = field(default_factory=list)
    unresolved: bool = False
    provenance: list[str] = field(default_factory=list)


def collect_graph_evidence(graph: GraphReader, query: str, relationships: bool = True) -> GraphEvidence:
    """Use search -> read -> links/backlinks, preserving missing evidence."""
    matches = list(graph.search(query))
    if not matches:
        return GraphEvidence(unresolved=True, provenance=[f"graph:search:{query}"])
    path = matches[0].get("path")
    if not isinstance(path, str) or not path:
        return GraphEvidence(matches=matches, unresolved=True, provenance=[f"graph:search:{query}"])
    entity = graph.read(path)
    provenance = [f"graph:search:{query}", f"graph:read:{path}"]
    if entity is None:
        return GraphEvidence(matches, unresolved=True, provenance=provenance)
    forward: list[Mapping[str, Any]] = []
    backlinks: list[Mapping[str, Any]] = []
    if relationships:
        forward = list(graph.links(path, "forward"))
        backlinks = list(graph.links(path, "backlinks"))
        provenance.extend((f"graph:links:forward:{path}", f"graph:links:backlinks:{path}"))
    return GraphEvidence(matches, entity, forward, backlinks, False, provenance)


def retain_graph_evidence(candidate: CandidateState, evidence: GraphEvidence, conflict: Any = None) -> None:
    """Retain unresolved and conflicting evidence instead of resolving it."""
    candidate.provenance.extend(evidence.provenance)
    if evidence.unresolved:
        candidate.unresolved_references.append(_record(evidence.matches, "unknown", tuple(evidence.provenance)))
    if conflict is not None:
        candidate.conflicts.append(_record(conflict, "conflicted", tuple(evidence.provenance)))


class FichaValidationError(ValueError):
    pass


@dataclass(frozen=True)
class FichaProposal:
    target: str
    content: str
    digest_basis: str


def serialize_ficha(candidate: CandidateState, *, world: str, slug: str, title: str,
                    existing_targets: set[str] | None = None) -> FichaProposal:
    """Serialize an additive v1 ficha and validate its authorized target."""
    if not world.strip() or not _SLUG.fullmatch(slug):
        raise FichaValidationError("invalid character slug")
    target = f"personajes/{slug}.md"
    path = PurePosixPath(target)
    if path.parts[0] != "personajes" or path.name != f"{slug}.md":
        raise FichaValidationError("unauthorized character target")
    if existing_targets and target in existing_targets:
        raise FichaValidationError("character slug collision")
    provenance = candidate.provenance or ["guided-character-v1"]
    frontmatter_values = {
        "type": "Personaje", "schema_version": 1, "id": slug,
        "title": title, "status": "proposed", "provenance": list(provenance),
    }
    frontmatter = "---\n" + yaml.safe_dump(frontmatter_values, sort_keys=False, allow_unicode=False) + "---\n"
    def section(name: str, values: Mapping[str, Any] | list[Any]) -> str:
        if not values:
            return ""
        return f"## {name}\n\n```yaml\n{yaml.safe_dump(values, sort_keys=False, allow_unicode=False)}```\n\n"
    body = (
        section("Identity", candidate.accepted_canon) +
        section("Canon Anchors", candidate.accepted_canon) +
        section("Exploratory Friction", candidate.proposals) +
        section("Relationships", candidate.conflicts) +
        section("Unresolved References", candidate.unresolved_references)
    )
    return FichaProposal(target, frontmatter + body, "\n".join((target, title, repr(candidate.accepted_canon), repr(candidate.provenance))))


def record_transition(state: SessionState, message_type: MessageType, content: Mapping[str, Any]) -> SessionState:
    """Append a typed acceptance/rejection transition to a copied state."""
    state.revision += 1
    state.messages.append(TypedMessage(message_type, dict(content), state.revision))
    return state
