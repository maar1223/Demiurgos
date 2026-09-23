# -*- coding: utf-8 -*-
"""Integration tests for the assistant-feature wiring in api_server.py (WU5).

Covers the end-to-end flows that PASO 3 introduced on top of the Hermes-first
semantic gate:

- AC-01/AC-08  multi-turn conversation memory (turns persisted, envelope unchanged)
- AC-02        distilled state is injected into the semantic gate
- AC-03/AC-05  skill routing on the non-guided path (skill_id stored on the turn)
- AC-04        compiled-contract projection propagated to the guided provider invoke
- AC-06        fail-open routing when the router/provider is unavailable
- fricción 5   activity stream persists user + assistant turns at stream close
- fricción 3   /api/chat injects distilled state into the gate

The Hermes gateway is never contacted: the semantic provider and the activity
runs adapter are fakes, and the real conversation memory / skill router seams
are replaced with in-memory / recording doubles.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402
from assistant_activity import assess_hermes_capabilities  # noqa: E402
from conversation_memory_store import ConversationMemoryStore  # noqa: E402
from guided_character_protocol import invoke_bounded  # noqa: E402


def _activity_capability():
    return assess_hermes_capabilities(
        {
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
    )


def _parse_sse(text: str) -> list[dict]:
    records = []
    event_name: str | None = None
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("event: "):
            event_name = line[len("event: "):]
        elif line.startswith("data: "):
            data_lines.append(line[len("data: "):])
        elif line == "" and event_name is not None:
            records.append(json.loads("\n".join(data_lines)))
            event_name = None
            data_lines = []
    return records


class _SemanticRuns:
    """Minimal runs adapter shape consumed by SemanticIntentProvider."""

    def __init__(self, *payloads):
        self._payloads = list(payloads)
        self.starts = 0
        self.requests = []

    async def start(self, request):
        self.starts += 1
        self.requests.append(request)
        return f"run-{self.starts}"

    async def events(self, run_id):
        payload = self._payloads.pop(0) if self._payloads else None
        yield {"event": "run.completed", "run_id": run_id, "output": payload}


def _semantic_payload(state="allow", **overrides):
    payload = {
        "state": state,
        "response": "Hermes semantic answer.",
        "request_id": "r1",
        "session_id": "s1",
        "guided": True,
    }
    payload.update(overrides)
    return payload


class _RecordingProvider:
    """Wraps a real provider and records the bounded context it receives."""

    def __init__(self, inner):
        self.inner = inner
        self.distilled = []
        self.recent_turns = []

    async def decide(
        self, author_input, *, request_id, session_id=None, context=None,
        distilled_state=None, recent_turns=None,
    ):
        self.distilled.append(distilled_state)
        self.recent_turns.append(recent_turns)
        return await self.inner.decide(
            author_input, request_id=request_id, session_id=session_id,
            context=context, distilled_state=distilled_state,
            recent_turns=recent_turns,
        )


class _FakeRouter:
    def __init__(self, skill_id="narrative-draft", raise_on_route=False):
        self.skill_id = skill_id
        self.raise_on_route = raise_on_route
        self.calls = []

    async def route(self, prompt, mundo, *, distilled_state=None):
        self.calls.append((prompt, mundo, distilled_state))
        if self.raise_on_route:
            raise RuntimeError("router unavailable")
        return api_server.SkillRouteResult(self.skill_id, 0.5, "keyword", True)


class _CapturingGuidedProvider:
    """Guided provider that records the compiled_contract_markdown hint."""

    def __init__(self):
        self.received = None

    async def invoke(self, request, token, *, compiled_contract_markdown=None):
        self.received = compiled_contract_markdown
        return {
            "protocol_version": "guided-character-v1",
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "What drives them?",
        }


class _ProbeRecordingGuidedProvider:
    """Guided provider that records how many times it was invoked."""

    def __init__(self):
        self.invocations = 0

    async def invoke(self, request, token, **kwargs):
        self.invocations += 1
        return {
            "protocol_version": "guided-character-v1",
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "What drives them?",
        }


class _PartialActivityAdapter:
    """Emits a delta answer then completes; used for the streaming path."""

    available = True
    capability = _activity_capability()

    def __init__(self):
        self.cancelled = []

    def start(self, request):
        return "run-1"

    async def events(self, run_id):
        yield {
            "event": "message.delta", "run_id": run_id, "delta": "preserve this answer",
        }
        yield {"event": "run.completed", "run_id": run_id, "output": "preserve this answer"}

    def cancel(self, run_id):
        self.cancelled.append(run_id)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a temp mundos dir, in-memory conversation memory, and a
    recording skill router. The semantic provider is unwired (fail-closed) by
    default; tests that exercise /ai/ask wire a fake provider explicitly."""
    mundos = tmp_path / "mundos"
    world = mundos / "test_mundo"
    lore = world / "lore"
    lore.mkdir(parents=True)
    (lore / "00_inicio.md").write_text(
        "---\ntype: criatura\ntitle: Inicio\n---\n# Inicio\n", encoding="utf-8"
    )

    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", None)
    monkeypatch.setattr(api_server, "_CONVERSATION_MEMORY", ConversationMemoryStore(":memory:"))
    router = _FakeRouter()
    monkeypatch.setattr(api_server, "_SKILL_ROUTER", router)
    api_server._graph_indices.clear()
    api_server._confirmation_store.clear()
    api_server._GUIDED_PENDING_PROPOSALS.clear()
    api_server._GUIDED_CONSENT_TOKENS.clear()
    api_server._GUIDED_INDEX_REQUESTS.clear()
    api_server._METHODOLOGY_LIBRARY = None
    api_server._METHODOLOGY_QUARANTINE = None
    with api_server._local_session_lock:
        api_server._local_sessions.clear()
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _wire_semantic_provider(monkeypatch, runs, recorder=False):
    provider = api_server.SemanticIntentProvider(runs)
    if recorder:
        provider = _RecordingProvider(provider)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", provider)
    return provider


