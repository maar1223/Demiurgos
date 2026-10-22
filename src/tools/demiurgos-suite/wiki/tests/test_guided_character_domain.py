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
    extract_related_goal,
    resolve_named_reference,
    retain_graph_evidence,
    route_new_character_intent,
    confirmation_decision,
    serialize_ficha,
    candidate_minimum_complete,
    has_finished_exchange,
    next_required_question,
    resolve_candidate_nivel,
)
from guided_character_protocol import (  # noqa: E402
    CandidateState,
    MessageType,
    SessionState,
    TypedMessage,
)


def test_new_character_routing_is_focused_and_compact() -> None:
    result = route_new_character_intent("I need a new character")
    assert result.is_new_character
    assert result.question and result.question.count("?") == 1
    assert len(result.response) < 80
    assert not route_new_character_intent("Tell me about the existing character Aria").is_new_character
    for edit_request in (
        "edit the character Aria",
        "editar el personaje Aria",
        "existing character Aria",
        "personaje existente Aria",
        "modify the character Aria",
        "modificar el personaje Aria",
        "update the character Aria",
        "actualizar el personaje Aria",
        "change the character Aria",
        "cambiar el personaje Aria",
    ):
        assert not route_new_character_intent(edit_request).is_new_character


def test_default_guided_questions_follow_configured_language_not_prompt() -> None:
    spanish_prompt = route_new_character_intent("I want a character", language="es")
    english_prompt = route_new_character_intent("Quiero un personaje", language="en")
    assert "¿" in spanish_prompt.question or "deseo" in spanish_prompt.question
    assert "?" in english_prompt.question and "¿" not in english_prompt.question
    assert spanish_prompt.question != english_prompt.question


def test_descriptive_seeds_require_the_explicit_guided_start_context() -> None:
    for seed in ("Un guerrero de las sombras", "Un personaje llamado Aria"):
        assert not route_new_character_intent(seed).is_new_character
        assert route_new_character_intent(seed, allow_descriptive_seed=True).is_new_character


@pytest.mark.parametrize("prompt", [
    "Quiero crear la esposa de Rhyz", "I want to create Rhyz's wife",
    "Create the spouse of Rhyz", "Necesito crear la pareja de Rhyz",
    "Quiero crear al primo de Rhyz", "Create the grandfather of Rhyz",
    "Necesito un sobrino de Rhyz", "Create the mentor de Rhyz",
])
def test_relationship_creation_requires_confirmation(prompt: str) -> None:
    result = route_new_character_intent(prompt)
    assert result.is_new_character
    assert result.requires_confirmation


def test_relationship_detection_is_structural_and_not_descriptive_false_positive() -> None:
    for prompt in ("¿Quién es el primo de Rhyz?", "Tell me about Rhyz's cousin", "Rhyz's cousin"):
        result = route_new_character_intent(prompt, allow_descriptive_seed=True)
        assert not result.is_new_character
        assert not result.requires_confirmation
    assert route_new_character_intent("Create Rhyz's cousin").requires_confirmation
    assert route_new_character_intent("Un guerrero de sombras").is_new_character is False


@pytest.mark.parametrize("prompt", [
    "Create a character quickly",
    "Quiero crear un personaje solo con lo fundamental",
    "Write the character immediately and skip the questionnaire",
])
def test_fast_mode_is_explicit_and_bounded(prompt: str) -> None:
    result = route_new_character_intent(prompt)
    assert result.mode == "fast"
    assert result.depth == "fundamental"


@pytest.mark.parametrize("prompt", [
    "escríbelo ya", "write it now", "créalo ya", "create it now",
    "sin preguntas", "no me hagas preguntas", "just create it",
])
def test_concise_author_fast_markers_select_fundamental_depth(prompt: str) -> None:
    result = route_new_character_intent(f"Create a character: {prompt}")
    assert result.mode == "fast"
    assert result.depth == "fundamental"


