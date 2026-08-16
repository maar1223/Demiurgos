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
from demiurgos_language import normalize_language, resolve_ui_language


_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NEW_CHARACTER_TERMS = (
    "character", "personaje", "protagonist", "protagonista", "villain", "villano",
    "warrior", "guerrero", "brother", "sister", "hermano", "hermana", "character",
    "wife", "spouse", "husband", "partner", "esposa", "cónyuge", "esposo", "pareja",
)
_NEW_CHARACTER_VERBS = ("create", "crear", "write", "escribir", "invent", "inventar", "need", "necesito", "want", "quiero", "design", "diseñar", "make", "hacer")
_EDIT_CHARACTER_TERMS = ("edit", "editar", "existing", "existente", "modify", "modificar", "update", "actualizar", "change", "cambiar")
_RELATED_REFERENCE_PATTERN = re.compile(
    r"\b(?:[a-záéíóúñ]+(?:\s+[a-záéíóúñ]+){0,3})\s+(?:of|de)\s+"
    r"([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'’-]*(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'’-]*){0,2})"
    r"|\b([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'’-]*(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ'’-]*){0,2})['’]s\s+"
    r"(?:the\s+)?[a-záéíóúñ]+(?:\s+[a-záéíóúñ]+){0,3}\b",
)
_FAST_MODE_MARKERS = (
    "immediate", "immediately", "right now", "rápidamente", "rapidamente", "inmediatamente", "ahora mismo",
    "fundamental", "fundamentals", "lo básico", "lo basico", "only basics", "solo lo fundamental",
    "skip the questionnaire", "skip questionnaire", "sin cuestionario", "omitir cuestionario",
    "write it now", "escríbelo ya", "escribelo ya", "create it now", "créalo ya", "crealo ya",
    "just create it", "just write it", "sin preguntas", "no me hagas preguntas", "without questions",
    "no questions",
)
_FAST_QUICK_MARKERS = ("fast", "quick", "quickly", "rápido", "rapido")
_FAST_DIRECT_VERBS = ("create", "crear", "write", "escribir", "make", "hacer", "haz", "quiero", "want")

_RELATION_TERM_TO_KEY: dict[str, str] = {
    "brother": "brother", "sister": "sister", "wife": "wife", "husband": "husband",
    "spouse": "spouse", "partner": "partner", "cousin": "cousin",
    "grandfather": "grandfather", "grandmother": "grandmother",
    "uncle": "uncle", "aunt": "aunt", "nephew": "nephew", "niece": "niece",
    "mentor": "mentor",
    "hermano": "brother", "hermana": "brother",
    "esposa": "wife", "esposo": "husband",
    "cónyuge": "spouse", "conyuge": "spouse", "pareja": "partner",
    "primo": "cousin", "prima": "cousin",
    "abuelo": "grandfather", "abuela": "grandmother",
    "tío": "uncle", "tio": "uncle", "tía": "aunt", "tia": "aunt",
    "sobrino": "nephew", "sobrina": "niece",
    "mentora": "mentor",
}
_RELATION_ES_LABELS: dict[str, str] = {
    "brother": "hermano", "sister": "hermana", "wife": "esposa", "husband": "esposo",
    "spouse": "cónyuge", "partner": "pareja", "cousin": "primo",
    "grandfather": "abuelo", "grandmother": "abuela", "uncle": "tío", "aunt": "tía",
    "nephew": "sobrino", "niece": "sobrina", "mentor": "mentor/mentora",
}
_SPANISH_RELATION_TERMS = frozenset({
    "hermano", "hermana", "esposa", "esposo", "cónyuge", "conyuge", "pareja",
    "primo", "prima", "abuelo", "abuela", "tío", "tio", "tía", "tia",
    "sobrino", "sobrina", "mentora",
})
_RELATION_GOAL_BUDGET = 400

# Server-owned minimum identity data that must be present in a candidate before
# a provider delta may be promoted to a proposal in full guided mode. These are
# the essential identity anchors of the v1 character contract: an identity
# (name) and a defining desire. Fast mode proceeds with marked assumptions.
MINIMUM_IDENTITY_FIELDS = ("name", "nombre", "title")
MINIMUM_DESIRE_FIELDS = ("desire", "deseo", "motivacion", "motivations", "motivation", "motivaciones")


