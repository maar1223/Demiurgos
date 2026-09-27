"""Focused production adapter tests for Hermes idea-materialization wiring.

The provider is transport + prompt assembly only: strict envelope validation
is the server-side ``MaterializationResponse.from_provider`` boundary
(R-IM-09), so malformed output must be passed through unchanged. The transport
is a ``httpx.MockTransport`` client injected through ``client_provider``; the
activity adapter is a stub used only by ``probe()``.
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

from assistant_activity import CapabilityAssessment  # noqa: E402
from idea_materialization_protocol import (  # noqa: E402
    CancellationToken,
    MAX_IDEA_BODY_CHARS,
    MaterializationRequest,
    MaterializationResponse,
    PROTOCOL_VERSION,
)
from idea_materialization_provider import HermesMaterializationProvider  # noqa: E402

_CHAT_URL = "http://hermes.test/v1/chat/completions"


def materialization_request(**overrides) -> MaterializationRequest:
    values = dict(
        protocol_version=PROTOCOL_VERSION,
        request_id="request-1",
        session_id="session-1",
        world="Vibrantes",
        section="lore",
        folder="sistema-stal-poderes-vibrantes",
        slug="arquero-ciego",
        title="El Arquero Ciego",
        idea_type="personaje",
        idea_body="An idea body.",
        tags=("personaje", "vibrantes"),
        candidates=(
            {"id": "Política | Distribución Y Territorios::Atherr", "title": "Atherr", "type": "lugar", "summary": "A ruined city."},
            {"id": "Naciones::Vibrantes", "title": "Vibrantes", "type": "concepto", "summary": "The empire."},
        ),
    )
    values.update(overrides)
    return MaterializationRequest(**values)


def delta_envelope(**overrides) -> dict:
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": "request-1",
        "session_id": "session-1",
        "outcome": "delta",
        "delta": {
            "body": "# El Arquero Ciego\n\nUn arquero que no ve.",
            "relations": [
                {"target_id": "Política | Distribución Y Territorios::Atherr", "rel_type": "lugar"},
            ],
        },
    }
    payload.update(overrides)
    return payload


class _FakeActivityAdapter:
    """Stub for the ``probe()`` delegation contract only (never used in invoke)."""

    def __init__(self) -> None:
        self.probed = 0

    async def probe(self) -> CapabilityAssessment:
        self.probed += 1
        return CapabilityAssessment(True, "", None)


def _mock_provider(
    handler,
    adapter: object | None = None,
) -> tuple[HermesMaterializationProvider, httpx.AsyncClient]:
    """Build the provider over a ``MockTransport`` client and return both."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = HermesMaterializationProvider(
        adapter if adapter is not None else _FakeActivityAdapter(),
        chat_url=_CHAT_URL,
        client_provider=lambda: client,
    )
    return provider, client


