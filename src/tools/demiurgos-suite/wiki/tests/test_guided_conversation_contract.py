"""RED/unit tests for the shared guided conversation contract.

Covers: the synthesis/observations envelope extension, its durable commit, the
synthesis-before-question rendering, the server-owned known-state summary, and
the bounded world-lore injection that keeps the provider from asking the author
to explain their own canon.
"""

from __future__ import annotations

import sys
from pathlib import Path

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import api_server  # noqa: E402
from guided_character_protocol import (  # noqa: E402
    CandidateState,
    GuidedRequest,
    GuidedResponse,
    Outcome,
    PROTOCOL_VERSION,
    SessionState,
)
from guided_session_store import GuidedSessionStore  # noqa: E402


class TestEnvelope:
    def test_accepts_synthesis_and_observations(self) -> None:
        request = _request()
        response = GuidedResponse.from_provider({
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "¿Qué busca ahora?",
            "synthesis": "Lo que llevamos: Ganic saltó años y la deuda lo alcanza.",
            "observations": {"nombre": "Ganic", "error": "saltó años"},
        }, request)
        assert response is not None
        assert response.synthesis.startswith("Lo que llevamos")
        assert response.observations == {"nombre": "Ganic", "error": "saltó años"}

    def test_rejects_non_string_synthesis(self) -> None:
        request = _request()
        assert GuidedResponse.from_provider({
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "¿Qué busca ahora?",
            "synthesis": {"bad": "shape"},
        }, request) is None

    def test_rejects_non_mapping_observations(self) -> None:
        request = _request()
        assert GuidedResponse.from_provider({
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "¿Qué busca ahora?",
            "observations": ["not", "a", "mapping"],
        }, request) is None


class TestCommit:
    def test_commit_persists_synthesis_and_accumulates_observations(self, tmp_path: Path) -> None:
        store = GuidedSessionStore(tmp_path / "guided.sqlite3")
        store.create("s1", "Vibrantes", "auth")
        request = _request(revision=0)
        response = GuidedResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id, 0,
            Outcome.QUESTION, question="¿Qué busca ahora?",
            synthesis="Lo que llevamos: Ganic saltó años.",
            observations={"nombre": "Ganic"},
        )
        state = store.commit(request, response)
        assert state is not None
        assert state.messages[-1].content["synthesis"] == "Lo que llevamos: Ganic saltó años."
        assert state.messages[-1].content["question"] == "¿Qué busca ahora?"
        assert state.candidate.observations == {"nombre": "Ganic"}
        assert state.candidate.proposals == {}
        assert state.candidate.accepted_canon == {}


class TestPublicRendering:
    def test_synthesis_is_rendered_before_the_question(self) -> None:
        text = api_server._guided_message_text({
            "synthesis": "Lo que llevamos: Ganic.",
            "question": "¿Qué busca?",
        })
        assert text == "Lo que llevamos: Ganic.\n\n¿Qué busca?"

    def test_meta_proposals_are_hidden_from_the_author_facing_view(self) -> None:
        candidate = CandidateState(
            proposals={
                "intencion": {"value": "crear un personaje nuevo"},
                "nombre": {"value": "Ganic"},
            }
        )
        public = api_server._public_guided_proposals(candidate)
        assert "intencion" not in public
        assert public["nombre"]["value"] == "Ganic"

    def test_observations_feed_known_state_but_not_public_proposals(self) -> None:
        candidate = CandidateState(observations={"mundo": "Vibrantes"})
        state = SessionState(
            "s", "Vibrantes", "conversation", 1, "auth", candidate=candidate,
        )
        payload = api_server._guided_public_state(state)
        assert payload["candidate"]["proposals"] == {}
        assert payload["proposal"] is None
        known = api_server._guided_known_state(candidate)
        assert "[observed] mundo: Vibrantes" in known

    def test_legacy_question_only_renders_unchanged(self) -> None:
        assert api_server._guided_message_text({"question": "¿Qué busca?"}) == "¿Qué busca?"