def test_ambiguous_speed_request_keeps_full_mode() -> None:
    result = route_new_character_intent("I need a character with a fast horse")
    assert result.mode == "full"


def test_confirmation_classifier_fails_closed_for_ambiguous_answers() -> None:
    assert confirmation_decision("sí") is True
    assert confirmation_decision("no, más tarde") is False
    assert confirmation_decision("maybe") is None


def test_related_goal_extracts_safe_spanish_and_english_relations() -> None:
    spanish = extract_related_goal("quiero crear al hermano de Rhyz", language="es")
    assert spanish.relation == "brother"
    assert spanish.reference_name == "Rhyz"
    assert "hermano" in spanish.summary and "Rhyz" in spanish.summary

    english = extract_related_goal("I want to create Rhyz's brother", language="en")
    assert english.relation == "brother"
    assert english.reference_name == "Rhyz"
    assert "brother" in english.summary and "Rhyz" in english.summary


def test_related_goal_preserves_the_authors_spanish_gender_term() -> None:
    goal = extract_related_goal("quiero crear a la hermana de Rhyz", language="es")
    assert goal.relation == "brother"
    assert goal.summary == "Nuevo personaje: hermana de Rhyz"


def test_related_goal_never_invents_a_relation() -> None:
    assert extract_related_goal("Create a character").summary == ""
    assert extract_related_goal("Quiero crear un personaje para la historia").summary == ""
    assert extract_related_goal("Crear un hermano sin referencia").summary == ""
    ambiguous = extract_related_goal("quiero crear la esposa y la hermana de Rhyz", language="es")
    assert ambiguous.relation is None and ambiguous.summary == ""


def test_related_goal_summary_is_bounded() -> None:
    goal = extract_related_goal(
        "quiero crear al hermano de Rhyz el antiguo señor de las tormentas",
        language="es",
    )
    assert goal.summary and len(goal.summary) <= 400


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


def test_candidate_minimum_complete_requires_identity_and_desire() -> None:
    assert not candidate_minimum_complete(CandidateState())
    assert not candidate_minimum_complete(CandidateState(proposals={"desire": {"value": "freedom"}}))
    assert not candidate_minimum_complete(CandidateState(proposals={"name": {"value": "Pert"}}))
    assert candidate_minimum_complete(CandidateState(proposals={"name": "Pert", "desire": "freedom"}))
    assert candidate_minimum_complete(CandidateState(proposals={"nombre": "Pert", "motivacion": "freedom"}))
    assert candidate_minimum_complete(CandidateState(accepted_canon={"name": "Pert", "desire": "freedom"}))


def test_candidate_minimum_complete_considers_incoming_delta() -> None:
    assert candidate_minimum_complete(CandidateState(), delta={"name": "Pert", "desire": "freedom"})
    assert not candidate_minimum_complete(CandidateState(), delta={"age": "~30"})


def test_candidate_minimum_complete_fast_mode_skips_the_gate() -> None:
    assert candidate_minimum_complete(CandidateState(), mode="fast")
    assert candidate_minimum_complete(CandidateState(proposals={"desire": "freedom"}), mode="fast")


def test_next_required_question_asks_one_focused_missing_field() -> None:
    assert "?" in next_required_question(CandidateState(), language="en")
    assert "name" in next_required_question(CandidateState(), language="en").casefold()
    assert "llama" in next_required_question(CandidateState(), language="es").casefold()
    desire = next_required_question(CandidateState(proposals={"name": "Pert"}), language="en")
    assert "?" in desire and desire.count("?") == 1
    assert "desire" in desire.casefold() or "want" in desire.casefold()
    assert next_required_question(CandidateState(), delta={"name": "Pert"}, language="en").count("?") == 1


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


