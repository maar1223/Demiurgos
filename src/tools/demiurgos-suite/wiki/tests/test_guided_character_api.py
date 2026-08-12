"""PR5-A route and public contract smoke tests."""

from pathlib import Path
import sys

from fastapi.testclient import TestClient

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import api_server  # noqa: E402
from guided_character_protocol import (  # noqa: E402
    CandidateState,
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
