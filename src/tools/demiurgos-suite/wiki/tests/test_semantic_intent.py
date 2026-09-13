"""Focused tests for the Hermes semantic intent contract, validator, and bounds."""

from __future__ import annotations

import asyncio
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from semantic_intent import (  # noqa: E402
    MAX_CONTINUATION_DELTA_KEYS,
    MAX_CONTINUATION_QUESTION_CHARS,
    MAX_CONTINUATION_VALUE_CHARS,
    MAX_RESPONSE_CHARS,
    MAX_SEMANTIC_ATTEMPTS,
    SELF_CONTAINED_SEMANTIC_STATES,
    SemanticContext,
    SemanticContinuation,
    SemanticDecision,
    SemanticIntentProvider,
    SemanticResult,
    SemanticState,
    action_for_state,
    normalize_context,
    unavailable_copy,
    validate_semantic_decision,
)

_ALL_STATES = ("allow", "clarify", "require_confirmation", "proposal_ready", "blocked")
_ACTIONS = {
    "allow": "answer",
    "clarify": "ask_question",
    "require_confirmation": "request_confirmation",
    "proposal_ready": "show_proposal",
    "blocked": "blocked_explanation",
}


def valid_payload(state: str = "allow", **overrides) -> dict:
    payload = {
        "state": state,
        "response": "Understood.",
        "request_id": "request-1",
        "session_id": "session-1",
        "guided": True,
    }
    payload.update(overrides)
    return payload


def assert_rejected(value) -> None:
    result = validate_semantic_decision(value)
    assert not result.admitted
    assert result.decision is None
    assert result.reason


def test_all_five_states_validate() -> None:
    for state in _ALL_STATES:
        result = validate_semantic_decision(valid_payload(state))
        assert result.admitted
        assert result.reason == ""
        assert result.decision is not None
        assert result.decision.state == state


def test_action_is_derived_server_side_for_every_state() -> None:
    for state in _ALL_STATES:
        assert action_for_state(state) == _ACTIONS[state]
    assert set(_ACTIONS) == set(_ALL_STATES)


def test_self_contained_states_are_the_deliverable_envelope_subset() -> None:
    assert SELF_CONTAINED_SEMANTIC_STATES == frozenset({"allow", "clarify", "blocked"})
    assert {"allow", "clarify", "blocked"} <= set(_ALL_STATES)
    assert "require_confirmation" not in SELF_CONTAINED_SEMANTIC_STATES
    assert "proposal_ready" not in SELF_CONTAINED_SEMANTIC_STATES


def test_decision_is_immutable_frozen_dto() -> None:
    decision = SemanticDecision(state="allow", response="OK", request_id="request-1")
    with pytest.raises(FrozenInstanceError):
        decision.response = "tampered"


def test_unknown_state_rejected() -> None:
    for state in ("write", "execute", "approve", "UNKNOWN", "allow_now", ""):
        assert_rejected(valid_payload(state))


def test_missing_required_fields_rejected() -> None:
    for field in ("state", "response", "request_id"):
        payload = valid_payload()
        del payload[field]
        assert_rejected(payload)


def test_empty_or_non_string_values_rejected() -> None:
    assert_rejected(valid_payload(response=""))
    assert_rejected(valid_payload(response="   "))
    assert_rejected(valid_payload(response=42))
    assert_rejected(valid_payload(request_id=""))
    assert_rejected(valid_payload(request_id=123))
    assert_rejected(valid_payload(session_id=42))
    assert_rejected(valid_payload(guided="yes"))


def test_over_length_response_is_bounded_and_rejected() -> None:
    assert_rejected(valid_payload(response="x" * (MAX_RESPONSE_CHARS + 1)))
    bounded = validate_semantic_decision(valid_payload(response="x" * MAX_RESPONSE_CHARS))
    assert bounded.admitted


def test_provider_supplied_reference_is_server_only_and_rejected() -> None:
    assert_rejected(valid_payload(reference="evidence-123"))
    assert_rejected(valid_payload(reference=""))


def test_malformed_non_mapping_values_rejected() -> None:
    for value in (None, "text", 42, ["allow"], ("allow",), object()):
        assert_rejected(value)


def test_valid_decision_preserves_required_fields() -> None:
    result = validate_semantic_decision(valid_payload("proposal_ready"))
    assert result.decision is not None
    assert result.decision.request_id == "request-1"
    assert result.decision.session_id == "session-1"
    assert result.decision.guided is True


