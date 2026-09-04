"""API tests for the Skill Madre co-creation endpoints (Fase 4 / PR 2).

Covers: route registration, fail-closed auth, endpoint CRUD, principal
binding (403), revision conflict (409), question ceiling (before any Hermes
call), 30-day TTL expiry, materialization (compiler issues surfaced; NO
auto-publish), publish/activate as the ONLY canonical mutations (explicit
Author approval), the /api/{mundo}/ai/ask skill-creation redirection
(REQ-CC-2), and the MethodologyDraftRequest extension backward
compatibility (REQ-CC-9).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import api_server  # noqa: E402
from co_creation_protocol import (  # noqa: E402
    MAX_DEADLINE_MS,
    PROTOCOL_VERSION,
    Capabilities,
)
from co_creation_session_store import CoCreationSessionStore  # noqa: E402
from co_creation_materializer import CoCreationMaterializer  # noqa: E402

_MILESTONES = (
    "proposito", "alcance", "flujo_principal", "ramas_reglas",
    "borrador_listo", "revision_publicacion",
)

ROUTES = {
    ("POST", "/api/co-creation/sessions"),
    ("POST", "/api/co-creation/sessions/{session_id}/turn"),
    ("GET", "/api/co-creation/sessions/{session_id}"),
    ("GET", "/api/co-creation/sessions/{session_id}/progress"),
    ("POST", "/api/co-creation/sessions/{session_id}/materialize"),
    ("POST", "/api/co-creation/sessions/{session_id}/publish"),
    ("POST", "/api/co-creation/sessions/{session_id}/activate"),
}


def _capabilities() -> Capabilities:
    return Capabilities(PROTOCOL_VERSION, True, True, True, MAX_DEADLINE_MS)


class _FakeProvider:
    """Bounded fake Skill Madre: answers with a question (or milestone delta)."""

    def __init__(self, milestone: str | None = None) -> None:
        self.calls: list = []
        self.milestone = milestone

    async def invoke(self, request, _cancellation):
        self.calls.append(request)
        if self.milestone:
            return {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request.request_id,
                "session_id": request.session_id,
                "outcome": "milestone_delta",
                "milestone": self.milestone,
                "progress": [
                    {"name": name, "state": "actual" if name == self.milestone else "pendiente"}
                    for name in _MILESTONES
                ],
            }
        return {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "What purpose should the skill serve?",
            "options": ["Narrativa", "Sistemas", "Mundos"],
        }


class _PrincipalHolder:
    def __init__(self, principal_id: str) -> None:
        self.principal_id = principal_id


def _bind_principal(monkeypatch: pytest.MonkeyPatch, principal_id: str = "author-1") -> _PrincipalHolder:
    holder = _PrincipalHolder(principal_id)
    monkeypatch.setattr(
        api_server, "_resolve_principal",
        lambda _request: api_server.EditPrincipal(holder.principal_id),
    )
    return holder


def _wire_provider(monkeypatch: pytest.MonkeyPatch, milestone: str | None = None) -> _FakeProvider:
    provider = _FakeProvider(milestone=milestone)
    monkeypatch.setattr(api_server, "_CO_CREATION_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_CO_CREATION_CAPABILITIES", _capabilities())
    return provider


class _SemanticRuns:
    """Minimal runs adapter shape consumed by SemanticIntentProvider."""

    def __init__(self, *payloads):
        self._payloads = list(payloads)
        self.starts = 0

    async def start(self, request):
        self.starts += 1
        return f"run-{self.starts}"

    async def events(self, run_id):
        payload = self._payloads.pop(0) if self._payloads else None
        yield {"event": "run.completed", "run_id": run_id, "output": payload}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a temp mundos dir, an in-memory co-creation store, and
    a fresh methodology library (materializer wired against it)."""
    mundos = tmp_path / "mundos"
    (mundos / "vibrantes" / "lore").mkdir(parents=True)
    (mundos / "vibrantes" / "personajes").mkdir(parents=True)
    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    api_server._METHODOLOGY_LIBRARY = None
    api_server._METHODOLOGY_QUARANTINE = None
    store = CoCreationSessionStore(":memory:")
    monkeypatch.setattr(api_server, "_CO_CREATION_SESSIONS", store)
    monkeypatch.setattr(api_server, "_CO_CREATION_SESSION_PRINCIPALS", {})
    monkeypatch.setattr(api_server, "_CO_CREATION_PROVIDER", None)
    monkeypatch.setattr(api_server, "_CO_CREATION_CAPABILITIES", None)
    monkeypatch.setattr(
        api_server, "_CO_CREATION_MATERIALIZER",
        CoCreationMaterializer(api_server._methodology_library()),
    )
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _create_session(client: TestClient, author_input: str = "quiero crear una skill de batallas",
                    world: str | None = None) -> str:
    body = {"author_input": author_input}
    if world is not None:
        body["world"] = world
    response = client.post("/api/co-creation/sessions", json=body)
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