class TestMultiTurnMemory:
    def test_turns_persist_and_envelope_stays_unchanged(self, client: TestClient, monkeypatch):
        """AC-01 + AC-08: each non-guided /ai/ask with a session persists user +
        assistant turns, and the returned envelope is untouched (no new keys)."""
        runs = _SemanticRuns(_semantic_payload("allow"), _semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)

        first = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Hola", "session_id": "sess-1",
        })
        assert first.status_code == 200
        envelope = first.json()
        assert envelope["state"] == "allow"
        assert envelope["response"] == "Hermes semantic answer."
        assert "skill" not in envelope
        assert "distilled" not in envelope

        memory = api_server._CONVERSATION_MEMORY
        turns = memory.get_recent_turns("sess-1")
        assert len(turns) == 2
        assert [t.role for t in turns] == ["user", "assistant"]
        assert turns[0].content == "Hola"

        second = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Otra pregunta", "session_id": "sess-1",
        })
        assert second.json()["state"] == "allow"
        assert len(memory.get_recent_turns("sess-1")) == 4

    def test_empty_session_id_persists_nothing(self, client: TestClient, monkeypatch):
        """Fricción 4: an empty session_id never names a conversation and must
        not produce memory writes or routing/LLM calls."""
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        response = client.post("/api/test_mundo/ai/ask", json={"prompt": "Hola"})
        assert response.status_code == 200
        assert api_server._CONVERSATION_MEMORY.get_recent_turns("") == []
        assert api_server._SKILL_ROUTER.calls == []


class TestSkillRouting:
    def test_route_stores_skill_on_user_turn(self, client: TestClient, monkeypatch):
        """AC-03 + AC-05: the router maps intent and the skill_id lands on the
        persisted user turn; the envelope is unchanged."""
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Escribe un borrador", "session_id": "sess-2",
        })
        assert response.status_code == 200
        assert response.json()["state"] == "allow"
        assert api_server._SKILL_ROUTER.calls  # routed for a real session
        turns = api_server._CONVERSATION_MEMORY.get_recent_turns("sess-2")
        assert turns[0].skill_id == "narrative-draft"
        assert turns[1].skill_id is None

    def test_fail_open_when_router_unavailable(self, client: TestClient, monkeypatch):
        """AC-06: a failing router never blocks the answer; routing degrades to
        no skill and the response envelope is still served."""
        monkeypatch.setattr(api_server, "_SKILL_ROUTER", _FakeRouter(raise_on_route=True))
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Hola", "session_id": "sess-3",
        })
        assert response.status_code == 200
        assert response.json()["state"] == "allow"
        turns = api_server._CONVERSATION_MEMORY.get_recent_turns("sess-3")
        assert turns[0].skill_id is None


class TestDistilledGateInjection:
    def test_distilled_state_reaches_gate_on_ai_ask(self, client: TestClient, monkeypatch):
        """AC-02: the distilled summary is injected into the semantic gate so
        the single-run answer is memory-aware (fricción 3)."""
        api_server._CONVERSATION_MEMORY.update_distilled_state(
            "sess-d", "test_mundo", "Resumen de contexto", 5,
        )
        runs = _SemanticRuns(_semantic_payload("allow"))
        recorder = _wire_semantic_provider(monkeypatch, runs, recorder=True)
        client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Hola", "session_id": "sess-d",
        })
        assert recorder.distilled == ["Resumen de contexto"]

    def test_chat_injects_distilled_state_to_gate(self, client: TestClient, monkeypatch):
        """Fricción 3 via /api/chat: minimal gate context includes the summary."""
        api_server._CONVERSATION_MEMORY.update_distilled_state(
            "sess-c", "test_mundo", "Contexto de chat", 3,
        )
        runs = _SemanticRuns(_semantic_payload("allow"))
        recorder = _wire_semantic_provider(monkeypatch, runs, recorder=True)
        response = client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "Hola"}],
            "mundo": "test_mundo", "session_id": "sess-c",
        })
        assert response.status_code == 200
        assert recorder.distilled == ["Contexto de chat"]


