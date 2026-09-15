"""PR5-A route and public contract smoke tests."""

from pathlib import Path
import asyncio
from datetime import datetime, timedelta, timezone
import json
import shutil
import sys
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import api_server  # noqa: E402
from guided_character_protocol import (  # noqa: E402
    Capabilities,
    CandidateState,
    GuidedRequest,
    GuidedResponse,
    GuidedSessionStore,
    ErrorCode,
    MessageType,
    Outcome,
    PROTOCOL_VERSION,
    SessionState,
    StructuredError,
    TypedMessage,
)
from guided_character_provider import HermesGuidedProvider  # noqa: E402
from methodology_library import MethodologyLibrary  # noqa: E402
from methodology_seed import install_seeds  # noqa: E402

REPO_ROOT = _WIKI.parents[3]
SEED_ROOT = REPO_ROOT / "data" / "methodology" / "seeds"


client = TestClient(api_server.app)


@pytest.fixture(autouse=True)
def _isolate_methodology_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep guided tests off the real repo methodology store.

    The guided start route snapshots the active methodology, which lazy-inits
    the server library; without isolation the first such call would construct
    AND seed the real ``data/methodology/library.json`` (this module shares
    one module-level TestClient across tests). A fresh empty tmp library keeps
    the builtin runtime and the repo store untouched (S6 guard).
    """
    monkeypatch.setattr(
        api_server,
        "_METHODOLOGY_LIBRARY",
        MethodologyLibrary(tmp_path / "data" / "methodology" / "library.json"),
    )

ROUTES = {
    ("GET", "/api/{mundo}/guided-character/session/{session_id}"),
    ("POST", "/api/{mundo}/guided-character/session"),
    ("POST", "/api/{mundo}/guided-character/turn"),
    ("POST", "/api/{mundo}/guided-character/consent/accept"),
    ("POST", "/api/{mundo}/guided-character/consent/decline"),
    ("POST", "/api/{mundo}/guided-character/proposal/accept"),
    ("POST", "/api/{mundo}/guided-character/proposal/reject"),
    ("POST", "/api/{mundo}/guided-character/proposal/serialize"),
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
        ("post", "/api/nec/guided-character/consent/accept", {"token": "ct-deadbeef"}),
        ("post", "/api/nec/guided-character/consent/decline", {"token": "ct-deadbeef"}),
        ("post", "/api/nec/guided-character/proposal/accept", {"session_id": "s", "base_revision": 0, "key": "x"}),
        ("post", "/api/nec/guided-character/proposal/reject", {"session_id": "s", "base_revision": 0, "key": "x"}),
        ("post", "/api/nec/guided-character/proposal/serialize", {"session_id": "s", "base_revision": 0}),
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
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", None)
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
        "pending_question", "messages", "candidate", "proposal", "reference", "mode", "depth",
    }
    assert "provenance" not in payload["candidate"]
    assert payload["messages"] == [{"role": "assistant", "content": "What drives them?"}]


def test_internal_guided_turn_reuses_verified_reference_across_turns(monkeypatch, tmp_path) -> None:
    captured = []

    async def provider(request, _token):
        captured.append(request)
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "What drives them?",
        }

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    monkeypatch.setattr(
        api_server,
        "_named_reference_context",
        lambda _world, _prompt: ("Verified reference: Rhyz El Resonante\nFacts: Resonates.", False, "Rhyz El Resonante"),
    )
    semantic_runs = _SemanticRuns(
        {
            "state": "require_confirmation", "response": "¿Creo este personaje?",
            "request_id": "r-1", "session_id": "s-1", "guided": True,
            "guided_explicitness": "imperative",
            "continuation": {"outcome": "question", "question": "¿Creo este personaje?"},
        },
        {"state": "allow", "response": "ok", "request_id": "r-2", "session_id": "s-1", "guided": False},
        {"state": "allow", "response": "ok", "request_id": "r-3", "session_id": "s-1", "guided": False},
    )
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", api_server.SemanticIntentProvider(semantic_runs))

    first = client.post("/api/vibrantes/ai/ask", json={"prompt": "quiero crear al hermano de Rhyz"})
    assert first.status_code == 200
    first_state = first.json()["guided_state"]
    assert first_state["reference"]["name"] == "Rhyz El Resonante"
    assert first_state["reference"]["verified"] is True

    accepted = client.post("/api/vibrantes/ai/ask", json={
        "prompt": "sí", "session_id": "chat-1",
        "guided_session_id": first_state["session_id"],
        "guided_revision": first_state["revision"],
    })
    assert accepted.status_code == 200
    accepted_state = accepted.json()["guided_state"]

    with monkeypatch.context() as context:
        normal = AsyncMock(return_value="Rhyz fulfills a resonant role.")
        context.setattr(api_server, "_run_hermes", normal)
        second = client.post("/api/vibrantes/ai/ask", json={
            "prompt": "¿qué papel cumple Rhyz?",
            "session_id": "chat-1",
            "guided_session_id": accepted_state["session_id"],
            "guided_revision": accepted_state["revision"],
        })
    assert second.status_code == 200
    # The verified reference is reused across turns on the guarded provider
    # path; the factual shortcut is gone, so no plain-chat call happens.
    assert len(captured) == 2
    assert captured[1].reference_context == first_state["reference"]["context"]
    assert second.json()["guided_session_id"] == first_state["session_id"]
    assert second.json()["guided_revision"] == accepted_state["revision"] + 1
    normal.assert_not_awaited()


def test_authenticated_adapter_commits_delta_and_accepts_one_proposal(monkeypatch, tmp_path) -> None:
    async def provider(request, _token):
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": {"name": "Aria", "desire": "freedom"},
            "provenance": ["provider:run-1"],
        }

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    monkeypatch.setattr(api_server, "_named_reference_context", lambda *_args: ("", False, None))
    _guided_semantic_allow(monkeypatch, count=1)

    response = client.post("/api/vibrantes/guided-character/session", json={"author_input": "Create a character"})
    assert response.status_code == 200
    session = response.json()
    assert session["revision"] == 1
    assert session["candidate"]["proposals"]["desire"]["certainty"] == "proposed"


def test_fast_guided_start_exposes_server_owned_mode_and_keeps_proposal_diskless(monkeypatch, tmp_path) -> None:
    captured = []

    async def provider(request, _token):
        captured.append(request)
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": {"desire": "freedom"},
        }

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    _guided_semantic_allow(monkeypatch, count=1)

    started = client.post("/api/vibrantes/guided-character/session", json={
        "author_input": "Create a character quickly with only fundamentals",
    })
    assert started.status_code == 200
    session = started.json()
    assert session["mode"] == "fast"
    assert session["depth"] == "fundamental"
    assert captured[0].guided_mode == "fast"
    assert captured[0].question_depth == "fundamental"
    serialized = client.post("/api/vibrantes/guided-character/proposal/serialize", json={
        "session_id": session["session_id"], "base_revision": session["revision"],
        "slug": "fast-character", "title": "Fast Character",
    })
    assert serialized.status_code == 200
    assert serialized.json()["is_new_file"] is True
    assert not list((tmp_path / "vibrantes").rglob("*.md"))
    accepted = client.post("/api/vibrantes/guided-character/proposal/accept", json={
        "session_id": session["session_id"], "base_revision": 1, "key": "desire",
    })
    assert accepted.status_code == 200
    assert accepted.json()["candidate"]["accepted_canon"]["desire"]["certainty"] == "accepted"


def test_guided_start_accepts_descriptive_character_seeds(monkeypatch, tmp_path) -> None:
    async def provider(request, _token):
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "What drives them?",
        }

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    _guided_semantic_allow(monkeypatch, count=2)

    for seed in ("Un guerrero de las sombras", "Un personaje llamado Aria"):
        response = client.post("/api/vibrantes/guided-character/session", json={"author_input": seed})
        assert response.status_code == 200
        assert response.json()["revision"] == 1


def test_vague_backstory_delta_keeps_asking_one_focused_question(monkeypatch, tmp_path) -> None:
    """A rough backstory/scene must NOT become a proposal in full guided mode.

    The provider returns a delta after a vague description; the server-owned
    completeness gate converts it into exactly one focused question, so the
    author keeps building the character one turn at a time.
    """
    calls = []

    async def provider(request, _token):
        calls.append(request)
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": {"relation": "brother of Rhyz", "age": "~30", "scene": "a storm at sea"},
        }

    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "es")
    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    monkeypatch.setattr(
        api_server, "_named_reference_context",
        lambda *_args: ("Verified reference: Rhyz\nFacts: Patient tactician.", False, "Rhyz"),
    )
    _guided_semantic_allow(monkeypatch, count=2)

    started = client.post("/api/vibrantes/guided-character/session", json={
        "author_input": "quiero crear al hermano de Rhyz",
    })
    assert started.status_code == 200
    assert started.json()["phase"] == "confirmation"
    assert calls == []

    confirmed = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": started.json()["session_id"],
        "base_revision": started.json()["revision"],
        "author_input": "sí",
    })
    assert confirmed.status_code == 200
    session = confirmed.json()
    assert session["phase"] == "conversation"
    assert session["proposal"] is None
    assert session["candidate"]["proposals"] == {}
    assert session["candidate"]["accepted_canon"] == {}
    assert session["pending_question"] and session["pending_question"].count("?") == 1
    assert len(calls) == 1


def test_vague_backstory_turn_never_produces_diff_after_rough_description(monkeypatch, tmp_path) -> None:
    """Multi-turn regression: after a vague scene the server keeps asking, so the
    frontend never receives a proposal/diff to review."""
    calls = []

    async def provider(request, _token):
        calls.append(request)
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": {"backstory": "raised in the storm"},
        }

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    _guided_semantic_allow(monkeypatch, count=2)

    started = client.post("/api/vibrantes/guided-character/session", json={
        "author_input": "Create a character",
    })
    assert started.status_code == 200
    assert started.json()["pending_question"] and "?" in started.json()["pending_question"]

    turned = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": started.json()["session_id"],
        "base_revision": started.json()["revision"],
        "author_input": "Raised in the storm, quiet and patient",
    })
    assert turned.status_code == 200
    assert turned.json()["proposal"] is None
    assert turned.json()["candidate"]["proposals"] == {}
    assert turned.json()["pending_question"] and "?" in turned.json()["pending_question"]
    assert len(calls) == 2


def test_complete_candidate_still_reaches_proposal_across_turns(monkeypatch, tmp_path) -> None:
    """Once identity + desire are present, a later delta is admitted as a proposal."""
    calls = []

    async def provider(request, _token):
        calls.append(request)
        if request.base_revision == 0:
            delta = {"name": "Pert", "desire": "freedom"}
        else:
            delta = {"fear": "the storm"}
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": delta,
        }

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    _guided_semantic_allow(monkeypatch, count=2)

    started = client.post("/api/vibrantes/guided-character/session", json={
        "author_input": "Create a character",
    })
    assert started.status_code == 200
    assert started.json()["candidate"]["proposals"]["name"]["value"] == "Pert"

    turned = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": started.json()["session_id"],
        "base_revision": started.json()["revision"],
        "author_input": "he fears the storm",
    })
    assert turned.status_code == 200
    assert "fear" in turned.json()["candidate"]["proposals"]
    assert turned.json()["proposal"] is not None
    assert len(calls) == 2


def test_relationship_start_requires_confirmation_and_acceptance_enters_provider(monkeypatch, tmp_path) -> None:
    calls = []

    async def provider(request, _token):
        calls.append(request.author_input)
        return {
            "protocol_version": request.protocol_version, "request_id": request.request_id,
            "session_id": request.session_id, "outcome": "question", "question": "What drives them?",
        }

    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "es")
    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    monkeypatch.setattr(api_server, "_named_reference_context", lambda *_args: ("", False, None))
    _guided_semantic_allow(monkeypatch, count=3)

    started = client.post("/api/vibrantes/guided-character/session", json={"author_input": "Quiero crear la esposa de Rhyz"})
    assert started.status_code == 200
    session = started.json()
    assert session["phase"] == "confirmation"
    assert session["pending_question"] == (
        "Puedo preparar una propuesta guiada para este personaje relacionado. "
        "¿Comenzamos las preguntas? (sí/no)"
    )
    assert session["candidate"]["proposals"] == {}
    assert calls == []

    ambiguous = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": session["session_id"], "base_revision": 1, "author_input": "maybe",
    })
    assert ambiguous.status_code == 200
    assert ambiguous.json()["phase"] == "confirmation"
    assert ambiguous.json()["pending_question"] == (
        "Por favor, responde sí para comenzar la propuesta guiada del personaje o no para cancelarla."
    )
    assert calls == []

    accepted = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": session["session_id"], "base_revision": 2, "author_input": "sí",
    })
    assert accepted.status_code == 200
    assert accepted.json()["phase"] == "conversation"
    assert calls == ["Quiero crear la esposa de Rhyz"]


def test_relationship_confirmation_decline_is_terminal_and_non_mutating(monkeypatch, tmp_path) -> None:
    async def provider(*_args):
        raise AssertionError("provider must not run after decline")

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "es")
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    monkeypatch.setattr(api_server, "_named_reference_context", lambda *_args: ("", False, None))
    _guided_semantic_allow(monkeypatch, count=3)
    started = client.post("/api/vibrantes/guided-character/session", json={"author_input": "Create Rhyz's spouse"}).json()
    declined = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": started["session_id"], "base_revision": 1, "author_input": "no",
    })
    assert declined.status_code == 200
    assert declined.json()["phase"] == "complete"
    assert declined.json()["messages"][-1]["content"] == "No se inició ninguna propuesta de personaje."
    assert declined.json()["candidate"]["proposals"] == {}

    repeated = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": started["session_id"], "base_revision": declined.json()["revision"], "author_input": "yes",
    })
    assert repeated.status_code == 200
    assert repeated.json() == declined.json()


def test_relationship_goal_survives_confirmation_and_multi_turn(monkeypatch, tmp_path) -> None:
    requests = []

    async def provider(request, _token):
        requests.append(request)
        return {
            "protocol_version": request.protocol_version, "request_id": request.request_id,
            "session_id": request.session_id, "outcome": "question", "question": "What drives them?",
        }

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "es")
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    monkeypatch.setattr(
        api_server, "_named_reference_context",
        lambda *_args: ("Verified reference: Rhyz\nFacts: Patient tactician.", False, "Rhyz"),
    )
    _guided_semantic_allow(monkeypatch, count=3)

    started = client.post("/api/vibrantes/guided-character/session", json={
        "author_input": "quiero crear al hermano de Rhyz",
    })
    assert started.status_code == 200
    session = started.json()
    assert session["phase"] == "confirmation"
    assert session["reference"]["goal"] == "Nuevo personaje: hermano de Rhyz"
    assert requests == []

    confirmed = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": session["session_id"], "base_revision": 1, "author_input": "sí",
    })
    assert confirmed.status_code == 200
    assert len(requests) == 1
    assert requests[0].reference_name == "Rhyz"
    assert requests[0].relation_goal == "Nuevo personaje: hermano de Rhyz"

    turned = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": session["session_id"],
        "base_revision": confirmed.json()["revision"],
        "author_input": "Su deseo secreto es la libertad",
    })
    assert turned.status_code == 200
    assert len(requests) == 2
    assert requests[1].relation_goal == requests[0].relation_goal == "Nuevo personaje: hermano de Rhyz"
    assert turned.json()["reference"]["goal"] == "Nuevo personaje: hermano de Rhyz"


def test_english_relation_goal_follows_configured_language(monkeypatch, tmp_path) -> None:
    requests = []

    async def provider(request, _token):
        requests.append(request)
        return {
            "protocol_version": request.protocol_version, "request_id": request.request_id,
            "session_id": request.session_id, "outcome": "question", "question": "What drives them?",
        }

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    monkeypatch.setattr(
        api_server, "_named_reference_context",
        lambda *_args: ("Verified reference: Rhyz\nFacts: Patient tactician.", False, "Rhyz"),
    )
    _guided_semantic_allow(monkeypatch, count=2)

    started = client.post("/api/vibrantes/guided-character/session", json={
        "author_input": "quiero crear al hermano de Rhyz",
    })
    assert started.status_code == 200
    assert started.json()["phase"] == "confirmation"
    assert started.json()["reference"]["goal"] == "New character: brother of Rhyz"
    assert requests == []

    confirmed = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": started.json()["session_id"], "base_revision": 1, "author_input": "yes",
    })
    assert confirmed.status_code == 200
    assert requests and requests[0].relation_goal == "New character: brother of Rhyz"


def test_plain_character_start_never_invents_a_relation(monkeypatch, tmp_path) -> None:
    requests = []

    async def provider(request, _token):
        requests.append(request)
        return {
            "protocol_version": request.protocol_version, "request_id": request.request_id,
            "session_id": request.session_id, "outcome": "question", "question": "What drives them?",
        }

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    monkeypatch.setattr(api_server, "_named_reference_context", lambda *_args: ("", False, None))
    _guided_semantic_allow(monkeypatch, count=1)

    started = client.post("/api/vibrantes/guided-character/session", json={
        "author_input": "Create a character",
    })
    assert started.status_code == 200
    session = started.json()
    assert session["phase"] == "conversation"
    assert session["reference"]["goal"] is None
    assert len(requests) == 1
    assert requests[0].relation_goal == ""


def test_relationship_prompt_on_ai_ask_does_not_fall_through_to_prose(monkeypatch, tmp_path) -> None:
    async def provider(*_args):
        raise AssertionError("the guided provider must wait for confirmation")

    prose = AsyncMock(return_value="Invented character prose")
    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "es")
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    monkeypatch.setattr(api_server, "_named_reference_context", lambda *_args: ("", False, None))
    monkeypatch.setattr(api_server, "_run_hermes", prose)
    semantic_runs = _SemanticRuns({
        "state": "require_confirmation", "response": "¿Creo este personaje?",
        "request_id": "r-1", "session_id": "s-1", "guided": True,
        "guided_explicitness": "imperative",
        "continuation": {"outcome": "question", "question": "¿Creo este personaje?"},
    })
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", api_server.SemanticIntentProvider(semantic_runs))

    response = client.post("/api/vibrantes/ai/ask", json={"prompt": "I want to create Rhyz's wife"})

    assert response.status_code == 200
    assert response.json()["response"] == "¿Creo este personaje?"
    assert response.json()["guided_state"]["phase"] == "confirmation"
    prose.assert_not_awaited()


def test_confirmation_text_follows_configured_language_in_both_entry_paths(monkeypatch, tmp_path) -> None:
    async def provider(*_args):
        raise AssertionError("provider must not run before confirmation")

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)

    def setup():
        monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
        monkeypatch.setattr(api_server, "_named_reference_context", lambda *_args: ("", False, None))
        semantic_runs = _SemanticRuns(
            {
                "state": "require_confirmation", "response": "¿Creo este personaje?",
                "request_id": "r-1", "session_id": "s-1", "guided": True,
                "guided_explicitness": "imperative",
                "continuation": {"outcome": "question", "question": "¿Creo este personaje?"},
            },
            {"state": "allow", "response": "ok", "request_id": "r-2", "session_id": "s-1", "guided": False},
            {"state": "allow", "response": "ok", "request_id": "r-3", "session_id": "s-1", "guided": False},
        )
        monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", api_server.SemanticIntentProvider(semantic_runs))

    setup()
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "es")
    spanish_with_english_prompt = client.post(
        "/api/vibrantes/guided-character/session",
        json={"author_input": "I want to create Rhyz's brother"},
    ).json()
    assert spanish_with_english_prompt["pending_question"] == (
        "Puedo preparar una propuesta guiada para este personaje relacionado. "
        "¿Comenzamos las preguntas? (sí/no)"
    )
    spanish_ambiguous = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": spanish_with_english_prompt["session_id"], "base_revision": 1, "author_input": "maybe",
    }).json()
    assert spanish_ambiguous["pending_question"] == (
        "Por favor, responde sí para comenzar la propuesta guiada del personaje o no para cancelarla."
    )
    spanish_declined = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": spanish_with_english_prompt["session_id"], "base_revision": 2, "author_input": "no",
    }).json()
    assert spanish_declined["messages"][-1]["content"] == "No se inició ninguna propuesta de personaje."

    setup()
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")
    english_with_spanish_prompt = client.post("/api/vibrantes/ai/ask", json={
        "prompt": "quiero crear al hermano de Rhyz",
    }).json()
    assert english_with_spanish_prompt["response"] == "¿Creo este personaje?"
    assert english_with_spanish_prompt["guided_state"]["phase"] == "confirmation"
    english_ambiguous = client.post("/api/vibrantes/ai/ask", json={
        "prompt": "quizás",
        "guided_session_id": english_with_spanish_prompt["guided_session_id"],
        "guided_revision": english_with_spanish_prompt["guided_revision"],
    }).json()
    assert english_ambiguous["response"] == (
        "Please answer yes to start the guided character proposal, or no to cancel."
    )
    english_declined = client.post("/api/vibrantes/ai/ask", json={
        "prompt": "no",
        "guided_session_id": english_with_spanish_prompt["guided_session_id"],
        "guided_revision": english_ambiguous["guided_revision"],
    }).json()
    assert english_declined["response"] == "No character proposal was started."


def test_guided_start_normalizes_structured_question_for_public_state(monkeypatch, tmp_path) -> None:
    class Runs:
        async def start(self, request):
            self.request = request
            return "run-1"

        async def events(self, _run_id):
            payload = {
                "version": "guided-character-v1",
                "request_id": self.request.request_id,
                "session_id": self.request.session_id,
                "outcome": "question",
                "question": {
                    "text": "What drives them?",
                    "options": ["Freedom", "Power"],
                    "allow_custom": True,
                    "provenance": "private",
                },
                "provenance": ["private-provider-run"],
            }
            yield {"event": "run.completed", "run_id": "run-1", "output": json.dumps(payload)}

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", HermesGuidedProvider(Runs()))
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    _guided_semantic_allow(monkeypatch, count=1)

    response = client.post("/api/vibrantes/guided-character/session", json={"author_input": "Create a character"})

    assert response.status_code == 200
    assert response.json()["pending_question"] == (
        "What drives them?\n\nOptions:\n- Freedom\n- Power\n\nCustom answers are allowed."
    )
    assert "private" not in response.text


def test_guided_start_rejects_explicit_edit_requests(monkeypatch, tmp_path) -> None:
    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    sessions = GuidedSessionStore()
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", object())
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    _guided_semantic_allow(monkeypatch, count=10)

    for edit_term in (
        "edit", "editar", "existing", "existente", "modify", "modificar",
        "update", "actualizar", "change", "cambiar",
    ):
        response = client.post(
            "/api/vibrantes/guided-character/session",
            json={"author_input": f"{edit_term} the existing character Aria"},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "New-character intent is required."

    assert sessions.recover("guided-missing", "author-1") is None


def test_adapter_rejects_stale_transition_without_mutation(monkeypatch) -> None:
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    state = api_server._GUIDED_SESSIONS.create("guided-1", "vibrantes", "author-1")
    response = client.post("/api/vibrantes/guided-character/proposal/accept", json={
        "session_id": state.session_id, "base_revision": 1, "key": "desire",
    })
    assert response.status_code == 409
    assert api_server._GUIDED_SESSIONS.recover("guided-1", "author-1").revision == 0


def test_serialization_is_owned_revision_bound_and_diskless(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    (tmp_path / "vibrantes" / "personajes").mkdir(parents=True)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    sessions = GuidedSessionStore()
    state = sessions.create("guided-1", "vibrantes", "author-1")
    state.candidate.proposals["desire"] = {"value": "freedom", "certainty": "proposed"}
    sessions._sessions[state.session_id] = state
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)

    response = client.post("/api/vibrantes/guided-character/proposal/serialize", json={
        "session_id": "guided-1", "base_revision": 0, "slug": "aria", "title": "Aria",
    })
    assert response.status_code == 200
    proposal = response.json()
    assert proposal["target"] == "personajes/aria.md"
    assert proposal["is_new_file"] is True
    assert proposal["guided_revision"] == 0
    assert not list((tmp_path / "vibrantes").rglob("*.md"))

    stale = client.post("/api/vibrantes/guided-character/proposal/serialize", json={
        "session_id": "guided-1", "base_revision": 1,
    })
    assert stale.status_code == 409

    other = sessions.create("guided-2", "vibrantes", "other-author")
    sessions._sessions[other.session_id] = other
    owned = client.post("/api/vibrantes/guided-character/proposal/serialize", json={
        "session_id": "guided-2", "base_revision": 0,
    })
    assert owned.status_code == 401


def test_all_frontend_calls_preserve_public_state_and_do_not_write_files(tmp_path, monkeypatch) -> None:
    async def provider(request, _token):
        if request.base_revision == 0:
            return {
                "protocol_version": request.protocol_version,
                "request_id": request.request_id,
                "session_id": request.session_id,
                "outcome": "delta",
                "delta": {"name": "Aria", "desire": "freedom"},
                "provenance": ["private-provider-run"],
            }
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": {"fear": "freedom"},
            "provenance": ["private-provider-run"],
        }

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    _guided_semantic_allow(monkeypatch, count=2)

    started = client.post("/api/vibrantes/guided-character/session", json={"author_input": "Create a character"})
    assert started.status_code == 200
    session = started.json()
    assert set(session) == {"protocol_version", "session_id", "world", "phase", "revision", "pending_question", "messages", "candidate", "proposal", "reference", "mode", "depth"}
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


class _SemanticRuns:
    """Minimal runs adapter shape consumed by SemanticIntentProvider."""

    def __init__(self, *payloads):
        self._payloads = list(payloads)
        self.starts = 0

    async def start(self, request):
        self.starts += 1
        return f"run-{self.starts}"

    async def events(self, run_id):
        if self._payloads:
            payload = self._payloads.pop(0)
        else:
            payload = None
        yield {"event": "run.completed", "run_id": run_id, "output": payload}


def _guided_semantic_allow(monkeypatch, count=1):
    """Wire the mandatory semantic gate with ``allow`` decisions (Hermes-first).

    PR3 makes guided start/continuation gate on a validated Hermes decision;
    these allow payloads let the guarded Demiurgos policy proceed after
    interpretation.
    """
    runs = _SemanticRuns(*[
        {"state": "allow", "response": "ok", "request_id": f"r-{index}",
         "session_id": "s-1", "guided": False}
        for index in range(1, count + 1)
    ])
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", api_server.SemanticIntentProvider(runs))
    return runs


def test_guided_flow_gates_semantic_then_guarded(monkeypatch, tmp_path) -> None:
    """PR 3: guided session start interprets via Hermes FIRST, then runs the
    guarded guided path. One semantic run backs the session, then the guarded
    provider continues — no lexical shortcut precedes the gate."""
    guided_calls = []
    semantic_runs = _SemanticRuns(
        {"state": "allow", "response": "semantic answer", "request_id": "r", "session_id": "s", "guided": False}
    )

    async def provider(request, _token):
        guided_calls.append(request)
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "What drives them?",
        }

    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", api_server.SemanticIntentProvider(semantic_runs))

    started = client.post("/api/vibrantes/guided-character/session", json={"author_input": "Create a character"})
    assert started.status_code == 200
    assert started.json()["revision"] == 1
    assert len(guided_calls) == 1
    assert semantic_runs.starts == 1


def test_guided_canon_safety_holds_when_semantic_provider_is_wired(monkeypatch, tmp_path) -> None:
    """PR 2: semantic routing cannot bypass guided auth/revision/digest guards."""
    semantic_runs = _SemanticRuns(
        {"state": "proposal_ready", "response": "write", "request_id": "r", "session_id": "s", "guided": False}
    )
    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", None)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", api_server.SemanticIntentProvider(semantic_runs))

    missing = client.post("/api/vibrantes/guided-character/proposal/accept", json={
        "session_id": "missing", "base_revision": 0, "key": "desire",
    })
    assert missing.status_code == 409
    unavailable = client.post("/api/vibrantes/guided-character/session", json={"author_input": "Create a character"})
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "capability_unavailable"
    assert semantic_runs.starts == 0
    assert list(tmp_path.rglob("*")) == [tmp_path / "vibrantes"]


def test_semantic_single_run_continuation_uses_guarded_machinery_and_handoff(monkeypatch, tmp_path) -> None:
    """PR 2 continuation (task 2.3): one semantic run backs a diskless proposal.

    The same run that emits proposal_ready also supplies the candidate delta;
    the server creates the guarded session, serializes a server-owned diskless
    proposal, and the created session inherits guided_handoff (no second run).
    """
    semantic_runs = _SemanticRuns({
        "state": "proposal_ready",
        "response": "Propuesta lista.",
        "request_id": "r-1",
        "session_id": "s-1",
        "guided": True,
        "guided_explicitness": "imperative",
        "continuation": {"outcome": "delta", "delta": {"name": "Rhyz's Wife", "desire": "freedom"}},
    })
    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PENDING_PROPOSALS", {})
    monkeypatch.setattr(api_server, "_named_reference_context", lambda _mundo, _prompt: ("", False, None))
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", api_server.SemanticIntentProvider(semantic_runs))

    created = client.post("/api/vibrantes/ai/ask", json={"prompt": "Define el perfil de un ser que lo protege"})
    assert created.status_code == 200
    envelope = created.json()
    assert envelope["state"] == "proposal_ready"
    assert envelope["target"] == "personajes/rhyz-s-wife.md"
    assert envelope["guided_session_id"].startswith("guided-")
    assert semantic_runs.starts == 1

    recovered = client.get(f"/api/vibrantes/guided-character/session/{envelope['guided_session_id']}")
    assert recovered.status_code == 200
    assert recovered.json()["session_id"] == envelope["guided_session_id"]

    handoff = client.post("/api/vibrantes/ai/ask/activity", json={
        "prompt": "x", "session_id": "chat-1",
        "guided_session_id": envelope["guided_session_id"],
        "guided_revision": envelope["guided_revision"],
    })
    assert handoff.status_code == 503
    assert handoff.json()["code"] == "guided_handoff"
    assert semantic_runs.starts == 1
    assert not (tmp_path / "vibrantes" / "personajes").exists()


def test_semantic_proposal_ready_with_incomplete_delta_asks_one_question(monkeypatch, tmp_path) -> None:
    """proposal_ready delta is not a trusted completeness claim.

    When the single-run delta lacks the minimum identity data (name + desire),
    the server does NOT emit a proposal/diff: it converts the delta into exactly
    one focused question and keeps the guided session in conversation.
    """
    semantic_runs = _SemanticRuns({
        "state": "proposal_ready",
        "response": "Propuesta lista.",
        "request_id": "r-1",
        "session_id": "s-1",
        "guided": True,
        "guided_explicitness": "imperative",
        "continuation": {"outcome": "delta", "delta": {"relation": "brother of Rhyz", "scene": "a storm at sea"}},
    })
    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PENDING_PROPOSALS", {})
    monkeypatch.setattr(api_server, "_named_reference_context", lambda _mundo, _prompt: ("", False, None))
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", api_server.SemanticIntentProvider(semantic_runs))

    created = client.post("/api/vibrantes/ai/ask", json={"prompt": "Define el perfil de un ser que lo protege"})
    assert created.status_code == 200
    envelope = created.json()
    assert "state" not in envelope
    assert envelope["response"] and "?" in envelope["response"]
    assert envelope["guided_session_id"].startswith("guided-")
    assert envelope["guided_state"]["phase"] == "conversation"
    assert envelope["guided_state"]["proposal"] is None
    assert envelope["guided_state"]["candidate"]["proposals"] == {}
    assert "proposal" not in envelope and "target" not in envelope and "digest" not in envelope
    assert semantic_runs.starts == 1
    assert not (tmp_path / "vibrantes" / "personajes").exists()


# ---------------------------------------------------------------------------
# PR2 consent lifecycle: token consume + accept/decline endpoints (REQ-GFC-05/07)
# ---------------------------------------------------------------------------


def _musing_continuation_payload(state: str = "require_confirmation") -> dict:
    """A musing single-run envelope: semantic decision + typed continuation."""
    return {
        "state": state,
        "response": "Hermes semantic answer.",
        "request_id": "r-consent",
        "session_id": "s-consent",
        "guided": True,
        "guided_explicitness": "musing",
        "continuation": (
            {"outcome": "question", "question": "¿Creo este personaje?"}
            if state == "require_confirmation"
            else {"outcome": "delta", "delta": {"name": "Rhyz's Wife", "desire": "freedom"}}
        ),
    }


def _consent_harness(monkeypatch, tmp_path, *payloads):
    """Wire a musing suggestion path with isolated memory, sessions, tokens."""
    (tmp_path / "vibrantes").mkdir(exist_ok=True)
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_GUIDED_PENDING_PROPOSALS", {})
    monkeypatch.setattr(api_server, "_GUIDED_CONSENT_TOKENS", {})
    monkeypatch.setattr(api_server, "_named_reference_context", lambda _mundo, _prompt: ("", False, None))
    memory = api_server.ConversationMemoryStore(":memory:")
    monkeypatch.setattr(api_server, "_CONVERSATION_MEMORY", memory)
    runs = _SemanticRuns(*payloads)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", api_server.SemanticIntentProvider(runs))
    return memory, runs


def _issue_consent_suggestion(client: TestClient, session_id: str = "consent-1") -> str:
    """Drive one musing chat turn and return the issued consent token."""
    response = client.post("/api/vibrantes/ai/ask", json={
        "prompt": "Quisiera que me propongas un compañero para ese mundo",
        "session_id": session_id,
    })
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["consent"] == "required"
    assert "guided_session_id" not in envelope
    return envelope["consent_token"]


def test_consent_accept_opens_deferred_flow_with_single_hermes_run(monkeypatch, tmp_path) -> None:
    """REQ-GFC-05: accept consumes the token and opens the guided flow with NO
    second Hermes run and WITHOUT route_new_character_intent."""
    _memory, runs = _consent_harness(
        monkeypatch, tmp_path, _musing_continuation_payload("require_confirmation"),
    )
    token = _issue_consent_suggestion(client)
    assert runs.starts == 1

    routed: list[str] = []
    monkeypatch.setattr(
        api_server, "route_new_character_intent",
        lambda *args, **kwargs: routed.append("route") or None,
    )
    accepted = client.post(
        "/api/vibrantes/guided-character/consent/accept", json={"token": token},
    )
    assert accepted.status_code == 200, accepted.text
    envelope = accepted.json()
    assert envelope["state"] == "require_confirmation"
    assert envelope["guided_session_id"].startswith("guided-")
    assert envelope["guided_state"]["phase"] == "confirmation"
    assert "consent" not in envelope and "consent_token" not in envelope
    assert runs.starts == 1          # the accept click starts no Hermes run
    assert routed == []              # no lexical re-routing on accept


def test_consent_accept_replayed_token_fails_closed(monkeypatch, tmp_path) -> None:
    """REQ-GFC-07: a consumed token can never open a second session."""
    _consent_harness(monkeypatch, tmp_path, _musing_continuation_payload())
    token = _issue_consent_suggestion(client)
    sessions = api_server._GUIDED_SESSIONS
    first = client.post("/api/vibrantes/guided-character/consent/accept", json={"token": token})
    assert first.status_code == 200
    replay = client.post("/api/vibrantes/guided-character/consent/accept", json={"token": token})
    assert replay.status_code == 422
    assert len(sessions._sessions) == 1


def test_consent_accept_expired_token_fails_closed(monkeypatch, tmp_path) -> None:
    """REQ-GFC-07: an expired token opens nothing and is discarded."""
    _consent_harness(monkeypatch, tmp_path, _musing_continuation_payload())
    token = _issue_consent_suggestion(client)
    record = api_server._GUIDED_CONSENT_TOKENS[token]
    record["created_at"] = (
        datetime.now(timezone.utc) - api_server.CONSENT_TOKEN_TTL - timedelta(minutes=1)
    )
    sessions = api_server._GUIDED_SESSIONS
    response = client.post("/api/vibrantes/guided-character/consent/accept", json={"token": token})
    assert response.status_code == 422
    assert sessions._sessions == {}
    assert token not in api_server._GUIDED_CONSENT_TOKENS


def test_consent_accept_foreign_principal_fails_closed(monkeypatch, tmp_path) -> None:
    """REQ-GFC-07: a foreign token opens nothing and does not destroy the
    rightful owner's pending token."""
    _consent_harness(monkeypatch, tmp_path, _musing_continuation_payload())
    token = _issue_consent_suggestion(client)
    sessions = api_server._GUIDED_SESSIONS
    monkeypatch.setattr(
        api_server, "_resolve_principal",
        lambda _request: api_server.EditPrincipal("intruder"),
    )
    response = client.post("/api/vibrantes/guided-character/consent/accept", json={"token": token})
    assert response.status_code == 422
    assert sessions._sessions == {}
    assert token in api_server._GUIDED_CONSENT_TOKENS


