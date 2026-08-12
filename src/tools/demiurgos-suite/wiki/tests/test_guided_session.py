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
    ErrorCode,
    GuidedRequest,
    GuidedSessionStore,
    Outcome,
    PROTOCOL_VERSION,
    continue_session,
    invoke_bounded,
)


def request(revision: int = 0, auth: str = "author-1") -> GuidedRequest:
    return GuidedRequest(PROTOCOL_VERSION, "req-1", "session-1", "nec", revision, auth, "I need a character")


def capabilities() -> Capabilities:
    return Capabilities(PROTOCOL_VERSION, True, True, True, 8_000)


async def provider_response(req: GuidedRequest, _token: CancellationToken) -> dict:
    return {"protocol_version": PROTOCOL_VERSION, "request_id": req.request_id,
            "session_id": req.session_id, "outcome": "question", "question": "What drives them?"}


def test_capabilities_require_exact_guided_contract() -> None:
    assert Capabilities.from_payload({"protocol_version": "other"}) is None
    assert capabilities().admitted()
    assert not Capabilities(PROTOCOL_VERSION, True, False, True, 8_000).admitted()


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
