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

import hashlib
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
from convergence_injection import carrier_root_for, read_adjunto_bytes  # noqa: E402
from methodology_compiler import MAX_ADJUNTO_BYTES, MAX_ADJUNTOS  # noqa: E402
from methodology_compiler import AttachmentEntry  # noqa: E402

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
    ("POST", "/api/co-creation/sessions/{session_id}/trigger/approve"),
    ("POST", "/api/co-creation/sessions/{session_id}/activate"),
    ("PUT", "/api/co-creation/sessions/{session_id}/canvas"),
    ("POST", "/api/co-creation/sessions/{session_id}/validate"),
    ("GET", "/api/co-creation/sessions/{session_id}/history"),
    ("POST", "/api/co-creation/sessions/{session_id}/history/restore"),
    ("POST", "/api/co-creation/sessions/{session_id}/warnings/{idx}/status"),
    ("POST", "/api/co-creation/sessions/{session_id}/pending-questions/{idx}/status"),
    ("POST", "/api/co-creation/sessions/{session_id}/adjuntos"),
    ("POST", "/api/co-creation/derive"),
}

#: Production materializer seam captured at import, before any fixture swaps it
#: for a concrete instance. Used by the API-level regression test to drive the
#: route through the binding that ships in ``api_server`` (REQ-CC-5).
_PRODUCTION_MATERIALIZER_SEAM = api_server._CO_CREATION_MATERIALIZER


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
        ("post", "/api/co-creation/sessions/s-1/trigger/approve", {"base_revision": 0, "description": "x"}),
        ("post", "/api/co-creation/sessions/s-1/activate", {"base_revision": 0, "world": "vibrantes"}),
        ("put", "/api/co-creation/sessions/s-1/canvas", {"base_revision": 0, "payload": {}}),
        ("post", "/api/co-creation/sessions/s-1/validate", {"payload": {}}),
        ("get", "/api/co-creation/sessions/s-1/history", None),
        ("post", "/api/co-creation/sessions/s-1/history/restore", {"base_revision": 0, "revision": 1}),
        ("post", "/api/co-creation/sessions/s-1/warnings/0/status", {"base_revision": 0, "state": "resuelta"}),
        ("post", "/api/co-creation/sessions/s-1/pending-questions/0/status", {"base_revision": 0, "state": "resuelta"}),
        ("post", "/api/co-creation/derive", {"skill_id": "s", "version": "1.0.0"}),
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


def test_production_materializer_seam_is_wired() -> None:
    """REQ-CC-5 regression: the production seam must not be ``None``.

    Before the fix ``_CO_CREATION_MATERIALIZER`` was declared but never
    assigned, so ``materialize``/``derive``/``canvas``/``validate`` fail closed
    with 503 ``capability_unavailable`` in production (only tests injected the
    seam). This guards the wiring against silently regressing to ``None``.
    """
    assert api_server._CO_CREATION_MATERIALIZER is not None


def test_materialize_route_does_not_fail_closed_through_production_seam(
    client: TestClient, monkeypatch,
) -> None:
    """REQ-CC-5 regression at the API level, driven through the REAL seam.

    Re-installs the production ``_CO_CREATION_MATERIALIZER`` binding (captured
    at import, before any fixture replaces it) and drives a session at
    ``borrador_listo`` through ``POST .../materialize``. On the pre-fix code the
    production seam is ``None`` and the route returns 503
    ``capability_unavailable``; with it wired the draft is materialized.
    """
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    seam = _PRODUCTION_MATERIALIZER_SEAM
    assert seam is not None
    if isinstance(seam, api_server._LazyBinding):
        # Clear any cached resolution so the lazy seam binds to THIS test's
        # tmp library root instead of an earlier one.
        seam._value = None
    monkeypatch.setattr(api_server, "_CO_CREATION_MATERIALIZER", seam)
    session_id = _create_session(client)
    materialized = client.post(
        f"/api/co-creation/sessions/{session_id}/materialize",
        json={"base_revision": 1, "name": "Batallas Épicas", "skill_id": "batallas-epicas"},
    )
    assert materialized.status_code != 503, materialized.text
    assert materialized.json().get("code") != "capability_unavailable", materialized.text
    assert materialized.status_code == 200, materialized.text
    assert materialized.json()["ok"] is True
    assert materialized.json()["draft_id"]