def test_consent_accept_malformed_token_fails_closed(monkeypatch, tmp_path) -> None:
    """REQ-GFC-07: a malformed token opens nothing."""
    _consent_harness(monkeypatch, tmp_path, _musing_continuation_payload())
    sessions = api_server._GUIDED_SESSIONS
    response = client.post(
        "/api/vibrantes/guided-character/consent/accept", json={"token": "not-a-token"},
    )
    assert response.status_code == 422
    assert sessions._sessions == {}


def test_consent_decline_discards_token_records_flag_and_blocks_accept(monkeypatch, tmp_path) -> None:
    """REQ-GFC-06/07: decline persists the flag, creates no session, and the
    discarded token can never be accepted afterwards."""
    memory, runs = _consent_harness(monkeypatch, tmp_path, _musing_continuation_payload())
    token = _issue_consent_suggestion(client)
    sessions = api_server._GUIDED_SESSIONS

    declined = client.post(
        "/api/vibrantes/guided-character/consent/decline", json={"token": token},
    )
    assert declined.status_code == 200
    assert declined.json() == {"consent": "declined"}
    assert memory.guided_consent_declined("consent-1", "vibrantes") is True
    assert sessions._sessions == {}

    accepted = client.post(
        "/api/vibrantes/guided-character/consent/accept", json={"token": token},
    )
    assert accepted.status_code == 422
    assert sessions._sessions == {}
    assert runs.starts == 1