def _candidate_known_fields(candidate: CandidateState, delta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    known = dict(candidate.accepted_canon)
    known.update(candidate.proposals)
    if delta:
        known.update(delta)
    return known


def candidate_minimum_complete(candidate: CandidateState, *, delta: Mapping[str, Any] | None = None,
                               mode: str = "full") -> bool:
    """Server-authoritative minimum completeness gate for guided creation.

    A provider delta is never a trusted completeness claim: only the candidate
    data the server actually holds decides readiness. A candidate is minimally
    complete when it carries both an identity anchor and a defining desire.
    Fast mode proceeds with marked assumptions and skips the gate.
    """
    if mode == "fast":
        return True
    known = _candidate_known_fields(candidate, delta)
    return (
        any(key in known for key in MINIMUM_IDENTITY_FIELDS)
        and any(key in known for key in MINIMUM_DESIRE_FIELDS)
    )


def _identity_question(language: str) -> str:
    if language == "en":
        return "What is this character's name?"
    return "¿Cómo se llama este personaje?"


def next_required_question(candidate: CandidateState, *, delta: Mapping[str, Any] | None = None,
                           language: str | None = None) -> str:
    """One server-owned focused question for the first missing required field.

    Asks for the missing identity anchor first, then the defining desire, in
    the configured UI language. Never a questionnaire: exactly one question.
    """
    known = _candidate_known_fields(candidate, delta)
    lang = normalize_language(language or resolve_ui_language())
    if not any(key in known for key in MINIMUM_IDENTITY_FIELDS):
        return _identity_question(lang)
    return _default_question(lang, short=True)[0]


def _default_question(language: str, short: bool) -> tuple[str, str]:
    """Default guided question/response in the configured UI language."""
    if language == "en":
        return (
            "What is the character's defining desire?",
            "Let's define the character one step at a time.",
        ) if short else (
            "What should this character want most?",
            "I can help shape this new character.",
        )
    return (
        "¿Cuál es el deseo que define a este personaje?",
        "Definamos el personaje paso a paso.",
    ) if short else (
        "¿Qué debería querer este personaje por encima de todo?",
        "Puedo ayudar a dar forma a este nuevo personaje.",
    )


@dataclass(frozen=True)
class GuidedTurn:
    """Compact routing result; provider-facing details stay out of the reply."""

    is_new_character: bool
    question: str | None = None
    response: str = ""
    requires_confirmation: bool = False
    mode: str = "full"
    depth: str = "standard"


def route_new_character_intent(author_input: str, *, allow_descriptive_seed: bool = False,
                               language: str | None = None) -> GuidedTurn:
    """Admit new-character intent and ask at most one question."""
    words = set(re.findall(r"[a-záéíóúñ]+", author_input.lower()))
    if words & set(_EDIT_CHARACTER_TERMS):
        return GuidedTurn(False)
    related_reference = named_reference_name(author_input) is not None
    related_creation = related_reference and bool(words & set(_NEW_CHARACTER_VERBS))
    is_new = related_creation or (bool(words & set(_NEW_CHARACTER_TERMS)) and (
        allow_descriptive_seed or bool(words & set(_NEW_CHARACTER_VERBS))
    ))
    if not is_new:
        return GuidedTurn(False)
    lowered_input = author_input.casefold()
    fast_mode = any(
        re.search(rf"\b{re.escape(marker)}\b", lowered_input)
        for marker in _FAST_MODE_MARKERS
    )
    if not fast_mode and any(re.search(rf"\b{re.escape(marker)}\b", lowered_input) for marker in _FAST_QUICK_MARKERS):
        fast_mode = any(
            re.search(rf"\b{re.escape(verb)}\b.{{0,32}}\b(?:fast|quick|quickly|rápido|rapido)\b", lowered_input)
            for verb in _FAST_DIRECT_VERBS
        )
    mode = "fast" if fast_mode else "full"
    depth = "fundamental" if fast_mode else "standard"
    question, response = _default_question(language or resolve_ui_language(), len(words) <= 4)
    return GuidedTurn(
        True, question, response, related_creation, mode, depth,
    )


def confirmation_decision(author_input: str) -> bool | None:
    """Classify only unambiguous confirmation answers; fail closed otherwise."""
    words = set(re.findall(r"[a-záéíóúñ]+", author_input.lower()))
    affirmative = {"yes", "y", "si", "sí", "sure", "ok", "okay", "adelante", "confirmo", "acepto", "start", "empezar"}
    negative = {"no", "n", "cancel", "cancelar", "later", "después", "despues", "stop", "detener"}
    if words & affirmative and not words & negative:
        return True
    if words & negative and not words & affirmative:
        return False
    return None


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


@dataclass(frozen=True)
class NamedReference:
    """Bounded result of resolving a named entity for a related character."""

    name: str
    context: str = ""
    unresolved: bool = False
    ambiguous: bool = False


def named_reference_name(author_input: str) -> str | None:
    match = _RELATED_REFERENCE_PATTERN.search(author_input)
    if not match:
        return None
    return next((group.strip() for group in match.groups() if group), None)


@dataclass(frozen=True)
class RelatedGoal:
    """Safe, structured relational objective for a new character."""

    relation: str | None
    reference_name: str | None
    summary: str


def _detect_relation(author_input: str) -> tuple[str, str] | None:
    """Return ``(canonical_key, matched_term)`` only for a single safe relation."""
    lowered = author_input.casefold()
    matches: list[tuple[str, str]] = []
    for term, key in _RELATION_TERM_TO_KEY.items():
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            matches.append((key, term))
    unique_keys = {key for key, _ in matches}
    if len(unique_keys) != 1:
        return None
    return unique_keys.pop(), matches[0][1]


def _relation_goal_text(relation_key: str, matched_term: str, reference: str, language: str) -> str:
    if language == "es":
        label = matched_term if matched_term in _SPANISH_RELATION_TERMS else _RELATION_ES_LABELS.get(relation_key, relation_key)
        return f"Nuevo personaje: {label} de {reference}"
    return f"New character: {relation_key} of {reference}"


def extract_related_goal(author_input: str, *, reference_name: str | None = None,
                         language: str | None = None) -> RelatedGoal:
    """Extract a safe relational goal without ever inventing one.

    Returns a bounded, localized summary of the requested relationship and its
    reference character.  When no single relation can be detected safely, the
    goal is empty and the original author request remains the only preserved
    intent; nothing is fabricated.
    """
    reference = reference_name or named_reference_name(author_input)
    detected = _detect_relation(author_input)
    if detected is None or not reference:
        return RelatedGoal(None, reference, "")
    relation_key, matched_term = detected
    lang = normalize_language(language or resolve_ui_language())
    return RelatedGoal(
        relation_key,
        reference,
        _relation_goal_text(relation_key, matched_term, reference, lang)[:_RELATION_GOAL_BUDGET],
    )


def _graph_value(item: Mapping[str, Any] | Any, key: str, default: Any = "") -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _is_canonical_character(item: Mapping[str, Any] | Any) -> bool:
    entity_type = str(_graph_value(item, "type")).casefold()
    path = str(_graph_value(item, "path")).replace("\\", "/").casefold()
    return entity_type in {"personaje", "character"} or (
        not entity_type and path.startswith("personajes/")
    )


def resolve_named_reference(graph: GraphReader, author_input: str) -> NamedReference | None:
    """Resolve only an explicit related-entity name through search then read."""
    name = named_reference_name(author_input)
    if name is None:
        return None
    matches = list(graph.search(name))
    canonical = [item for item in matches if _is_canonical_character(item)]
    exact = [item for item in canonical if str(_graph_value(item, "name")).casefold() == name.casefold()]
    if not exact:
        exact = [
            item for item in canonical
            if str(_graph_value(item, "name")).casefold().startswith(name.casefold())
        ]
    if len(exact) != 1:
        return NamedReference(name, unresolved=True, ambiguous=bool(matches))

    path = _graph_value(exact[0], "path")
    if not isinstance(path, str) or not path:
        return NamedReference(name, unresolved=True)
    entity = graph.read(path)
    if entity is None:
        return NamedReference(name, unresolved=True)

    # Relationship links are relevant for a request that explicitly asks for a sibling.
    forward = list(graph.links(path, "forward"))
    backlinks = list(graph.links(path, "backlinks"))
    lines = [f"Verified reference: {str(_graph_value(entity, 'name', name))}"]
    for label, key in (("Type", "type"), ("Title", "title"), ("Description", "description")):
        value = _graph_value(entity, key)
        if isinstance(value, str) and value.strip():
            lines.append(f"{label}: {value.strip()}")
    content = _graph_value(entity, "content")
    if isinstance(content, str) and content.strip():
        lines.append(f"Facts:\n{content[:3_000].strip()}")
    related_names = [
        str(_graph_value(item, "name"))
        for item in (*forward, *backlinks)
        if str(_graph_value(item, "name")).strip()
    ]
    if related_names:
        lines.append("Verified graph relationships: " + ", ".join(dict.fromkeys(related_names)))
    return NamedReference(name, "\n".join(lines)[:4_000])


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
