"""The guided turn's own context must fit the budget its request validates.

Live regression (2026-11-08): a Vibrantes session with 61 observations produced
a 4 000-char ``known_state``; the plan-progress line was prefixed AFTER that
budget was applied, so the composed field reached 4 090 chars and
``GuidedRequest.validate()`` rejected every turn with ``invalid_input`` (422)
while the chat showed only the generic blocked copy.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import api_server  # noqa: E402
from guided_character_protocol import (  # noqa: E402
    PROTOCOL_VERSION,
    CandidateState,
    GuidedRequest,
    MethodologySnapshot,
    SessionState,
)


def _crowded_state(entries: int = 40, size: int = 200) -> SessionState:
    state = SessionState("session-1", "nec", "conversation", 3, "author-1")
    state.candidate = CandidateState(
        observations={f"dato_{index}": "x" * size for index in range(entries)},
    )
    return state


def test_guided_turn_known_state_stays_inside_the_context_budget() -> None:
    state = _crowded_state()
    value = api_server._guided_turn_known_state(state, api_server.GUIDED_CONTEXT_BUDGET)
    assert value
    assert len(value) <= api_server.GUIDED_CONTEXT_BUDGET
    # The plan line is the part the provider must not lose; the fact list trims.
    assert value.startswith(api_server._guided_plan_state(state))


def test_the_composed_known_state_keeps_the_request_valid() -> None:
    """The exact 422: a known_state over the budget made every turn invalid."""
    state = _crowded_state()
    known_state = api_server._guided_turn_known_state(state, api_server.GUIDED_CONTEXT_BUDGET)
    request = GuidedRequest(
        PROTOCOL_VERSION, "req-1", "session-1", "nec", 3, "author-1",
        "el deseo lo dejaremos para luego", known_state=known_state,
    )
    assert request.validate() is None
    # The raw content really overflows: the composition is what clamps it.
    raw = (
        f"{api_server._guided_plan_state(state)}\n"
        f"{api_server._guided_known_state(state.candidate, budget=10**6)}"
    )
    assert len(raw) > api_server.GUIDED_CONTEXT_BUDGET


def test_guided_request_validation_names_the_oversized_field() -> None:
    request = GuidedRequest(
        PROTOCOL_VERSION, "req-1", "session-1", "nec", 3, "author-1", "hola",
        known_state="x" * (4_000 + 1), world_context="y" * (4_000 + 1),
    )
    error = request.validate()
    assert error is not None
    assert "known_state" in error.message and "world_context" in error.message
    assert error.retryable is False


def _adversarial_candidates() -> dict[str, CandidateState]:
    huge = "x" * 1_000_000
    return {
        "empty": CandidateState(),
        "one_megabyte_field": CandidateState(observations={"nombre": huge}),
        "ten_thousand_facts": CandidateState(
            observations={f"dato_{index}": "y" * 120 for index in range(10_000)},
        ),
        "non_ascii": CandidateState(
            observations={"nombre": "Ganic de Chaart 名前 🜚", "deseo": "ñ" * 50_000},
        ),
        "nested_values": CandidateState(
            observations={"nota": {"value": "z" * 90_000, "certainty": "proposed"}},
        ),
    }


@pytest.mark.parametrize("name", sorted(_adversarial_candidates()))
def test_the_composer_can_never_produce_an_invalid_request(name: str) -> None:
    """S3: for ANY candidate, size can not be the cause of a failure."""
    state = SessionState("session-1", "nec", "conversation", 3, "author-1")
    state.candidate = _adversarial_candidates()[name]
    known_state = api_server._guided_turn_known_state(state, api_server.GUIDED_CONTEXT_BUDGET)
    request = api_server._compose_guided_request(
        request_id="req-1",
        session_id="session-1",
        mundo="nec",
        revision=3,
        principal_id="author-1",
        author_input="sigue",
        reference_context="r" * 1_000_000,
        reference_name="  ",
        relation_goal="g" * 1_000_000,
        world_context="w" * 1_000_000,
        known_state=known_state,
    )
    assert request.validate() is None
    for field in ("reference_context", "relation_goal", "world_context", "known_state"):
        assert len(getattr(request, field)) <= api_server.GUIDED_CONTEXT_BUDGET
    assert request.reference_name is None


def test_a_trimmed_fact_list_says_how_many_it_dropped() -> None:
    """S2: truncation is visible and never cuts a fact in half."""
    candidate = CandidateState(
        observations={f"dato_{index}": "v" * 120 for index in range(200)},
    )
    value = api_server._guided_known_state(candidate, budget=1_000)
    assert len(value) <= 1_000
    assert "facts omitted)" in value
    assert value.count("\n") >= 1
    # The last kept line is whole: no marker glued onto a truncated value.
    assert "vvv…" not in value and "… (" in value


def _state_with(candidate: CandidateState) -> SessionState:
    state = SessionState("session-1", "nec", "conversation", 3, "author-1")
    state.candidate = candidate
    return state


def test_identity_is_read_from_the_nested_canon_record() -> None:
    """The name can live under ``identidad``; the target must still be named."""
    state = _state_with(CandidateState(
        accepted_canon={"identidad": {"value": {"nombre": "Ganic", "origen": "Chaart"}}},
    ))
    assert api_server._guided_entity_title(state) == "Ganic"
    assert api_server._guided_entity_slug(state) == "ganic"


def test_identity_cleans_an_observation_note() -> None:
    """``"Ganic (ya declarado…)"`` is a note, not a title."""
    state = _state_with(CandidateState(
        observations={"nombre": "Ganic (ya declarado por el autor; no volver a preguntar)"},
    ))
    assert api_server._guided_entity_title(state) == "Ganic"
    assert api_server._guided_entity_slug(state) == "ganic"


def test_identity_prefers_a_proposed_field_over_internal_notes() -> None:
    state = _state_with(CandidateState(
        proposals={"nombre": {"value": "Ganic de Chaart"}},
        observations={"nombre": "Ganic (nota vieja)"},
    ))
    assert api_server._guided_entity_title(state) == "Ganic de Chaart"
    assert api_server._guided_entity_slug(state) == "ganic-de-chaart"


def test_slug_drops_accents_and_stays_a_valid_filename() -> None:
    state = _state_with(CandidateState(proposals={"nombre": "Ñandú Pérez"}))
    assert api_server._guided_entity_slug(state) == "nandu-perez"
    assert api_server._guided_entity_title(state) == "Ñandú Pérez"


def test_identity_is_none_when_the_session_has_no_name() -> None:
    state = _state_with(CandidateState())
    assert api_server._guided_entity_title(state) is None
    assert api_server._guided_entity_slug(state) is None


def test_public_state_names_where_the_sheet_would_land() -> None:
    """The author must see the destination BEFORE anything is written."""
    state = _state_with(CandidateState(
        accepted_canon={
            "identidad": {"value": {"nombre": "Ganic"}},
            "deseo": {"value": "no ser una carga"},
        },
    ))
    profile = api_server.builtin_profile(api_server.GUIDED_CHARACTER_FLOW)
    assert profile is not None
    state.methodology_snapshot = MethodologySnapshot(
        flow_type="guided-character", profile=profile.as_dict(),
    )
    payload = api_server._guided_public_state(state)
    assert payload["target_preview"] == "personajes/ganic.md"
    # Decision B: the level is visible before anything is written.
    assert payload["target_level"] == "1º"


def test_public_state_exposes_the_recorded_level() -> None:
    state = _state_with(CandidateState(
        accepted_canon={
            "identidad": {"value": {"nombre": "Ganic"}},
            "deseo": {"value": "no ser una carga"},
        },
        proposals={"nivel": {"value": "2"}},
    ))
    profile = api_server.builtin_profile(api_server.GUIDED_CHARACTER_FLOW)
    state.methodology_snapshot = MethodologySnapshot(
        flow_type="guided-character", profile=profile.as_dict() if profile else None,
    )
    assert api_server._guided_public_state(state)["target_level"] == "2º"


def test_public_state_has_no_target_preview_while_the_candidate_is_incomplete() -> None:
    state = _state_with(CandidateState())
    profile = api_server.builtin_profile(api_server.GUIDED_CHARACTER_FLOW)
    state.methodology_snapshot = MethodologySnapshot(
        flow_type="guided-character", profile=profile.as_dict() if profile else None,
    )
    assert "target_preview" not in api_server._guided_public_state(state)
    assert "target_level" not in api_server._guided_public_state(state)