def test_named_reference_requires_unique_match_and_passes_verified_facts() -> None:
    graph = FakeGraph([{"path": "personajes/rhyz.md", "name": "Rhyz"}])
    def read(path: str) -> dict:
        graph.calls.append(("read", path))
        return {"path": path, "name": "Rhyz", "type": "Personaje", "content": "Patient tactician."}
    graph.read = read  # type: ignore[method-assign]
    reference = resolve_named_reference(graph, "quiero crear un hermano de Rhyz")
    assert reference and not reference.unresolved
    assert "Patient tactician." in reference.context
    assert [call[0] for call in graph.calls] == ["search", "read", "links", "links"]


def test_named_reference_does_not_select_ambiguous_match() -> None:
    graph = FakeGraph([
        {"path": "personajes/rhyz-a.md", "name": "Rhyz"},
        {"path": "personajes/rhyz-b.md", "name": "Rhyz"},
    ])
    reference = resolve_named_reference(graph, "crear una hermana de Rhyz")
    assert reference and reference.unresolved and reference.ambiguous
    assert [call[0] for call in graph.calls] == ["search"]


def test_named_reference_prefers_unique_canonical_prefix_over_mentions() -> None:
    graph = FakeGraph([
        {"path": "sagas/echo.md", "name": "Echo Ayagar de Rhyz", "type": "Criatura"},
        {"path": "relaciones/rhyz.md", "name": "Rhyz y el eco", "type": "Relacion"},
        {"path": "personajes/rhyz-resonante.md", "name": "Rhyz El Resonante", "type": "Personaje"},
    ])

    def read(path: str) -> dict:
        graph.calls.append(("read", path))
        return {"path": path, "name": "Rhyz El Resonante", "type": "Personaje", "content": "Resonant."}

    graph.read = read  # type: ignore[method-assign]
    reference = resolve_named_reference(graph, "me gustaria que crearamos al hermano de Rhyz")

    assert reference and not reference.unresolved
    assert "Rhyz El Resonante" in reference.context
    assert graph.calls == [
        ("search", "Rhyz"),
        ("read", "personajes/rhyz-resonante.md"),
        ("links", "forward"),
        ("links", "backlinks"),
    ]


def test_named_reference_keeps_multiple_canonical_prefix_matches_ambiguous() -> None:
    graph = FakeGraph([
        {"path": "personajes/rhyz-a.md", "name": "Rhyz El Resonante", "type": "Personaje"},
        {"path": "personajes/rhyz-b.md", "name": "Rhyz El Errante", "type": "Personaje"},
    ])

    reference = resolve_named_reference(graph, "crear una hermana de Rhyz")

    assert reference and reference.unresolved and reference.ambiguous
    assert graph.calls == [("search", "Rhyz")]


def test_named_reference_keeps_noncanonical_mentions_unresolved() -> None:
    graph = FakeGraph([
        {"path": "sagas/rhyz.md", "name": "Rhyz El Resonante", "type": "Saga"},
        {"path": "lore/rhyz.md", "name": "Rhyz", "type": "Mencion"},
    ])

    reference = resolve_named_reference(graph, "crear una hermana de Rhyz")

    assert reference and reference.unresolved and reference.ambiguous
    assert graph.calls == [("search", "Rhyz")]


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


def _state_with(*messages: tuple[MessageType, dict]) -> SessionState:
    """SessionState carrying exactly the given typed messages, in order."""
    state = SessionState("s", "nec", "conversation", 0, "author")
    for revision, (message_type, content) in enumerate(messages, start=1):
        state.messages.append(TypedMessage(message_type, content, revision))
    return state


