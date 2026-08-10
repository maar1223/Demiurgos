# -*- coding: utf-8 -*-
"""Focused Hermes runs contract and safety tests for assistant activity."""

from __future__ import annotations

import json
import asyncio
from pathlib import Path
import sys

import httpx
import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _path in (str(_WIKI), str(_SUITE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from assistant_activity import (  # noqa: E402
    ACTIVITY_UNAVAILABLE_REASON,
    ActivityTranslator,
    HermesActivityRequest,
    HermesRunsActivityAdapter,
    INCOMPLETE_EVIDENCE_WARNING,
    NEUTRAL_EVIDENCE_WARNING,
    assess_hermes_capabilities,
    validate_structured_world_path,
)


def capabilities() -> dict:
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


def event(name: str, **values: object) -> dict:
    return {"event": name, "run_id": "run-1", **values}


def translator(tmp_path: Path) -> ActivityTranslator:
    assessment = assess_hermes_capabilities(capabilities())
    assert assessment.admitted
    return ActivityTranslator(
        capability=assessment,
        request_id="request-1",
        run_id="run-1",
        session_id="session-1",
        world_root=tmp_path,
    )


def test_documented_runs_capabilities_are_admitted():
    result = assess_hermes_capabilities(capabilities())

    assert result.admitted is True
    assert result.capabilities is not None


def test_missing_documented_capability_keeps_adapter_disabled():
    payload = capabilities()
    payload["features"].pop("run_stop")

    result = assess_hermes_capabilities(payload)

    assert result.admitted is False
    assert result.reason == ACTIVITY_UNAVAILABLE_REASON


def test_runs_adapter_uses_documented_endpoints_and_fields():
    async def scenario():
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/v1/capabilities":
                return httpx.Response(200, json=capabilities())
            if request.url.path == "/v1/runs" and request.method == "POST":
                return httpx.Response(202, json={"run_id": "run-1", "status": "started"})
            if request.url.path == "/v1/runs/run-1/stop":
                return httpx.Response(200, json={"status": "stopping"})
            if request.url.path == "/v1/runs/run-1":
                return httpx.Response(200, json={"run_id": "run-1", "status": "completed", "output": "answer"})
            if request.url.path == "/v1/runs/run-1/events":
                body = "\n".join(
                    [
                        f"data: {json.dumps(event('tool.started', tool='graph_search'))}",
                        "",
                        f"data: {json.dumps(event('run.completed', output='answer'))}",
                        "",
                    ]
                )
                return httpx.Response(200, content=body, headers={"Content-Type": "text/event-stream"})
            return httpx.Response(404)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = HermesRunsActivityAdapter(
            "http://hermes.test/v1",
            api_key="redacted-test-key",
            client_provider=lambda: client,
        )
        try:
            assert (await adapter.probe()).admitted
            run_id = await adapter.start(HermesActivityRequest("request-1", "safe prompt", "session-1"))
            streamed = [item async for item in adapter.events(run_id)]
            status = await adapter.status(run_id)
            await adapter.cancel(run_id)
        finally:
            await client.aclose()

        assert run_id == "run-1"
        assert streamed[0]["event"] == "tool.started"
        assert streamed[1]["event"] == "run.completed"
        assert status["status"] == "completed"
        assert requests[1].url.path == "/v1/runs"
        assert json.loads(requests[1].content) == {"input": "safe prompt", "session_id": "session-1"}
        assert requests[-1].url.path == "/v1/runs/run-1/stop"

    asyncio.run(scenario())


def test_correlated_tool_lifecycle_emits_running_then_success_without_fake_path(tmp_path: Path):
    translator_instance = translator(tmp_path)

    running = translator_instance.translate(
        event("tool.started", tool="graph_read", preview="lore/secret.md")
    )
    succeeded = translator_instance.translate(
        event("tool.completed", tool="graph_read", error=False)
    )

    assert running[0].as_dict() == {
        "kind": "activity",
        "request_id": "request-1",
        "item_id": "item-1",
        "operation": "Read world",
        "status": "running",
    }
    assert succeeded[0].as_dict() == {
        "kind": "activity",
        "request_id": "request-1",
        "item_id": "item-1",
        "operation": "Read world",
        "status": "succeeded",
    }


def test_answer_deltas_and_terminal_output_are_correlated(tmp_path: Path):
    translator_instance = translator(tmp_path)

    first = translator_instance.translate(event("message.delta", delta="The "))
    second = translator_instance.translate(event("message.delta", delta="answer"))
    terminal = translator_instance.translate(event("run.completed", output="ignored"))

    assert first[0].as_dict()["response"] == "The "
    assert second[0].as_dict()["response"] == "The answer"
    assert terminal[0].as_dict() == {
        "kind": "terminal",
        "request_id": "request-1",
        "status": "succeeded",
    }


def test_unknown_tool_and_mismatched_run_are_discarded(tmp_path: Path):
    translator_instance = translator(tmp_path)

    assert translator_instance.translate(event("tool.started", tool="read_file")) == []
    assert translator_instance.translate(event("tool.started", run_id="other", tool="graph_read")) == []
    neutral = translator_instance.finalize()

    assert neutral[0].as_dict() == {
        "kind": "terminal",
        "request_id": "request-1",
        "status": "unknown",
        "warning": NEUTRAL_EVIDENCE_WARNING,
    }


def test_failed_completion_and_failed_run_are_incomplete(tmp_path: Path):
    translator_instance = translator(tmp_path)
    translator_instance.translate(event("tool.started", tool="graph_search"))

    failed = translator_instance.translate(
        event("tool.completed", tool="graph_search", error=True, preview="secret")
    )
    terminal = translator_instance.translate(event("run.failed", error="secret provider error"))

    assert failed[0].as_dict()["warning"] == INCOMPLETE_EVIDENCE_WARNING
    assert terminal[0].as_dict() == {
        "kind": "terminal",
        "request_id": "request-1",
        "status": "failed",
        "warning": INCOMPLETE_EVIDENCE_WARNING,
    }


def test_structured_path_validator_rejects_unsafe_or_unvalidated_paths(tmp_path: Path):
    world = tmp_path / "world"
    (world / "lore").mkdir(parents=True)
    (world / "lore" / "inicio.md").write_text("# Inicio\n", encoding="utf-8")

    for raw_path in (
        "/absolute/lore/inicio.md",
        "C:\\outside\\secret.md",
        "lore/../secret.md",
        "lore//inicio.md",
        "missing.md",
    ):
        assert validate_structured_world_path(world, raw_path) is None

    assert validate_structured_world_path(world, "lore/inicio.md") == "lore/inicio.md"
