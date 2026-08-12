"""PR5-A route and public contract smoke tests."""

from pathlib import Path
import sys

from fastapi.testclient import TestClient

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import api_server  # noqa: E402
from guided_character_protocol import (  # noqa: E402
    Capabilities,
    CandidateState,
    GuidedSessionStore,
    ErrorCode,
    MessageType,
    SessionState,
    StructuredError,
    TypedMessage,
)


client = TestClient(api_server.app)

ROUTES = {
    ("GET", "/api/{mundo}/guided-character/session/{session_id}"),
    ("POST", "/api/{mundo}/guided-character/session"),
    ("POST", "/api/{mundo}/guided-character/turn"),
    ("POST", "/api/{mundo}/guided-character/proposal/accept"),
    ("POST", "/api/{mundo}/guided-character/proposal/reject"),
    ("POST", "/api/{mundo}/guided-character/index/retry"),
}


def test_route_map_registers_frontend_paths_and_methods() -> None:
    actual = {
        (method, route.path)
        for route in api_server.app.routes
        if hasattr(route, "methods")
        for method in route.methods
        if route.path.startswith("/api/{mundo}/guided-character")
    }
    assert actual == ROUTES


def test_routes_fail_closed_with_stable_auth_error(monkeypatch) -> None:
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    calls = [
        ("get", "/api/nec/guided-character/session/session-1", None),
        ("post", "/api/nec/guided-character/session", {"author_input": "Create a character"}),
        ("post", "/api/nec/guided-character/turn", {"session_id": "s", "base_revision": 0, "author_input": "x"}),
        ("post", "/api/nec/guided-character/proposal/accept", {"session_id": "s", "base_revision": 0, "key": "x"}),
        ("post", "/api/nec/guided-character/proposal/reject", {"session_id": "s", "base_revision": 0, "key": "x"}),
        ("post", "/api/nec/guided-character/index/retry", {"session_id": "s", "base_revision": 0}),
    ]
    for method, path, body in calls:
        response = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
        assert response.status_code == 401
        assert response.json() == {
            "detail": "Authentication required.",
            "code": "unauthorized",
            "message": "Authentication required.",
            "retryable": False,
        }


def test_error_mapping_and_authenticated_unavailable_envelope(monkeypatch) -> None:
    assert api_server._GUIDED_ERROR_STATUS[ErrorCode.REVISION_CONFLICT] == 409
    assert api_server._GUIDED_ERROR_STATUS[ErrorCode.UNAUTHORIZED] == 401
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("test-author"))
    response = client.post("/api/nec/guided-character/session", json={"author_input": "Create a character"})
    assert response.status_code == 503
    assert response.json()["code"] == "capability_unavailable"
    assert response.json()["retryable"] is True


def test_public_state_envelope_excludes_backend_provenance() -> None:
    state = SessionState("s", "nec", "conversation", 1, "author")
    state.messages.append(TypedMessage(MessageType.ASSISTANT_RESPONSE, {"question": "What drives them?"}, 1))
    state.candidate = CandidateState(proposals={"desire": {"value": "freedom"}}, provenance=["secret-run"])
    payload = api_server._guided_public_state(state)
    assert set(payload) == {
        "protocol_version", "session_id", "world", "phase", "revision",
        "pending_question", "messages", "candidate", "proposal",
    }
    assert "provenance" not in payload["candidate"]
    assert payload["messages"] == [{"role": "assistant", "content": "What drives them?"}]


def test_authenticated_adapter_commits_delta_and_accepts_one_proposal(monkeypatch) -> None:
    async def provider(request, _token):
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": {"desire": "freedom"},
            "provenance": ["provider:run-1"],
        }

    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 8000))

    response = client.post("/api/vibrantes/guided-character/session", json={"author_input": "Create a character"})
    assert response.status_code == 200
    session = response.json()
    assert session["revision"] == 1
    assert session["candidate"]["proposals"]["desire"]["certainty"] == "proposed"
    accepted = client.post("/api/vibrantes/guided-character/proposal/accept", json={
        "session_id": session["session_id"], "base_revision": 1, "key": "desire",
    })
    assert accepted.status_code == 200
    assert accepted.json()["candidate"]["accepted_canon"]["desire"]["certainty"] == "accepted"


def test_adapter_rejects_stale_transition_without_mutation(monkeypatch) -> None:
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    state = api_server._GUIDED_SESSIONS.create("guided-1", "vibrantes", "author-1")
    response = client.post("/api/vibrantes/guided-character/proposal/accept", json={
        "session_id": state.session_id, "base_revision": 1, "key": "desire",
    })
    assert response.status_code == 409
    assert api_server._GUIDED_SESSIONS.recover("guided-1", "author-1").revision == 0


def test_all_frontend_calls_preserve_public_state_and_do_not_write_files(tmp_path, monkeypatch) -> None:
    async def provider(request, _token):
        key = "desire" if request.base_revision == 0 else "fear"
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": {key: "freedom"},
            "provenance": ["private-provider-run"],
        }

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 8000))

    started = client.post("/api/vibrantes/guided-character/session", json={"author_input": "Create a character"})
    assert started.status_code == 200
    session = started.json()
    assert set(session) == {"protocol_version", "session_id", "world", "phase", "revision", "pending_question", "messages", "candidate", "proposal"}
    assert "provenance" not in session["candidate"]

    recovered = client.get(f"/api/vibrantes/guided-character/session/{session['session_id']}")
    assert recovered.status_code == 200
    assert recovered.json() == session

    turned = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": session["session_id"], "base_revision": 1, "author_input": "They seek freedom",
    })
    assert turned.status_code == 200
    assert turned.json()["revision"] == 2

    accepted = client.post("/api/vibrantes/guided-character/proposal/accept", json={
        "session_id": session["session_id"], "base_revision": 2, "key": "desire",
    })
    assert accepted.status_code == 200
    assert accepted.json()["candidate"]["accepted_canon"]["desire"]["certainty"] == "accepted"

    rejected = client.post("/api/vibrantes/guided-character/proposal/reject", json={
        "session_id": session["session_id"], "base_revision": 3, "key": "fear",
    })
    assert rejected.status_code == 200
    assert "fear" not in rejected.json()["candidate"]["proposals"]

    api_server._GUIDED_INDEX_REQUESTS[session["session_id"]] = ("op-1", "ficha.md", "digest")
    class Reindex:
        def reconcile(self, **_kwargs):
            return type("Result", (), {"index_status": "pending", "retryable": True, "message": "Index pending"})()
    monkeypatch.setattr(api_server, "_GUIDED_REINDEX", Reindex())
    retried = client.post("/api/vibrantes/guided-character/index/retry", json={
        "session_id": session["session_id"], "base_revision": 4,
    })
    assert retried.status_code == 200
    assert retried.json()["index_status"] == "pending"
    assert list(tmp_path.rglob("*")) == [tmp_path / "vibrantes"]


def test_guided_failures_are_stable_and_non_mutating(monkeypatch) -> None:
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    stale = client.post("/api/nec/guided-character/turn", json={"session_id": "missing", "base_revision": 0, "author_input": "x"})
    assert stale.status_code == 401
    assert stale.json()["code"] == "unauthorized"
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", None)
    unavailable = client.post("/api/nec/guided-character/session", json={"author_input": "Create a character"})
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "capability_unavailable"
    assert unavailable.json()["retryable"] is True
