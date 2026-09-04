"""Focused protocol tests for bounded co-creation turns.

Covers: deadline/timeout/cancel, revision gating, the question ceiling
(enforced BEFORE any Hermes call), and authority-key rejection end-to-end.
Mirrors the ``test_guided_session`` harness.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from co_creation_protocol import (  # noqa: E402
    AUTHORITY_KEYS,
    CANVAS_PAYLOAD_KEYS,
    CANVAS_SYNC_ENVELOPE_KEYS,
    CancellationToken,
    Capabilities,
    CoCreationOutcome,
    CoCreationRequest,
    CoCreationResponse,
    ErrorCode,
    MAX_DEADLINE_MS,
    PROTOCOL_VERSION,
    QUESTION_CEILING,
    canvas_payload_issues,
    continue_co_creation_session,
    invoke_bounded_co_creation,
    reject_authority_keys,
)
from co_creation_session_store import CoCreationSessionStore  # noqa: E402


def request(revision: int = 0, auth: str = "author-1", author_input: str = "I want a skill") -> CoCreationRequest:
    return CoCreationRequest(
        PROTOCOL_VERSION, "req-1", "session-1", "author-1", revision, auth, author_input,
    )


def capabilities() -> Capabilities:
    return Capabilities(PROTOCOL_VERSION, True, True, True, MAX_DEADLINE_MS)


def _question_response(req: CoCreationRequest) -> CoCreationResponse:
    return CoCreationResponse(
        PROTOCOL_VERSION, req.request_id, req.session_id, req.base_revision,
        CoCreationOutcome.QUESTION,
        question="What purpose should the skill serve?",
        provenance=("hermes:run:r1",),
    )


async def provider_response(req: CoCreationRequest, _token: CancellationToken) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": req.request_id,
        "session_id": req.session_id,
        "outcome": "question",
        "question": "What purpose should the skill serve?",
    }


def test_capabilities_require_exact_co_creation_contract() -> None:
    assert Capabilities.from_payload({"protocol_version": "other"}) is None
    assert capabilities().admitted()
    assert not Capabilities(PROTOCOL_VERSION, True, False, True, 8_000).admitted()


def test_deadline_bounds_are_validated() -> None:
    assert request().deadline_ms == MAX_DEADLINE_MS
    invalid = CoCreationRequest(**{**request().__dict__, "deadline_ms": MAX_DEADLINE_MS + 1})
    error = invalid.validate()
    assert error and error.code is ErrorCode.INVALID_INPUT
    zero = CoCreationRequest(**{**request().__dict__, "deadline_ms": 0})
    assert zero.validate() and zero.validate().code is ErrorCode.INVALID_INPUT  # type: ignore[union-attr]


def test_stale_revision_and_wrong_principal_do_not_mutate_state() -> None:
    async def scenario() -> None:
        store = CoCreationSessionStore(":memory:")
        store.create("session-1", "author-1", "author-1")
        stale, stale_state = await continue_co_creation_session(
            store, provider_response, request(1), capabilities()
        )
        unauthorized, unauthorized_state = await continue_co_creation_session(
            store, provider_response, request(auth="other"), capabilities()
        )
        assert stale.error and stale.error.code is ErrorCode.REVISION_CONFLICT
        assert unauthorized.error and unauthorized.error.code is ErrorCode.UNAUTHORIZED
        assert stale_state is unauthorized_state is None
        assert store.recover("session-1", "author-1").revision == 0  # type: ignore[union-attr]

    asyncio.run(scenario())


def test_valid_question_commits_and_recovers() -> None:
    async def scenario() -> None:
        store = CoCreationSessionStore(":memory:")
        store.create("session-1", "author-1", "author-1")
        response, state = await continue_co_creation_session(
            store, provider_response, request(), capabilities()
        )
        assert response.outcome is CoCreationOutcome.QUESTION
        assert state and state.revision == 1
        assert state.question_count == 1
        recovered = store.recover("session-1", "author-1")
        assert recovered and recovered.pending_question == "What purpose should the skill serve?"
        assert recovered.messages[0].role == "author"
        assert recovered.messages[1].role == "assistant"

    asyncio.run(scenario())


def test_ceiling_is_enforced_before_hermes_call() -> None:
    async def scenario() -> None:
        store = CoCreationSessionStore(":memory:")
        store.create("session-1", "author-1", "author-1")
        for revision in range(QUESTION_CEILING):
            committed = store.commit(
                request(revision=revision),
                _question_response(request(revision=revision)),
            )
            assert committed is not None

        class SpyProvider:
            def __init__(self) -> None:
                self.calls = 0

            async def invoke(self, req: CoCreationRequest, _token: CancellationToken) -> dict:
                self.calls += 1
                return {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": req.request_id,
                    "session_id": req.session_id,
                    "outcome": "question",
                    "question": "One more?",
                }

        spy = SpyProvider()
        response, state = await continue_co_creation_session(
            store, spy, request(revision=QUESTION_CEILING), capabilities()
        )
        assert response.error is not None
        assert response.error.code is ErrorCode.CEILING_REACHED
        assert spy.calls == 0
        assert state is None

    asyncio.run(scenario())


def test_timeout_and_cancellation_are_typed_and_never_committed() -> None:
    async def slow(_request: CoCreationRequest, _token: CancellationToken) -> object:
        await asyncio.sleep(0.05)
        return {}

    async def scenario() -> None:
        short = CoCreationRequest(**{**request().__dict__, "deadline_ms": 1})
        timed_out = await invoke_bounded_co_creation(slow, short, capabilities())
        assert timed_out.error and timed_out.error.code is ErrorCode.TIMEOUT

        token = CancellationToken()
        token.cancel()
        cancelled = await invoke_bounded_co_creation(slow, request(), capabilities(), token)
        assert cancelled.error is not None and cancelled.error.code is ErrorCode.CANCELLED

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "bad",
    [None, {}, {"outcome": "question"}, {"protocol_version": PROTOCOL_VERSION, "outcome": "milestone_delta"}],
)
def test_malformed_provider_output_fails_closed(bad: object) -> None:
    async def provider(_request: CoCreationRequest, _token: CancellationToken) -> object:
        return bad

    result = asyncio.run(invoke_bounded_co_creation(provider, request(), capabilities()))
    assert result.outcome is CoCreationOutcome.ERROR
    assert result.error and result.error.code is ErrorCode.MALFORMED_OUTPUT


@pytest.mark.parametrize(
    "authority_payload",
    [
        {"acceptance": "approved"},
        {"delta": {"digest": "abc"}},
        {"delta": {"nested": {"authorization": "granted"}}},
    ],
)
def test_authority_key_rejection_end_to_end_never_commits(authority_payload: dict) -> None:
    """A provider envelope with authority keys must fail closed with zero
    session mutations, even when the provider itself returned it directly."""

    async def scenario() -> None:
        store = CoCreationSessionStore(":memory:")
        store.create("session-1", "author-1", "author-1")

        async def provider(req: CoCreationRequest, _token: CancellationToken) -> dict:
            return {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": req.request_id,
                "session_id": req.session_id,
                "outcome": "question",
                "question": "What purpose should the skill serve?",
                **authority_payload,
            }

        response, state = await continue_co_creation_session(
            store, provider, request(), capabilities()
        )
        assert response.error is not None
        assert response.error.code is ErrorCode.MALFORMED_OUTPUT
        assert state is None
        assert store.recover("session-1", "author-1").revision == 0  # type: ignore[union-attr]

    asyncio.run(scenario())


def test_milestone_delta_commits_milestone_advancement() -> None:
    async def scenario() -> None:
        store = CoCreationSessionStore(":memory:")
        store.create("session-1", "author-1", "author-1")

        async def provider(req: CoCreationRequest, _token: CancellationToken) -> dict:
            return {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": req.request_id,
                "session_id": req.session_id,
                "outcome": "milestone_delta",
                "milestone": "flujo_principal",
            }

        response, state = await continue_co_creation_session(
            store, provider, request(), capabilities()
        )
        assert response.outcome is CoCreationOutcome.MILESTONE_DELTA
        assert state is not None
        assert state.milestone == "flujo_principal"
        recovered = store.recover("session-1", "author-1")
        assert recovered is not None and recovered.question_count == 1

    asyncio.run(scenario())


def test_provider_unavailable_fails_closed() -> None:
    async def provider(_request: CoCreationRequest, _token: CancellationToken) -> object:
        raise ConnectionError("hermes down")

    result = asyncio.run(invoke_bounded_co_creation(provider, request(), capabilities()))
    assert result.outcome is CoCreationOutcome.UNAVAILABLE
    assert result.error and result.error.code is ErrorCode.PROVIDER_UNAVAILABLE


def test_unadmitted_capabilities_return_unavailable() -> None:
    async def scenario() -> None:
        store = CoCreationSessionStore(":memory:")
        store.create("session-1", "author-1", "author-1")
        response, state = await continue_co_creation_session(
            store, provider_response, request(), None
        )
        assert response.outcome is CoCreationOutcome.UNAVAILABLE
        assert state is None
        assert store.recover("session-1", "author-1").revision == 0  # type: ignore[union-attr]

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# TW12 canvas contract — envelope safety (REQ-CC-23) + payload validation
# ---------------------------------------------------------------------------

def test_canvas_envelope_keys_stay_outside_authority_keys() -> None:
    """REQ-CC-23: canvas-sync envelope extension keys never collide with the
    8-key AUTHORITY_KEYS set, so REQ-CC-7 validation passes by construction."""
    assert AUTHORITY_KEYS.isdisjoint(CANVAS_SYNC_ENVELOPE_KEYS)
    assert CANVAS_SYNC_ENVELOPE_KEYS == {"base_revision", "payload"}
    envelope = {"base_revision": 0, "payload": {"purpose": "x"}}
    assert reject_authority_keys(envelope) is False


def test_canvas_payload_typed_keys_are_editable_sections() -> None:
    assert CANVAS_PAYLOAD_KEYS == {
        "name", "description", "purpose", "scope", "main_flow",
        "branches", "rules", "pending_questions", "world",
    }
    assert CANVAS_PAYLOAD_KEYS.isdisjoint(AUTHORITY_KEYS)


def test_canvas_payload_issues_accepts_typed_payload() -> None:
    payload = {
        "name": "Skill",
        "description": "d",
        "purpose": "p",
        "scope": "s",
        "main_flow": "f",
        "branches": ["a", "b"],
        "rules": ["r"],
        "pending_questions": [{"text": "q", "state": "pendiente"}],
        "world": "nec",
    }
    assert canvas_payload_issues(payload) == []


def test_canvas_payload_issues_rejects_authority_keys_flat_and_nested() -> None:
    assert canvas_payload_issues({"acceptance": "approved"}) != []
    assert canvas_payload_issues({"purpose": {"nested": {"authorization": "granted"}}}) != []


def test_canvas_payload_issues_rejects_unknown_and_mistyped_keys() -> None:
    assert canvas_payload_issues({"hacked": 1}) != []
    assert canvas_payload_issues({"branches": "not-a-list"}) != []
    assert canvas_payload_issues({"rules": [1, 2]}) != []
    assert canvas_payload_issues({"branches": ["a", 2]}) != []
    assert canvas_payload_issues({"purpose": 42}) != []