class Runs:
    def __init__(self, *payloads) -> None:
        self._payloads = list(payloads)
        self.starts = 0
        self.requests: list[object] = []

    async def start(self, request: object) -> str:
        self.starts += 1
        self.requests.append(request)
        return f"run-{self.starts}"

    async def events(self, run_id: str):
        if self._payloads:
            payload = self._payloads.pop(0)
            yield {"event": "run.completed", "run_id": run_id, "output": payload}
        else:
            yield {"event": "run.completed", "run_id": run_id, "output": None}


async def decide_once(provider: SemanticIntentProvider, runs: Runs, **kwargs):
    return await provider.decide("Create a character", request_id="request-1", **kwargs)


def test_valid_decision_on_first_attempt() -> None:
    async def scenario() -> None:
        runs = Runs(valid_payload("allow"))
        result = await decide_once(SemanticIntentProvider(runs), runs)
        assert result.decision is not None
        assert result.state == "allow"
        assert result.action == "answer"
        assert result.attempts == 1
        assert result.unavailable is False
        assert runs.starts == 1

    asyncio.run(scenario())


def test_fenced_json_output_is_admitted() -> None:
    async def scenario() -> None:
        fenced = "```json\n" + json.dumps(valid_payload("allow")) + "\n```"
        runs = Runs(fenced)
        result = await decide_once(SemanticIntentProvider(runs), runs)
        assert result.decision is not None
        assert result.state == "allow"
        assert result.unavailable is False
        assert result.attempts == 1
        assert runs.starts == 1

    asyncio.run(scenario())


def test_invalid_attempts_retry_then_succeed_within_bound() -> None:
    async def scenario() -> None:
        runs = Runs(
            valid_payload("bad_state"),
            valid_payload("response"),
            valid_payload("require_confirmation"),
        )
        result = await decide_once(SemanticIntentProvider(runs), runs)
        assert result.decision is not None
        assert result.state == "require_confirmation"
        assert result.action == "request_confirmation"
        assert result.attempts == 3
        assert runs.starts == 3

    asyncio.run(scenario())


def test_configured_attempts_never_exceed_contract_bound() -> None:
    async def scenario() -> None:
        runs = Runs(valid_payload("bad"), valid_payload("bad"), valid_payload("bad"))
        result = await decide_once(SemanticIntentProvider(runs, max_attempts=99), runs)
        assert result.state == "blocked"
        assert result.attempts == MAX_SEMANTIC_ATTEMPTS
        assert runs.starts == MAX_SEMANTIC_ATTEMPTS

    asyncio.run(scenario())


def test_exhausted_attempts_fail_closed_blocked_without_fallback(monkeypatch) -> None:
    monkeypatch.delenv("DEMIURGOS_LANGUAGE", raising=False)

    async def scenario() -> None:
        runs = Runs(valid_payload("bad"), valid_payload("bad"), valid_payload("bad"))
        result = await decide_once(SemanticIntentProvider(runs), runs)
        assert result.decision is None
        assert result.state == "blocked"
        assert result.action == "blocked_explanation"
        assert result.unavailable is True
        assert result.response.startswith("El Asistente IA no pudo")
        assert "fallback" not in result.as_dict()
        assert result.attempts == MAX_SEMANTIC_ATTEMPTS
        assert runs.starts == MAX_SEMANTIC_ATTEMPTS

    asyncio.run(scenario())


def test_provider_never_enables_lexical_or_chat_fallback() -> None:
    provider = SemanticIntentProvider(Runs())
    assert not hasattr(provider, "_fallback_enabled")
    with pytest.raises(TypeError):
        SemanticIntentProvider(Runs(), fallback_enabled=True)


def test_provider_failure_retries_bounded_and_fails_closed() -> None:
    async def scenario() -> None:
        class FailingRuns:
            starts = 0

            async def start(self, request: object) -> str:
                self.starts += 1
                raise RuntimeError("provider unavailable")

        runs = FailingRuns()
        result = await decide_once(SemanticIntentProvider(runs), runs)
        assert result.decision is None
        assert result.state == "blocked"
        assert result.unavailable is True
        assert runs.starts == MAX_SEMANTIC_ATTEMPTS

    asyncio.run(scenario())


def test_malformed_output_never_inferred_as_permission() -> None:
    async def scenario() -> None:
        runs = Runs("not-json", b"bytes", {"state": "approve", "response": "go"})
        result = await decide_once(SemanticIntentProvider(runs), runs)
        assert result.decision is None
        assert result.unavailable is True
        assert result.state == "blocked"

    asyncio.run(scenario())