def test_has_finished_exchange_shape_table() -> None:
    """D3: a finished exchange is a provider-committed message — a committed
    QUESTION (``ASSISTANT_RESPONSE`` carrying the ``"question"`` key) or a
    committed DELTA (``PROPOSAL``). Server-authored ``{"text": …}``
    confirmation messages are excluded by shape."""
    assert has_finished_exchange(_state_with()) is False
    # Committed QUESTION → ASSISTANT_RESPONSE with "question" key counts.
    assert has_finished_exchange(_state_with(
        (MessageType.ASSISTANT_RESPONSE, {"question": "¿Cómo se llama este personaje?"}),
    )) is True
    # Committed DELTA → PROPOSAL counts regardless of its content shape.
    assert has_finished_exchange(_state_with(
        (MessageType.PROPOSAL, {"name": "Pert", "desire": "freedom"}),
    )) is True
    # begin_confirmation / resolve_confirmation messages {"text": …} do NOT
    # count — they are server-authored, never a provider run.
    assert has_finished_exchange(_state_with(
        (MessageType.ASSISTANT_RESPONSE, {"text": "Start? (yes/no)"}),
    )) is False
    assert has_finished_exchange(_state_with(
        (MessageType.AUTHOR_INPUT, {"text": "Create a character"}),
        (MessageType.ASSISTANT_RESPONSE, {"text": "Start? (yes/no)"}),
    )) is False
    # A mixed history counts once any committed exchange exists.
    assert has_finished_exchange(_state_with(
        (MessageType.AUTHOR_INPUT, {"text": "Create a character"}),
        (MessageType.ASSISTANT_RESPONSE, {"question": "¿Cómo se llama?"}),
    )) is True


def test_resolve_candidate_nivel_table() -> None:
    """D4: the free-form nivel probes resolve to 1º/2º/3º by first string hit;
    unknown or missing nivel locks to 1º (scenario "unknown nivel → 1º")."""
    # contains "2"/"secund" → 2º
    assert resolve_candidate_nivel(CandidateState(proposals={"nivel": "2"})) == "2º"
    assert resolve_candidate_nivel(CandidateState(proposals={"nivel": "Secundario"})) == "2º"
    assert resolve_candidate_nivel(CandidateState(proposals={"nivel_narrativo": "secundario"})) == "2º"
    assert resolve_candidate_nivel(CandidateState(proposals={"rol_narrativo": "Secundario"})) == "2º"
    assert resolve_candidate_nivel(CandidateState(proposals={"nivel narrativo": "2"})) == "2º"
    assert resolve_candidate_nivel(CandidateState(proposals={"rol narrativo": "secundario"})) == "2º"
    # contains "3"/"rellen" → 3º
    assert resolve_candidate_nivel(CandidateState(proposals={"nivel": "3"})) == "3º"
    assert resolve_candidate_nivel(CandidateState(proposals={"nivel_narrativo": "Relleno"})) == "3º"
    assert resolve_candidate_nivel(CandidateState(proposals={"rol_narrativo": "relleno"})) == "3º"
    assert resolve_candidate_nivel(CandidateState(proposals={"nivel": "3º"})) == "3º"
    # else / missing → 1º (locked fallback)
    assert resolve_candidate_nivel(CandidateState(proposals={"nivel": "Protagonista"})) == "1º"
    assert resolve_candidate_nivel(CandidateState(proposals={"otro": "2"})) == "1º"
    assert resolve_candidate_nivel(CandidateState()) == "1º"
    # accepted canon counts too (first probe order: nivel before others).
    assert resolve_candidate_nivel(CandidateState(
        accepted_canon={"nivel": "secundario"}, proposals={"nivel_narrativo": "3"},
    )) == "2º"


# ---------------------------------------------------------------------------
# Generic flow surface (S2/S3): the same domain rules driven by a profile.
# ---------------------------------------------------------------------------


def test_system_completion_gate_requires_identity_origin_and_limit() -> None:
    from okf_contract import prompt_minimums_for

    groups = prompt_minimums_for("sistema")
    assert not candidate_minimum_complete(CandidateState(), groups=groups)
    assert not candidate_minimum_complete(
        CandidateState(proposals={"name": "Magia"}), groups=groups,
    )
    assert not candidate_minimum_complete(
        CandidateState(proposals={"name": "Magia", "origen": "los dioses"}),
        groups=groups,
    )
    assert candidate_minimum_complete(
        CandidateState(proposals={
            "name": "Magia", "origen": "los dioses", "limite": "no crea materia",
        }),
        groups=groups,
    )


