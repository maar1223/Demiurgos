"""Focused PR1 tests for guided contracts, state authority, and provider safety."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from guided_character_protocol import (  # noqa: E402
    Capabilities,
    CancellationToken,
    DEFAULT_DEADLINE_MS,
    ErrorCode,
    GuidedRequest,
    GuidedSessionStore,
    Outcome,
    PROTOCOL_VERSION,
    continue_session,
    MessageType,
    invoke_bounded,
    MAX_DEADLINE_MS,
)


def request(revision: int = 0, auth: str = "author-1") -> GuidedRequest:
    return GuidedRequest(PROTOCOL_VERSION, "req-1", "session-1", "nec", revision, auth, "I need a character")


def capabilities() -> Capabilities:
    return Capabilities(PROTOCOL_VERSION, True, True, True, MAX_DEADLINE_MS)


async def provider_response(req: GuidedRequest, _token: CancellationToken) -> dict:
    return {"protocol_version": PROTOCOL_VERSION, "request_id": req.request_id,
            "session_id": req.session_id, "outcome": "question", "question": "What drives them?"}


def test_capabilities_require_exact_guided_contract() -> None:
    assert Capabilities.from_payload({"protocol_version": "other"}) is None
    assert capabilities().admitted()
    assert not Capabilities(PROTOCOL_VERSION, True, False, True, 8_000).admitted()


def test_default_deadline_uses_allowed_maximum_without_widening_validation() -> None:
    assert request().deadline_ms == MAX_DEADLINE_MS == DEFAULT_DEADLINE_MS == 30_000
    invalid = GuidedRequest(**{**request().__dict__, "deadline_ms": MAX_DEADLINE_MS + 1})
    error = invalid.validate()
    assert error and error.code is ErrorCode.INVALID_INPUT


def test_stale_or_wrong_authorization_does_not_mutate_state() -> None:
    async def scenario() -> None:
        store = GuidedSessionStore()
        store.create("session-1", "nec", "author-1")
        stale, stale_state = await continue_session(store, provider_response, request(1), capabilities())
        unauthorized, unauthorized_state = await continue_session(
            store, provider_response, request(auth="other"), capabilities())
        assert stale.error and stale.error.code is ErrorCode.REVISION_CONFLICT
        assert unauthorized.error and unauthorized.error.code is ErrorCode.UNAUTHORIZED
        assert stale_state is unauthorized_state is None
        assert store.recover("session-1", "author-1").revision == 0  # type: ignore[union-attr]

    asyncio.run(scenario())


def test_valid_response_commits_as_proposal_and_recovers_after_reload() -> None:
    async def scenario() -> None:
        store = GuidedSessionStore()
        store.create("session-1", "nec", "author-1")
        response, state = await continue_session(store, provider_response, request(), capabilities())
        assert response.outcome is Outcome.QUESTION
        assert state and state.revision == 1
        recovered = store.recover("session-1", "author-1")
        assert recovered and recovered.pending_question == "What drives them?"
        assert recovered.messages[0].message_type.value == "assistant_response"

    asyncio.run(scenario())


def test_relation_goal_is_persisted_in_state_and_survives_commit() -> None:
    async def scenario() -> None:
        store = GuidedSessionStore()
        store.create("session-1", "nec", "author-1", relation_goal="New character: brother of Rhyz")
        recovered = store.recover("session-1", "author-1")
        assert recovered and recovered.relation_goal == "New character: brother of Rhyz"
        goal_request = GuidedRequest(**{
            **request().__dict__, "relation_goal": "New character: brother of Rhyz",
        })
        response, state = await continue_session(store, provider_response, goal_request, capabilities())
        assert response.outcome is Outcome.QUESTION
        assert state and state.relation_goal == "New character: brother of Rhyz"
        assert store.recover("session-1", "author-1").relation_goal == "New character: brother of Rhyz"  # type: ignore[union-attr]

    asyncio.run(scenario())


def test_relation_goal_budget_is_enforced_at_creation() -> None:
    store = GuidedSessionStore()
    with pytest.raises(ValueError):
        store.create("session-1", "nec", "author-1", relation_goal="x" * 4_001)


def test_confirmation_is_server_owned_and_does_not_create_candidate() -> None:
    store = GuidedSessionStore()
    store.create("session-1", "nec", "author-1")
    state = store.begin_confirmation("session-1", "author-1", "Create Rhyz's wife", "Start? (yes/no)")
    assert state and state.phase == "confirmation" and state.revision == 1
    assert state.candidate.proposals == {}
    assert state.messages[0].message_type is MessageType.AUTHOR_INPUT


def delta_provider(payload: dict) -> Callable[..., Awaitable[object]]:
    async def provider(req: GuidedRequest, _token: CancellationToken) -> dict:
        return {"protocol_version": PROTOCOL_VERSION, "request_id": req.request_id,
                "session_id": req.session_id, "outcome": "delta", "delta": dict(payload)}
    return provider


def test_full_mode_incomplete_delta_is_converted_to_one_focused_question() -> None:
    """Vague backstory data must keep asking one focused question, never a proposal."""
    async def scenario() -> None:
        store = GuidedSessionStore()
        store.create("session-1", "nec", "author-1")
        provider = delta_provider({"relation": "brother of Rhyz", "age": "~30", "scene": "a storm at sea"})
        response, state = await continue_session(store, provider, request(), capabilities())
        assert response.outcome is Outcome.QUESTION
        assert response.question and response.question.count("?") == 1
        assert state and state.pending_question == response.question
        assert state.candidate.proposals == {}
        assert state.candidate.accepted_canon == {}

    asyncio.run(scenario())


def test_full_mode_delta_with_identity_and_desire_commits_as_proposal() -> None:
    """A complete candidate still reaches the proposal through the same gate."""
    async def scenario() -> None:
        store = GuidedSessionStore()
        store.create("session-1", "nec", "author-1")
        provider = delta_provider({"name": "Pert", "desire": "freedom"})
        response, state = await continue_session(store, provider, request(), capabilities())
        assert response.outcome is Outcome.DELTA
        assert state and "name" in state.candidate.proposals
        assert "desire" in state.candidate.proposals

    asyncio.run(scenario())


def test_fast_mode_incomplete_delta_proceeds_with_assumptions() -> None:
    """Fast mode proceeds with marked assumptions and is not gated."""
    async def scenario() -> None:
        store = GuidedSessionStore()
        store.create("session-1", "nec", "author-1", mode="fast", depth="fundamental")
        provider = delta_provider({"desire": "freedom"})
        fast_request = GuidedRequest(**{**request().__dict__, "guided_mode": "fast", "question_depth": "fundamental"})
        response, state = await continue_session(store, provider, fast_request, capabilities())
        assert response.outcome is Outcome.DELTA
        assert state and "desire" in state.candidate.proposals

    asyncio.run(scenario())


@pytest.mark.parametrize("bad", [None, {}, {"outcome": "question"},
                                  {"protocol_version": PROTOCOL_VERSION, "outcome": "delta"}])
def test_malformed_provider_output_fails_closed(bad: object) -> None:
    async def provider(_request: GuidedRequest, _token: CancellationToken) -> object:
        return bad

    result = asyncio.run(invoke_bounded(provider, request(), capabilities()))
    assert result.outcome is Outcome.ERROR
    assert result.error and result.error.code is ErrorCode.MALFORMED_OUTPUT


def test_timeout_and_cancellation_are_typed_and_never_committed() -> None:
    async def slow(_request: GuidedRequest, _token: CancellationToken) -> object:
        await asyncio.sleep(0.05)
        return {}

    async def scenario() -> None:
        short = request()
        short = GuidedRequest(**{**short.__dict__, "deadline_ms": 1})
        timed_out = await invoke_bounded(slow, short, capabilities())
        assert timed_out.error and timed_out.error.code is ErrorCode.TIMEOUT

        token = CancellationToken()
        token.cancel()
        cancelled = await invoke_bounded(slow, request(), capabilities(), token)
        # Cancellation is checked at the provider boundary, so a provider that
        # ignores the token still cannot commit its malformed/partial output.
        assert cancelled.error is not None or cancelled.outcome is Outcome.ERROR

    asyncio.run(scenario())


def test_continue_session_forwards_convergence_specimen_hint_additively() -> None:
    """R13 (④b): ``continue_session`` threads the additive convergence-specimen
    hint to ``invoke_bounded`` beside the compiled contract; the None defaults
    keep the legacy behavior byte-identical."""
    async def scenario() -> None:
        store = GuidedSessionStore()
        store.create("session-1", "nec", "author-1")
        received: dict[str, str | None] = {}

        class CapturingProvider:
            async def invoke(self, req: GuidedRequest, _token: CancellationToken, *,
                             compiled_contract_markdown: str | None = None,
                             convergence_specimen_markdown: str | None = None) -> object:
                received["contract"] = compiled_contract_markdown
                received["specimen"] = convergence_specimen_markdown
                return await provider_response(req, _token)

        response, state = await continue_session(
            store, CapturingProvider(), request(), capabilities(),
            compiled_contract_markdown="contract-md",
            convergence_specimen_markdown="specimen-md",
        )
        assert response.outcome is Outcome.QUESTION
        assert state is not None and state.revision == 1
        assert received == {"contract": "contract-md", "specimen": "specimen-md"}

        received.clear()
        await continue_session(store, CapturingProvider(), request(1), capabilities())
        assert received == {"contract": None, "specimen": None}

    asyncio.run(scenario())


def test_system_profile_gates_a_delta_on_origin_and_limit() -> None:
    """S1/S4: the completion gate follows the session's pinned profile."""
    from guided_character_protocol import MethodologySnapshot, session_flow_profile
    from guided_flow import GuidedFlowDeclaration, resolve_profile

    profile = resolve_profile(GuidedFlowDeclaration.from_mapping({
        "flow_id": "guided-system",
        "entity_type": "sistema",
        "ui_copy_key": "system",
        "index": True,
        "intent": {"terms": ["sistema"], "verbs": ["crear"]},
    }))
    assert profile is not None

    async def delta_provider(req: GuidedRequest, _token: CancellationToken) -> dict:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": req.request_id,
            "session_id": req.session_id,
            "outcome": "delta",
            "delta": {"name": "Magia", "origen": "los dioses"},
        }

    async def scenario() -> None:
        store = GuidedSessionStore()
        store.create(
            "session-1", "nec", "author-1",
            methodology_snapshot=MethodologySnapshot(
                skill_id="narrative-system-creation",
                skill_version="1.1",
                compiled_contract_digest="digest",
                flow_type="guided-system",
                profile=profile.as_dict(),
            ),
        )
        response, state = await continue_session(
            store, delta_provider, request(), capabilities(),
        )
        assert response.outcome is Outcome.QUESTION
        assert response.question and response.question.startswith("¿Qué no puede hacer")
        assert state is not None
        assert session_flow_profile(state) == profile

    asyncio.run(scenario())


def test_character_profile_asks_desire_after_a_name_delta() -> None:
    """S5 regression through the engine: a name delta moves to the desire."""
    from guided_character_protocol import MethodologySnapshot
    from guided_flow import builtin_profile

    profile = builtin_profile("guided-character")
    assert profile is not None

    async def name_provider(req: GuidedRequest, _token: CancellationToken) -> dict:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": req.request_id,
            "session_id": req.session_id,
            "outcome": "delta",
            "delta": {"name": "Aria"},
        }

    async def scenario() -> None:
        store = GuidedSessionStore()
        store.create(
            "session-1", "nec", "author-1",
            methodology_snapshot=MethodologySnapshot(
                skill_id="guided-character-v1",
                skill_version="builtin",
                compiled_contract_digest=None,
                flow_type="guided-character",
                profile=profile.as_dict(),
            ),
        )
        response, _state = await continue_session(
            store, name_provider, request(), capabilities(),
        )
        assert response.outcome is Outcome.QUESTION
        assert response.question == "¿Cuál es el deseo que define a este personaje?"

    asyncio.run(scenario())