def test_no_canon_or_disk_mutation_on_any_path() -> None:
    root = _WIKI.parents[3]
    mundos = root / "mundos"
    if not mundos.is_dir():
        pytest.skip("world canon directory not present in this checkout")

    def snapshot() -> dict:
        state = {}
        for path in mundos.rglob("*"):
            if path.is_file():
                stat = path.stat()
                state[str(path.relative_to(mundos))] = (stat.st_size, stat.st_mtime_ns)
        return state

    before = snapshot()

    async def scenario() -> None:
        runs = Runs(valid_payload("proposal_ready"), valid_payload("bad"))
        provider = SemanticIntentProvider(runs)
        await decide_once(provider, runs)
        await decide_once(provider, runs)

    asyncio.run(scenario())

    assert snapshot() == before


# ---------------------------------------------------------------------------
# PR1 corrective contract (tasks 1.1-1.3): bounded authorized context reaches
# the Hermes prompt, unavailable copy is localized and free of provider terms,
# and exhausted attempts set the unavailable flag with zero fallback.
# ---------------------------------------------------------------------------

_ORDERED_CONTEXT = {
    "mundo": "nec",
    "ficha": "Kael Thornwood",
    "reference": "lore/ashen-valley.md",
    "graph": "Kael Thornwood -> Ashen Valley",
}

_NO_SECRETS = ("sk-secret-123", "auth-token", "/etc/passwd", "write-lore", "abc123")
_NO_AUTHORITY_KEYS = ("api_key", "token", "path")

_PROVIDER_TERMS = (
    "hermes", "provider", "gateway", "http ", "http:", "timeout", "quota",
    "credits", "credential", "model", "error:",
)


def test_decide_prompt_carries_bounded_authorized_context() -> None:
    async def scenario() -> None:
        runs = Runs(valid_payload("allow"))
        provider = SemanticIntentProvider(runs)
        result = await provider.decide(
            "Create a character",
            request_id="request-1",
            session_id="session-1",
            context=dict(_ORDERED_CONTEXT),
        )
        assert result.decision is not None
        assert runs.starts == 1
        prompt = runs.requests[0].prompt
        for key, value in _ORDERED_CONTEXT.items():
            assert key in prompt
            assert value in prompt

    asyncio.run(scenario())


def test_context_is_bounded_never_credentials_or_write_authority() -> None:
    provider = SemanticIntentProvider(Runs())
    prompt = provider._build_prompt(
        "Create a character",
        "request-1",
        "session-1",
        context={
            **_ORDERED_CONTEXT,
            "api_key": "sk-secret-123",
            "token": "auth-token",
            "path": "/etc/passwd",
            "authority": "write-lore",
            "digest": "abc123",
        },
    )
    for secret in _NO_SECRETS:
        assert secret not in prompt
    for key in _NO_AUTHORITY_KEYS:
        assert key not in prompt
    for key, value in _ORDERED_CONTEXT.items():
        assert key in prompt and value in prompt


def test_normalize_context_admits_only_bounded_keys() -> None:
    bounded = normalize_context(
        {"mundo": "nec", "ficha": "Kael", "api_key": "sk-secret", "token": "t"}
    )
    assert bounded.mundo == "nec"
    assert bounded.ficha == "Kael"
    assert bounded.reference is None and bounded.graph is None
    assert bounded.as_dict() == {
        "mundo": "nec", "ficha": "Kael", "reference": None, "graph": None,
    }
    assert normalize_context(None) == SemanticContext()
    assert normalize_context("not-a-mapping") == SemanticContext()
    assert normalize_context({"ficha": 42}) == SemanticContext()


def test_unavailable_copy_is_spanish_by_default_and_safe(monkeypatch) -> None:
    monkeypatch.delenv("DEMIURGOS_LANGUAGE", raising=False)
    copy = unavailable_copy()
    assert copy.startswith("El Asistente IA no pudo")
    lowered = copy.lower()
    for term in _PROVIDER_TERMS:
        assert term not in lowered


@pytest.mark.parametrize("language,prefix", [
    ("es", "El Asistente IA no pudo"),
    ("es-ar", "El Asistente IA no pudo"),
    ("en", "The AI Assistant could not"),
])
def test_unavailable_copy_follows_demiurgos_language(language, prefix, monkeypatch) -> None:
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", language)
    assert unavailable_copy().startswith(prefix)


