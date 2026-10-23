"""API contracts for skill-declared guided flows (S1-S6).

The character flow is pinned by the existing regression suite; these tests
cover the first declared flow (Sistemas): profile resolution, consent/method
selection, serialization into the kernel-owned section, OKF minimums, the
gated write + index, and cross-flow rejection.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import api_server  # noqa: E402
from guided_character_protocol import (  # noqa: E402
    Capabilities,
    GuidedSessionStore,
    MethodologySnapshot,
)
from methodology_library import MethodologyLibrary  # noqa: E402
from methodology_seed import install_seeds  # noqa: E402
from okf_contract import validate  # noqa: E402

REPO_ROOT = _WIKI.parents[3]
SEED_ROOT = REPO_ROOT / "data" / "methodology" / "seeds"

client = TestClient(api_server.app)


class _Runs:
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


def _allow(monkeypatch: pytest.MonkeyPatch, count: int = 1) -> None:
    runs = _Runs(*[
        {"state": "allow", "response": "ok", "request_id": f"r-{index}",
         "session_id": "s-1", "guided": False}
        for index in range(1, count + 1)
    ])
    monkeypatch.setattr(
        api_server, "_SEMANTIC_PROVIDER", api_server.SemanticIntentProvider(runs),
    )


@pytest.fixture(autouse=True)
def _isolated_flow_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    library = MethodologyLibrary(tmp_path / "library.json")
    install_seeds(library, SEED_ROOT)
    monkeypatch.setattr(api_server, "_METHODOLOGY_LIBRARY", library)
    (tmp_path / "vibrantes" / "lore").mkdir(parents=True)
    (tmp_path / "vibrantes" / "personajes").mkdir()
    monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
    monkeypatch.setattr(
        api_server, "_resolve_principal",
        lambda _request: api_server.EditPrincipal("author-1"),
    )
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", GuidedSessionStore())
    monkeypatch.setattr(
        api_server, "_GUIDED_CAPABILITIES",
        Capabilities("guided-character-v1", True, True, True, 30_000),
    )
    monkeypatch.setattr(
        api_server, "_named_reference_context", lambda *_args: ("", False, None),
    )
    return library


def _system_snapshot(library: MethodologyLibrary) -> MethodologySnapshot:
    profile = library.flow_profile_for("guided-system", "narrative-system-creation")
    assert profile is not None
    return MethodologySnapshot(
        skill_id="narrative-system-creation",
        skill_version="1.2",
        compiled_contract_digest="digest",
        flow_type="guided-system",
        profile=profile.as_dict(),
    )


def test_generic_guided_route_aliases_are_registered() -> None:
    paths = {
        getattr(route, "path", None) for route in api_server.app.routes
    }
    for path in (
        "/api/{mundo}/guided/session",
        "/api/{mundo}/guided/session/{session_id}",
        "/api/{mundo}/guided/turn",
        "/api/{mundo}/guided/consent/accept",
        "/api/{mundo}/guided/consent/decline",
        "/api/{mundo}/guided/proposal/accept",
        "/api/{mundo}/guided/proposal/reject",
        "/api/{mundo}/guided/proposal/serialize",
        "/api/{mundo}/guided/index/retry",
    ):
        assert path in paths


def test_guided_methods_are_listed_per_flow() -> None:
    systems = client.get(
        "/api/methodologies/guided-methods?world=vibrantes&flow=guided-system",
    )
    assert systems.status_code == 200
    payload = systems.json()
    assert payload["flow"] == "guided-system"
    assert [item["skill_id"] for item in payload["methods"]] == [
        "narrative-system-creation",
    ]
    assert payload["default"] == {
        "skill_id": "narrative-system-creation", "version": "1.2",
    }

    character = client.get(
        "/api/methodologies/guided-methods?world=vibrantes",
    ).json()
    assert "narrative-character-creation" in [
        item["skill_id"] for item in character["methods"]
    ]
    assert "narrative-system-creation" not in [
        item["skill_id"] for item in character["methods"]
    ]

    invalid = client.get("/api/methodologies/guided-methods?flow=wizard")
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "unsupported_flow_type"


def _chronology_snapshot(library: MethodologyLibrary) -> MethodologySnapshot:
    profile = library.flow_profile_for(
        "guided-chronology", "narrative-chronology-creation",
    )
    assert profile is not None
    return MethodologySnapshot(
        skill_id="narrative-chronology-creation",
        skill_version="1.2",
        compiled_contract_digest="digest",
        flow_type="guided-chronology",
        profile=profile.as_dict(),
    )


def test_guided_methods_are_listed_for_chronology() -> None:
    payload = client.get(
        "/api/methodologies/guided-methods?world=vibrantes&flow=guided-chronology",
    )
    assert payload.status_code == 200, payload.json()
    body = payload.json()
    assert body["flow"] == "guided-chronology"
    assert [item["skill_id"] for item in body["methods"]] == [
        "narrative-chronology-creation",
    ]
    assert body["default"] == {
        "skill_id": "narrative-chronology-creation", "version": "1.2",
    }

    for flow in ("guided-system", None):
        url = "/api/methodologies/guided-methods?world=vibrantes"
        if flow:
            url += f"&flow={flow}"
        listed = client.get(url).json()
        assert "narrative-chronology-creation" not in [
            item["skill_id"] for item in listed["methods"]
        ]


def test_chat_intent_resolves_the_chronology_flow(_isolated_flow_env) -> None:
    profile = api_server._resolve_input_flow("Quiero crear una cronología")
    assert profile is not None
    assert profile.flow_id == "guided-chronology"
    assert profile.ui_copy_key == "chronology"
    assert profile.target_section == "lore"

    seeded = api_server._resolve_input_flow("Quiero registrar una era")
    assert seeded is not None
    assert seeded.flow_id == "guided-chronology"

    # An unmatched turn keeps the historical character default.
    fallback = api_server._resolve_input_flow("Háblame de los personajes")
    assert fallback is not None
    assert fallback.flow_id == "guided-character"


def test_chronology_consent_copy_is_flow_specific() -> None:
    copy = api_server.GUIDED_CONSENT_SUGGESTION_TEXT_BY_COPY_KEY["chronology"]
    assert "cronología" in copy
    assert "guíado" not in copy.lower()


def test_chronology_session_start_uses_the_declared_profile(monkeypatch) -> None:
    _allow(monkeypatch, 1)

    async def provider(request, _token):
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": {"name": "La Caída", "evento": "El imperio se parte"},
        }

    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    response = client.post("/api/vibrantes/guided/session", json={
        "author_input": "Quiero crear una cronología",
        "flow_id": "guided-chronology",
    })
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["flow"] == {
        "flow_id": "guided-chronology",
        "entity_type": "cronologia",
        "target_section": "lore",
        "ui_copy_key": "chronology",
    }
    assert payload["methodology"]["skill_id"] == "narrative-chronology-creation"
    assert payload["methodology"]["skill_version"] == "1.2"
    assert payload["methodology"]["factory"] is False
    assert payload["candidate"]["proposals"]


def test_chronology_serialization_targets_lore_and_passes_okf(
    _isolated_flow_env,
) -> None:
    library = _isolated_flow_env
    sessions = api_server._GUIDED_SESSIONS
    sessions.create(
        "guided-chron", "vibrantes", "author-1",
        methodology_snapshot=_chronology_snapshot(library),
    )
    state = sessions.recover("guided-chron", "author-1")
    assert state is not None
    state.candidate.accepted_canon = {
        "name": "La Caída", "evento": "El imperio se parte en dos",
    }
    sessions._sessions["guided-chron"] = state  # noqa: SLF001

    response = client.post("/api/vibrantes/guided/proposal/serialize", json={
        "session_id": "guided-chron", "base_revision": 0,
        "slug": "la-caida", "title": "La Caída",
    })
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["target"] == "lore/la-caida.md"
    validation = validate(payload["proposed_content"])
    assert validation.ok, validation.issues
    metadata = validation.document.frontmatter
    assert metadata["type"] == "Cronologia"
    assert metadata["evento"] == "El imperio se parte en dos"


def test_system_session_start_uses_the_declared_profile(monkeypatch) -> None:
    _allow(monkeypatch, 1)

    async def provider(request, _token):
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": {
                "name": "Magia", "origen": "los dioses",
                "limite": "no crea materia",
            },
        }

    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    response = client.post("/api/vibrantes/guided/session", json={
        "author_input": "Quiero crear un sistema de magia",
        "flow_id": "guided-system",
    })
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["flow"] == {
        "flow_id": "guided-system",
        "entity_type": "sistema",
        "target_section": "lore",
        "ui_copy_key": "system",
    }
    assert payload["methodology"]["skill_id"] == "narrative-system-creation"
    assert payload["methodology"]["skill_version"] == "1.2"
    assert payload["methodology"]["factory"] is False
    assert payload["candidate"]["proposals"]


def test_system_session_rejects_a_character_method(monkeypatch) -> None:
    _allow(monkeypatch, 1)

    async def provider(request, _token):  # pragma: no cover - never reached
        raise AssertionError("the provider must not run on a rejected method")

    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    response = client.post("/api/vibrantes/guided/session", json={
        "author_input": "Quiero crear un sistema de magia",
        "flow_id": "guided-system",
        "method_skill_id": "narrative-character-creation",
        "method_version": "1.3",
    })
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "ineligible_guided_method"
    assert api_server._GUIDED_SESSIONS.recover(
        body.get("session_id", ""), "author-1",
    ) is None


def test_system_activation_rejects_a_character_method() -> None:
    response = client.post("/api/methodologies/activate", json={
        "world": "vibrantes",
        "skill_id": "narrative-character-creation",
        "version": "1.3",
        "flow_type": "guided-system",
    })
    assert response.status_code == 422
    assert response.json()["code"] == "ineligible_guided_method"
    assert api_server._methodology_library().active_for(
        "vibrantes", "guided-system",
    ) is None


def test_system_serialization_targets_lore_and_passes_okf(_isolated_flow_env) -> None:
    library = _isolated_flow_env
    sessions = api_server._GUIDED_SESSIONS
    sessions.create(
        "guided-sys", "vibrantes", "author-1",
        methodology_snapshot=_system_snapshot(library),
    )
    state = sessions.recover("guided-sys", "author-1")
    assert state is not None
    state.candidate.accepted_canon = {
        "name": "Magia", "origen": "los dioses", "limite": "no crea materia",
    }
    sessions._sessions["guided-sys"] = state  # noqa: SLF001

    response = client.post("/api/vibrantes/guided/proposal/serialize", json={
        "session_id": "guided-sys", "base_revision": 0,
        "slug": "magia", "title": "Magia",
    })
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["target"] == "lore/magia.md"
    validation = validate(payload["proposed_content"])
    assert validation.ok, validation.issues
    metadata = validation.document.frontmatter
    assert metadata["type"] == "Sistema"
    assert metadata["origen"] == "los dioses"
    assert metadata["limite"] == "no crea materia"


def test_system_create_writes_lore_and_indexes(monkeypatch, tmp_path) -> None:
    library = api_server._methodology_library()
    sessions = api_server._GUIDED_SESSIONS
    sessions.create(
        "guided-sys", "vibrantes", "author-1",
        methodology_snapshot=_system_snapshot(library),
    )
    state = sessions.recover("guided-sys", "author-1")
    assert state is not None
    state.candidate.accepted_canon = {
        "name": "Magia", "origen": "los dioses", "limite": "no crea materia",
    }
    sessions._sessions["guided-sys"] = state  # noqa: SLF001

    serialized = client.post("/api/vibrantes/guided/proposal/serialize", json={
        "session_id": "guided-sys", "base_revision": 0,
        "slug": "magia", "title": "Magia",
    })
    assert serialized.status_code == 200, serialized.json()
    proposal = serialized.json()
    content = proposal["proposed_content"]
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

    class _Reindex:
        def reconcile(self, **kwargs):
            return SimpleNamespace(
                index_status="indexed", retryable=False, message="Indexed",
            )

    monkeypatch.setattr(api_server, "_GUIDED_REINDEX", _Reindex())
    confirmation = client.post(
        "/api/vibrantes/lore/edit-confirmation?path=magia.md",
        json={
            "edit_id": proposal["proposal_id"], "kind": "new",
            "proposed_content": content,
        },
    )
    assert confirmation.status_code == 200, confirmation.json()
    created = client.post("/api/vibrantes/lore/create?path=magia.md", json={
        "content": content,
        "edit_id": proposal["proposal_id"],
        "proposed_digest": digest,
        "token": confirmation.json()["token"],
    })
    assert created.status_code == 200, created.json()
    assert created.json()["index_status"] == "indexed"
    written = tmp_path / "vibrantes" / "lore" / "magia.md"
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == content


def test_system_reject_removes_the_proposal_without_writing(_isolated_flow_env) -> None:
    library = _isolated_flow_env
    sessions = api_server._GUIDED_SESSIONS
    sessions.create(
        "guided-sys", "vibrantes", "author-1",
        methodology_snapshot=_system_snapshot(library),
    )
    state = sessions.recover("guided-sys", "author-1")
    assert state is not None
    state.candidate.proposals["origen"] = {"value": "los dioses"}
    sessions._sessions["guided-sys"] = state  # noqa: SLF001

    response = client.post("/api/vibrantes/guided/proposal/reject", json={
        "session_id": "guided-sys", "base_revision": 0, "key": "origen",
    })
    assert response.status_code == 200, response.json()
    assert response.json()["candidate"]["proposals"] == {}
    assert not list((Path(api_server.MUNDOS_DIR) / "vibrantes" / "lore").iterdir())


def test_reviewing_a_system_before_accepting_cannot_persist_below_okf(monkeypatch) -> None:
    """S4 regression: the review button is visible while the fields are still
    proposals; the serialized file must already carry the OKF minimums."""
    _allow(monkeypatch, 1)

    async def provider(request, _token):
        return {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": {
                "name": "Magia", "origen": "los dioses",
                "limite": "no crea materia",
            },
        }

    monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
    started = client.post("/api/vibrantes/guided/session", json={
        "author_input": "Quiero crear un sistema de magia",
        "flow_id": "guided-system",
    })
    assert started.status_code == 200, started.json()
    payload = started.json()
    assert payload["candidate"]["proposals"]

    reviewed = client.post("/api/vibrantes/guided/proposal/serialize", json={
        "session_id": payload["session_id"], "base_revision": payload["revision"],
    })
    assert reviewed.status_code == 200, reviewed.json()
    validation = validate(reviewed.json()["proposed_content"])
    assert validation.ok, validation.issues