class TestGuidedContractProjection:
    def test_compiled_contract_markdown_none_for_builtin(self, monkeypatch, tmp_path):
        """Fricción 2: a world with no activation resolves to None (builtin)."""
        library = api_server.MethodologyLibrary(tmp_path / "no-such-library.json")
        monkeypatch.setattr(api_server, "_methodology_library", lambda: library)
        assert api_server._compiled_contract_markdown("test_mundo") is None

    def test_guided_continue_propagates_contract_to_invoke(self, client: TestClient, monkeypatch):
        """Fricción 1: _guided_continue resolves the contract and it reaches the
        provider's invoke() as compiled_contract_markdown."""
        provider = _CapturingGuidedProvider()
        store = api_server.GuidedSessionStore()
        store.create("guided-sess", "test_mundo", "tester")
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", store)
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", api_server.Capabilities(
            "guided-character-v1", True, True, True, 30000,
        ))
        monkeypatch.setattr(
            api_server, "_compiled_contract_markdown",
            lambda _world, _flow_type: "## Methodology: Test\n**Phases**: a → b\n",
        )
        asyncio.run(api_server._guided_continue(
            "test_mundo", "guided-sess", 0, "answer",
            api_server.EditPrincipal("tester"),
        ))
        assert provider.received == "## Methodology: Test\n**Phases**: a → b\n"

    def test_invoke_bounded_without_contract_hint_is_backward_compatible(self, monkeypatch):
        """Fricción 1: a plain-callable provider keeps working when no contract
        hint is passed (the additive kwarg never changes legacy behavior)."""
        async def provider(request, _token):
            return {
                "protocol_version": "guided-character-v1",
                "request_id": request.request_id,
                "session_id": request.session_id,
                "outcome": "question",
                "question": "What drives them?",
            }

        request = api_server.GuidedRequest(
            "guided-character-v1", "req-1", "session-1", "test_mundo",
            0, "tester", "answer",
        )
        result = asyncio.run(invoke_bounded(
            provider, request,
            api_server.Capabilities("guided-character-v1", True, True, True, 30000),
        ))
        assert result.outcome.value == "question"


class TestGuidedContinuationProbe:
    def test_guided_continue_probes_capabilities_before_invoking(self, monkeypatch):
        """Regression: a session opened through the semantic chat path never
        called the REST start route, so _GUIDED_CAPABILITIES stayed None and the
        first real turn failed closed with CAPABILITY_UNAVAILABLE (503) without
        ever invoking the provider. The shared continuation choke point must
        probe before invoking, so an unpopulated global is resolved here."""
        provider = _ProbeRecordingGuidedProvider()
        store = api_server.GuidedSessionStore()
        store.create("guided-sess", "test_mundo", "tester")
        confirming = store.begin_confirmation(
            "guided-sess", "tester", "Create Rhyz's sister", "Start? (yes/no)",
        )
        assert confirming is not None and confirming.phase == "confirmation"
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", store)
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        # Regression condition: the chat path never populated the global.
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", None)
        probe_calls = []

        async def spy():
            probe_calls.append(True)
            return api_server.Capabilities("guided-character-v1", True, True, True, 30000)

        monkeypatch.setattr(api_server, "_probe_guided_capabilities", spy)

        asyncio.run(api_server._guided_continue(
            "test_mundo", "guided-sess", 1, "sí",
            api_server.EditPrincipal("tester"),
        ))

        assert probe_calls == [True]
        assert provider.invocations == 1


class TestActivityStreamMemory:
    def test_stream_persists_user_and_assistant_turns(self, client: TestClient, monkeypatch):
        """Fricción 5: the user turn is stored up front and the assistant turn is
        stored at stream close with the full answer text."""
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        adapter = _PartialActivityAdapter()
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)

        response = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "Hola", "session_id": "sess-act",
        })
        assert response.status_code == 200
        events = _parse_sse(response.text)
        assert events[0]["kind"] == "semantic_decision"
        assert events[-1]["kind"] == "terminal"

        turns = api_server._CONVERSATION_MEMORY.get_recent_turns("sess-act")
        assert [t.role for t in turns] == ["user", "assistant"]
        assert turns[0].content == "Hola"
        assert turns[1].content == "preserve this answer"
        # The user turn carries the routed skill.
        assert turns[0].skill_id == "narrative-draft"