def test_consent_decline_foreign_token_fails_closed_without_write(monkeypatch, tmp_path) -> None:
    """REQ-GFC-07: a foreign decline writes no durable decline flag."""
    memory, _runs = _consent_harness(monkeypatch, tmp_path, _musing_continuation_payload())
    token = _issue_consent_suggestion(client)
    monkeypatch.setattr(
        api_server, "_resolve_principal",
        lambda _request: api_server.EditPrincipal("intruder"),
    )
    response = client.post(
        "/api/vibrantes/guided-character/consent/decline", json={"token": token},
    )
    assert response.status_code == 422
    assert memory.guided_consent_declined("consent-1", "vibrantes") is False


def test_guided_start_fails_closed_when_semantic_unavailable(monkeypatch, tmp_path) -> None:
    """PR3 (task 3.2): guided start gates on a validated Hermes decision.

    Unavailable Hermes fails closed with a blocked-safe envelope, zero session
    creation, zero writes, and NO lexical shortcut: route_new_character_intent
    never runs before the semantic gate.
    """
    lexical = []
    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    sessions = GuidedSessionStore()
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", object())
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", None)
    monkeypatch.setattr(api_server, "route_new_character_intent", lambda *a, **k: lexical.append("lexical") or None)

    response = client.post("/api/vibrantes/guided-character/session", json={
        "author_input": "Create a character",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "blocked"
    assert body["unavailable"] is True
    assert body["response"].startswith("El Asistente IA no pudo")
    assert lexical == []
    assert sessions._sessions == {}
    assert not list((tmp_path / "vibrantes").rglob("*.md"))


def test_guided_turn_fails_closed_when_semantic_unavailable(monkeypatch, tmp_path) -> None:
    """PR3 (task 3.2): guided continuation gates on a validated Hermes decision.

    Unavailable Hermes fails closed with zero session mutation, proposal, or
    write.
    """
    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    sessions = GuidedSessionStore()
    state = sessions.create("guided-1", "vibrantes", "author-1")
    state.messages.append(TypedMessage(MessageType.ASSISTANT_RESPONSE, {"question": "What drives them?"}, 1))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", None)

    response = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": "guided-1", "base_revision": 0, "author_input": "Freedom",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "blocked"
    assert body["unavailable"] is True
    assert body["response"].startswith("El Asistente IA no pudo")
    assert sessions.recover("guided-1", "author-1").revision == 0


def test_guided_start_semantic_decides_before_lexical_policy(monkeypatch, tmp_path) -> None:
    """PR3 (task 3.2): Hermes interprets guided creation BEFORE any lexical
    guided policy; route_new_character_intent derives policy only after a
    validated decision."""
    order = []
    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(api_server, "_named_reference_context", lambda *_args: ("", False, None))

    async def provider(request, _token):
        order.append("guided_provider")
        return {
            "protocol_version": request.protocol_version, "request_id": request.request_id,
            "session_id": request.session_id, "outcome": "question", "question": "What drives them?",
        }

    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    runs = _guided_semantic_allow(monkeypatch, count=1)
    provider_semantic = api_server._SEMANTIC_PROVIDER
    original_decide = provider_semantic.decide

    async def recorded_decide(*args, **kwargs):
        order.append("semantic.decide")
        return await original_decide(*args, **kwargs)

    provider_semantic.decide = recorded_decide
    real_route = api_server.route_new_character_intent

    def recorded_route(*args, **kwargs):
        order.append("route_new_character_intent")
        return real_route(*args, **kwargs)

    monkeypatch.setattr(api_server, "route_new_character_intent", recorded_route)

    response = client.post("/api/vibrantes/guided-character/session", json={
        "author_input": "Create a character",
    })

    assert response.status_code == 200
    assert order == ["semantic.decide", "route_new_character_intent", "guided_provider"]
    assert runs.starts == 1


def test_guided_turn_semantic_decides_before_confirmation_policy(monkeypatch, tmp_path) -> None:
    """PR3 (task 3.2): Hermes interprets a typed confirmation BEFORE the lexical
    confirmation policy runs on the guarded /guided-character/turn surface."""
    order = []
    (tmp_path / "vibrantes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: api_server.EditPrincipal("author-1"))
    sessions = GuidedSessionStore()
    state = sessions.create("guided-1", "vibrantes", "author-1")
    confirming = sessions.begin_confirmation("guided-1", "author-1", "Crea un personaje", "¿Sí o no?")
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)
    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", None)
    monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities("guided-character-v1", True, True, True, 30000))
    runs = _guided_semantic_allow(monkeypatch, count=1)
    provider_semantic = api_server._SEMANTIC_PROVIDER
    original_decide = provider_semantic.decide

    async def recorded_decide(*args, **kwargs):
        order.append("semantic.decide")
        return await original_decide(*args, **kwargs)

    provider_semantic.decide = recorded_decide

    def recorded_confirmation(*args, **kwargs):
        order.append("confirmation_decision")
        return None  # ambiguous -> re-prompt, guided provider stays off

    monkeypatch.setattr(api_server, "confirmation_decision", recorded_confirmation)

    response = client.post("/api/vibrantes/guided-character/turn", json={
        "session_id": "guided-1", "base_revision": confirming.revision, "author_input": "quizás",
    })

    assert response.status_code == 200
    assert order == ["semantic.decide", "confirmation_decision"]
    assert runs.starts == 1


def test_seeded_library_leaves_builtin_guided_runtime_untouched(monkeypatch, tmp_path) -> None:
    """S6: the seeded library never wires or alters the builtin guided runtime.

    A library with the bundled foundational seed installed must behave exactly
    like the pre-change builtin pin: ``_ACTIVE_METHODOLOGY_VERSION`` stays
    ``"builtin"`` and the guided snapshot for a world without an activation is
    the builtin contract (no compiled methodology is loaded dynamically).
    """
    seed_root = tmp_path / "seeds"
    shutil.copytree(SEED_ROOT, seed_root)
    library = MethodologyLibrary(tmp_path / "library.json")
    report = install_seeds(library, seed_root)
    assert report.installed == 1
    monkeypatch.setattr(api_server, "_METHODOLOGY_LIBRARY", library)

    assert api_server._BUILTIN_METHODOLOGY_VERSION == "builtin"
    assert api_server._ACTIVE_METHODOLOGY_VERSION == "builtin"
    snapshot = api_server._active_methodology_snapshot("nec")
    assert snapshot.skill_id == "guided-character-v1"
    assert snapshot.skill_version == "builtin"
    assert snapshot.compiled_contract_digest is None
    assert api_server._compiled_contract_markdown("nec") is None


class _SpecimenCapturingProvider:
    """Guided provider that records the convergence_specimen_markdown hint."""

    def __init__(self) -> None:
        self.received: list[str | None] = []

    async def invoke(self, request, token, *, compiled_contract_markdown=None,
                     convergence_specimen_markdown=None) -> dict:
        self.received.append(convergence_specimen_markdown)
        return {
            "protocol_version": "guided-character-v1",
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "What drives them?",
        }


class TestConvergenceSpecimenB5:
    """R10/R11/R13 (④b): the convergence specimen is resolved pre-invocation
    in ``_guided_continue`` and threaded beside the compiled contract — never
    on turn one, gated by the finished-exchange conjunct, exactly one block
    when the gate passes, and fail-open byte-identical for pre-PR④ records."""

    def _wired_library(self, tmp_path: Path) -> MethodologyLibrary:
        """Library with the REAL wired seed published and activated for
        ``vibrantes``; the serving seam reads the real repo seed dir."""
        seed_root = tmp_path / "seeds"
        shutil.copytree(SEED_ROOT, seed_root)
        library = MethodologyLibrary(tmp_path / "library.json")
        report = install_seeds(library, seed_root)
        assert report.installed == 1
        library.activate("vibrantes", "narrative-character-creation", "1.2")
        return library

    def _harness(self, monkeypatch, tmp_path: Path, *, mode: str = "full",
                 library: MethodologyLibrary | None = None):
        (tmp_path / "vibrantes").mkdir()
        monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
        provider = _SpecimenCapturingProvider()
        store = GuidedSessionStore()
        store.create(
            "guided-1", "vibrantes", "author-1", mode=mode,
            depth="fundamental" if mode == "fast" else "standard",
        )
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", store)
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", Capabilities(
            "guided-character-v1", True, True, True, 30000,
        ))
        if library is not None:
            monkeypatch.setattr(api_server, "_METHODOLOGY_LIBRARY", library)
        return provider, store

    @staticmethod
    def _finish_exchange(store: GuidedSessionStore) -> None:
        """Commit one provider DELTA: a finished exchange (PROPOSAL) and a
        minimum-complete candidate (identity + desire) in one step."""
        request = GuidedRequest(
            PROTOCOL_VERSION, "req-1", "guided-1", "vibrantes", 0, "author-1",
            "Create a character",
        )
        response = GuidedResponse(
            PROTOCOL_VERSION, "req-1", "guided-1", 0, Outcome.DELTA,
            delta={"name": "Pert", "desire": "freedom"},
        )
        assert store.commit(request, response) is not None

    def test_never_turn_one_resolves_no_specimen(self, monkeypatch, tmp_path) -> None:
        """Scenario "never turn one": turn one resolves NO specimen — the
        prompt stays byte-identical to pre-PR④ (the None hint path is locked
        byte-for-byte in the provider tests)."""
        provider, _ = self._harness(monkeypatch, tmp_path, library=self._wired_library(tmp_path))
        asyncio.run(api_server._guided_continue(
            "vibrantes", "guided-1", 0, "Create a character",
            api_server.EditPrincipal("author-1"),
        ))
        assert provider.received == [None]

    def test_fast_mode_guard_finished_exchange_conjunct_blocks(self, monkeypatch, tmp_path) -> None:
        """Scenario "fast-mode guard": fast mode short-circuits the gate, but
        the finished-exchange conjunct still blocks injection on turn one."""
        provider, _ = self._harness(
            monkeypatch, tmp_path, mode="fast", library=self._wired_library(tmp_path),
        )
        asyncio.run(api_server._guided_continue(
            "vibrantes", "guided-1", 0, "Create a character",
            api_server.EditPrincipal("author-1"),
        ))
        assert provider.received == [None]

    def test_gate_passed_injects_exactly_one_specimen_block(self, monkeypatch, tmp_path) -> None:
        """Scenario "gate-passed injects": a gate-passed turn appends exactly
        one specimen block (unknown nivel → 1º default first-pin exemplar)."""
        provider, store = self._harness(monkeypatch, tmp_path, library=self._wired_library(tmp_path))
        self._finish_exchange(store)
        asyncio.run(api_server._guided_continue(
            "vibrantes", "guided-1", 1, "Add a scar",
            api_server.EditPrincipal("author-1"),
        ))
        assert len(provider.received) == 1
        block = provider.received[0]
        assert block is not None
        assert block.count("[Convergence specimen — nivel ") == 1
        assert block.startswith("[Convergence specimen — nivel 1º]")
        assert "Nara Veless" in block

    def test_pre_pr4_fail_open_record_without_adjuntos_stays_byte_identical(
        self, monkeypatch, tmp_path,
    ) -> None:
        """Scenario "pre-PR④ fail-open": a published record WITHOUT adjuntos
        resolves no specimen even on a gate-passed turn — the prompt stays
        byte-identical to today."""
        library = self._wired_library(tmp_path)
        payload = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
        record = next(iter(payload["published"].values()))
        record.pop("adjuntos", None)
        (tmp_path / "library.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        stripped = MethodologyLibrary(tmp_path / "library.json")
        stripped.activate("vibrantes", "narrative-character-creation", "1.2")
        provider, store = self._harness(monkeypatch, tmp_path, library=stripped)
        self._finish_exchange(store)
        asyncio.run(api_server._guided_continue(
            "vibrantes", "guided-1", 1, "Add a scar",
            api_server.EditPrincipal("author-1"),
        ))
        assert provider.received == [None]
