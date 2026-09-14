"""T-A tests for the per-flow activation API (SR1 — contract §2).

API flow is an optional body field (POST) / query param (GET) defaulting to
``guided-character`` (design D4). Unknown/empty flow types fail as 422
``unsupported_flow_type`` BEFORE any library call (zero mutation). Every
fixture is tmp — the on-disk ``data/methodology/library.json`` is never read
or written by these tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import api_server  # noqa: E402
from assistant_activity import assess_hermes_capabilities  # noqa: E402
from guided_session_store import GuidedSessionStore as DurableGuidedSessionStore  # noqa: E402

_SOURCE = "## Construcción segura\n\nHaz preguntas de a una.\n"

# The live on-disk legacy record shape (data/methodology/library.json,
# read-only): world-keyed, no ``flow_type`` — the coercion fixture (R4).
_LEGACY_RECORD = {
    "world": "test_mundo",
    "skill_id": "narrative-character-creation",
    "version": "1.0",
    "digest": "2ae521a09bf014ccdefd7296f6ec94092aa6421703802f2d432d9eaf4f1bbe81",
    "activated_at": "2026-09-11T20:18:25.280907+00:00",
}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a temp mundos dir and a sample world (tmp-only)."""
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
    api_server._graph_indices.clear()
    api_server._confirmation_store.clear()
    api_server._GUIDED_PENDING_PROPOSALS.clear()
    api_server._METHODOLOGY_LIBRARY = None
    api_server._METHODOLOGY_QUARANTINE = None
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _principal(monkeypatch: pytest.MonkeyPatch, pid: str = "author-1") -> None:
    monkeypatch.setattr(
        api_server, "_resolve_principal", lambda request: api_server.EditPrincipal(pid)
    )


def _activity_capability():
    return assess_hermes_capabilities({
        "object": "hermes.api_server.capabilities",
        "platform": "hermes-agent",
        "features": {
            "run_submission": True,
            "run_status": True,
            "run_events_sse": True,
            "run_stop": True,
            "tool_progress_events": True,
        },
    })


class _SemanticRuns:
    """Minimal runs adapter shape consumed by SemanticIntentProvider."""

    def __init__(self, *payloads):
        self._payloads = list(payloads)

    async def start(self, request):
        return "run-1"

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


def _wire_semantic_provider(monkeypatch, runs):
    provider = api_server.SemanticIntentProvider(runs)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", provider)
    return provider


def _delta_guided_provider():
    async def provider(request, _token):
        return {
            "protocol_version": "guided-character-v1",
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": {"name": "Pert", "desire": "freedom"},
        }

    return provider


class _RecordingActivityAdapter:
    """Records every submitted prompt (injection assertions)."""

    available = True
    capability = _activity_capability()

    def __init__(self):
        self.prompts = []

    def start(self, request):
        self.prompts.append(request.prompt)
        return "bridge-run-1"

    async def events(self, run_id):
        yield {"event": "run.completed", "run_id": run_id, "output": "bridge answer"}

    def cancel(self, run_id):
        pass


class _NoWinnerRouter:
    """Skill router that never selects a winner (free chat baseline)."""

    async def route(self, prompt, mundo, distilled_state=None):
        return api_server.SkillRouteResult(None, 0.0, "fallback", False)


