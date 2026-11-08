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
