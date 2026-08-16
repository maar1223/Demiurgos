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
from guided_character_provider import HermesGuidedProvider, guided_capabilities  # noqa: E402


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
