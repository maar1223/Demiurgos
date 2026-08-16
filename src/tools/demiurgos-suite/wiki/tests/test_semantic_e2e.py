# -*- coding: utf-8 -*-
"""PR5 (tasks 5.1-5.2) E2E proofs for Hermes-first semantic authority.

Part A — Deterministic recorder-spy E2E (in-process, no real gateway).

For every assistant surface (``/api/{mundo}/ai/ask``, activity SSE, guided
start, guided continuation, typed confirmation, and compatible ``/api/chat``)
a recorder proves the FIRST provider touch is the Hermes semantic gate
(``SemanticIntentProvider.decide``) and that no lexical classifier or policy
helper (``route_new_character_intent``, ``confirmation_decision``, plain-chat
fallback) runs before a validated decision. Pre-flight auth/world/revision
guards run before the gate but are NOT intent classifiers: they never decide
intent and never consume a provider run. Single-run continuation asserts
exactly one semantic run per turn (no second Hermes run).

Part B — Bounded real Hermes gateway E2E (skipped when the gateway is down).

One safe request per essential surface as feasible against the real gateway,
asserting semantic decision ordering, the localized fail-closed blocked
envelope when the gateway is stopped (with clean restart teardown), and the
auth guard before the gate. Never prints secrets or provider/internal text.
The stop-gateway test only runs when DEMIURGOS_E2E_STOP_GATEWAY=1.
"""

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402
from guided_character_domain import route_new_character_intent  # noqa: E402

GATEWAY_HEALTH = "http://127.0.0.1:8642/health"
GATEWAY_PID_FILE = Path("/tmp/demiurgos-launcher/gateway.pid")
GATEWAY_LOG = Path("/tmp/demiurgos-gateway.log")
PROJECT_ROOT = _WIKI.parents[3]
STOP_GATEWAY = os.getenv("DEMIURGOS_E2E_STOP_GATEWAY") == "1"


# ---------------------------------------------------------------------------
# Shared helpers (mirror the fixture/helper shapes used by the phase suites)
# ---------------------------------------------------------------------------