# ---------------------------------------------------------------------------
# Single-run continuation contract (task 2.3): require_confirmation and
# proposal_ready are real only when a typed continuation backs them in the
# SAME Hermes envelope. The validator admits the base five-state envelope for
# every state (state classification is orthogonal to routing), but any
# present continuation must be strictly structured, bounded, and free of
# provider authority claims.
# ---------------------------------------------------------------------------


def _continuation_payload(state: str = "proposal_ready", **overrides) -> dict:
    payload = valid_payload(state, guided=True)
    payload["continuation"] = {
        "outcome": "question" if state == "require_confirmation" else "delta",
        "question": "¿Creo este personaje?" if state == "require_confirmation" else None,
        "delta": None if state == "require_confirmation" else {"name": "Rhyz's Wife", "desire": "freedom"},
    }
    payload.update(overrides)
    return payload


def test_proposal_ready_continuation_delta_is_admitted_and_preserved() -> None:
    result = validate_semantic_decision(_continuation_payload("proposal_ready"))
    assert result.admitted
    assert result.decision is not None
    assert result.decision.continuation is not None
    assert result.decision.continuation.outcome == "delta"
    assert result.decision.continuation.delta == {"name": "Rhyz's Wife", "desire": "freedom"}


def test_require_confirmation_continuation_question_is_admitted_and_preserved() -> None:
    result = validate_semantic_decision(_continuation_payload("require_confirmation"))
    assert result.admitted
    assert result.decision is not None
    assert result.decision.continuation is not None
    assert result.decision.continuation.outcome == "question"
    assert result.decision.continuation.question == "¿Creo este personaje?"


def test_base_guided_proposal_envelope_admits_without_continuation() -> None:
    """State classification admits the five states; backing is a routing concern.

    A proposal_ready/require_confirmation decision without a continuation is a
    valid state envelope that the router MUST fail closed because no guarded
    session/proposal backs it (never a hollow emit)."""
    for state in ("require_confirmation", "proposal_ready"):
        result = validate_semantic_decision(valid_payload(state))
        assert result.admitted
        assert result.decision is not None
        assert result.decision.continuation is None


def test_continuation_is_rejected_for_self_contained_states() -> None:
    for state in ("allow", "clarify", "blocked"):
        assert_rejected(_continuation_payload(state))


def test_continuation_is_rejected_when_guided_is_false() -> None:
    assert_rejected(_continuation_payload("proposal_ready", guided=False))


def test_continuation_question_outcome_requires_a_bounded_question() -> None:
    assert_rejected(_continuation_payload("require_confirmation", continuation={"outcome": "question"}))
    assert_rejected(_continuation_payload("require_confirmation", continuation={"outcome": "question", "question": "  "}))
    assert_rejected(_continuation_payload("require_confirmation", continuation={"outcome": "question", "question": "x" * (MAX_CONTINUATION_QUESTION_CHARS + 1)}))


def test_continuation_delta_outcome_requires_a_bounded_mapping() -> None:
    assert_rejected(_continuation_payload("proposal_ready", continuation={"outcome": "delta"}))
    assert_rejected(_continuation_payload("proposal_ready", continuation={"outcome": "delta", "delta": {}}))
    assert_rejected(_continuation_payload("proposal_ready", continuation={"outcome": "delta", "delta": "not-a-map"}))


def test_continuation_outcome_fields_are_mutually_exclusive() -> None:
    assert_rejected(_continuation_payload("require_confirmation", continuation={"outcome": "question", "question": "Go?", "delta": {"x": 1}}))
    assert_rejected(_continuation_payload("proposal_ready", continuation={"outcome": "delta", "question": "Go?", "delta": {"x": 1}}))


def test_continuation_rejects_unknown_fields() -> None:
    assert_rejected(_continuation_payload("proposal_ready", continuation={"outcome": "delta", "delta": {"x": 1}, "extra": True}))


@pytest.mark.parametrize("authoritative", [
    "target", "digest", "revision", "authority", "reference",
    "acceptance", "accepted_canon", "authorization",
])
def test_continuation_delta_rejects_provider_authority_keys(authoritative: str) -> None:
    assert_rejected(_continuation_payload("proposal_ready", continuation={"outcome": "delta", "delta": {authoritative: "x"}}))