def test_turns_never_create_library_drafts(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    client.post(f"/api/co-creation/sessions/{session_id}/turn", json={
        "base_revision": 1, "author_input": "narrar batallas",
    })
    assert api_server._methodology_library().list_drafts() == []


# ---------------------------------------------------------------------------
# TW12 canvas data layer (Phase 1 / PR 1) — canvas, validate, history, restore
# ---------------------------------------------------------------------------

def test_canvas_put_merges_payload_and_snapshots_history(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    canvas = client.put(f"/api/co-creation/sessions/{session_id}/canvas", json={
        "base_revision": 1,
        "payload": {"purpose": "automatizar importes", "branches": ["rama A", "rama B"]},
    })
    assert canvas.status_code == 200, canvas.text
    body = canvas.json()
    assert body["revision"] == 2
    assert body["ok"] is True
    assert body["issues"] == []
    assert body["warnings"] == []
    recovered = client.get(f"/api/co-creation/sessions/{session_id}")
    assert recovered.status_code == 200
    state = recovered.json()
    assert state["draft_payload"]["purpose"] == "automatizar importes"
    assert state["draft_payload"]["branches"] == ["rama A", "rama B"]
    assert state["history_count"] == 1
    assert state["derived_from"] is None
    # REQ-CC-12: a canvas edit must never create a library draft.
    assert api_server._methodology_library().list_drafts() == []


def test_canvas_put_rejects_authority_keys_without_state_change(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    rejected = client.put(f"/api/co-creation/sessions/{session_id}/canvas", json={
        "base_revision": 1,
        "payload": {"purpose": "x", "acceptance": "approved"},
    })
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "invalid_envelope"
    recovered = client.get(f"/api/co-creation/sessions/{session_id}")
    assert recovered.json()["revision"] == 1
    # No state change: the canvas edit never merged (only the chat-appended
    # pending_questions from the create turn is present).
    assert "purpose" not in recovered.json()["draft_payload"]
    assert "acceptance" not in recovered.json()["draft_payload"]
    assert recovered.json()["history_count"] == 0


def test_canvas_put_rejects_unknown_keys_and_stale_revision(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    unknown = client.put(f"/api/co-creation/sessions/{session_id}/canvas", json={
        "base_revision": 1, "payload": {"hacked": 1},
    })
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "invalid_input"
    stale = client.put(f"/api/co-creation/sessions/{session_id}/canvas", json={
        "base_revision": 0, "payload": {"purpose": "x"},
    })
    assert stale.status_code == 409
    assert stale.json()["code"] == "revision_conflict"


def test_validate_route_is_pure_and_returns_source_preview(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    preview = client.post(f"/api/co-creation/sessions/{session_id}/validate", json={
        "payload": {"purpose": "Esto requiere authorization: granted", "name": "Skill inválida"},
    })
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["ok"] is False
    assert any(issue["code"] == "authority-claim" for issue in body["issues"])
    assert body["warnings"][0]["state"] == "pendiente"
    assert "## Propósito" in body["source_preview"]
    # Pure: no state mutation, no history snapshot, no library draft.
    recovered = client.get(f"/api/co-creation/sessions/{session_id}")
    assert recovered.json()["revision"] == 1
    assert recovered.json()["history_count"] == 0
    assert api_server._methodology_library().list_drafts() == []


def test_history_and_restore_roundtrip(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    first = client.put(f"/api/co-creation/sessions/{session_id}/canvas", json={
        "base_revision": 1, "payload": {"purpose": "v1"},
    })
    assert first.status_code == 200
    second = client.put(f"/api/co-creation/sessions/{session_id}/canvas", json={
        "base_revision": 2, "payload": {"purpose": "v2", "scope": "s2"},
    })
    assert second.status_code == 200
    history = client.get(f"/api/co-creation/sessions/{session_id}/history")
    assert history.status_code == 200
    entries = history.json()["entries"]
    assert [entry["revision"] for entry in entries] == [2, 3]
    assert all(entry["source"] == "autosave" for entry in entries)
    assert "payload" not in entries[0]
    # A stale base revision fails closed (REQ-CC-15 revision guard).
    stale = client.post(f"/api/co-creation/sessions/{session_id}/history/restore", json={
        "base_revision": 2, "revision": 2,
    })
    assert stale.status_code == 409
    restored = client.post(f"/api/co-creation/sessions/{session_id}/history/restore", json={
        "base_revision": 3, "revision": 2,
    })
    assert restored.status_code == 200, restored.text
    assert restored.json()["revision"] == 4
    # The restored payload is the full snapshot: the chat-appended
    # pending_questions survive alongside the restored purpose.
    assert restored.json()["payload"]["purpose"] == "v1"
    assert "scope" not in restored.json()["payload"]
    # An unknown target snapshot fails closed.
    ghost = client.post(f"/api/co-creation/sessions/{session_id}/history/restore", json={
        "base_revision": 4, "revision": 99,
    })
    assert ghost.status_code == 422
    assert ghost.json()["code"] == "invalid_input"


def test_warning_status_route_transitions_and_persists(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    # A canvas edit whose CONTENT triggers a compiler authority-claim marker
    # seeds a Pendiente warning (content marker, not an envelope key).
    canvas = client.put(f"/api/co-creation/sessions/{session_id}/canvas", json={
        "base_revision": 1,
        "payload": {"purpose": "Esto requiere authorization: granted"},
    })
    assert canvas.status_code == 200, canvas.text
    body = canvas.json()
    assert body["ok"] is False
    assert len(body["warnings"]) == 1
    assert body["warnings"][0]["state"] == "pendiente"
    assert body["warnings"][0]["code"] == "authority-claim"
    # The Author transitions Pendiente -> Resuelta.
    resolved = client.post(f"/api/co-creation/sessions/{session_id}/warnings/0/status", json={
        "base_revision": 2, "state": "resuelta",
    })
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["warnings"][0]["state"] == "resuelta"
    # Invalid transitions fail closed (no re-open).
    invalid = client.post(f"/api/co-creation/sessions/{session_id}/warnings/0/status", json={
        "base_revision": 3, "state": "pendiente",
    })
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_input"
    # The Author decision persists across reloads (no auto-clear, REQ-CC-13).
    recovered = client.get(f"/api/co-creation/sessions/{session_id}")
    assert recovered.json()["warnings"][0]["state"] == "resuelta"


def test_pending_question_status_route_is_author_only(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    # The chat's question is chat-appended to pending_questions (REQ-CC-14).
    recovered = client.get(f"/api/co-creation/sessions/{session_id}")
    questions = recovered.json()["draft_payload"]["pending_questions"]
    assert len(questions) == 1
    assert questions[0]["state"] == "pendiente"
    accepted = client.post(
        f"/api/co-creation/sessions/{session_id}/pending-questions/0/status",
        json={"base_revision": 1, "state": "aceptada_por_autor"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["pending_questions"][0]["state"] == "aceptada_por_autor"
    # Accepted entries are never re-opened.
    reopened = client.post(
        f"/api/co-creation/sessions/{session_id}/pending-questions/0/status",
        json={"base_revision": 2, "state": "pendiente"},
    )
    assert reopened.status_code == 422
    assert reopened.json()["code"] == "invalid_input"


# ---------------------------------------------------------------------------
# Publish / activate (REQ-CC-6) — explicit Author approval only
# ---------------------------------------------------------------------------

def _approve_session_trigger(client: TestClient, session_id: str) -> None:
    """Etapa 2: record the session draft's trigger approval at the library
    boundary, using the value the session's publish will use so the gate's
    digest match holds. The HTTP approve route itself is covered in
    ``test_api_server.py``.
    """
    state = client.get(f"/api/co-creation/sessions/{session_id}").json()
    draft_id = state["draft_id"]
    assert draft_id is not None, session_id
    payload = state.get("draft_payload") or {}
    description = payload.get("description") or "Approved test trigger"
    api_server._methodology_library().approve_trigger(draft_id, description, "author-1")


def _materialize_ok(client: TestClient, session_id: str) -> int:
    materialized = client.post(f"/api/co-creation/sessions/{session_id}/materialize", json={
        "base_revision": 1, "name": "Batallas Épicas",
    })
    assert materialized.status_code == 200, materialized.text
    assert materialized.json()["ok"] is True
    _approve_session_trigger(client, session_id)
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
# TW13/TW14 (Phase 2 / PR 2) — derivation + server-injected provenance
# ---------------------------------------------------------------------------

def _publish_skill(
    *,
    skill_id: str = "skill-oficial",
    version: str = "1.0.0",
    name: str = "Skill Oficial",
    source: str | None = None,
    clasificacion: str | None = "Oficiales",
    trust_attributes: tuple[str, ...] = ("verified",),
    adjuntos: tuple[AttachmentEntry, ...] = (),
) -> None:
    library = api_server._methodology_library()
    draft_id = library.create_draft(
        skill_id=skill_id,
        version=version,
        name=name,
        source=source or f"# {name}\n\n## Propósito\nPropósito base.\n",
        description="Descripción oficial.",
        clasificacion=clasificacion,
        trust_attributes=trust_attributes,
        adjuntos=adjuntos,
    )
    library.approve_trigger(draft_id, "Descripción oficial.", "author-1")
    library.publish(draft_id)


def _template_source(name: str, purpose: str = "Propósito base.") -> str:
    """A template-shaped source so the adaptation seed parses back."""
    return (
        f"# {name}\nDescripción oficial.\n\n"
        f"## Propósito\n{purpose}\n\n"
        "## Alcance\nAlcance base. (transversal)\n\n"
        "## Flujo principal\nFlujo base.\n\n"
        "## Ramas y reglas\n- rama base\n- regla base\n"
    )


def test_derive_creates_derived_draft_with_server_injected_provenance(
    client: TestClient, monkeypatch,
) -> None:
    _bind_principal(monkeypatch)
    _publish_skill(source=_template_source("Skill Oficial"))
    # REQ-CC-20: a client-supplied derived_from is IGNORED — the server
    # injects its own identity read from the PUBLISHED record.
    derived = client.post("/api/co-creation/derive", json={
        "skill_id": "skill-oficial",
        "version": "1.0.0",
        "derived_from": {"skill_id": "evil-skill", "version": "9.9.9"},
    })
    assert derived.status_code == 200, derived.text
    body = derived.json()
    assert body["session_id"]
    assert body["draft_id"]
    assert body["derived_from"] == {"skill_id": "skill-oficial", "version": "1.0.0"}
    library = api_server._methodology_library()
    draft = library.get_draft(body["draft_id"])
    assert draft is not None
    assert draft.parent_skill_id == "skill-oficial"
    assert draft.parent_version == "1.0.0"
    assert draft.version == "1.0.1"  # version+1 policy (REQ-CC-19)
    # The adaptation session is bound to the draft and exposes provenance.
    session = client.get(f"/api/co-creation/sessions/{body['session_id']}")
    assert session.status_code == 200, session.text
    state = session.json()
    assert state["draft_id"] == body["draft_id"]
    assert state["derived_from"] == {"skill_id": "skill-oficial", "version": "1.0.0"}
    # REQ-CC-17: the canvas payload is seeded from the original's sections.
    assert state["draft_payload"]["purpose"] == "Propósito base."
    assert state["draft_payload"]["branches"] == ["rama base", "regla base"]


def _pins() -> list[dict]:
    """Two deterministic pins in the canvas ``adjuntos`` wire shape."""
    first, second = b"# Ejemplar uno\n", b"# Ejemplar dos\n"
    return [
        {"path": "ej01.md", "sha256": hashlib.sha256(first).hexdigest(),
         "bytes": len(first), "nivel": "1º"},
        {"path": "ej02.md", "sha256": hashlib.sha256(second).hexdigest(),
         "bytes": len(second), "nivel": "2º"},
    ]


def _pin_entries(pins: list[dict]) -> tuple[AttachmentEntry, ...]:
    return tuple(AttachmentEntry(**pin) for pin in pins)


def test_derive_preserves_author_exemplar_pins(client: TestClient, monkeypatch) -> None:
    """EP-1/DP-1: an author original's N pins reach the derived draft + canvas."""
    _bind_principal(monkeypatch)
    pins = _pins()
    _publish_skill(
        source=_template_source("Skill Oficial"), adjuntos=_pin_entries(pins),
    )
    derived = client.post("/api/co-creation/derive", json={
        "skill_id": "skill-oficial", "version": "1.0.0",
    })
    assert derived.status_code == 200, derived.text
    body = derived.json()
    draft = api_server._methodology_library().get_draft(body["draft_id"])
    assert draft is not None
    assert [entry.as_dict() for entry in draft.adjuntos] == pins
    recovered = client.get(f"/api/co-creation/sessions/{body['session_id']}").json()
    assert recovered["draft_payload"]["adjuntos"] == pins


def test_derive_preserves_seeded_exemplar_pins(client: TestClient, monkeypatch) -> None:
    """EP-1: a seeded (fundacional) original's pins are preserved too."""
    _bind_principal(monkeypatch)
    pins = _pins()
    _publish_skill(
        source=_template_source("Skill Oficial"),
        trust_attributes=("fundacional", "verified"),
        adjuntos=_pin_entries(pins),
    )
    derived = client.post("/api/co-creation/derive", json={
        "skill_id": "skill-oficial", "version": "1.0.0",
    })
    assert derived.status_code == 200, derived.text
    body = derived.json()
    draft = api_server._methodology_library().get_draft(body["draft_id"])
    assert draft is not None
    assert [entry.as_dict() for entry in draft.adjuntos] == pins
    # S9 still holds: the derived fork is demoted despite the preserved pins.
    assert draft.clasificacion == "Personalizadas"
    assert "fundacional" not in draft.trust_attributes
    recovered = client.get(f"/api/co-creation/sessions/{body['session_id']}").json()
    assert recovered["draft_payload"]["adjuntos"] == pins


def test_derive_gate_oficiales_requires_derivation_and_blocks_in_place_edit(
    client: TestClient, monkeypatch,
) -> None:
    """REQ-CC-16: Oficiales ⇒ derivation required; in-place replacement of a
    published version is impossible (immutability)."""
    _bind_principal(monkeypatch)
    _publish_skill(source=_template_source("Skill Oficial"))
    # The protected path IS derivation — it succeeds and records provenance.
    derived = client.post("/api/co-creation/derive", json={
        "skill_id": "skill-oficial", "version": "1.0.0",
    })
    assert derived.status_code == 200, derived.text
    assert derived.json()["derived_from"] == {"skill_id": "skill-oficial", "version": "1.0.0"}
    # In-place edit attempt: a same-version draft cannot replace the published
    # Oficiales record — publish fails closed as immutable (409).
    draft = client.post("/api/methodologies/drafts", json={
        "skill_id": "skill-oficial", "version": "1.0.0",
        "name": "Skill Oficial (editada)",
        "source": "# Skill Oficial (editada)\n",
    })
    assert draft.status_code == 200, draft.text
    published = client.post(f"/api/methodologies/drafts/{draft.json()['draft_id']}/publish")
    assert published.status_code == 409
    assert published.json()["code"] == "already_published"
    # The original is untouched.
    original = api_server._methodology_library().get_published("skill-oficial", "1.0.0")
    assert original is not None
    assert original.name == "Skill Oficial"


def test_derive_allows_non_protected_skills(client: TestClient, monkeypatch) -> None:
    """REQ-CC-16: non-protected skills MAY be derived (optional path)."""
    _bind_principal(monkeypatch)
    _publish_skill(skill_id="skill-libre", clasificacion="Personalizadas")
    derived = client.post("/api/co-creation/derive", json={
        "skill_id": "skill-libre", "version": "1.0.0",
    })
    assert derived.status_code == 200, derived.text
    assert derived.json()["derived_from"] == {"skill_id": "skill-libre", "version": "1.0.0"}


def test_derive_unpublished_skill_fails_closed(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    derived = client.post("/api/co-creation/derive", json={
        "skill_id": "skill-fantasma", "version": "9.9.9",
    })
    assert derived.status_code == 422
    assert derived.json()["code"] == "invalid_input"
    # Nothing created.
    assert api_server._methodology_library().list_drafts() == []


def test_derive_rejects_unavailable_world(client: TestClient, monkeypatch) -> None:
    _bind_principal(monkeypatch)
    _publish_skill(source=_template_source("Skill Oficial"))
    derived = client.post("/api/co-creation/derive", json={
        "skill_id": "skill-oficial", "version": "1.0.0", "world": "mundo-inexistente",
    })
    assert derived.status_code == 422
    assert derived.json()["code"] == "invalid_input"


def test_derived_publish_auto_versions_and_preserves_original(
    client: TestClient, monkeypatch,
) -> None:
    """REQ-CC-19: derived publish → S@(V+1) with provenance; S@V intact."""
    _bind_principal(monkeypatch)
    _publish_skill(source=_template_source("Skill Oficial"))
    library = api_server._methodology_library()
    original = library.get_published("skill-oficial", "1.0.0")
    assert original is not None
    derived = client.post("/api/co-creation/derive", json={
        "skill_id": "skill-oficial", "version": "1.0.0",
    })
    assert derived.status_code == 200
    session_id = derived.json()["session_id"]
    # Canvas edit on the adaptation session (revision 0 -> 1).
    canvas = client.put(f"/api/co-creation/sessions/{session_id}/canvas", json={
        "base_revision": 0,
        "payload": {"purpose": "Propósito adaptado.", "scope": "Alcance adaptado."},
    })
    assert canvas.status_code == 200, canvas.text
    assert canvas.json()["revision"] == 1
    # Publish: the POST is the Author's explicit approval.
    _approve_session_trigger(client, session_id)
    published = client.post(f"/api/co-creation/sessions/{session_id}/publish", json={
        "base_revision": 1,
    })
    assert published.status_code == 200, published.text
    assert published.json()["published"]["version"] == "1.0.1"
    # New published version carries provenance + the canvas content.
    new_version = library.get_published("skill-oficial", "1.0.1")
    assert new_version is not None
    assert new_version.parent_skill_id == "skill-oficial"
    assert new_version.parent_version == "1.0.0"
    assert "Propósito adaptado." in new_version.source
    # The original is untouched (immutability preserved).
    after = library.get_published("skill-oficial", "1.0.0")
    assert after is not None
    assert after.source == original.source
    assert after.digest == original.digest
    assert after.parent_skill_id is None


def test_derived_session_publish_without_edits_preserves_original_content(
    client: TestClient, monkeypatch,
) -> None:
    """Derive → publish with NO canvas edits: S@(V+1) still carries the
    original's content (the seeded payload round-trips through the template)."""
    _bind_principal(monkeypatch)
    _publish_skill(source=_template_source("Skill Oficial"))
    derived = client.post("/api/co-creation/derive", json={
        "skill_id": "skill-oficial", "version": "1.0.0",
    })
    assert derived.status_code == 200
    session_id = derived.json()["session_id"]
    _approve_session_trigger(client, session_id)
    published = client.post(f"/api/co-creation/sessions/{session_id}/publish", json={
        "base_revision": 0,
    })
    assert published.status_code == 200, published.text
    new_version = api_server._methodology_library().get_published("skill-oficial", "1.0.1")
    assert new_version is not None
    assert "Propósito base." in new_version.source
    assert "- rama base" in new_version.source


def test_published_detail_route_returns_source_and_provenance(
    client: TestClient, monkeypatch,
) -> None:
    _bind_principal(monkeypatch)
    _publish_skill(source=_template_source("Skill Oficial"))
    detail = client.get("/api/methodologies/published/skill-oficial/1.0.0")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["skill_id"] == "skill-oficial"
    assert body["version"] == "1.0.0"
    assert "## Propósito" in body["source"]  # inventory omits source; detail has it
    assert body["clasificacion"] == "Oficiales"
    assert body["parent_skill_id"] is None
    assert body["parent_version"] is None
    # After a derived publish, the detail exposes the provenance (REQ-CC-21).
    library = api_server._methodology_library()
    derived_id = library.create_derived_draft(
        "skill-oficial", "1.0.0", seed_source=_template_source("Skill Oficial"),
        name="Skill Oficial",
    )
    derived_draft = library.get_draft(derived_id)
    library.approve_trigger(derived_id, derived_draft.description, "author-1")
    library.publish(derived_id)
    derived_detail = client.get("/api/methodologies/published/skill-oficial/1.0.1")
    assert derived_detail.status_code == 200
    assert derived_detail.json()["parent_skill_id"] == "skill-oficial"
    assert derived_detail.json()["parent_version"] == "1.0.0"
    # Missing version -> 404; unauthenticated -> 401.
    missing = client.get("/api/methodologies/published/skill-oficial/9.9.9")
    assert missing.status_code == 404


def test_list_routes_expose_derived_provenance(
    client: TestClient, monkeypatch,
) -> None:
    """REQ-CC-21: when the inventory/status list a derived published version,
    the list items include the server-injected provenance (read from the
    stored published record, never from client input)."""
    _bind_principal(monkeypatch)
    _publish_skill(source=_template_source("Skill Oficial"))
    derived = client.post("/api/co-creation/derive", json={
        "skill_id": "skill-oficial", "version": "1.0.0",
    })
    assert derived.status_code == 200, derived.text
    session_id = derived.json()["session_id"]
    _approve_session_trigger(client, session_id)
    published = client.post(f"/api/co-creation/sessions/{session_id}/publish", json={
        "base_revision": 0,
    })
    assert published.status_code == 200, published.text
    assert published.json()["published"]["version"] == "1.0.1"
    # Inventory (public list) exposes provenance on the derived item.
    inventory = client.get("/api/methodologies/inventory")
    assert inventory.status_code == 200, inventory.text
    items = {
        item["skill_id"] + "@" + item["version"]: item
        for item in inventory.json()["items"]
    }
    derived_item = items["skill-oficial@1.0.1"]
    assert derived_item["parent_skill_id"] == "skill-oficial"
    assert derived_item["parent_version"] == "1.0.0"
    # The original (never-derived) item carries explicit null provenance.
    assert items["skill-oficial@1.0.0"]["parent_skill_id"] is None
    assert items["skill-oficial@1.0.0"]["parent_version"] is None
    # Status (auth-required) exposes the same provenance on its list.
    status = client.get("/api/methodologies/status")
    assert status.status_code == 200, status.text
    status_items = {
        item["skill_id"] + "@" + item["version"]: item
        for item in status.json()["published"]
    }
    derived_entry = status_items["skill-oficial@1.0.1"]
    assert derived_entry["parent_skill_id"] == "skill-oficial"
    assert derived_entry["parent_version"] == "1.0.0"
    assert status_items["skill-oficial@1.0.0"]["parent_skill_id"] is None
    assert status_items["skill-oficial@1.0.0"]["parent_version"] is None


def test_published_detail_route_fails_closed_without_auth(client: TestClient) -> None:
    response = client.get("/api/methodologies/published/skill-oficial/1.0.0")
    assert response.status_code == 401


def test_canvas_put_rejects_nested_authority_keys_without_state_change(
    client: TestClient, monkeypatch,
) -> None:
    """REQ-CC-7: authority keys nested (depth <= 4) inside a canvas payload are
    envelope violations — rejected with zero state changes."""
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    rejected = client.put(f"/api/co-creation/sessions/{session_id}/canvas", json={
        "base_revision": 1,
        "payload": {"purpose": "x", "meta": {"deep": {"target": "y"}}},
    })
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "invalid_envelope"
    recovered = client.get(f"/api/co-creation/sessions/{session_id}")
    assert recovered.json()["revision"] == 1
    assert "purpose" not in recovered.json()["draft_payload"]
    assert recovered.json()["history_count"] == 0


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


def test_draft_request_rejects_claimed_trust_fields(client: TestClient, monkeypatch) -> None:
    """S7: clasificacion/trust_attributes are server-derived — a client claim
    is 400-rejected before any draft exists (old passthrough removed)."""
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
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "client_trust_claim_not_allowed"
    drafts = api_server._methodology_library().list_drafts()
    assert drafts == []


# ---------------------------------------------------------------------------
# S2 — session staging upload (AE-1 / AE-2)
# ---------------------------------------------------------------------------


def _upload(client: TestClient, session_id: str, filename: str, data: bytes,
            nivel: str = "1º"):
    return client.post(
        f"/api/co-creation/sessions/{session_id}/adjuntos",
        files={"file": (filename, data, "text/markdown")},
        data={"nivel": nivel},
    )


def _staging_dir(tmp_path: Path, session_id: str) -> Path:
    return tmp_path / "data" / "methodology" / "staging" / session_id


def test_upload_stages_bytes_and_returns_server_computed_pin(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """AE-1 happy path: the pin is server-computed and bytes stay staged."""
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    data = b"# Ejemplar\n\nContenido.\n"

    response = _upload(client, session_id, "ejemplo.md", data)

    assert response.status_code == 200, response.text
    assert response.json() == {"adjunto": {
        "path": "ejemplo.md",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "nivel": "1º",
    }}
    staged = _staging_dir(tmp_path, session_id)
    assert (staged / "ejemplo.md").read_bytes() == data
    # Nothing moved: attachments/ is untouched by staging.
    assert not (tmp_path / "data" / "methodology" / "attachments").exists()


@pytest.mark.parametrize("filename", [
    "../escape.md", "/abs/x.md", "mundos/x.md", "x.txt",
])
def test_upload_rejects_path_escape_with_zero_mutation(
    client: TestClient, monkeypatch, tmp_path: Path, filename: str,
) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)

    response = _upload(client, session_id, filename, b"# x\n")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_input"
    assert not _staging_dir(tmp_path, session_id).exists()


def test_upload_rejects_oversize_with_zero_mutation(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)

    response = _upload(client, session_id, "big.md", b"x" * (MAX_ADJUNTO_BYTES + 1))

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "attachment_limit_reached"
    assert not _staging_dir(tmp_path, session_id).exists()


def test_upload_rejects_invalid_nivel(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)

    response = _upload(client, session_id, "a.md", b"# x\n", nivel="   ")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_input"
    assert not _staging_dir(tmp_path, session_id).exists()


def test_upload_rejects_empty_file(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)

    response = _upload(client, session_id, "empty.md", b"")

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "invalid_input"


def test_upload_rejects_ninth_attachment(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    staged = _staging_dir(tmp_path, session_id)
    staged.mkdir(parents=True)
    for index in range(MAX_ADJUNTOS):
        (staged / f"f{index}.md").write_bytes(b"# staged\n")

    response = _upload(client, session_id, "one-more.md", b"# x\n")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "attachment_limit_reached"
    assert len(list(staged.glob("*.md"))) == MAX_ADJUNTOS


def test_upload_rejects_duplicate_basename_as_conflict(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    first = _upload(client, session_id, "a.md", b"# original\n")
    assert first.status_code == 200, first.text

    conflict = _upload(client, session_id, "a.md", b"# other\n")

    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "attachment_conflict"
    assert (_staging_dir(tmp_path, session_id) / "a.md").read_bytes() == b"# original\n"


def test_upload_foreign_principal_fails_closed_with_403(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    holder = _bind_principal(monkeypatch, "author-1")
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    holder.principal_id = "author-2"

    response = _upload(client, session_id, "a.md", b"# x\n")

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "unauthorized"
    assert not _staging_dir(tmp_path, session_id).exists()
    # The owning principal's session is untouched.
    assert set(_staging_dir(tmp_path, session_id).glob("*.md")) == set()


def test_upload_without_principal_is_401(client: TestClient, tmp_path: Path) -> None:
    session_id = "co-creation-ghost"

    response = _upload(client, session_id, "a.md", b"# x\n")

    assert response.status_code == 401, response.text
    assert response.json()["code"] == "unauthorized"
    assert not _staging_dir(tmp_path, session_id).exists()


# ---------------------------------------------------------------------------
# S3 — materialize threads adjuntos + moves staged bytes (REQ-CC-25 / AE-3)
# ---------------------------------------------------------------------------


def _attachments_dir(tmp_path: Path, skill_id: str) -> Path:
    return tmp_path / "data" / "methodology" / "attachments" / skill_id


def test_materialize_threads_adjuntos_and_moves_staged_bytes(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """AE-3: materialize moves pinned bytes and persists the pins on the draft."""
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    data = b"# Ejemplar\n\nContenido.\n"
    uploaded = _upload(client, session_id, "ejemplo.md", data, nivel="1º")
    assert uploaded.status_code == 200, uploaded.text
    pin = uploaded.json()["adjunto"]

    materialized = client.post(
        f"/api/co-creation/sessions/{session_id}/materialize",
        json={
            "base_revision": 1,
            "name": "Batallas Épicas",
            "skill_id": "batallas-epicas",
            "version": "0.1.0",
            "adjuntos": [pin],
        },
    )

    assert materialized.status_code == 200, materialized.text
    body = materialized.json()
    assert body["ok"] is True
    assert (_attachments_dir(tmp_path, "batallas-epicas")
            / "ejemplo.md").read_bytes() == data
    assert not _staging_dir(tmp_path, session_id).exists()
    draft = api_server._methodology_library().get_draft(body["draft_id"])
    assert [entry.as_dict() for entry in draft.adjuntos] == [pin]
    recovered = client.get(f"/api/co-creation/sessions/{session_id}").json()
    assert recovered["draft_payload"]["adjuntos"] == [pin]


def test_materialize_adjuntos_survive_publish(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """REQ-CC-25: the published record carries the same pins and echoes them."""
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    data = b"# Ejemplar\n"
    pin = _upload(client, session_id, "ejemplo.md", data).json()["adjunto"]

    materialized = client.post(
        f"/api/co-creation/sessions/{session_id}/materialize",
        json={
            "base_revision": 1, "name": "Batallas Épicas",
            "skill_id": "batallas-epicas", "version": "0.1.0", "adjuntos": [pin],
        },
    ).json()
    _approve_session_trigger(client, session_id)
    published = client.post(
        f"/api/co-creation/sessions/{session_id}/publish",
        json={"base_revision": materialized["revision"]},
    )
    assert published.status_code == 200, published.text

    detail = client.get("/api/methodologies/published/batallas-epicas/0.1.0")
    assert detail.status_code == 200, detail.text
    assert detail.json()["adjuntos"] == [pin]


def test_materialize_adjuntos_missing_bytes_fails_closed(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """AE-3: a pin without staged bytes fails closed — no draft, no tree."""
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    phantom = {"path": "fantasma.md", "sha256": "a" * 64, "bytes": 10, "nivel": "1º"}

    response = client.post(
        f"/api/co-creation/sessions/{session_id}/materialize",
        json={
            "base_revision": 1, "name": "Sin bytes",
            "skill_id": "sin-bytes", "adjuntos": [phantom],
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "attachment_unavailable"
    assert api_server._methodology_library().list_drafts() == []
    assert not (tmp_path / "data" / "methodology" / "attachments").exists()


def test_materialize_without_adjuntos_is_unchanged(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """Backward compatible: no pins -> no attachments dir, empty draft pins."""
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)

    materialized = client.post(
        f"/api/co-creation/sessions/{session_id}/materialize",
        json={"base_revision": 1, "name": "Sin ejemplares", "skill_id": "sin-ejemplares"},
    )

    assert materialized.status_code == 200, materialized.text
    draft = api_server._methodology_library().get_draft(materialized.json()["draft_id"])
    assert draft.adjuntos == ()
    assert not (tmp_path / "data" / "methodology" / "attachments").exists()


def test_validate_preview_threads_adjuntos_without_draft_or_move(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """REQ-CC-25 pre-materialize preview: pins compile, nothing moves/creates."""
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    data = b"# Ejemplar\n"
    pin = _upload(client, session_id, "ejemplo.md", data).json()["adjunto"]

    response = client.post(
        f"/api/co-creation/sessions/{session_id}/validate",
        json={"payload": {"name": "Vista previa", "adjuntos": [pin]}},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["issues"] == []
    assert api_server._methodology_library().list_drafts() == []
    assert (_staging_dir(tmp_path, session_id) / "ejemplo.md").read_bytes() == data


def test_canvas_put_accepts_and_persists_adjuntos(
    client: TestClient, monkeypatch,
) -> None:
    """REQ-CC-11: the additive adjuntos section merges through the canvas."""
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)
    pin = {"path": "ejemplo.md", "sha256": "b" * 64, "bytes": 9, "nivel": "1º"}

    response = client.put(
        f"/api/co-creation/sessions/{session_id}/canvas",
        json={"base_revision": 1, "payload": {"adjuntos": [pin]}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    recovered = client.get(f"/api/co-creation/sessions/{session_id}").json()
    assert recovered["draft_payload"]["adjuntos"] == [pin]


def test_canvas_put_rejects_bad_adjuntos_shape(
    client: TestClient, monkeypatch,
) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch)
    session_id = _create_session(client)

    response = client.put(
        f"/api/co-creation/sessions/{session_id}/canvas",
        json={"base_revision": 1, "payload": {"adjuntos": "not-a-list"}},
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_input"


# ---------------------------------------------------------------------------
# U2 — source-independent publish sync (EP-3..EP-7 / DP-2)
# ---------------------------------------------------------------------------


def _materialized_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, skill_id: str,
) -> tuple[str, int, str]:
    """Start a ``borrador_listo`` session and materialize an empty draft."""
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    materialized = client.post(
        f"/api/co-creation/sessions/{session_id}/materialize",
        json={"base_revision": 1, "name": "Batallas Épicas", "skill_id": skill_id},
    )
    assert materialized.status_code == 200, materialized.text
    assert materialized.json()["ok"] is True
    _approve_session_trigger(client, session_id)
    return session_id, materialized.json()["revision"], materialized.json()["draft_id"]


def _publish_pins(client: TestClient, session_id: str, revision: int, adjuntos: list[dict]):
    """PUT the canvas ``adjuntos`` then publish at the resulting revision."""
    canvas = client.put(
        f"/api/co-creation/sessions/{session_id}/canvas",
        json={"base_revision": revision, "payload": {"adjuntos": adjuntos}},
    )
    assert canvas.status_code == 200, canvas.text
    _approve_session_trigger(client, session_id)
    return client.post(
        f"/api/co-creation/sessions/{session_id}/publish",
        json={"base_revision": canvas.json()["revision"]},
    )


def _write_carrier(tmp_path: Path, skill_id: str, name: str, data: bytes) -> None:
    carrier = _attachments_dir(tmp_path, skill_id)
    carrier.mkdir(parents=True, exist_ok=True)
    (carrier / name).write_bytes(data)


def test_publish_syncs_exemplars_when_source_is_unchanged(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """DP-2/EP-3: an exemplar-only edit publishes the reduced pins with the
    derived source unchanged."""
    _bind_principal(monkeypatch)
    pins = _pins()
    for pin, raw in zip(pins, (b"# Ejemplar uno\n", b"# Ejemplar dos\n")):
        _write_carrier(tmp_path, "skill-oficial", pin["path"], raw)
    _publish_skill(source=_template_source("Skill Oficial"), adjuntos=_pin_entries(pins))
    derived = client.post("/api/co-creation/derive", json={
        "skill_id": "skill-oficial", "version": "1.0.0",
    })
    assert derived.status_code == 200, derived.text
    session_id, draft_id = derived.json()["session_id"], derived.json()["draft_id"]
    library = api_server._methodology_library()
    source_before = library.get_draft(draft_id).source
    published = _publish_pins(client, session_id, 0, [pins[0]])
    assert published.status_code == 200, published.text
    record = library.get_published("skill-oficial", "1.0.1")
    assert [entry.as_dict() for entry in record.adjuntos] == [pins[0]]
    assert record.source == source_before


def test_publish_without_adjuntos_key_leaves_pins_untouched(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """EP-3: a payload without the key never touches the draft's pins."""
    session_id, revision, draft_id = _materialized_session(client, monkeypatch, "sin-key")
    library = api_server._methodology_library()
    library.update_draft(draft_id, adjuntos=_pin_entries(_pins()))
    published = client.post(f"/api/co-creation/sessions/{session_id}/publish",
                            json={"base_revision": revision})
    assert published.status_code == 200, published.text
    record = library.get_published("sin-key", published.json()["published"]["version"])
    assert [entry.as_dict() for entry in record.adjuntos] == _pins()


def test_publish_materializes_a_new_basename_verifiable(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """EP-4: a pending pinned exemplar moves into the carrier root and verifies."""
    session_id, revision, _ = _materialized_session(client, monkeypatch, "nuevo-skill")
    data = b"# Nuevo ejemplar\n"
    pin = _upload(client, session_id, "nuevo.md", data).json()["adjunto"]
    published = _publish_pins(client, session_id, revision, [pin])
    assert published.status_code == 200, published.text
    assert (_attachments_dir(tmp_path, "nuevo-skill") / "nuevo.md").read_bytes() == data
    root = carrier_root_for("nuevo-skill", project_root=tmp_path)
    assert read_adjunto_bytes(root, AttachmentEntry(**pin)) == data


def test_publish_refuses_same_basename_byte_drift(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """EP-5: same-basename byte drift is 422; the parent's pin still resolves."""
    _bind_principal(monkeypatch)
    pin = _pins()[0]
    raw = b"# Ejemplar uno\n"
    _write_carrier(tmp_path, "skill-oficial", pin["path"], raw)
    _publish_skill(source=_template_source("Skill Oficial"), adjuntos=_pin_entries([pin]))
    derived = client.post("/api/co-creation/derive", json={
        "skill_id": "skill-oficial", "version": "1.0.0",
    })
    session_id = derived.json()["session_id"]
    drift = _upload(client, session_id, pin["path"], b"# Drift\n").json()["adjunto"]
    published = _publish_pins(client, session_id, 0, [drift])
    assert published.status_code == 422, published.text
    assert published.json()["code"] == "attachment_overwrite_refused"
    root = carrier_root_for("skill-oficial", project_root=tmp_path)
    assert read_adjunto_bytes(root, AttachmentEntry(**pin)) == raw


def test_publish_refuses_replacement_on_a_seeded_skill(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """EP-6/D5: a seeded skill refuses a replacement pin (preserve-only)."""
    session_id, revision, _ = _materialized_session(client, monkeypatch, "seed-skill")
    (tmp_path / "data" / "methodology" / "seeds" / "seed-skill").mkdir(parents=True)
    pin = _upload(client, session_id, "nuevo.md", b"# Nuevo\n").json()["adjunto"]
    published = _publish_pins(client, session_id, revision, [pin])
    assert published.status_code == 422, published.text
    assert published.json()["code"] == "attachment_seed_immutable"
    assert not _attachments_dir(tmp_path, "seed-skill").exists()


def test_publish_maps_adjuntos_overflow_to_422_limit(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """EP-7: > MAX_ADJUNTOS maps to 422 attachment_limit_reached, not validation."""
    session_id, revision, _ = _materialized_session(client, monkeypatch, "overflow-skill")
    overflow = []
    for index in range(MAX_ADJUNTOS + 1):
        data = f"# Ejemplar {index}\n".encode()
        _write_carrier(tmp_path, "overflow-skill", f"e{index}.md", data)
        overflow.append({"path": f"e{index}.md", "sha256": hashlib.sha256(data).hexdigest(),
                         "bytes": len(data), "nivel": "1º"})
    published = _publish_pins(client, session_id, revision, overflow)
    assert published.status_code == 422, published.text
    assert published.json()["code"] == "attachment_limit_reached"


def test_publish_rolls_back_moved_pins_when_update_fails(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """EP-4: a post-move update failure rolls the moved bytes back (no tree)."""
    session_id, revision, _ = _materialized_session(client, monkeypatch, "rollback-skill")
    pin = _upload(client, session_id, "nuevo.md", b"# Nuevo\n").json()["adjunto"]

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("draft store unavailable")

    monkeypatch.setattr(api_server._methodology_library(), "update_draft", _boom)
    with pytest.raises(RuntimeError):
        _publish_pins(client, session_id, revision, [pin])
    assert not _attachments_dir(tmp_path, "rollback-skill").exists()


def test_publish_rejects_pending_pin_without_staged_bytes(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """EP-4: a pending pin whose staged bytes are absent is 422 with no tree."""
    session_id, revision, _ = _materialized_session(client, monkeypatch, "missing-skill")
    phantom = {"path": "fantasma.md", "sha256": "a" * 64, "bytes": 10, "nivel": "1º"}
    published = _publish_pins(client, session_id, revision, [phantom])
    assert published.status_code == 422, published.text
    assert published.json()["code"] == "attachment_unavailable"
    assert not _attachments_dir(tmp_path, "missing-skill").exists()

# ---------------------------------------------------------------------------
# Etapa 2 (WU 2.2) — session trigger approval + publish gate
# ---------------------------------------------------------------------------

def _materialize_only(client: TestClient, session_id: str) -> dict:
    """Materialize without approving, so the publish gate can be exercised."""
    materialized = client.post(
        f"/api/co-creation/sessions/{session_id}/materialize",
        json={"base_revision": 1, "name": "Batallas Épicas"},
    )
    assert materialized.status_code == 200, materialized.text
    assert materialized.json()["ok"] is True
    return materialized.json()


def test_session_publish_without_approval_refused_and_stays_incomplete(
    client: TestClient, monkeypatch,
) -> None:
    """The co-creation route maps the gate refusal to 409
    ``trigger_not_approved`` (never a generic 500) and the session does NOT
    advance to complete; the draft remains approvable."""
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    materialized = _materialize_only(client, session_id)
    draft_id = materialized["draft_id"]

    refused = client.post(
        f"/api/co-creation/sessions/{session_id}/publish",
        json={"base_revision": materialized["revision"]},
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "trigger_not_approved"

    recovered = client.get(f"/api/co-creation/sessions/{session_id}").json()
    assert recovered["phase"] != "complete"
    assert recovered["draft_id"] == draft_id
    library = api_server._methodology_library()
    assert library.get_draft(draft_id) is not None
    assert library.list_published() == []


def test_session_approve_endpoint_records_and_enables_publish(
    client: TestClient, monkeypatch,
) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    materialized = _materialize_only(client, session_id)
    revision = materialized["revision"]

    approved = client.post(
        f"/api/co-creation/sessions/{session_id}/trigger/approve",
        json={"base_revision": revision, "description": "Cuenta batallas épicas"},
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["trigger_approval"]["text"] == "Cuenta batallas épicas"
    assert body["trigger_approval"]["digest"]
    assert body["revision"] == revision + 1

    # The approved value lands in the canvas AND is exposed by the state view,
    # so the value approved is the value publish will use.
    recovered = client.get(f"/api/co-creation/sessions/{session_id}").json()
    assert recovered["draft_payload"]["description"] == "Cuenta batallas épicas"
    assert recovered["trigger_approval"]["text"] == "Cuenta batallas épicas"

    published = client.post(
        f"/api/co-creation/sessions/{session_id}/publish",
        json={"base_revision": body["revision"]},
    )
    assert published.status_code == 200, published.text
    assert published.json()["phase"] == "complete"
    assert published.json()["published"]["description"] == "Cuenta batallas épicas"


def test_session_approve_rejects_stale_revision_and_over_bound(
    client: TestClient, monkeypatch,
) -> None:
    _bind_principal(monkeypatch)
    _wire_provider(monkeypatch, milestone="borrador_listo")
    session_id = _create_session(client)
    materialized = _materialize_only(client, session_id)
    revision = materialized["revision"]

    stale = client.post(
        f"/api/co-creation/sessions/{session_id}/trigger/approve",
        json={"base_revision": revision + 5, "description": "ok"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "revision_conflict"

    over = client.post(
        f"/api/co-creation/sessions/{session_id}/trigger/approve",
        json={"base_revision": revision, "description": "x" * 61},
    )
    assert over.status_code == 422
    assert over.json()["code"] == "trigger_invalid"

    # Zero mutation on either refusal.
    recovered = client.get(f"/api/co-creation/sessions/{session_id}").json()
    assert recovered["revision"] == revision
    assert recovered["trigger_approval"] is None