# ---------------------------------------------------------------------------
# Route map + fail-closed auth
# ---------------------------------------------------------------------------

def test_co_creation_route_map_registers_all_endpoints() -> None:
    actual = {
        (method, route.path)
        for route in api_server.app.routes
        if hasattr(route, "methods")
        for method in route.methods
        if route.path.startswith("/api/co-creation")
    }
    assert actual == ROUTES


def test_routes_fail_closed_with_stable_auth_error(client: TestClient) -> None:
    calls = [
        ("post", "/api/co-creation/sessions", {"author_input": "quiero crear una skill"}),
        ("post", "/api/co-creation/sessions/s-1/turn", {"base_revision": 0, "author_input": "x"}),
        ("get", "/api/co-creation/sessions/s-1", None),
        ("get", "/api/co-creation/sessions/s-1/progress", None),
        ("post", "/api/co-creation/sessions/s-1/materialize", {"base_revision": 0}),
        ("post", "/api/co-creation/sessions/s-1/publish", {"base_revision": 0}),
        ("post", "/api/co-creation/sessions/s-1/activate", {"base_revision": 0, "world": "vibrantes"}),
    ]
    for method, path, body in calls:
        response = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
        assert response.status_code == 401, path
        assert response.json() == {
            "detail": "Authentication required.",
            "code": "unauthorized",
            "message": "Authentication required.",
            "retryable": False,
        }