def _sample_world(mundos: Path) -> Path:
    world = mundos / "test_mundo"
    lore = world / "lore"
    lore.mkdir(parents=True)
    (lore / "00_inicio.md").write_text(
        "---\ntype: criatura\ntitle: Inicio\n---\n# Inicio\n",
        encoding="utf-8",
    )
    return world


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a temp mundos dir and a sample world (fail-closed by
    default: the semantic provider is unwired unless a test wires a fake)."""
    _sample_world(tmp_path / "mundos")
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path / "mundos")
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", None)
    api_server._graph_indices.clear()
    api_server._confirmation_store.clear()
    with api_server._local_session_lock:
        api_server._local_sessions.clear()
    api_server._target_locks.clear()
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _principal(monkeypatch: pytest.MonkeyPatch, pid: str = "tester") -> None:
    monkeypatch.setattr(
        api_server, "_resolve_principal",
        lambda _request: api_server.EditPrincipal(pid),
    )


def _parse_sse(text: str) -> list[dict]:
    """Parse ``event: <kind>`` / ``data: <json>`` records in stream order."""
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
    """Minimal runs adapter shape consumed by SemanticIntentProvider.

    Records every ``start`` so tests can assert single-run continuation (one
    semantic run per turn) and can replay fixed provider payloads.
    """

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
        "request_id": "request-1",
        "session_id": "chat-1",
        "guided": True,
    }
    payload.update(overrides)
    return payload


def _continuation_semantic_payload(state="proposal_ready", **overrides):
    payload = {
        "state": state,
        "response": "Hermes semantic answer.",
        "request_id": "request-1",
        "session_id": "chat-1",
        "guided": True,
        "continuation": {
            "outcome": "question" if state == "require_confirmation" else "delta",
            "question": "¿Creo este personaje?" if state == "require_confirmation" else None,
            "delta": None if state == "require_confirmation" else {"name": "Rhyz's Wife", "desire": "freedom"},
        },
    }
    payload.update(overrides)
    return payload


def _wire_semantic_provider(monkeypatch, runs, **provider_kwargs):
    provider = api_server.SemanticIntentProvider(runs, **provider_kwargs)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", provider)
    return provider


def _wire_recorder(monkeypatch, runs, order):
    """Wire the semantic gate and record the provider-touch order.

    ``decide`` appends ``"semantic.decide"`` as the first/only provider touch;
    classifier/policy helpers append their own markers only when invoked.
    """
    provider = _wire_semantic_provider(monkeypatch, runs)
    original_decide = provider.decide

    async def recorded_decide(*args, **kwargs):
        order.append("semantic.decide")
        return await original_decide(*args, **kwargs)

    provider.decide = recorded_decide
    return runs


# ---------------------------------------------------------------------------
# Part A — Deterministic recorder-spy E2E: Hermes is the first provider touch
# ---------------------------------------------------------------------------

class TestFirstProviderTouchE2E:
    """Task 5.1 RED evidence: the first provider touch on EVERY assistant
    surface is Hermes semantic interpretation, before any lexical classifier or
    policy helper that is not a preflight auth/world/revision guard."""

    def test_ai_ask_first_touch_is_semantic(self, client, monkeypatch):
        order = []
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_recorder(monkeypatch, runs, order)
        monkeypatch.setattr(
            api_server, "route_new_character_intent",
            lambda *a, **k: order.append("route_new_character_intent") or None,
        )
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": "Hola"})
        assert response.status_code == 200
        assert response.json()["state"] == "allow"
        assert order == ["semantic.decide"]
        assert runs.starts == 1
        legacy.assert_not_awaited()

    def test_ai_ask_lexical_prompt_still_semantic_first(self, client, monkeypatch):
        """Even a lexical new-character prompt is interpreted by Hermes first;
        the guarded guided machinery runs only after the validated decision."""
        order = []
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_recorder(monkeypatch, runs, order)
        real_route = api_server.route_new_character_intent

        def recorded_route(*args, **kwargs):
            order.append("route_new_character_intent")
            return real_route(*args, **kwargs)

        monkeypatch.setattr(api_server, "route_new_character_intent", recorded_route)
        response = client.post(
            "/api/test_mundo/ai/ask",
            json={"prompt": "Un guerrero de las sombras", "session_id": "chat-1"},
        )
        assert response.status_code == 200
        assert response.json()["state"] == "allow"
        assert order == ["semantic.decide"]
        assert runs.starts == 1

    def test_activity_first_touch_is_semantic(self, client, monkeypatch):
        order = []
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_recorder(monkeypatch, runs, order)

        class FakeAdapter:
            available = True

            def __init__(self):
                self.cancelled = []

            def start(self, request):
                return "run-1"

            async def events(self, run_id):
                yield {"event": "message.delta", "run_id": run_id, "delta": "safe answer"}
                yield {"event": "run.completed", "run_id": run_id, "output": "safe answer"}

            def cancel(self, run_id):
                self.cancelled.append(run_id)

        adapter = FakeAdapter()
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)
        monkeypatch.setattr(
            api_server, "route_new_character_intent",
            lambda *a, **k: order.append("route_new_character_intent") or None,
        )
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post(
                "/api/test_mundo/ai/ask/activity", json={"prompt": "Hola"},
            )
        assert response.status_code == 200
        kinds = [event["kind"] for event in _parse_sse(response.text)]
        assert kinds[0] == "semantic_decision"
        assert order == ["semantic.decide"]
        assert runs.starts == 1
        legacy.assert_not_awaited()

    def test_guided_start_first_touch_is_semantic(self, client, monkeypatch, tmp_path):
        order = []
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_recorder(monkeypatch, runs, order)
        _principal(monkeypatch)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(
            api_server, "_named_reference_context",
            lambda _mundo, _prompt: ("", False, None),
        )

        async def provider(request, _token):
            order.append("guided_provider")
            return {
                "protocol_version": request.protocol_version,
                "request_id": request.request_id,
                "session_id": request.session_id,
                "outcome": "question",
                "question": "What drives them?",
            }

        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(
            api_server, "_GUIDED_CAPABILITIES",
            api_server.Capabilities("guided-character-v1", True, True, True, 30000),
        )
        real_route = api_server.route_new_character_intent

        def recorded_route(*args, **kwargs):
            order.append("route_new_character_intent")
            return real_route(*args, **kwargs)

        monkeypatch.setattr(api_server, "route_new_character_intent", recorded_route)
        response = client.post(
            "/api/test_mundo/guided-character/session",
            json={"author_input": "Create a character"},
        )
        assert response.status_code == 200
        assert order[0] == "semantic.decide"
        assert order == ["semantic.decide", "route_new_character_intent", "guided_provider"]
        assert runs.starts == 1

    def test_guided_turn_first_touch_is_semantic(self, client, monkeypatch):
        order = []
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_recorder(monkeypatch, runs, order)
        _principal(monkeypatch)
        sessions = api_server.GuidedSessionStore()
        state = sessions.create("guided-1", "test_mundo", "tester")
        confirming = sessions.begin_confirmation(
            "guided-1", "tester", "Crea un personaje", "¿Sí o no?",
        )
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", None)
        monkeypatch.setattr(
            api_server, "_GUIDED_CAPABILITIES",
            api_server.Capabilities("guided-character-v1", True, True, True, 30000),
        )

        def recorded_confirmation(*args, **kwargs):
            order.append("confirmation_decision")
            return None

        monkeypatch.setattr(api_server, "confirmation_decision", recorded_confirmation)
        response = client.post("/api/test_mundo/guided-character/turn", json={
            "session_id": state.session_id,
            "base_revision": confirming.revision,
            "author_input": "Freedom",
        })
        assert response.status_code == 200
        assert order == ["semantic.decide", "confirmation_decision"]
        assert runs.starts == 1

    def test_typed_confirmation_first_touch_is_semantic(self, client, monkeypatch):
        """Typed confirmation is parsed as policy ONLY after validated Hermes
        interpretation on the /ai/ask continuation surface."""
        order = []
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_recorder(monkeypatch, runs, order)
        _principal(monkeypatch)
        sessions = api_server.GuidedSessionStore()
        state = sessions.create("guided-confirm", "test_mundo", "tester")
        confirming = sessions.begin_confirmation(
            "guided-confirm", "tester", "Crea un personaje", "¿Sí o no?",
        )
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)
        monkeypatch.setattr(
            api_server, "_named_reference_context",
            lambda _mundo, _prompt: ("", False, None),
        )

        def recorded_confirmation(*args, **kwargs):
            order.append("confirmation_decision")
            return None

        monkeypatch.setattr(api_server, "confirmation_decision", recorded_confirmation)
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", None)
        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "sí", "session_id": "chat-1",
            "guided_session_id": state.session_id,
            "guided_revision": confirming.revision,
        })
        assert response.status_code == 200
        assert order == ["semantic.decide", "confirmation_decision"]
        assert runs.starts == 1

    def test_chat_first_touch_is_semantic(self, client, monkeypatch):
        order = []
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_recorder(monkeypatch, runs, order)
        monkeypatch.setattr(
            api_server, "route_new_character_intent",
            lambda *a, **k: order.append("route_new_character_intent") or None,
        )
        response = client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "Hola"}],
            "mundo": "test_mundo",
        })
        assert response.status_code == 200
        assert response.json()["state"] == "allow"
        assert order == ["semantic.decide"]
        assert runs.starts == 1

    def test_preflight_auth_guard_never_consumes_provider(self, client, monkeypatch):
        """Auth guard is a preflight (not a classifier): it runs BEFORE the gate
        and consumes zero provider runs."""
        order = []
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_recorder(monkeypatch, runs, order)
        monkeypatch.setattr(api_server, "route_new_character_intent",
                            lambda *a, **k: order.append("classifier") or None)
        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Hola", "session_id": "chat-1",
            "guided_session_id": "missing", "guided_revision": 0,
        })
        assert response.status_code == 401
        assert order == []
        assert runs.starts == 0

    def test_preflight_world_guard_never_consumes_provider(self, client, monkeypatch):
        order = []
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_recorder(monkeypatch, runs, order)
        _principal(monkeypatch)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(
            api_server, "route_new_character_intent",
            lambda *a, **k: order.append("classifier") or None,
        )
        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Hola", "session_id": "chat-1",
            "guided_session_id": "missing", "guided_revision": 0,
        })
        assert response.status_code == 401
        assert order == []
        assert runs.starts == 0

    def test_preflight_revision_guard_never_consumes_provider(self, client, monkeypatch):
        order = []
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_recorder(monkeypatch, runs, order)
        _principal(monkeypatch)
        sessions = api_server.GuidedSessionStore()
        state = sessions.create("guided-1", "test_mundo", "tester")
        confirming = sessions.begin_confirmation(
            "guided-1", "tester", "Crea un personaje", "¿Sí o no?",
        )
        assert confirming.revision > 0
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)
        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Hola", "session_id": "chat-1",
            "guided_session_id": state.session_id, "guided_revision": 0,
        })
        assert response.status_code == 409
        assert order == []
        assert runs.starts == 0


class TestSingleRunContinuationE2E:
    """Task 5.2: one semantic run backs decision + continuation; no second run."""

    def test_proposal_ready_single_run_no_second_run(self, client, monkeypatch):
        runs = _SemanticRuns(_continuation_semantic_payload("proposal_ready"))
        _wire_semantic_provider(monkeypatch, runs)
        _principal(monkeypatch)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(api_server, "_GUIDED_PENDING_PROPOSALS", {})
        monkeypatch.setattr(
            api_server, "_named_reference_context",
            lambda _mundo, _prompt: ("", False, None),
        )
        with patch("api_server._run_hermes", new=AsyncMock(return_value="unused")) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={
                "prompt": "Define el perfil de un ser que lo protege",
            })
        envelope = response.json()
        assert response.status_code == 200
        assert envelope["state"] == "proposal_ready"
        assert envelope["target"] == "personajes/rhyz-s-wife.md"
        assert re.fullmatch(r"[0-9a-f]{64}", envelope["proposed_digest"])
        assert hashlib.sha256(envelope["proposed_content"].encode("utf-8")).hexdigest() == envelope["proposed_digest"]
        assert runs.starts == 1
        legacy.assert_not_awaited()
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "personajes").exists()

    def test_require_confirmation_single_run_no_second_run(self, client, monkeypatch):
        runs = _SemanticRuns(_continuation_semantic_payload("require_confirmation"))
        _wire_semantic_provider(monkeypatch, runs)
        _principal(monkeypatch)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(
            api_server, "_named_reference_context",
            lambda _mundo, _prompt: ("", False, None),
        )
        with patch("api_server._run_hermes", new=AsyncMock(return_value="unused")) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={
                "prompt": "Quisiera que me propongas un compañero para ese mundo",
            })
        envelope = response.json()
        assert response.status_code == 200
        assert envelope["state"] == "require_confirmation"
        assert envelope["response"] == "¿Creo este personaje?"
        assert runs.starts == 1
        legacy.assert_not_awaited()

    def test_unavailable_continuation_no_mutation_no_write(self, client, monkeypatch, tmp_path):
        canon = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        before = {p.name: p.read_bytes() for p in canon.iterdir() if p.is_file()}
        pending_before = dict(api_server._GUIDED_PENDING_PROPOSALS)
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={
                "prompt": "Define el perfil de un ser que lo protege",
            })
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "blocked"
        assert envelope["unavailable"] is True
        assert envelope["response"].startswith("El Asistente IA no pudo")
        assert api_server._GUIDED_PENDING_PROPOSALS == pending_before
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "personajes").exists()
        after = {p.name: p.read_bytes() for p in canon.iterdir() if p.is_file()}
        assert after == before
        legacy.assert_not_awaited()


# ---------------------------------------------------------------------------
# Part B — Bounded real Hermes gateway E2E (skipped when the gateway is down)
# ---------------------------------------------------------------------------

def _gateway_available(timeout: float = 3.0) -> bool:
    import httpx
    try:
        response = httpx.get(GATEWAY_HEALTH, timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


def _wait_health(expected: bool, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _gateway_available(1.0) is expected:
            return True
        time.sleep(1)
    return False


def _stop_gateway() -> bool:
    """SIGTERM the launcher-owned gateway; returns True when it went down."""
    if not GATEWAY_PID_FILE.exists():
        return False
    try:
        pid = int(GATEWAY_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.2)
    return False


def _start_gateway() -> bool:
    """Restart the gateway with the launcher-equivalent command and health wait."""
    import shutil
    hermes = shutil.which("hermes")
    if hermes is None or not Path(hermes).exists():
        hermes = str(Path.home() / ".local/bin/hermes")
    if not Path(hermes).exists():
        return False
    env = {
        **os.environ,
        "HERMES_GATEWAY_HOST": "127.0.0.1",
        "HERMES_GATEWAY_PORT": "8642",
    }
    # The gateway subprocess must NOT look like a pytest child: Hermes' live
    # system guard refuses to open the production state.db when
    # PYTEST_CURRENT_TEST / PYTEST_VERSION are inherited, which would make the
    # clean-teardown restart crash.
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop("PYTEST_VERSION", None)
    try:
        with open(GATEWAY_LOG, "ab") as log:
            proc = subprocess.Popen(
                [hermes, "gateway", "run"],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError:
        return False
    try:
        GATEWAY_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    except OSError:
        pass
    return _wait_health(True, timeout=120.0)


@pytest.fixture()
def live_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient that keeps the REAL gateway-backed semantic provider wired
    (does NOT null _SEMANTIC_PROVIDER) so requests exercise the live Hermes
    runtime through the full server stack."""
    _sample_world(tmp_path / "mundos")
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path / "mundos")
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    api_server._graph_indices.clear()
    api_server._confirmation_store.clear()
    with api_server._local_session_lock:
        api_server._local_sessions.clear()
    api_server._target_locks.clear()
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _requires_gateway():
    if not _gateway_available():
        pytest.skip("Real Hermes gateway is not available at " + GATEWAY_HEALTH)
    return True