class TestKnownState:
    def test_summarizes_accepted_and_proposed_values(self) -> None:
        candidate = CandidateState(
            accepted_canon={"nombre": {"value": "Ganic"}},
            proposals={"error": {"value": "saltó años"}},
            unknowns=["qué busca"],
        )
        text = api_server._guided_known_state(candidate)
        assert "[accepted] nombre: Ganic" in text
        assert "[proposed] error: saltó años" in text
        assert "[unknown] qué busca" in text


class TestWorldLore:
    def test_returns_matching_world_lore(self, monkeypatch) -> None:
        index = _FakeGraph()
        monkeypatch.setattr(api_server, "_get_graph", lambda _mundo: index)
        text = api_server._world_lore_context("Vibrantes", "háblame de Ekkor y su vibrastal")
        assert "Ekkor" in text
        assert "Reino septentrional" in text
        assert index.searches, "the graph must be queried"

    def test_returns_empty_when_nothing_matches(self, monkeypatch) -> None:
        monkeypatch.setattr(api_server, "_get_graph", lambda _mundo: _FakeGraph())
        assert api_server._world_lore_context("Vibrantes", "algo inventado sin lore") == ""

    def test_returns_empty_when_graph_is_unavailable(self, monkeypatch) -> None:
        monkeypatch.setattr(api_server, "_get_graph", lambda _mundo: None)
        assert api_server._world_lore_context("Vibrantes", "Ekkor") == ""

    def test_geography_category_gets_a_verified_section_index(
        self, monkeypatch, tmp_path,
    ) -> None:
        section = (
            tmp_path / "Vibrantes" / "lore"
            / "politica-distribucion-y-territorios"
        )
        section.mkdir(parents=True)
        (section / "politica-distribucion-y-territorios.md").write_text(
            "---\ntitle: Política | Distribución Y Territorios\n"
            "description: Regiones del mundo.\n---\n",
            encoding="utf-8",
        )
        (section / "atherr.md").write_text(
            '---\ntitle: Atherr\ntype: lugar\n'
            'description: "Territorio del nororiente de Vibral."\n---\n',
            encoding="utf-8",
        )
        (section / "pannj.md").write_text(
            '---\ntitle: Pannj\ntype: lugar\ndescription: "Archipiélago vibrante."\n---\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
        monkeypatch.setattr(api_server, "_get_graph", lambda _mundo: None)

        text = api_server._world_lore_context(
            "Vibrantes", "hay paises con sus descripciones, a eso me refiero",
        )
        assert "Atherr" in text
        assert "Pannj" in text
        assert "Territorio del nororiente" in text


class TestRequestValidation:
    def test_world_context_over_budget_is_rejected(self) -> None:
        request = GuidedRequest(
            PROTOCOL_VERSION, "req", "s1", "Vibrantes", 0, "auth", "hi",
            context_budget=10, world_context="x" * 11,
        )
        error = request.validate()
        assert error is not None
        assert error.code.value == "invalid_input"

    def test_known_state_over_budget_is_rejected(self) -> None:
        request = GuidedRequest(
            PROTOCOL_VERSION, "req", "s1", "Vibrantes", 0, "auth", "hi",
            context_budget=10, known_state="x" * 11,
        )
        error = request.validate()
        assert error is not None


def _request(revision: int = 0) -> GuidedRequest:
    return GuidedRequest(
        PROTOCOL_VERSION, "req-1", "s1", "Vibrantes", revision, "auth",
        "háblame de Ekkor",
    )


class _FakeGraph:
    def __init__(self) -> None:
        self.searches: list[str] = []

    def search(self, query: str) -> list[dict[str, object]]:
        self.searches.append(query)
        if "ekkor" in query.casefold() or "vibrastal" in query.casefold():
            return [{
                "name": "Ekkor",
                "title": "Ekkor",
                "description": "Reino septentrional",
                "path": "lore/ekkor.md",
            }]
        return []

    def read(self, path: str) -> dict[str, object] | None:
        if path == "lore/ekkor.md":
            return {
                "name": "Ekkor",
                "type": "Reino",
                "title": "Ekkor",
                "description": "Reino septentrional",
                "content": "El vibrastal define su economía.",
            }
        return None