class TestPerFlowActivationApi:
    """R1/R2/R4/R5 API scenarios (design testing table, T-A)."""

    def _wire_guided(self, monkeypatch, store, payloads: int = 1) -> None:
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", store)
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", _delta_guided_provider())
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", api_server.Capabilities(
            "guided-character-v1", True, True, True, 30000,
        ))
        _wire_semantic_provider(
            monkeypatch, _SemanticRuns(*([_semantic_payload("allow")] * payloads))
        )

    def _publish(self, client: TestClient, skill_id: str, version: str, name: str) -> None:
        draft = client.post("/api/methodologies/drafts", json={
            "skill_id": skill_id, "version": version, "name": name, "source": _SOURCE,
        })
        assert draft.status_code == 200, draft.text
        published = client.post(f"/api/methodologies/drafts/{draft.json()['draft_id']}/publish")
        assert published.status_code == 200, published.text

    def _activate(self, client: TestClient, skill_id: str, version: str,
                  flow_type: str | None = None) -> dict:
        payload = {"world": "test_mundo", "skill_id": skill_id, "version": version}
        if flow_type is not None:
            payload["flow_type"] = flow_type
        activated = client.post("/api/methodologies/activate", json=payload)
        assert activated.status_code == 200, activated.text
        return activated.json()

    def test_session_pin_snapshot_carries_flow_type(self, client, monkeypatch, tmp_path):
        """R1 pins session: the pinned snapshot carries the flow type."""
        store = DurableGuidedSessionStore(tmp_path / "guided.sqlite3")
        self._wire_guided(monkeypatch, store)
        _principal(monkeypatch)
        self._publish(client, "guided-character-v1", "1.2.0", "Guided character methodology")
        self._activate(client, "guided-character-v1", "1.2.0")
        started = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Pert",
        })
        assert started.status_code == 200
        snapshot = store.methodology_snapshot(started.json()["session_id"], "author-1")
        assert snapshot is not None
        assert snapshot.skill_version == "1.2.0"
        assert snapshot.flow_type == "guided-character"

    def test_drift_only_within_pinned_flow(self, client, monkeypatch, tmp_path):
        """R1 version drift: a flow-B activation never rejects a flow-A session."""
        store = DurableGuidedSessionStore(tmp_path / "guided.sqlite3")
        self._wire_guided(monkeypatch, store, payloads=2)
        _principal(monkeypatch)
        self._publish(client, "guided-character-v1", "1.2.0", "Guided character methodology")
        self._publish(client, "guided-character-v1", "1.3.0", "Guided character methodology")
        self._publish(client, "co-creation-skill", "1.0.0", "Co-creation skill")
        self._activate(client, "guided-character-v1", "1.2.0")
        started = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Pert",
        })
        assert started.status_code == 200
        sid = started.json()["session_id"]
        # Flow A moves 1.2.0 -> 1.3.0: the pinned session is rejected.
        self._activate(client, "guided-character-v1", "1.3.0")
        assert client.get(f"/api/test_mundo/guided-character/session/{sid}").status_code == 422
        fresh = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Pert",
        })
        assert fresh.status_code == 200
        fresh_sid = fresh.json()["session_id"]
        # Flow B activation must NOT reject the flow-A session.
        self._activate(client, "co-creation-skill", "1.0.0", flow_type="co-creation")
        resumed = client.get(f"/api/test_mundo/guided-character/session/{fresh_sid}")
        assert resumed.status_code == 200

    def test_empty_slot_falls_back_builtin_guided(self, client, monkeypatch, tmp_path):
        """R1 no activation: the builtin guided-character contract applies."""
        store = DurableGuidedSessionStore(tmp_path / "guided.sqlite3")
        self._wire_guided(monkeypatch, store)
        _principal(monkeypatch)
        started = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Pert",
        })
        assert started.status_code == 200
        snapshot = store.methodology_snapshot(started.json()["session_id"], "author-1")
        assert snapshot is not None
        assert snapshot.skill_id == "guided-character-v1"
        assert snapshot.skill_version == "builtin"
        assert snapshot.flow_type == "guided-character"

    def test_multi_slot_free_chat_zero_injection(self, client, monkeypatch, tmp_path):
        """R2/SR1: active slots never inject into free chat (companion-only)."""
        _principal(monkeypatch)
        self._publish(client, "guided-character-v1", "1.2.0", "Guided character methodology")
        self._publish(client, "co-creation-skill", "1.0.0", "Co-creation skill")
        self._activate(client, "guided-character-v1", "1.2.0")
        self._activate(client, "co-creation-skill", "1.0.0", flow_type="co-creation")
        monkeypatch.setattr(api_server, "_SKILL_ROUTER", _NoWinnerRouter())
        monkeypatch.setattr(api_server, "_CONVERSATION_MEMORY", api_server.ConversationMemoryStore(":memory:"))
        adapter = _RecordingActivityAdapter()
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)
        _wire_semantic_provider(monkeypatch, _SemanticRuns(_semantic_payload("allow")))
        response = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "Hola", "session_id": "free-1",
        })
        assert response.status_code == 200
        prompt = adapter.prompts[0]
        assert prompt.strip().endswith("Hola")
        assert "[Companion methodology:" not in prompt
        assert "Guided character methodology" not in prompt
        assert "Co-creation skill" not in prompt

    def test_pinned_session_resolves_coerced_slot(self, client, monkeypatch, tmp_path):
        """R4: a session pinned to the load-coerced slot resolves, no drift."""
        store_file = tmp_path / "data" / "methodology" / "library.json"
        store_file.parent.mkdir(parents=True)
        store_file.write_text(json.dumps({
            "drafts": {}, "published": {}, "companions": {},
            "activations": {"test_mundo": dict(_LEGACY_RECORD)},
            "history": {"test_mundo": [dict(_LEGACY_RECORD)]},
            "draft_history": {},
        }), encoding="utf-8")
        store = DurableGuidedSessionStore(tmp_path / "guided.sqlite3")
        self._wire_guided(monkeypatch, store)
        _principal(monkeypatch)
        started = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Pert",
        })
        assert started.status_code == 200
        snapshot = store.methodology_snapshot(started.json()["session_id"], "author-1")
        assert snapshot is not None
        assert snapshot.skill_id == "narrative-character-creation"
        assert snapshot.skill_version == "1.0"
        assert snapshot.flow_type == "guided-character"
        assert snapshot.compiled_contract_digest == _LEGACY_RECORD["digest"]
        # Continuation/drift resolve via the coerced guided-character slot.
        assert client.get(
            f"/api/test_mundo/guided-character/session/{started.json()['session_id']}"
        ).status_code == 200

    def test_activate_then_get_active_echoes_flow(self, client, monkeypatch):
        """R5 round-trip: activate then read echo the flow; flow B untouched."""
        _principal(monkeypatch)
        self._publish(client, "skill-b", "1.0.0", "Skill B")
        activated = self._activate(client, "skill-b", "1.0.0", flow_type="co-creation")
        assert activated["flow_type"] == "co-creation"
        read = client.get("/api/methodologies/active/test_mundo?flow_type=co-creation")
        assert read.status_code == 200
        body = read.json()
        assert body["flow_type"] == "co-creation"
        assert body["activation"]["skill_id"] == "skill-b"
        assert body["activation"]["flow_type"] == "co-creation"
        # Flow A (guided-character) untouched.
        guided = client.get("/api/methodologies/active/test_mundo")
        assert guided.status_code == 200
        assert guided.json()["activation"] is None

    def test_unknown_flow_422_zero_mutation(self, client, monkeypatch):
        """R5: bogus/empty flow -> 422 on every route, zero slot mutation."""
        _principal(monkeypatch)
        self._publish(client, "skill-a", "1.0.0", "Skill A")
        for flow in ("bogus-flow", ""):
            resp = client.post("/api/methodologies/activate", json={
                "world": "test_mundo", "skill_id": "skill-a", "version": "1.0.0",
                "flow_type": flow,
            })
            assert resp.status_code == 422
            assert resp.json()["code"] == "unsupported_flow_type"
        assert client.get(
            "/api/methodologies/active/test_mundo?flow_type=bogus-flow"
        ).status_code == 422
        rolled = client.post("/api/methodologies/rollback", json={
            "world": "test_mundo", "flow_type": "bogus-flow",
        })
        assert rolled.status_code == 422
        assert rolled.json()["code"] == "unsupported_flow_type"
        # Zero mutation: no slot for ANY flow.
        assert client.get("/api/methodologies/active/test_mundo").json()["activation"] is None
        assert client.get(
            "/api/methodologies/active/test_mundo?flow_type=co-creation"
        ).json()["activation"] is None

    def test_rollback_clears_one_slot_idempotent(self, client, monkeypatch):
        """R5: deactivate is per-flow; empty clears stay idempotent; 401/404."""
        _principal(monkeypatch)
        self._publish(client, "skill-a", "1.0.0", "Skill A")
        self._publish(client, "skill-a", "1.1.0", "Skill A")
        self._publish(client, "skill-b", "2.0.0", "Skill B")
        self._activate(client, "skill-a", "1.0.0")
        self._activate(client, "skill-a", "1.1.0")
        self._activate(client, "skill-b", "2.0.0", flow_type="co-creation")
        rolled = client.post("/api/methodologies/rollback", json={
            "world": "test_mundo", "flow_type": "co-creation",
        })
        assert rolled.status_code == 200
        assert rolled.json()["flow_type"] == "co-creation"
        assert rolled.json()["skill_id"] is None
        assert client.get(
            "/api/methodologies/active/test_mundo?flow_type=co-creation"
        ).json()["activation"] is None
        # The guided slot is untouched; its own history restores 1.0.0.
        assert client.get(
            "/api/methodologies/active/test_mundo"
        ).json()["activation"]["version"] == "1.1.0"
        restored = client.post("/api/methodologies/rollback", json={"world": "test_mundo"})
        assert restored.status_code == 200
        assert restored.json()["version"] == "1.0.0"
        assert restored.json()["flow_type"] == "guided-character"
        # Repeating the empty co-creation clear is a no-op.
        again = client.post("/api/methodologies/rollback", json={
            "world": "test_mundo", "flow_type": "co-creation",
        })
        assert again.status_code == 200
        assert again.json()["skill_id"] is None
        # Prelude parity: 401 unauth, 404 unknown world on rollback + read.
        monkeypatch.setattr(api_server, "_resolve_principal", lambda request: None)
        assert client.post(
            "/api/methodologies/rollback", json={"world": "test_mundo"}
        ).status_code == 401
        assert client.get("/api/methodologies/active/test_mundo").status_code == 401
        _principal(monkeypatch)
        assert client.post(
            "/api/methodologies/rollback", json={"world": "no_such_world"}
        ).status_code == 404
        assert client.get("/api/methodologies/active/no_such_world").status_code == 404

    def test_deactivate_clears_one_slot_keeps_others(self, client, monkeypatch):
        """SR1: deactivate clears ONLY the requested flow slot; other flows
        keep their pin and the cleared slot reads back as ``activation: null``."""
        _principal(monkeypatch)
        self._publish(client, "skill-a", "1.0.0", "Skill A")
        self._publish(client, "skill-b", "2.0.0", "Skill B")
        self._activate(client, "skill-a", "1.0.0")
        self._activate(client, "skill-b", "2.0.0", flow_type="co-creation")
        cleared = client.post("/api/methodologies/deactivate", json={
            "world": "test_mundo", "flow_type": "co-creation",
        })
        assert cleared.status_code == 200
        assert cleared.json() == {
            "world": "test_mundo", "flow_type": "co-creation",
            "skill_id": None, "version": None, "digest": None, "activated_at": None,
        }
        assert client.get(
            "/api/methodologies/active/test_mundo?flow_type=co-creation"
        ).json()["activation"] is None
        # The guided-character slot is untouched.
        assert client.get(
            "/api/methodologies/active/test_mundo"
        ).json()["activation"]["skill_id"] == "skill-a"

    def test_deactivate_empty_slot_idempotent(self, client, monkeypatch):
        """SR1: clearing an already-empty slot is a 200 no-op with the same
        cleared echo (never an error)."""
        _principal(monkeypatch)
        self._publish(client, "skill-a", "1.0.0", "Skill A")
        self._activate(client, "skill-a", "1.0.0")
        first = client.post("/api/methodologies/deactivate", json={"world": "test_mundo"})
        assert first.status_code == 200
        assert first.json()["skill_id"] is None
        again = client.post("/api/methodologies/deactivate", json={"world": "test_mundo"})
        assert again.status_code == 200
        assert again.json()["skill_id"] is None
        assert again.json()["flow_type"] == "guided-character"

    def test_deactivate_unknown_flow_422_zero_mutation(self, client, monkeypatch):
        """SR1: bogus/empty flow -> 422 on deactivate BEFORE any library call;
        the remaining slot keeps its pin (zero mutation)."""
        _principal(monkeypatch)
        self._publish(client, "skill-a", "1.0.0", "Skill A")
        self._activate(client, "skill-a", "1.0.0")
        for flow in ("bogus-flow", ""):
            resp = client.post("/api/methodologies/deactivate", json={
                "world": "test_mundo", "flow_type": flow,
            })
            assert resp.status_code == 422
            assert resp.json()["code"] == "unsupported_flow_type"
        # Zero mutation: the guided slot still holds skill-a.
        assert client.get(
            "/api/methodologies/active/test_mundo"
        ).json()["activation"]["skill_id"] == "skill-a"

    def test_deactivate_prelude_parity_401_404(self, client, monkeypatch):
        """SR1: deactivate shares the slot routes' prelude — 401 unauth,
        404 unknown world."""
        monkeypatch.setattr(api_server, "_resolve_principal", lambda request: None)
        assert client.post(
            "/api/methodologies/deactivate", json={"world": "test_mundo"}
        ).status_code == 401
        _principal(monkeypatch)
        assert client.post(
            "/api/methodologies/deactivate", json={"world": "no_such_world"}
        ).status_code == 404