class TestLiveHermesFirstE2E:
    """Task 5.1/5.2 live proof against the real Hermes gateway (bounded: one
    safe request per essential surface as feasible). Skips when the gateway is
    down. Never prints secrets or provider/internal error text."""

    VALID_STATES = {"allow", "clarify", "require_confirmation", "proposal_ready", "blocked"}

    def test_live_ai_ask_semantic_first_and_valid(self, live_client, monkeypatch):
        _requires_gateway()
        order = []
        provider = api_server._SEMANTIC_PROVIDER
        original_decide = provider.decide

        async def recorded_decide(*args, **kwargs):
            order.append("semantic.decide")
            return await original_decide(*args, **kwargs)

        monkeypatch.setattr(provider, "decide", recorded_decide)
        monkeypatch.setattr(
            api_server, "route_new_character_intent",
            lambda *a, **k: order.append("route_new_character_intent") or None,
        )
        response = live_client.post("/api/test_mundo/ai/ask", json={"prompt": "Hola"})
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] in self.VALID_STATES
        assert isinstance(envelope["request_id"], str) and envelope["request_id"]
        assert order == ["semantic.decide"]
        lowered = f"{envelope.get('response', '')} {envelope.get('action', '')}".lower()
        for term in ("error:", "traceback", "gateway", "credential", "api_key", "bearer"):
            assert term not in lowered

    def test_live_chat_compatibility_envelope(self, live_client, monkeypatch):
        _requires_gateway()
        order = []
        provider = api_server._SEMANTIC_PROVIDER
        original_decide = provider.decide

        async def recorded_decide(*args, **kwargs):
            order.append("semantic.decide")
            return await original_decide(*args, **kwargs)

        monkeypatch.setattr(provider, "decide", recorded_decide)
        response = live_client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "Hola"}],
            "mundo": "test_mundo",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["state"] in self.VALID_STATES
        if body["state"] not in ("blocked", "require_confirmation", "proposal_ready"):
            assert body["content"] == body["response"]
        assert order == ["semantic.decide"]

    def test_live_activity_semantic_decision_first(self, live_client, monkeypatch):
        _requires_gateway()
        response = live_client.post(
            "/api/test_mundo/ai/ask/activity", json={"prompt": "Hola"},
        )
        assert response.status_code == 200
        events = _parse_sse(response.text)
        kinds = [event["kind"] for event in events]
        assert kinds[0] == "semantic_decision"
        decision = events[0]
        assert decision["state"] in {"allow", "clarify", "blocked"}
        assert isinstance(decision["unavailable"], bool)
        lowered = response.text.lower()
        for term in ("error:", "traceback", "credential", "api_key", "bearer"):
            assert term not in lowered

    def test_live_guided_start_semantic_first(self, live_client, monkeypatch):
        _requires_gateway()
        order = []
        provider = api_server._SEMANTIC_PROVIDER
        original_decide = provider.decide

        async def recorded_decide(*args, **kwargs):
            order.append("semantic.decide")
            return await original_decide(*args, **kwargs)

        monkeypatch.setattr(provider, "decide", recorded_decide)
        _principal(monkeypatch)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(
            api_server, "_named_reference_context",
            lambda _mundo, _prompt: ("", False, None),
        )
        response = live_client.post(
            "/api/test_mundo/guided-character/session",
            json={"author_input": "Create a character"},
        )
        assert response.status_code in {200, 503}
        assert order[0] == "semantic.decide"
        lowered = response.text.lower()
        for term in ("error:", "traceback", "credential", "api_key", "bearer"):
            assert term not in lowered

    def test_live_auth_guard_before_gate(self, live_client, monkeypatch):
        """Preflight auth guard runs BEFORE the live gate: 401 with zero
        provider runs on an unauthenticated guided continuation."""
        _requires_gateway()
        provider = api_server._SEMANTIC_PROVIDER
        original_decide = provider.decide
        calls = []

        async def recorded_decide(*args, **kwargs):
            calls.append("decide")
            return await original_decide(*args, **kwargs)

        monkeypatch.setattr(provider, "decide", recorded_decide)
        response = live_client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Hola", "session_id": "chat-1",
            "guided_session_id": "missing", "guided_revision": 0,
        })
        assert response.status_code == 401
        assert calls == []

    @pytest.mark.skipif(not STOP_GATEWAY, reason="set DEMIURGOS_E2E_STOP_GATEWAY=1")
    def test_live_stopped_gateway_fails_closed_with_clean_teardown(self, live_client):
        """Stop the real gateway: /ai/ask must fail closed over HTTP 200 with
        the localized blocked envelope and zero writes. Teardown restarts the
        gateway and verifies health (clean teardown is unconditional)."""
        _requires_gateway()
        try:
            assert _stop_gateway(), "gateway did not stop"
            assert _wait_health(False, timeout=15.0), "gateway still reachable after stop"
            canon = api_server.MUNDOS_DIR / "test_mundo" / "lore"
            before = {p.name: p.read_bytes() for p in canon.iterdir() if p.is_file()}
            with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
                response = live_client.post(
                    "/api/test_mundo/ai/ask", json={"prompt": "Hola"},
                )
            assert response.status_code == 200
            envelope = response.json()
            assert envelope["state"] == "blocked"
            assert envelope["unavailable"] is True
            assert envelope["response"].startswith("El Asistente IA no pudo")
            assert api_server._GUIDED_PENDING_PROPOSALS == {}
            assert not (api_server.MUNDOS_DIR / "test_mundo" / "personajes").exists()
            after = {p.name: p.read_bytes() for p in canon.iterdir() if p.is_file()}
            assert after == before
            legacy.assert_not_awaited()
        finally:
            restarted = _start_gateway()
            assert restarted, "gateway did not come back after teardown restart"
            assert _gateway_available(), "gateway health not restored"
