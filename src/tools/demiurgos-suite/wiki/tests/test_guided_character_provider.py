"""Focused production adapter tests for Hermes guided-character wiring."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import httpx
import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from assistant_activity import HermesRunsActivityAdapter  # noqa: E402
from guided_character_protocol import (  # noqa: E402
    Capabilities,
    CancellationToken,
    GuidedRequest,
    PROTOCOL_VERSION,
    invoke_bounded,
)
from guided_character_provider import (
    HermesGuidedProvider,
    first_pending_question,
    guided_capabilities,
)  # noqa: E402


def gateway_capabilities() -> dict:
    return {
        "object": "hermes.api_server.capabilities",
        "platform": "hermes-agent",
        "features": {
            "run_submission": True,
            "run_status": True,
            "run_events_sse": True,
            "run_stop": True,
            "tool_progress_events": True,
        },
    }


def guided_request(author_input: str = "Create a character") -> GuidedRequest:
    return GuidedRequest(
        PROTOCOL_VERSION, "request-1", "session-1", "vibrantes", 0, "author-1", author_input,
        deadline_ms=8_000,
        reference_context="Rhyz is a patient tactician.",
    )


def test_invoke_starts_exactly_one_run_per_turn() -> None:
    """Single-run guarantee: one guided provider invocation = one Hermes run.

    The semantic single-run contract (decision + guided continuation in one
    run) lives in SemanticIntentProvider; HermesGuidedProvider keeps the same
    one-run-per-turn property so a turn never fans out multiple runs.
    """

    async def scenario() -> None:
        class Runs:
            def __init__(self) -> None:
                self.starts = 0

            async def start(self, request: object) -> str:
                self.starts += 1
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": "request-1", "session_id": "session-1",
                    "outcome": "question", "question": "What drives them?",
                }}

        runs = Runs()
        provider = HermesGuidedProvider(runs)
        capabilities = Capabilities(PROTOCOL_VERSION, True, True, True, 8_000)
        await invoke_bounded(provider.invoke, guided_request(), capabilities)
        await invoke_bounded(provider.invoke, guided_request(), capabilities)
        assert runs.starts == 2

    asyncio.run(scenario())


def test_fast_mode_prompt_is_fundamental_and_assumption_bound() -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, request: object) -> str:
                assert "Guided mode: fast" in request.prompt  # type: ignore[attr-defined]
                assert "question depth: fundamental" in request.prompt  # type: ignore[attr-defined]
                assert "mark assumptions clearly" in request.prompt  # type: ignore[attr-defined]
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": "request-1", "session_id": "session-1",
                    "outcome": "question", "question": "What is their desire?",
                }}

        request = GuidedRequest(**{**guided_request().__dict__, "guided_mode": "fast", "question_depth": "fundamental"})
        result = await invoke_bounded(HermesGuidedProvider(Runs()).invoke, request, Capabilities(PROTOCOL_VERSION, True, True, True, 8_000))
        assert result.outcome.value == "question"

    asyncio.run(scenario())


def test_provider_prompt_follows_configured_language_without_relaxing_constraints(monkeypatch) -> None:
    async def scenario() -> None:
        prompts: list[str] = []

        class Runs:
            async def start(self, request: object) -> str:
                prompts.append(request.prompt)  # type: ignore[attr-defined]
                return f"run-{len(prompts)}"

            async def events(self, run_id: str):
                yield {
                    "event": "run.completed", "run_id": run_id, "output": {
                        "protocol_version": PROTOCOL_VERSION,
                        "request_id": "request-1", "session_id": "session-1",
                        "outcome": "question", "question": "What drives them?",
                    },
                }

        provider = HermesGuidedProvider(Runs())
        capabilities = Capabilities(PROTOCOL_VERSION, True, True, True, 8_000)
        monkeypatch.setenv("DEMIURGOS_LANGUAGE", "es")
        await invoke_bounded(provider.invoke, guided_request("I want to create a character"), capabilities)
        await invoke_bounded(provider.invoke, guided_request("Quiero crear un personaje"), capabilities)
        assert "(Spanish)" in prompts[0]
        assert "(Spanish)" in prompts[1]

        monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")
        await invoke_bounded(provider.invoke, guided_request("Quiero crear un personaje"), capabilities)
        await invoke_bounded(provider.invoke, guided_request("I want to create a character"), capabilities)
        assert "(English)" in prompts[2]
        assert "(English)" in prompts[3]

        for prompt in prompts:
            assert "ONLY one JSON object" in prompt
            assert "no filesystem, graph, or credential access" in prompt
            assert "never write or claim approval" in prompt

    asyncio.run(scenario())


def test_provider_prompt_focuses_on_new_relation_character_never_reference(monkeypatch) -> None:
    async def scenario() -> None:
        prompts: list[str] = []

        class Runs:
            async def start(self, request: object) -> str:
                prompts.append(request.prompt)  # type: ignore[attr-defined]
                return f"run-{len(prompts)}"

            async def events(self, run_id: str):
                yield {
                    "event": "run.completed", "run_id": run_id, "output": {
                        "protocol_version": PROTOCOL_VERSION,
                        "request_id": "request-1", "session_id": "session-1",
                        "outcome": "question", "question": "What drives them?",
                    },
                }

        provider = HermesGuidedProvider(Runs())
        capabilities = Capabilities(PROTOCOL_VERSION, True, True, True, 8_000)
        monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")
        relation_request = GuidedRequest(**{
            **guided_request("quiero crear al hermano de Rhyz").__dict__,
            "reference_name": "Rhyz",
            "relation_goal": "New character: brother of Rhyz",
        })
        await invoke_bounded(provider.invoke, relation_request, capabilities)
        await invoke_bounded(provider.invoke, guided_request("Create a character"), capabilities)

        focused = prompts[0]
        assert "STRICT TARGET: New character: brother of Rhyz" in focused
        assert "brand-new character" in focused
        assert "Never describe, summarize, expand, or develop the reference character itself" in focused
        assert "Rhyz is a patient tactician." in focused
        assert "STRICT TARGET" not in prompts[1]

    asyncio.run(scenario())


def test_production_adapter_probes_capabilities_and_invokes_structured_run() -> None:
    async def scenario() -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/v1/capabilities":
                return httpx.Response(200, json=gateway_capabilities())
            if request.url.path == "/v1/runs":
                return httpx.Response(202, json={"run_id": "run-1", "status": "started"})
            if request.url.path == "/v1/runs/run-1/events":
                payload = {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": "request-1",
                    "session_id": "session-1",
                    "outcome": "question",
                    "question": "What drives them?",
                }
                body = f"data: {json.dumps({'event': 'run.completed', 'run_id': 'run-1', 'output': json.dumps(payload)})}\n\n"
                return httpx.Response(200, content=body, headers={"Content-Type": "text/event-stream"})
            return httpx.Response(404)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        runs = HermesRunsActivityAdapter("http://hermes.test/v1", api_key="test-key", client_provider=lambda: client)
        try:
            assessment = await runs.probe()
            assert guided_capabilities(assessment).admitted()  # type: ignore[union-attr]
            result = await HermesGuidedProvider(runs).invoke(guided_request(), CancellationToken())
        finally:
            await client.aclose()

        assert result["outcome"] == "question"
        assert result["provider_run_id"] == "run-1"
        assert requests[0].headers["authorization"] == "Bearer test-key"
        submitted = json.loads(requests[1].content)
        assert submitted["session_id"] == "session-1"
        assert "Rhyz is a patient tactician." in submitted["input"]
        assert "filesystem" in submitted["input"]
        assert "exactly one concise question at a time" in submitted["input"]
        assert "no more than 5 useful options" in submitted["input"]
        assert "recite the ficha" in submitted["input"]

    asyncio.run(scenario())


def test_unavailable_or_malformed_gateway_stays_unadmitted() -> None:
    async def scenario() -> None:
        async def unavailable(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        async def malformed(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"object": "wrong"})

        for handler in (unavailable, malformed):
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            runs = HermesRunsActivityAdapter("http://hermes.test/v1", api_key="", client_provider=lambda: client)
            try:
                assert guided_capabilities(await runs.probe()) is None
            finally:
                await client.aclose()

    asyncio.run(scenario())


def test_malformed_run_output_is_rejected_by_guided_protocol() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/runs":
                return httpx.Response(202, json={"run_id": "run-1", "status": "started"})
            if request.url.path == "/v1/runs/run-1/events":
                return httpx.Response(
                    200,
                    content='data: {"event":"run.completed","run_id":"run-1","output":"not-json"}\n\n',
                    headers={"Content-Type": "text/event-stream"},
                )
            return httpx.Response(404)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        runs = HermesRunsActivityAdapter("http://hermes.test/v1", api_key="", client_provider=lambda: client)
        try:
            result = await invoke_bounded(
                HermesGuidedProvider(runs).invoke,
                guided_request(),
                Capabilities(PROTOCOL_VERSION, True, True, True, 8_000),
            )
        finally:
            await client.aclose()
        assert result.error is not None
        assert result.error.code.value == "malformed_output"

    asyncio.run(scenario())


def test_version_alias_is_normalized_before_strict_protocol_validation() -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                payload = {
                    "version": PROTOCOL_VERSION,
                    "request_id": "request-1",
                    "session_id": "session-1",
                    "outcome": "question",
                    "question": "What drives them?",
                }
                yield {"event": "run.completed", "run_id": "run-1", "output": json.dumps(payload)}

        result = await invoke_bounded(
            HermesGuidedProvider(Runs()).invoke,
            guided_request(),
            Capabilities(PROTOCOL_VERSION, True, True, True, 8_000),
        )

        assert result.outcome.value == "question"
        assert result.question == "What drives them?"
        assert result.provenance == ("hermes:run:run-1",)

    asyncio.run(scenario())


def test_fenced_json_output_is_accepted() -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                payload = {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": "request-1",
                    "session_id": "session-1",
                    "outcome": "question",
                    "question": "What drives them?",
                }
                fenced = "```json\n" + json.dumps(payload) + "\n```"
                yield {"event": "run.completed", "run_id": "run-1", "output": fenced}

        result = await invoke_bounded(
            HermesGuidedProvider(Runs()).invoke,
            guided_request(),
            Capabilities(PROTOCOL_VERSION, True, True, True, 8_000),
        )

        assert result.error is None
        assert result.outcome.value == "question"
        assert result.question == "What drives them?"

    asyncio.run(scenario())


def test_first_pending_question_collapses_multi_question_text_to_one() -> None:
    """REQ-GN-3 (3.3.4): two or more ``?``-terminated sentences collapse to
    the first pending question; everything after it is dropped."""
    assert first_pending_question("What is their name? What is their age?") == "What is their name?"
    assert first_pending_question("A? B? C?") == "A?"
    assert first_pending_question("Why? Also where?") == "Why?"
    assert first_pending_question("Name? Age? Era?") == "Name?"
    assert first_pending_question("What? Then why?!") == "What?"
    # A question ending in ``?`` right before the end keeps its question mark.
    assert first_pending_question("What is their name?") == "What is their name?"


def test_first_pending_question_single_or_no_question_is_unchanged() -> None:
    """REQ-GN-3 (3.3.4 control): a single question or a question-free text is
    never truncated."""
    assert first_pending_question("What drives them?") == "What drives them?"
    assert first_pending_question("Consider a character one step at a time.") == (
        "Consider a character one step at a time."
    )
    assert first_pending_question("") == ""
    # Markers like ``?!"`` stay inside the first question; no second question
    # is created by the punctuation.
    assert first_pending_question('"Why?!" she asked.') == '"Why?!" she asked.'


def test_multi_question_provider_response_surfaces_at_most_one_pending_question() -> None:
    """REQ-GN-3 scenario 2 (3.3.5): a provider response containing more than
    one question is surfaced as at most one pending question — the server-side
    enforcement never exposes a second question in the same turn."""
    async def scenario() -> None:
        class Runs:
            def __init__(self, question: object) -> None:
                self._question = question

            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                yield {
                    "event": "run.completed", "run_id": "run-1", "output": {
                        "version": PROTOCOL_VERSION,
                        "request_id": "request-1", "session_id": "session-1",
                        "outcome": "question", "question": self._question,
                    },
                }

        capabilities = Capabilities(PROTOCOL_VERSION, True, True, True, 8_000)
        # Plain-string multi-question response.
        result = await invoke_bounded(
            HermesGuidedProvider(Runs("What is their name? What is their age?")).invoke,
            guided_request(), capabilities,
        )
        assert result.error is None
        assert result.outcome.value == "question"
        assert result.question == "What is their name?"
        assert result.question.count("?") == 1
        assert "age" not in result.question
        # Structured mapping with options: the collapse happens on the question
        # text BEFORE the options block, so the first question keeps its options.
        structured = {
            "text": "What is their name? What is their age?",
            "options": ["Aria", "Pert"],
        }
        structured_result = await invoke_bounded(
            HermesGuidedProvider(Runs(structured)).invoke,
            guided_request(), capabilities,
        )
        assert structured_result.error is None
        assert structured_result.question == (
            "What is their name?\n\nOptions:\n- Aria\n- Pert"
        )
        assert structured_result.question.count("?") == 1
        assert "age" not in structured_result.question

    asyncio.run(scenario())


def test_structured_question_is_normalized_without_exposing_provider_metadata() -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                payload = {
                    "version": PROTOCOL_VERSION,
                    "request_id": "request-1",
                    "session_id": "session-1",
                    "outcome": "question",
                    "question": {
                        "text": "  What drives them?  ",
                        "options": ["Freedom", "Power"],
                        "allow_custom": True,
                        "provenance": "secret",
                    },
                    "provenance": ["secret-provider"],
                }
                yield {"event": "run.completed", "run_id": "run-1", "output": json.dumps(payload)}

        result = await invoke_bounded(
            HermesGuidedProvider(Runs()).invoke,
            guided_request(),
            Capabilities(PROTOCOL_VERSION, True, True, True, 8_000),
        )

        assert result.error is None
        assert result.question == "What drives them?\n\nOptions:\n- Freedom\n- Power\n\nCustom answers are allowed."
        assert result.provenance == ("secret-provider",)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "shape",
    [
        {"outcome": "question", "question": "What drives them?"},
        {"outcome": "delta", "delta": {"desire": "freedom"}},
    ],
)
def test_missing_versions_are_inferred_only_for_current_request_shapes(shape: dict) -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                payload = {
                    **shape,
                    "request_id": "request-1",
                    "session_id": "session-1",
                }
                yield {"event": "run.completed", "run_id": "run-1", "output": json.dumps(payload)}

        result = await invoke_bounded(
            HermesGuidedProvider(Runs()).invoke,
            guided_request(),
            Capabilities(PROTOCOL_VERSION, True, True, True, 8_000),
        )

        assert result.error is None
        assert result.outcome.value == shape["outcome"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "envelope",
    [
        {"request_id": "other", "session_id": "session-1", "outcome": "question", "question": "Why?"},
        {"request_id": "request-1", "session_id": "session-1", "outcome": "question", "question": "  "},
        {"request_id": "request-1", "session_id": "session-1", "outcome": "delta", "delta": "not-a-map"},
    ],
)
def test_missing_versions_do_not_bypass_identity_or_shape_validation(envelope: dict) -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": json.dumps(envelope)}

        result = await invoke_bounded(
            HermesGuidedProvider(Runs()).invoke,
            guided_request(),
            Capabilities(PROTOCOL_VERSION, True, True, True, 8_000),
        )

        assert result.error is not None
        assert result.error.code.value == "malformed_output"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "question",
    [
        {},
        {"text": "  "},
        {"text": "Why?", "options": "not-a-list"},
        {"text": "Why?", "options": ["Valid", "  "]},
        {"text": "Why?", "options": ["Too many"] * 6},
        {"text": "Why?", "allow_custom": "yes"},
    ],
)
def test_malformed_structured_questions_remain_rejected(question: dict) -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                payload = {
                    "version": PROTOCOL_VERSION,
                    "request_id": "request-1",
                    "session_id": "session-1",
                    "outcome": "question",
                    "question": question,
                }
                yield {"event": "run.completed", "run_id": "run-1", "output": json.dumps(payload)}

        result = await invoke_bounded(
            HermesGuidedProvider(Runs()).invoke,
            guided_request(),
            Capabilities(PROTOCOL_VERSION, True, True, True, 8_000),
        )
        assert result.error is not None
        assert result.error.code.value == "malformed_output"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "versions",
    [
        {"protocol_version": "guided-character-v2"},
        {"version": "guided-character-v2"},
        {"version": PROTOCOL_VERSION, "protocol_version": "guided-character-v2"},
    ],
)
def test_conflicting_or_invalid_versions_remain_rejected(versions: dict[str, str]) -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                payload = {
                    **versions,
                    "request_id": "request-1",
                    "session_id": "session-1",
                    "outcome": "question",
                    "question": "What drives them?",
                }
                yield {"event": "run.completed", "run_id": "run-1", "output": json.dumps(payload)}

        result = await invoke_bounded(
            HermesGuidedProvider(Runs()).invoke,
            guided_request(),
            Capabilities(PROTOCOL_VERSION, True, True, True, 8_000),
        )
        assert result.error is not None
        assert result.error.code.value == "malformed_output"

    asyncio.run(scenario())


class TestConvergenceSpecimenB4:
    """R13 (④b): the convergence-specimen hint is additive — the provider
    appends the block to ``methodology_context`` AFTER the contract block,
    outside the ≤1000-token projection; the None path stays byte-identical;
    a TypeError drops BOTH hints to the two-argument call (:427-433)."""

    def _runs(self, prompts: list[str]):
        class Runs:
            async def start(self, request: object) -> str:
                prompts.append(request.prompt)  # type: ignore[attr-defined]
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": "request-1", "session_id": "session-1",
                    "outcome": "question", "question": "What drives them?",
                }}

        return Runs()

    def test_specimen_appended_after_contract_block_outside_projection(self) -> None:
        """R13: the block lands in ``methodology_context`` after the contract
        block — exactly one block per turn, never inside the projection."""
        async def scenario() -> None:
            prompts: list[str] = []
            provider = HermesGuidedProvider(self._runs(prompts))
            capabilities = Capabilities(PROTOCOL_VERSION, True, True, True, 8_000)
            specimen = "[Convergence specimen — nivel 1º]\n\n# Korrane\n\nEjemplo.\n\n"
            await invoke_bounded(
                provider, guided_request(), capabilities,
                compiled_contract_markdown="## Methodology: Test\n**Phases**: a → b\n",
                convergence_specimen_markdown=specimen,
            )
            prompt = prompts[0]
            assert "[Active methodology contract" in prompt
            assert prompt.index("[Convergence specimen — nivel 1º]") > prompt.index(
                "Follow this methodology for the entire session."
            )
            assert prompt.count("[Convergence specimen — nivel 1º]") == 1
            assert specimen in prompt

        asyncio.run(scenario())

    def test_specimen_none_prompt_is_byte_identical_to_pre_pr4(self, monkeypatch) -> None:
        """R10/R13: with the hint ``None`` the prompt is byte-identical to the
        pre-PR④ prompt — no specimen marker, no fragment drift."""
        monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")

        async def scenario() -> None:
            prompts: list[str] = []
            provider = HermesGuidedProvider(self._runs(prompts))
            capabilities = Capabilities(PROTOCOL_VERSION, True, True, True, 8_000)
            await invoke_bounded(provider.invoke, guided_request(), capabilities)
            await invoke_bounded(
                provider.invoke, guided_request(), capabilities,
                convergence_specimen_markdown=None,
            )
            assert prompts[0] == prompts[1]
            assert "[Convergence specimen" not in prompts[0]
            expected = (
                "Act as the guided character provider. Return ONLY one JSON object — "
                "no markdown fences, no code blocks — matching the "
                f"{PROTOCOL_VERSION} response envelope. Use request_id "
                '"request-1" and session_id "session-1". '
                "The outcome must be question or delta; never claim author acceptance. "
                "For a question, ask exactly one concise question at a time. Keep it to one or "
                "two short sentences and provide no more than 5 useful options. "
                "Do not add long explanations or recite the ficha; use the reference silently. "
                "You have no filesystem, graph, or credential access. Use only the bounded "
                "reference material below; do not expose internal paths or provenance. "
                "Answer all questions and provide all deltas in the same language as the author's input (English). "
                "Keep the response JSON-only, concise, bounded to the supplied context, and never write or claim approval. "
                "Turn mode: creation. World: vibrantes. "
                "Guided mode: full; question depth: standard. "
                "Verified active ficha reference:\nRhyz is a patient tactician.\n"
                "Author input: Create a character"
            )
            assert prompts[0] == expected

        asyncio.run(scenario())

    def test_type_error_fallback_drops_both_hints_to_two_arg_call(self) -> None:
        """R13 (:427-433): a provider that rejects the keyword-only hints is
        called with exactly two arguments — both hints dropped."""
        async def scenario() -> None:
            calls: list[tuple] = []

            class TwoArgProvider:
                async def invoke(self, request: GuidedRequest, token: CancellationToken) -> object:
                    calls.append((request, token))
                    return {
                        "protocol_version": PROTOCOL_VERSION,
                        "request_id": request.request_id,
                        "session_id": request.session_id,
                        "outcome": "question",
                        "question": "What drives them?",
                    }

            result = await invoke_bounded(
                TwoArgProvider(), guided_request(),
                Capabilities(PROTOCOL_VERSION, True, True, True, 8_000),
                compiled_contract_markdown="contract",
                convergence_specimen_markdown="specimen",
            )
            assert result.outcome.value == "question"
            assert len(calls) == 1

        asyncio.run(scenario())