def _chat_handler(
    content: str,
    *,
    response_id: str | None = "chatcmpl-abc",
    status: int = 200,
    requests: list[httpx.Request] | None = None,
):
    """Return an async MockTransport handler serving one chat-completions body."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        body = {
            "object": "chat.completion",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}},
            ],
        }
        if response_id is not None:
            body["id"] = response_id
        return httpx.Response(status, json=body)

    return handler


def test_probe_delegates_to_runs_probe() -> None:
    async def scenario() -> None:
        adapter = _FakeActivityAdapter()

        async def handler(_request: httpx.Request) -> httpx.Response:
            raise AssertionError("probe must not POST to chat-completions")

        provider, client = _mock_provider(handler, adapter)
        try:
            assessment = await provider.probe()
        finally:
            await client.aclose()
        assert assessment.admitted is True
        assert adapter.probed == 1

    asyncio.run(scenario())


def test_invoke_posts_one_no_tools_chat_request_with_assembled_prompt(monkeypatch) -> None:
    """One invocation = exactly one non-streaming POST, no tool schemas."""
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")

    async def scenario() -> None:
        requests: list[httpx.Request] = []
        handler = _chat_handler(json.dumps(delta_envelope()), requests=requests)
        provider, client = _mock_provider(handler)
        try:
            first = await provider.invoke(materialization_request(), CancellationToken())
            second = await provider.invoke(materialization_request(), CancellationToken())
        finally:
            await client.aclose()

        assert len(requests) == 2  # exactly one POST per invocation
        sent = requests[0]
        assert sent.method == "POST"
        assert str(sent.url) == _CHAT_URL
        body = json.loads(sent.content)
        assert body["model"] == "hermes-agent"
        assert body["tool_choice"] == "none"
        assert set(body.keys()) == {"model", "tool_choice", "messages"}
        assert len(body["messages"]) == 1
        assert body["messages"][0]["role"] == "user"
        prompt = body["messages"][0]["content"]
        assert "Act as the world-materialization provider." in prompt
        assert "- world: Vibrantes" in prompt
        assert f"{PROTOCOL_VERSION} response envelope" in prompt

        assert first["outcome"] == "delta"
        assert first["delta"]["body"].startswith("# El Arquero Ciego")
        assert second["outcome"] == "delta"

    asyncio.run(scenario())


def test_fenced_json_output_is_stripped() -> None:
    """A fenced ```json block is stripped before parsing (fence precedent)."""

    async def scenario() -> None:
        fenced = "```json\n" + json.dumps(delta_envelope()) + "\n```"
        provider, client = _mock_provider(_chat_handler(fenced))
        try:
            result = await provider.invoke(materialization_request(), CancellationToken())
        finally:
            await client.aclose()
        assert result["outcome"] == "delta"
        assert result["delta"]["body"].startswith("# El Arquero Ciego")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "output",
    [
        "not-json",
        "",
        "```json\n{not valid json}\n```",
    ],
)
def test_invalid_json_text_is_passed_through_unchanged(output: str) -> None:
    """The provider never fabricates an envelope: unparseable text is returned
    as-is so the server-side ``from_provider`` fails it closed (R-IM-09)."""

    async def scenario() -> None:
        provider, client = _mock_provider(_chat_handler(output))
        try:
            result = await provider.invoke(materialization_request(), CancellationToken())
        finally:
            await client.aclose()
        assert result == output

    asyncio.run(scenario())


def test_non_envelope_mapping_is_passed_through_with_response_stamp() -> None:
    """A Mapping that is not a valid envelope is returned (stamped, unvalidated)
    and the strict server-side validator rejects it — fail closed."""

    async def scenario() -> None:
        content = json.dumps({"outcome": "delta", "delta": {"body": 42}})
        provider, client = _mock_provider(_chat_handler(content))
        try:
            result = await provider.invoke(materialization_request(), CancellationToken())
        finally:
            await client.aclose()
        assert isinstance(result, dict)
        assert result["provider_run_id"] == "chatcmpl-abc"
        assert result["provenance"] == ["hermes:chatcmpl:chatcmpl-abc"]
        assert MaterializationResponse.from_provider(result, materialization_request()) is None

    asyncio.run(scenario())


def test_non_2xx_response_raises() -> None:
    """A non-200 status raises so the handler maps PROVIDER_UNAVAILABLE
    (no fabricated text that would map MALFORMED_OUTPUT)."""

    async def scenario() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "unavailable"})

        provider, client = _mock_provider(handler)
        try:
            with pytest.raises(RuntimeError):
                await provider.invoke(materialization_request(), CancellationToken())
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_transport_error_raises() -> None:
    """A transport failure raises instead of returning fallback text."""

    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("gateway down", request=request)

        provider, client = _mock_provider(handler)
        try:
            with pytest.raises(RuntimeError):
                await provider.invoke(materialization_request(), CancellationToken())
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_provider_run_id_and_provenance_stamped_from_response_id() -> None:
    async def scenario() -> None:
        provider, client = _mock_provider(
            _chat_handler(json.dumps(delta_envelope()), response_id="chatcmpl-9")
        )
        try:
            result = await provider.invoke(materialization_request(), CancellationToken())
        finally:
            await client.aclose()
        assert result["provider_run_id"] == "chatcmpl-9"
        assert result["provenance"] == ["hermes:chatcmpl:chatcmpl-9"]

    asyncio.run(scenario())


def test_provider_run_id_falls_back_to_request_id_without_response_id() -> None:
    async def scenario() -> None:
        provider, client = _mock_provider(
            _chat_handler(json.dumps(delta_envelope()), response_id=None)
        )
        try:
            result = await provider.invoke(materialization_request(), CancellationToken())
        finally:
            await client.aclose()
        assert result["provider_run_id"] == "request-1"
        assert "provenance" not in result

    asyncio.run(scenario())


def test_stamped_defaults_do_not_override_provider_values() -> None:
    async def scenario() -> None:
        envelope = delta_envelope(provider_run_id="other-run", provenance=["custom"])
        provider, client = _mock_provider(
            _chat_handler(json.dumps(envelope), response_id="chatcmpl-9")
        )
        try:
            result = await provider.invoke(materialization_request(), CancellationToken())
        finally:
            await client.aclose()
        assert result["provider_run_id"] == "other-run"
        assert result["provenance"] == ["custom"]

    asyncio.run(scenario())


def test_prompt_contains_idea_target_candidates_and_envelope(monkeypatch) -> None:
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")

    async def scenario() -> None:
        requests: list[httpx.Request] = []
        provider, client = _mock_provider(
            _chat_handler(json.dumps(delta_envelope()), requests=requests)
        )
        try:
            await provider.invoke(materialization_request(), CancellationToken())
        finally:
            await client.aclose()
        prompt = json.loads(requests[0].content)["messages"][0]["content"]
        assert "ONLY one JSON object" in prompt
        assert "no markdown fences, no code blocks" in prompt
        assert PROTOCOL_VERSION in prompt
        assert 'request-1' in prompt
        assert 'session-1' in prompt
        assert "- world: Vibrantes" in prompt
        assert "- section: lore" in prompt
        assert "- folder: sistema-stal-poderes-vibrantes" in prompt
        assert "- slug: arquero-ciego" in prompt
        assert "- title: El Arquero Ciego" in prompt
        assert "- type: personaje" in prompt
        assert "- tags: personaje, vibrantes" in prompt
        assert "- body: An idea body." in prompt
        assert "Política | Distribución Y Territorios::Atherr" in prompt
        assert "Naciones::Vibrantes" in prompt
        assert '"outcome": "delta"' in prompt
        assert "no filesystem, graph, or credential access" in prompt
        assert "Never write frontmatter, paths, or new entity names" in prompt

    asyncio.run(scenario())


def test_prompt_truncates_idea_body_to_max_idea_body_chars(monkeypatch) -> None:
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")

    async def scenario() -> None:
        requests: list[httpx.Request] = []
        provider, client = _mock_provider(
            _chat_handler(json.dumps(delta_envelope()), requests=requests)
        )
        long_body = "x" * (MAX_IDEA_BODY_CHARS + 500)
        try:
            await provider.invoke(
                materialization_request(idea_body=long_body), CancellationToken()
            )
        finally:
            await client.aclose()
        prompt = json.loads(requests[0].content)["messages"][0]["content"]
        assert f"- body: {'x' * MAX_IDEA_BODY_CHARS}" in prompt
        assert "x" * (MAX_IDEA_BODY_CHARS + 1) not in prompt

    asyncio.run(scenario())


def test_empty_candidates_render_as_empty_json_list(monkeypatch) -> None:
    """An empty world yields ``[]`` in the prompt yet still a valid envelope
    (R-IM-03 empty-relation scenario is server-side, not provider-side)."""
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")

    async def scenario() -> None:
        requests: list[httpx.Request] = []
        provider, client = _mock_provider(
            _chat_handler(json.dumps(delta_envelope()), requests=requests)
        )
        try:
            result = await provider.invoke(
                materialization_request(candidates=()), CancellationToken()
            )
        finally:
            await client.aclose()
        prompt = json.loads(requests[0].content)["messages"][0]["content"]
        assert "[]" in prompt
        assert result["outcome"] == "delta"

    asyncio.run(scenario())


def test_prompt_language_follows_configured_ui_language(monkeypatch) -> None:
    async def scenario() -> None:
        requests: list[httpx.Request] = []
        provider, client = _mock_provider(
            _chat_handler(json.dumps(delta_envelope()), requests=requests)
        )
        try:
            monkeypatch.setenv("DEMIURGOS_LANGUAGE", "es")
            await provider.invoke(materialization_request(), CancellationToken())
            monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")
            await provider.invoke(materialization_request(), CancellationToken())
        finally:
            await client.aclose()
        first = json.loads(requests[0].content)["messages"][0]["content"]
        second = json.loads(requests[1].content)["messages"][0]["content"]
        assert "(Spanish)" in first
        assert "(English)" in second

    asyncio.run(scenario())


def test_cancelled_invoke_does_no_remote_work() -> None:
    """A pre-cancelled token refuses to start the POST (no run to stop)."""

    async def scenario() -> None:
        requests: list[httpx.Request] = []
        provider, client = _mock_provider(
            _chat_handler(json.dumps(delta_envelope()), requests=requests)
        )
        token = CancellationToken()
        token.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await provider.invoke(materialization_request(), token)
        finally:
            await client.aclose()
        assert requests == []

    asyncio.run(scenario())


def test_provider_performs_no_filesystem_write(tmp_path, monkeypatch) -> None:
    """The provider is transport-only: invoking it leaves the filesystem empty."""
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")
    monkeypatch.chdir(tmp_path)

    async def scenario() -> None:
        provider, client = _mock_provider(_chat_handler(json.dumps(delta_envelope())))
        try:
            await provider.invoke(materialization_request(), CancellationToken())
        finally:
            await client.aclose()
        assert list(tmp_path.iterdir()) == []

    asyncio.run(scenario())