def test_system_questions_walk_the_missing_group() -> None:
    from okf_contract import prompt_minimums_for

    groups = prompt_minimums_for("sistema")
    keys = ("identity", "origin", "limit")
    assert next_required_question(
        CandidateState(), groups=groups, question_keys=keys, language="es",
        ui_copy_key="system",
    ) == "¿Cómo se llama este sistema?"
    assert next_required_question(
        CandidateState(proposals={"name": "Magia"}),
        groups=groups, question_keys=keys, language="es",
    ).startswith("¿De dónde vienen las reglas")
    assert next_required_question(
        CandidateState(proposals={"name": "Magia", "origen": "los dioses"}),
        groups=groups, question_keys=keys, language="es",
    ).startswith("¿Qué no puede hacer")


def test_system_serializer_writes_the_kernel_section_and_type() -> None:
    from guided_character_domain import serialize_entity

    candidate = CandidateState(accepted_canon={
        "name": "Magia", "origen": "los dioses", "limite": "no crea materia",
    })
    proposal = serialize_entity(
        candidate, world="vibrantes", slug="magia", title="Magia",
        entity_type="sistema", target_section="lore", type_label="Sistema",
        provenance_default="guided-sistema-v1",
        frontmatter_fields=("origen", "limite"),
    )
    assert proposal.target == "lore/magia.md"
    frontmatter, body = proposal.content.split("---\n", 2)[1:]
    metadata = yaml.safe_load(frontmatter)
    assert metadata["type"] == "Sistema"
    assert metadata["id"] == "magia"
    assert metadata["origen"] == "los dioses"
    assert metadata["limite"] == "no crea materia"
    assert metadata["provenance"] == ["guided-sistema-v1"]
    assert "## Identity" in body
    from okf_contract import validate

    assert validate(proposal.content).ok, validate(proposal.content).issues


def test_system_intent_uses_the_declared_vocabulary() -> None:
    from guided_character_domain import route_guided_intent
    from guided_flow import GuidedFlowDeclaration, resolve_profile

    profile = resolve_profile(GuidedFlowDeclaration.from_mapping({
        "flow_id": "guided-system",
        "entity_type": "sistema",
        "ui_copy_key": "system",
        "index": True,
        "intent": {"terms": ["sistema"], "verbs": ["crear", "diseñar"]},
    }))
    assert profile is not None
    assert route_guided_intent("Quiero crear un sistema de magia", profile).is_new_entity
    assert route_guided_intent("Quiero diseñar un sistema económico", profile).is_new_entity
    assert not route_guided_intent("Editar el sistema existente", profile).is_new_entity
    assert not route_guided_intent("Háblame de los personajes", profile).is_new_entity


def test_character_profile_keeps_name_then_desire_question_order() -> None:
    """S5 regression: the profile-derived character gate must not add a third
    identity group (which would repeat the name question forever)."""
    from guided_flow import builtin_profile

    profile = builtin_profile("guided-character")
    assert profile is not None
    assert len(profile.minimum_groups) == len(profile.question_keys) == 2
    first = next_required_question(
        CandidateState(), language="es",
        groups=profile.minimum_groups, question_keys=profile.question_keys,
        ui_copy_key=profile.ui_copy_key,
    )
    second = next_required_question(
        CandidateState(accepted_canon={"name": {"value": "Aria"}}), language="es",
        groups=profile.minimum_groups, question_keys=profile.question_keys,
        ui_copy_key=profile.ui_copy_key,
    )
    assert first == "¿Cómo se llama este personaje?"
    assert second == "¿Cuál es el deseo que define a este personaje?"
