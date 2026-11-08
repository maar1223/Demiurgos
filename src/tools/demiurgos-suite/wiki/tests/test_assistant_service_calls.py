"""Service calls stay off the answer path and ask for cheap reasoning.

Two regressions are pinned here (2026-11-08):

* the answer waited for the memory curator and the distilled refresh, adding
  9 s (up to 32 s) to every turn;
* the volatile ``request_id`` sat near the top of the gate/guided prompts, so
  everything after it was uncacheable.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import api_server  # noqa: E402
from guided_character_protocol import (  # noqa: E402
    PROTOCOL_VERSION,
    GuidedRequest,
    SessionState,
)
from semantic_intent import SemanticIntentProvider  # noqa: E402


def test_scheduling_a_service_call_never_waits_for_it() -> None:
    """S4: the scheduler returns immediately; the work runs afterwards."""
    ran: list[str] = []

    async def slow_side_effect() -> None:
        await asyncio.sleep(0.05)
        ran.append("done")

    async def scenario() -> None:
        api_server._schedule_background(slow_side_effect(), label="test")
        assert ran == []  # not awaited by the caller
        await asyncio.sleep(0.15)
        assert ran == ["done"]

    asyncio.run(scenario())


def test_scheduling_without_a_loop_is_a_no_op() -> None:
    """A sync caller must not raise; the work simply does not run."""
    async def never() -> None:  # pragma: no cover - must not run
        raise AssertionError("should not run")

    coro = never()
    api_server._schedule_background(coro, label="test")
    assert coro.cr_frame is None  # closed, nothing leaked


class _FakeResponse:
    status_code = 200

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "ok"}}]}


class _FakeClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def post(self, _url: str, json: dict, headers: dict | None = None) -> _FakeResponse:
        self.payloads.append(json)
        return _FakeResponse()


def test_service_calls_request_no_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    """S6: the curator and the distillation ask the gateway for no reasoning."""
    client = _FakeClient()
    monkeypatch.setattr(api_server, "_get_hermes_client", lambda: client)

    asyncio.run(api_server._run_hermes("Extrae memorias", reasoning_effort="none"))
    assert client.payloads[-1]["model_options"] == {"reasoning_effort": "none"}

    asyncio.run(api_server._run_hermes("responde al autor"))
    assert "model_options" not in client.payloads[-1]


def test_the_curator_is_wired_with_no_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []

    async def fake_run(prompt: str, session_id: str = "",
                       reasoning_effort: str | None = None) -> str:
        seen.append(reasoning_effort)
        return "{}"

    monkeypatch.setattr(api_server, "_run_hermes", fake_run)
    monkeypatch.setattr(api_server, "_MEMORY_CURATOR", None)
    curator = api_server._memory_curator()
    asyncio.run(curator.extract(world="nec", user_text="a", assistant_text="b"))
    assert seen == ["none"]


def test_the_distilled_refresh_caps_what_it_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    """The refresh used to send the whole stored turns (1.16 MB measured)."""
    class _Turn:
        def __init__(self, role: str, content: str) -> None:
            self.role = role
            self.content = content

    class _Memory:
        def should_refresh_distilled(self, _session_id: str) -> bool:
            return True

        def get_recent_turns(self, _session_id: str, limit: int = 10):
            return [_Turn("user", "u" * 500_000), _Turn("assistant", "a" * 500_000)] * (limit // 2)

        def update_distilled_state(self, *_args, **_kwargs) -> None:
            return None

    prompts: list[str] = []

    async def fake_run(prompt: str, session_id: str = "",
                       reasoning_effort: str | None = None) -> str:
        prompts.append(prompt)
        return "resumen"

    monkeypatch.setattr(api_server, "_CONVERSATION_MEMORY", _Memory())
    monkeypatch.setattr(api_server, "_run_hermes", fake_run)
    asyncio.run(api_server._maybe_refresh_distilled("s-1", "nec"))
    assert prompts
    assert len(prompts[0]) < 10_000
    assert "u" * 2_000 in prompts[0]


def test_the_gate_prompt_puts_the_volatile_ids_last() -> None:
    """S7: a stable instruction prefix is what makes prompt caching possible."""
    provider = SemanticIntentProvider.__new__(SemanticIntentProvider)
    prompt = provider._build_prompt("hola", "req-abc123", "sess-1")
    assert prompt.index("Author input: hola") < prompt.index("req-abc123")
    assert prompt.rstrip().endswith("in the JSON object.")


def test_the_guided_prompt_puts_the_volatile_ids_last() -> None:
    from guided_character_provider import HermesGuidedProvider
    from guided_character_protocol import CancellationToken

    class _Runs:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def start(self, request: object) -> str:
            self.requests.append(request)
            return "run-1"

        def events(self, run_id: str):
            async def _gen():
                yield {"run_id": run_id, "event": "run.completed", "output": {}}
            return _gen()

        async def status(self, _run_id: str) -> dict:
            return {}

    runs = _Runs()
    provider = HermesGuidedProvider(runs)  # type: ignore[arg-type]
    request = GuidedRequest(
        PROTOCOL_VERSION, "req-abc123", "sess-1", "nec", 0, "author-1", "hola",
    )
    asyncio.run(provider.invoke(request, CancellationToken()))
    prompt = runs.requests[0].prompt
    assert prompt.index("Author input: hola") < prompt.index("req-abc123")
    assert prompt.rstrip().endswith("in the JSON object.")