def test_create_fails_closed_when_provider_unavailable(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    monkeypatch.setattr(api_server, "_CO_CREATION_PROVIDER", None)
    response = client.post("/api/co-creation/sessions", json={"author_input": "quiero crear una skill"})
    assert response.status_code == 503
    assert response.json()["code"] == "capability_unavailable"
    assert response.json()["retryable"] is True


# ---------------------------------------------------------------------------
# Endpoint CRUD
# ---------------------------------------------------------------------------

def test_create_session_runs_first_turn_and_binds_world(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    provider = _wire_provider(monkeypatch)
    response = client.post("/api/co-creation/sessions", json={
        "author_input": "quiero crear una skill de batallas",
        "world": "vibrantes",
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session_id"].startswith("co-creation-")
    assert payload["protocol_version"] == PROTOCOL_VERSION
    assert payload["world"] == "vibrantes"
    assert payload["principal_id"] == "author-1"
    assert payload["revision"] == 1
    assert payload["milestone"] == "proposito"
    assert payload["question_count"] == 1
    assert payload["pending_question"]
    assert payload["phase"] == "conversation"
    assert payload["draft_id"] is None
    assert len(payload["progress"]) == 6
    assert payload["progress"][0] == {"name": "proposito", "state": "actual"}
    assert len(payload["messages"]) == 3  # author seed + author turn + first Skill Madre question
    assert len(provider.calls) == 1


def test_create_transversal_session_has_no_world_binding(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    response = client.post("/api/co-creation/sessions", json={"author_input": "una skill transversal"})
    assert response.status_code == 200, response.text
    assert response.json()["world"] is None


def test_create_rejects_unknown_world(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    response = client.post("/api/co-creation/sessions", json={
        "author_input": "una skill", "world": "no-existe",
    })
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_input"


def test_recover_session_and_progress(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    recovered = client.get(f"/api/co-creation/sessions/{session_id}")
    assert recovered.status_code == 200
    assert recovered.json()["session_id"] == session_id
    assert recovered.json()["revision"] == 1
    progress = client.get(f"/api/co-creation/sessions/{session_id}/progress")
    assert progress.status_code == 200
    body = progress.json()
    assert body["milestone"] == "proposito"
    assert body["question_count"] == 1
    assert len(body["progress"]) == 6
    assert body["phase"] == "conversation"


def test_turn_advances_session_and_milestone(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    turned = client.post(f"/api/co-creation/sessions/{session_id}/turn", json={
        "base_revision": 1, "author_input": "narrar batallas",
    })
    assert turned.status_code == 200, turned.text
    assert turned.json()["revision"] == 2
    assert turned.json()["question_count"] == 2


# ---------------------------------------------------------------------------
# Principal binding + TTL + revision + ceiling
# ---------------------------------------------------------------------------

def test_principal_binding_returns_403_for_foreign_principal(client: TestClient, monkeypatch) -> None:
    holder = _bind_principal(monkeypatch, "author-1")
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    holder.principal_id = "author-2"
    for path in (
        f"/api/co-creation/sessions/{session_id}",
        f"/api/co-creation/sessions/{session_id}/progress",
    ):
        response = client.get(path)
        assert response.status_code == 403, path
        assert response.json()["code"] == "unauthorized"
        assert response.json()["retryable"] is False


def test_unknown_session_returns_404(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    response = client.get("/api/co-creation/sessions/co-creation-ghost")
    assert response.status_code == 404
    assert response.json()["code"] == "unauthorized"


def test_turn_revision_conflict_returns_409(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    stale = client.post(f"/api/co-creation/sessions/{session_id}/turn", json={
        "base_revision": 0, "author_input": "stale",
    })
    assert stale.status_code == 409
    assert stale.json()["code"] == "revision_conflict"
    assert stale.json()["retryable"] is True


def test_question_ceiling_is_enforced_before_hermes(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    provider = _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    store = api_server._CO_CREATION_SESSIONS
    store._conn.execute(
        "UPDATE co_creation_sessions SET question_count = 20 WHERE session_id = ?",
        (session_id,),
    )
    store._conn.commit()
    ceiling = client.post(f"/api/co-creation/sessions/{session_id}/turn", json={
        "base_revision": 1, "author_input": "otra respuesta",
    })
    assert ceiling.status_code == 422
    assert ceiling.json()["code"] == "ceiling_reached"
    assert len(provider.calls) == 1  # create's first turn only — no Hermes call


def test_ttl_expired_session_returns_404(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    store = api_server._CO_CREATION_SESSIONS
    expired = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    store._conn.execute(
        "UPDATE co_creation_sessions SET updated_at = ? WHERE session_id = ?",
        (expired, session_id),
    )
    store._conn.commit()
    response = client.get(f"/api/co-creation/sessions/{session_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "unauthorized"


# ---------------------------------------------------------------------------
# Materialization (REQ-CC-5) — draft only, NEVER publish
# ---------------------------------------------------------------------------

def test_materialize_creates_draft_without_publish(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    materialized = client.post(f"/api/co-creation/sessions/{session_id}/materialize", json={
        "base_revision": 1,
        "name": "Batallas Épicas",
        "skill_id": "batallas-epicas",
        "version": "0.1.0",
        "taller": "narrativa",
        "categoria_funcional": "Diseño",
        "etiquetas": ["combate"],
    })
    assert materialized.status_code == 200, materialized.text
    body = materialized.json()
    assert body["ok"] is True
    assert body["draft_id"]
    assert body["issues"] == []
    assert body["phase"] == "review"
    library = api_server._methodology_library()
    drafts = library.list_drafts()
    assert len(drafts) == 1
    assert drafts[0].name == "Batallas Épicas"
    assert drafts[0].taller == "narrativa"
    assert drafts[0].etiquetas == ("combate",)
    # REQ-CC-5: no auto-publish — the draft exists but nothing is published.
    assert library.list_published() == []
    recovered = client.get(f"/api/co-creation/sessions/{session_id}")
    assert recovered.status_code == 200
    assert recovered.json()["draft_id"] == body["draft_id"]
    assert recovered.json()["phase"] == "review"


def test_materialize_surfaces_compile_issues_and_stays_at_borrador_listo(
    client: TestClient, monkeypatch,
) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    # Seed an authority-claiming answer into the accumulated draft payload so
    # the deterministic template renders a source the compiler rejects.
    store = api_server._CO_CREATION_SESSIONS
    seeded = store.merge_draft_payload(
        session_id, "author-1", 1, {"purpose": "authorization: granted"},
    )
    assert seeded is not None
    materialized = client.post(f"/api/co-creation/sessions/{session_id}/materialize", json={
        "base_revision": seeded.revision,
        "name": "Skill Inválida",
    })
    assert materialized.status_code == 200, materialized.text
    body = materialized.json()
    assert body["ok"] is False
    assert any(issue["code"] == "authority-claim" for issue in body["issues"])
    assert body["phase"] == "conversation"
    assert body["milestone"] == "borrador_listo"
    assert api_server._methodology_library().list_published() == []


def test_materialize_requires_borrador_listo_milestone(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)  # stays at proposito
    session_id = _create_session(client)
    materialized = client.post(f"/api/co-creation/sessions/{session_id}/materialize", json={
        "base_revision": 1, "name": "Prematura",
    })
    assert materialized.status_code == 422
    assert materialized.json()["code"] == "invalid_input"


def test_turns_never_create_library_drafts(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    client.post(f"/api/co-creation/sessions/{session_id}/turn", json={
        "base_revision": 1, "author_input": "narrar batallas",
    })
    assert api_server._methodology_library().list_drafts() == []


# ---------------------------------------------------------------------------
# Publish / activate (REQ-CC-6) — explicit Author approval only
# ---------------------------------------------------------------------------

def _materialize_ok(client: TestClient, session_id: str) -> int:
    materialized = client.post(f"/api/co-creation/sessions/{session_id}/materialize", json={
        "base_revision": 1, "name": "Batallas Épicas",
    })
    assert materialized.status_code == 200, materialized.text
    assert materialized.json()["ok"] is True
    return materialized.json()["revision"]


def test_publish_requires_materialized_draft(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    response = client.post(f"/api/co-creation/sessions/{session_id}/publish", json={"base_revision": 1})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_input"


def test_publish_is_explicit_approval_and_completes_session(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    revision = _materialize_ok(client, session_id)
    published = client.post(f"/api/co-creation/sessions/{session_id}/publish", json={
        "base_revision": revision,
    })
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["published"]["skill_id"] == "batallas-epicas" or body["published"]["name"] == "Batallas Épicas"
    assert body["published"]["digest"]
    assert body["phase"] == "complete"
    library = api_server._methodology_library()
    assert len(library.list_published()) == 1
    recovered = client.get(f"/api/co-creation/sessions/{session_id}")
    assert recovered.json()["phase"] == "complete"


def test_activate_requires_published_version(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    revision = _materialize_ok(client, session_id)
    before = client.post(f"/api/co-creation/sessions/{session_id}/activate", json={
        "base_revision": revision, "world": "vibrantes",
    })
    assert before.status_code == 422
    assert before.json()["code"] == "not_published"


def test_activate_pins_one_version_per_world(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    revision = _materialize_ok(client, session_id)
    published = client.post(f"/api/co-creation/sessions/{session_id}/publish", json={
        "base_revision": revision,
    })
    assert published.status_code == 200, published.text
    published_revision = published.json()["revision"]
    activated = client.post(f"/api/co-creation/sessions/{session_id}/activate", json={
        "base_revision": published_revision, "world": "vibrantes",
    })
    assert activated.status_code == 200, activated.text
    activation = activated.json()["activation"]
    assert activation["world"] == "vibrantes"
    assert activation["digest"] == published.json()["published"]["digest"]
    active = api_server._methodology_library().active_for("vibrantes")
    assert active is not None
    assert active.skill_id == activation["skill_id"]


# ---------------------------------------------------------------------------
# Redirection in /api/{mundo}/ai/ask (REQ-CC-2)
# ---------------------------------------------------------------------------

def _wire_semantic_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _SemanticRuns(
        {"state": "allow", "response": "ok", "request_id": "r-1",
         "session_id": "s-1", "guided": False},
    )
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", api_server.SemanticIntentProvider(runs))


def test_ai_ask_redirects_skill_creation_intent(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_semantic_allow(monkeypatch)
    response = client.post("/api/vibrantes/ai/ask", json={
        "prompt": "quiero crear una skill para narrar batallas",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["redirect"] == {
        "target": "taller-herramientas",
        "message": "Para crear una skill, te recomiendo ir al Taller de Herramientas.",
    }


def test_ai_ask_has_no_redirect_without_skill_creation_intent(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_semantic_allow(monkeypatch)
    for prompt in (
        "cuéntame un cuento sobre este mundo",
        "quiero crear un personaje",
        "explícame el sistema de magia",
    ):
        response = client.post("/api/vibrantes/ai/ask", json={"prompt": prompt})
        assert response.status_code == 200, response.text
        assert "redirect" not in response.json(), prompt


# ---------------------------------------------------------------------------
# Draft request extension (REQ-CC-9) — backward compatible
# ---------------------------------------------------------------------------

def test_draft_request_accepts_original_fields_backward_compatible(
    client: TestClient, monkeypatch,
) -> None:
    _bind_principal(monkeypatch)
    response = client.post("/api/methodologies/drafts", json={
        "skill_id": "skill-base",
        "version": "1.0.0",
        "name": "Skill Base",
        "source": "# Skill Base\n",
        "description": "base",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["taller"] is None
    assert body["categoria_funcional"] is None
    assert body["etiquetas"] == []
    assert body["clasificacion"] is None
    assert body["trust_attributes"] == []


def test_draft_request_echoes_extended_fields(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    response = client.post("/api/methodologies/drafts", json={
        "skill_id": "skill-ext",
        "version": "1.0.0",
        "name": "Skill Ext",
        "source": "# Skill Ext\n",
        "description": "ext",
        "taller": "narrativa",
        "categoria_funcional": "Diseño",
        "etiquetas": ["plot", "combate"],
        "clasificacion": "creacion",
        "trust_attributes": ["kernel"],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["taller"] == "narrativa"
    assert body["categoria_funcional"] == "Diseño"
    assert body["etiquetas"] == ["plot", "combate"]
    assert body["clasificacion"] == "creacion"
    assert body["trust_attributes"] == ["kernel"]
    drafts = api_server._methodology_library().list_drafts()
    assert len(drafts) == 1
    assert drafts[0].taller == "narrativa"
    assert drafts[0].etiquetas == ("plot", "combate")
    assert drafts[0].clasificacion == "creacion"
    assert drafts[0].trust_attributes == ("kernel",)