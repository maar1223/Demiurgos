"""Focused production adapter tests for Skill Madre co-creation wiring.

Covers the Hermes boundary (REQ-CC-7) at the provider layer: envelope
parsing, authority-key rejection (flat ``acceptance`` and nested
``delta.digest``), the ≤5 options limit, fail-closed behavior on malformed or
unavailable output, and ``provider_run_id`` + ``provenance`` tracking.
"""

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
from co_creation_protocol import (  # noqa: E402
    CancellationToken,
    Capabilities,
    CoCreationRequest,
    PROTOCOL_VERSION,
    invoke_bounded_co_creation,
)
from hermes_co_creation_provider import (  # noqa: E402
    HermesCoCreationProvider,
    co_creation_capabilities,
)


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


def co_creation_request(author_input: str = "I want to create a skill") -> CoCreationRequest:
    return CoCreationRequest(
        PROTOCOL_VERSION, "request-1", "session-1", "author-1", 0, "author-1", author_input,
        deadline_ms=8_000,
    )


def capabilities() -> Capabilities:
    return Capabilities(PROTOCOL_VERSION, True, True, True, 8_000)


def _question_envelope(**overrides: object) -> dict:
    envelope = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": "request-1",
        "session_id": "session-1",
        "outcome": "question",
        "question": "What purpose should the skill serve?",
    }
    envelope.update(overrides)
    return envelope


def test_invoke_starts_exactly_one_run_per_turn() -> None:
    async def scenario() -> None:
        class Runs:
            def __init__(self) -> None:
                self.starts = 0

            async def start(self, request: object) -> str:
                self.starts += 1
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": _question_envelope()}

        runs = Runs()
        provider = HermesCoCreationProvider(runs)  # type: ignore[arg-type]
        await invoke_bounded_co_creation(provider.invoke, co_creation_request(), capabilities())
        await invoke_bounded_co_creation(provider.invoke, co_creation_request(), capabilities())
        assert runs.starts == 2

    asyncio.run(scenario())


def test_provider_prompt_encodes_skill_madre_method_rules() -> None:
    async def scenario() -> None:
        prompts: list[str] = []

        class Runs:
            async def start(self, request: object) -> str:
                prompts.append(request.prompt)  # type: ignore[attr-defined]
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": _question_envelope()}

        provider = HermesCoCreationProvider(Runs())  # type: ignore[arg-type]
        await invoke_bounded_co_creation(
            provider.invoke, co_creation_request("Quiero crear una skill"), capabilities()
        )
        prompt = prompts[0]
        assert "purpose before name" in prompt
        assert "mundo-specific or transversal" in prompt
        assert "main flow before branches" in prompt
        assert "rama vs skill-distinct" in prompt
        assert "proposito -> alcance -> flujo_principal" in prompt
        assert "never write, grant permissions, skip gates" in prompt
        assert "no more than 5 useful options" in prompt
        assert "no filesystem, graph, or credential access" in prompt

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "authority_payload",
    [
        {"acceptance": "approved"},
        {"delta": {"digest": "abc"}},
        {"delta": {"nested": {"authorization": "granted"}}},
        {"progress": [{"name": "proposito", "state": "actual", "target": "x"}]},
    ],
)
def test_authority_keys_are_rejected_flat_and_nested(authority_payload: dict) -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                yield {
                    "event": "run.completed",
                    "run_id": "run-1",
                    "output": {**_question_envelope(), **authority_payload},
                }

        result = await invoke_bounded_co_creation(
            HermesCoCreationProvider(Runs()).invoke,  # type: ignore[arg-type]
            co_creation_request(),
            capabilities(),
        )
        assert result.error is not None
        assert result.error.code.value == "invalid_envelope"

    asyncio.run(scenario())


def test_provider_layer_fails_closed_on_authority_keys() -> None:
    """The provider itself must never return an envelope that claims authority."""

    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                yield {
                    "event": "run.completed",
                    "run_id": "run-1",
                    "output": {**_question_envelope(), "acceptance": "approved"},
                }

        raw = await HermesCoCreationProvider(Runs()).invoke(  # type: ignore[arg-type]
            co_creation_request(), CancellationToken()
        )
        assert raw["outcome"] == "error"  # type: ignore[index]
        assert raw["error"]["code"] == "invalid_envelope"  # type: ignore[index]

    asyncio.run(scenario())


def test_more_than_five_options_are_rejected() -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                yield {
                    "event": "run.completed",
                    "run_id": "run-1",
                    "output": {
                        **_question_envelope(),
                        "options": [f"option-{index}" for index in range(6)],
                    },
                }

        result = await invoke_bounded_co_creation(
            HermesCoCreationProvider(Runs()).invoke,  # type: ignore[arg-type]
            co_creation_request(),
            capabilities(),
        )
        assert result.error is not None
        assert result.error.code.value == "malformed_output"

    asyncio.run(scenario())


def test_up_to_five_options_are_accepted_and_tracked() -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                yield {
                    "event": "run.completed",
                    "run_id": "run-1",
                    "output": {
                        **_question_envelope(),
                        "options": ["A", "B", "C", "D", "E"],
                    },
                }

        result = await invoke_bounded_co_creation(
            HermesCoCreationProvider(Runs()).invoke,  # type: ignore[arg-type]
            co_creation_request(),
            capabilities(),
        )
        assert result.error is None
        assert result.options == ("A", "B", "C", "D", "E")

    asyncio.run(scenario())