def test_continuation_delta_rejects_authority_keys_nested() -> None:
    assert_rejected(_continuation_payload("proposal_ready", continuation={
        "outcome": "delta", "delta": {"relations": {"target": "lore/canon.md"}},
    }))
    assert_rejected(_continuation_payload("proposal_ready", continuation={
        "outcome": "delta", "delta": {"list": [{"digest": "abc"}]},
    }))


def test_continuation_delta_is_bounded() -> None:
    oversized = {f"key_{i}": i for i in range(MAX_CONTINUATION_DELTA_KEYS + 1)}
    assert_rejected(_continuation_payload("proposal_ready", continuation={"outcome": "delta", "delta": oversized}))
    assert_rejected(_continuation_payload("proposal_ready", continuation={"outcome": "delta", "delta": {"long": "x" * (MAX_CONTINUATION_VALUE_CHARS + 1)}}))
    assert_rejected(_continuation_payload("proposal_ready", continuation={
        "outcome": "delta", "delta": {"deep": {"deep": {"deep": {"deep": {"deep": 1}}}}},
    }))


def test_continuation_is_an_immutable_frozen_dto() -> None:
    continuation = SemanticContinuation("delta", delta={"name": "Rhyz"})
    with pytest.raises(FrozenInstanceError):
        continuation.delta = {"tampered": True}


def test_provider_prompt_documents_the_single_run_continuation_contract() -> None:
    provider = SemanticIntentProvider(Runs())
    prompt = provider._build_prompt("Create a character", "request-1", "session-1")
    assert "continuation" in prompt
    assert "require_confirmation" in prompt and "proposal_ready" in prompt
    assert "target" in prompt and "digest" in prompt and "revision" in prompt
    assert "never write or claim approval" in prompt.lower()


# ---------------------------------------------------------------------------
# Guided-explicitness contract (REQ-GFC-01): an additive bounded field splits
# an explicit imperative (auto-open) from musing/absent (suggest only). It is
# emitted only for a guided continuation state and NEVER fails the envelope.
# ---------------------------------------------------------------------------


def test_valid_imperative_guided_explicitness_is_preserved() -> None:
    result = validate_semantic_decision(
        _continuation_payload("require_confirmation", guided_explicitness="imperative")
    )
    assert result.admitted
    assert result.decision is not None
    assert result.decision.guided_explicitness == "imperative"


def test_absent_or_invalid_guided_explicitness_defaults_to_musing() -> None:
    absent = validate_semantic_decision(_continuation_payload("proposal_ready"))
    assert absent.admitted
    assert absent.decision is not None
    assert absent.decision.guided_explicitness == "musing"

    for invalid in ("shout", "", None, 1, ["imperative"]):
        result = validate_semantic_decision(
            _continuation_payload("proposal_ready", guided_explicitness=invalid)
        )
        assert result.admitted, invalid  # degradation never blocks the envelope
        assert result.decision is not None
        assert result.decision.guided_explicitness == "musing"


def test_guided_explicitness_is_emitted_only_for_guided_continuation_states() -> None:
    imperative = validate_semantic_decision(
        _continuation_payload("proposal_ready", guided_explicitness="imperative")
    )
    assert imperative.decision is not None
    payload = SemanticResult(
        decision=imperative.decision, attempts=1, request_id="request-1"
    ).as_dict()
    assert payload["guided_explicitness"] == "imperative"

    musing = validate_semantic_decision(_continuation_payload("require_confirmation"))
    assert musing.decision is not None
    payload = SemanticResult(
        decision=musing.decision, attempts=1, request_id="request-1"
    ).as_dict()
    assert payload["guided_explicitness"] == "musing"

    for state in ("allow", "clarify", "blocked"):
        plain = validate_semantic_decision(valid_payload(state, guided=True))
        assert plain.decision is not None
        assert "guided_explicitness" not in SemanticResult(
            decision=plain.decision, attempts=1, request_id="request-1"
        ).as_dict()


def test_guided_explicitness_is_absent_when_not_guided() -> None:
    decision = validate_semantic_decision(valid_payload("proposal_ready", guided=False))
    assert decision.admitted
    assert decision.decision is not None
    payload = SemanticResult(
        decision=decision.decision, attempts=1, request_id="request-1"
    ).as_dict()
    assert "guided_explicitness" not in payload


def test_provider_prompt_documents_the_guided_explicitness_contract() -> None:
    provider = SemanticIntentProvider(Runs())
    prompt = provider._build_prompt("Create a character", "request-1", "session-1")
    assert "guided_explicitness" in prompt
    assert "imperative" in prompt and "musing" in prompt