def test_unavailable_gateway_stays_unadmitted() -> None:
    async def scenario() -> None:
        async def unavailable(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        async def malformed(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"object": "wrong"})

        for handler in (unavailable, malformed):
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            runs = HermesRunsActivityAdapter(
                "http://hermes.test/v1", api_key="", client_provider=lambda: client
            )
            try:
                assert co_creation_capabilities(await runs.probe()) is None
            finally:
                await client.aclose()

    asyncio.run(scenario())


def test_malformed_run_output_is_rejected_by_co_creation_protocol() -> None:
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
            result = await invoke_bounded_co_creation(
                HermesCoCreationProvider(runs).invoke,
                co_creation_request(),
                capabilities(),
            )
        finally:
            await client.aclose()
        assert result.error is not None
        assert result.error.code.value == "malformed_output"

    asyncio.run(scenario())


def test_provenance_and_run_id_are_tracked() -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-42"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-42", "output": _question_envelope()}

        result = await invoke_bounded_co_creation(
            HermesCoCreationProvider(Runs()).invoke,  # type: ignore[arg-type]
            co_creation_request(),
            capabilities(),
        )
        assert result.error is None
        assert result.provider_run_id == "run-42"
        assert result.provenance == ("hermes:run:run-42",)

    asyncio.run(scenario())


def test_fenced_json_output_is_accepted() -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                fenced = "```json\n" + json.dumps(_question_envelope()) + "\n```"
                yield {"event": "run.completed", "run_id": "run-1", "output": fenced}

        result = await invoke_bounded_co_creation(
            HermesCoCreationProvider(Runs()).invoke,  # type: ignore[arg-type]
            co_creation_request(),
            capabilities(),
        )
        assert result.error is None
        assert result.outcome.value == "question"
        assert result.question == "What purpose should the skill serve?"

    asyncio.run(scenario())


def test_version_alias_is_normalized_before_strict_validation() -> None:
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
                    "question": "What purpose should the skill serve?",
                }
                yield {"event": "run.completed", "run_id": "run-1", "output": json.dumps(payload)}

        result = await invoke_bounded_co_creation(
            HermesCoCreationProvider(Runs()).invoke,  # type: ignore[arg-type]
            co_creation_request(),
            capabilities(),
        )
        assert result.error is None
        assert result.question == "What purpose should the skill serve?"
        assert result.provenance == ("hermes:run:run-1",)

    asyncio.run(scenario())


def test_structured_question_is_normalized_with_options() -> None:
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
                        "text": "  What purpose should the skill serve?  ",
                        "options": ["Automation", "Analysis"],
                        "allow_custom": True,
                    },
                }
                yield {"event": "run.completed", "run_id": "run-1", "output": json.dumps(payload)}

        result = await invoke_bounded_co_creation(
            HermesCoCreationProvider(Runs()).invoke,  # type: ignore[arg-type]
            co_creation_request(),
            capabilities(),
        )
        assert result.error is None
        assert result.question == (
            "What purpose should the skill serve?\n\nOptions:\n- Automation\n- Analysis\n\n"
            "Custom answers are allowed."
        )
        assert result.options == ("Automation", "Analysis")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "envelope",
    [
        {"request_id": "other", "session_id": "session-1", "outcome": "question", "question": "Why?"},
        {"request_id": "request-1", "session_id": "session-1", "outcome": "question", "question": "  "},
        {"request_id": "request-1", "session_id": "session-1", "outcome": "milestone_delta"},
        {"request_id": "request-1", "session_id": "session-1", "outcome": "milestone_delta", "milestone": "not-a-milestone"},
    ],
)
def test_missing_versions_do_not_bypass_identity_or_shape_validation(envelope: dict) -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                yield {"event": "run.completed", "run_id": "run-1", "output": json.dumps(envelope)}

        result = await invoke_bounded_co_creation(
            HermesCoCreationProvider(Runs()).invoke,  # type: ignore[arg-type]
            co_creation_request(),
            capabilities(),
        )
        assert result.error is not None
        assert result.error.code.value == "malformed_output"

    asyncio.run(scenario())


def test_milestone_delta_envelope_parses_with_progress() -> None:
    async def scenario() -> None:
        class Runs:
            async def start(self, _request: object) -> str:
                return "run-1"

            async def events(self, _run_id: str):
                payload = {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": "request-1",
                    "session_id": "session-1",
                    "outcome": "milestone_delta",
                    "milestone": "alcance",
                    "progress": [
                        {"name": "proposito", "state": "completado"},
                        {"name": "alcance", "state": "actual"},
                        {"name": "flujo_principal", "state": "pendiente"},
                        {"name": "ramas_reglas", "state": "pendiente"},
                        {"name": "borrador_listo", "state": "pendiente"},
                        {"name": "revision_publicacion", "state": "pendiente"},
                    ],
                }
                yield {"event": "run.completed", "run_id": "run-1", "output": json.dumps(payload)}

        result = await invoke_bounded_co_creation(
            HermesCoCreationProvider(Runs()).invoke,  # type: ignore[arg-type]
            co_creation_request(),
            capabilities(),
        )
        assert result.error is None
        assert result.outcome.value == "milestone_delta"
        assert result.milestone == "alcance"
        assert result.progress is not None and len(result.progress) == 6
        assert result.progress[0].state == "completado"
        assert result.progress[1].state == "actual"

    asyncio.run(scenario())