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

    def test_accepts_a_bounded_answer_and_the_explore_intent(self) -> None:
        """S2: the exploration answer travels in its own bounded field."""
        request = _request()
        response = GuidedResponse.from_provider({
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "¿Qué deseo le pondrías?",
            "synthesis": "Ekkor queda como reino septentrional.",
            "answer": "Ekkor es un reino septentrional que comercia con Dvins.",
            "intent": "explore",
        }, request)
        assert response is not None
        assert response.answer == "Ekkor es un reino septentrional que comercia con Dvins."
        assert response.intent == "explore"

    def test_unknown_intent_and_non_string_answer_fall_back_to_legacy(self) -> None:
        """S5: fail-safe — an unusable intent/answer never invalidates the turn."""
        request = _request()
        response = GuidedResponse.from_provider({
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "¿Qué busca ahora?",
            "answer": {"bad": "shape"},
            "intent": "invented",
        }, request)
        assert response is not None
        assert response.answer is None
        assert response.intent is None

    def test_answer_is_capped_on_a_word_boundary(self) -> None:
        request = _request()
        response = GuidedResponse.from_provider({
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "question",
            "question": "¿Qué busca ahora?",
            "answer": "palabra " * 400,
            "intent": "explore",
        }, request)
        assert response is not None and response.answer
        assert len(response.answer) <= GuidedResponse.ANSWER_MAX_CHARS
        assert response.answer.endswith("…")
        assert response.answer.rstrip("…").endswith("palabra")


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

    def test_exploration_answer_renders_before_synthesis_and_question(self) -> None:
        """S2: the answer is its own block, never squeezed into the synthesis."""
        text = api_server._guided_message_text({
            "answer": "Ekkor comercia con Dvins desde la fractura.",
            "synthesis": "Ekkor queda como reino septentrional.",
            "question": "¿Qué deseo le pondrías?",
        })
        assert text == (
            "Ekkor comercia con Dvins desde la fractura.\n\n"
            "Ekkor queda como reino septentrional.\n\n"
            "¿Qué deseo le pondrías?"
        )


class TestExploreTurn:
    def test_plan_claimed_keys_are_dropped_and_world_facts_kept(self) -> None:
        """S3: exploring settles nothing, so plan facts never reach the cursor."""
        from guided_character_domain import plan_scoped_observations

        kept = plan_scoped_observations(
            {"deseo": "entiende el mundo a través de Ganic", "mundo": "Vibrantes",
             "oficio": "repara Dvexs"},
            entity_type="personaje",
            nivel="2º",
        )
        assert kept == {"mundo": "Vibrantes"}
        # A flow without a questionnaire plan drops nothing.
        assert plan_scoped_observations(
            {"origen": "un dios"}, entity_type="sistema", nivel="1º",
        ) == {"origen": "un dios"}
        assert plan_scoped_observations({}, entity_type="personaje", nivel="2º") == {}

    def test_explore_turn_answers_without_reaching_canon(self, tmp_path: Path) -> None:
        """S1/S3: the author explores, the cursor keeps its place."""
        import asyncio

        from guided_character_body import current_field
        from guided_character_protocol import MethodologySnapshot, continue_session
        from api_server import GUIDED_CHARACTER_FLOW, builtin_profile

        profile = builtin_profile(GUIDED_CHARACTER_FLOW)
        assert profile is not None
        store = GuidedSessionStore(tmp_path / "guided.sqlite3")
        store.create(
            "s1", "Vibrantes", "auth", path="fields",
            methodology_snapshot=MethodologySnapshot(
                flow_type="guided-character", profile=profile.as_dict(),
            ),
        )
        assert store.set_level("s1", "auth", "2º") is not None
        before = store.recover("s1", "auth")
        assert before is not None
        cursor_before = current_field(before.candidate)[1]

        async def explore(req, _token):
            return {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": req.request_id,
                "session_id": req.session_id,
                "outcome": "question",
                "question": "¿Qué deseo le pondrías?",
                "synthesis": "Ekkor queda como reino septentrional.",
                "answer": "Ekkor comercia con Dvins desde la fractura.",
                "intent": "explore",
                "observations": {"deseo": "entiende el mundo a través de Ganic",
                                 "mundo": "Vibrantes"},
                "delta": {"nombre": "Hesia"},
            }

        from guided_character_protocol import Capabilities
        request = GuidedRequest(
            PROTOCOL_VERSION, "req-1", "s1", "Vibrantes", 0, "auth", "contame del lore de Ekkor",
        )
        response, state = asyncio.run(
            continue_session(store, explore, request, _capabilities())
        )
        assert state is not None
        assert response.answer == "Ekkor comercia con Dvins desde la fractura."
        assert state.pending_question == "¿Qué deseo le pondrías?"
        # Nothing was committed: no proposal, no canon beyond the level.
        assert state.candidate.proposals == {}
        assert state.candidate.accepted_canon.keys() == {"nivel"}
        assert state.candidate.observations == {"mundo": "Vibrantes"}
        assert current_field(state.candidate)[1] == cursor_before

    def test_explore_intent_on_a_delta_is_ignored(self, tmp_path: Path) -> None:
        """S5: only a QUESTION can explore; a delta keeps today's behavior."""
        import asyncio

        from guided_character_protocol import continue_session

        store = GuidedSessionStore(tmp_path / "guided.sqlite3")
        store.create("s1", "Vibrantes", "auth")
        base = store.recover("s1", "auth")
        assert base is not None and base.candidate.proposals == {}

        async def delta_provider(req, _token):
            return {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": req.request_id,
                "session_id": req.session_id,
                "outcome": "delta",
                "intent": "explore",
                "delta": {"nombre": "Hesia"},
            }

        request = GuidedRequest(
            PROTOCOL_VERSION, "req-1", "s1", "Vibrantes", 0, "auth", "se llama Hesia",
        )
        _response, state = asyncio.run(
            continue_session(store, delta_provider, request, _capabilities())
        )
        assert state is not None
        # The gate demotes the incomplete delta into observations, as before.
        assert state.candidate.accepted_canon == {}


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

    def test_family_question_includes_every_stal_archetype(
        self, monkeypatch, tmp_path,
    ) -> None:
        section = (
            tmp_path / "Vibrantes" / "lore" / "sistema-stal-poderes-vibrantes"
        )
        section.mkdir(parents=True)
        (section / "sistema-stal-poderes-vibrantes.md").write_text(
            "---\ntitle: Sistema Stal | Poderes Vibrantes\n"
            "description: Los nueve arquetipos.\n---\n",
            encoding="utf-8",
        )
        for filename, title in (
            ("1er-stal-director", "1er Stal – Director"),
            ("5to-stal-aislador", "5to Stal – Aislador"),
            ("9no-stal-mediador", "9no Stal – Mediador"),
        ):
            (section / f"{filename}.md").write_text(
                f'---\ntitle: {title}\ntype: concepto\n'
                f'description: "Arquetipo del {title}."\n---\n',
                encoding="utf-8",
            )
        monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
        monkeypatch.setattr(api_server, "_get_graph", lambda _mundo: None)

        text = api_server._world_lore_context(
            "Vibrantes", "¿qué Stal crees que vaya bien con su personalidad?",
        )
        assert "5to Stal – Aislador" in text
        assert "9no Stal – Mediador" in text

    def test_multiple_hits_in_one_section_use_the_section_index(
        self, monkeypatch, tmp_path,
    ) -> None:
        section = tmp_path / "Vibrantes" / "lore" / "gremios"
        section.mkdir(parents=True)
        (section / "gremios.md").write_text(
            '---\ntitle: Gremios\ndescription: "Oficios de la ciudad."\n---\n',
            encoding="utf-8",
        )
        for filename, title in (
            ("herreros", "Gremio de Herreros"),
            ("tejedores", "Gremio de Tejedores"),
        ):
            (section / f"{filename}.md").write_text(
                f'---\ntitle: {title}\ntype: organización\n'
                'description: "Gremios de la ciudad."\n---\n',
                encoding="utf-8",
            )

        class _FamilyGraph:
            def search(self, query):
                if "gremio" not in query.casefold():
                    return []
                return [
                    {"name": "Herreros", "title": "Gremio de Herreros",
                     "description": "Gremios de la ciudad.",
                     "path": "lore/gremios/herreros.md"},
                    {"name": "Tejedores", "title": "Gremio de Tejedores",
                     "description": "Gremios de la ciudad.",
                     "path": "lore/gremios/tejedores.md"},
                ]

            def read(self, path):
                return None

        monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
        monkeypatch.setattr(api_server, "_get_graph", lambda _mundo: _FamilyGraph())
        text = api_server._world_lore_context(
            "Vibrantes", "háblame de los gremios de la ciudad",
        )
        assert "Gremio de Herreros" in text
        assert "Gremio de Tejedores" in text

    def test_flat_family_hits_are_all_listed(self, monkeypatch) -> None:
        class _FlatGraph:
            def search(self, query):
                if "gremio" not in query.casefold():
                    return []
                return [
                    {"name": "Herreros", "title": "Gremio de Herreros",
                     "description": "Gremios de la ciudad.",
                     "path": "lore/gremios/herreros.md"},
                    {"name": "Tejedores", "title": "Gremio de Tejedores",
                     "description": "Gremios de la ciudad.",
                     "path": "lore/cofradias/tejedores.md"},
                ]

            def read(self, path):
                return None

        monkeypatch.setattr(api_server, "_get_graph", lambda _mundo: _FlatGraph())
        text = api_server._world_lore_context(
            "Vibrantes", "háblame de los gremios de la ciudad",
        )
        assert "Gremio de Herreros" in text
        assert "Gremio de Tejedores" in text

    def test_unknown_category_gets_the_generic_world_index(
        self, monkeypatch, tmp_path,
    ) -> None:
        section = tmp_path / "Vibrantes" / "lore" / "gremios"
        section.mkdir(parents=True)
        (section / "gremios.md").write_text(
            '---\ntitle: Gremios\ndescription: "Oficios de la ciudad."\n---\n',
            encoding="utf-8",
        )

        class _EmptyGraph:
            def search(self, query):
                return []

            def read(self, path):
                return None

        monkeypatch.setattr(api_server, "MUNDOS_DIR", tmp_path)
        monkeypatch.setattr(api_server, "_get_graph", lambda _mundo: _EmptyGraph())
        text = api_server._world_lore_context(
            "Vibrantes", "¿qué hay de los oficios?",
        )
        assert "Gremios" in text

    def test_lore_query_keeps_the_previous_author_topic(self) -> None:
        class _Message:
            message_type = type("_Type", (), {"value": "author_input"})
            content = {"text": "¿qué Stal crees que vaya bien?"}

        class _State:
            messages = [_Message()]

        query = api_server._guided_lore_query(_State(), "¿personalidad?")
        assert "Stal" in query
        assert "personalidad" in query


class TestGuidedContextBudget:
    def test_lore_plus_memory_stays_within_the_request_budget(self, monkeypatch) -> None:
        monkeypatch.setattr(
            api_server, "_world_lore_context", lambda *_args, **_kwargs: "L" * 3_000,
        )
        monkeypatch.setattr(
            api_server, "_memory_context", lambda *_args, **_kwargs: "M" * 1_000,
        )
        text = api_server._guided_world_context("Vibrantes", None, "hola")
        assert len(text) <= api_server.GUIDED_CONTEXT_BUDGET
        assert "M" in text


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


def _capabilities():
    from guided_character_protocol import Capabilities, MAX_DEADLINE_MS

    return Capabilities(PROTOCOL_VERSION, True, True, True, MAX_DEADLINE_MS)


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


class TestTurnDirective:
    """S2/S3/S4: one decision per turn, recorded and rendered — never recomputed."""

    @staticmethod
    def _snapshot():
        from api_server import GUIDED_CHARACTER_FLOW, builtin_profile
        from guided_character_protocol import MethodologySnapshot

        profile = builtin_profile(GUIDED_CHARACTER_FLOW)
        assert profile is not None
        return MethodologySnapshot(flow_type="guided-character", profile=profile.as_dict())

    def _progress(self, key: str, label: str, index: int = 1, total: int = 21) -> dict:
        return {
            "nivel": "2º", "index": index, "total": total, "key": key, "label": label,
            "hint": "Un sobrenombre que diga algo.", "examples": ["Dos Llaves"],
            "optional": False, "covered": [], "skipped": [], "complete": False,
        }

    def _fields_request(self, revision: int, field_key: str, progress: dict, text="Hesia"):
        return GuidedRequest(
            PROTOCOL_VERSION, "req-1", "s-fields", "Vibrantes", revision, "auth", text,
            guided_path="fields", field_key=field_key, field_progress=progress,
        )

    def _explore_request(self, revision: int, text="sigo"):
        return GuidedRequest(
            PROTOCOL_VERSION, "req-1", "s-explore", "Vibrantes", revision, "auth", text,
        )

    def test_a_field_question_turn_records_the_served_decision(self, tmp_path: Path) -> None:
        import asyncio

        from guided_character_protocol import continue_session

        store = GuidedSessionStore(tmp_path / "g.sqlite3")
        store.create(
            "s-fields", "Vibrantes", "auth", path="fields",
            methodology_snapshot=self._snapshot(),
        )
        progress = self._progress("apodo", "Apodo", index=2)

        async def provider(req, _token):
            return {
                "protocol_version": PROTOCOL_VERSION, "request_id": req.request_id,
                "session_id": req.session_id, "outcome": "question",
                "question": "¿Cómo le dicen en el mundo?",
                "field_key": "apodo",
                "observations": {"apodo": "Dos Llaves"},
            }

        response, state = asyncio.run(
            continue_session(store, provider, self._fields_request(0, "apodo", progress), _capabilities())
        )
        assert state is not None and state.turn_decision is not None
        decision = state.turn_decision
        assert decision.kind == "field"
        assert decision.field_key == "apodo"
        assert decision.question == "¿Cómo le dicen en el mundo?"
        assert decision.source == "provider"
        assert decision.field_progress == progress
        payload = api_server._guided_public_state(state)
        assert payload["pending_question"] == decision.question
        assert payload["field_progress"] == decision.field_progress

    def test_provider_drift_keeps_the_extraction_and_serves_the_field_question(
        self, tmp_path: Path,
    ) -> None:
        """S4: told Apodo, answered about Deseo => fallback question, same facts."""
        import asyncio

        from guided_character_protocol import continue_session

        store = GuidedSessionStore(tmp_path / "g.sqlite3")
        store.create(
            "s-fields", "Vibrantes", "auth", path="fields",
            methodology_snapshot=self._snapshot(),
        )
        progress = self._progress("apodo", "Apodo", index=2)

        async def provider(req, _token):
            return {
                "protocol_version": PROTOCOL_VERSION, "request_id": req.request_id,
                "session_id": req.session_id, "outcome": "question",
                "question": "¿Cuál es el deseo que define a este personaje?",
                "field_key": "deseo",
                "observations": {"apodo": "Dos Llaves"},
            }

        _response, state = asyncio.run(
            continue_session(store, provider, self._fields_request(0, "apodo", progress), _capabilities())
        )
        assert state is not None and state.turn_decision is not None
        assert state.turn_decision.source == "server"
        assert "Apodo" in state.turn_decision.question
        assert "Deseo" not in state.turn_decision.question
        # The extraction survives: drifting never costs the author a fact.
        assert state.candidate.observations["apodo"] == "Dos Llaves"

    def test_missing_echo_counts_as_drift(self, tmp_path: Path) -> None:
        import asyncio

        from guided_character_protocol import continue_session

        store = GuidedSessionStore(tmp_path / "g.sqlite3")
        store.create(
            "s-fields", "Vibrantes", "auth", path="fields",
            methodology_snapshot=self._snapshot(),
        )
        progress = self._progress("edad", "Edad", index=3)

        async def provider(req, _token):
            return {
                "protocol_version": PROTOCOL_VERSION, "request_id": req.request_id,
                "session_id": req.session_id, "outcome": "question",
                "question": "¿Cuántos años tiene?",
            }

        _response, state = asyncio.run(
            continue_session(store, provider, self._fields_request(0, "edad", progress), _capabilities())
        )
        assert state is not None and state.turn_decision is not None
        assert state.turn_decision.source == "server"
        assert "Edad" in state.turn_decision.question

    def test_free_turn_records_no_field_and_no_field_progress(self, tmp_path: Path) -> None:
        import asyncio

        from guided_character_protocol import continue_session

        store = GuidedSessionStore(tmp_path / "g.sqlite3")
        store.create("s-explore", "Vibrantes", "auth")

        async def provider(req, _token):
            return {
                "protocol_version": PROTOCOL_VERSION, "request_id": req.request_id,
                "session_id": req.session_id, "outcome": "question",
                "question": "¿Qué lo mueve?",
            }

        _response, state = asyncio.run(
            continue_session(store, provider, self._explore_request(0), _capabilities())
        )
        assert state is not None and state.turn_decision is not None
        assert state.turn_decision.kind == "free"
        payload = api_server._guided_public_state(state)
        assert "field_progress" not in payload
        assert payload["pending_question"] == "¿Qué lo mueve?"

    def test_legacy_session_without_a_decision_keeps_todays_derivation(self) -> None:
        """M7: an existing row has no record; the payload still shows a cursor."""
        candidate = CandidateState(observations={"nombre": "Hesia"})
        state = SessionState(
            "legacy", "Vibrantes", "conversation", 4, "auth",
            candidate=candidate, path="fields", pending_question="¿Apodo?",
            # S6: the store backfills settlement for a pre-change row, so the
            # derived cursor matches the question that was already served.
            settled_fields=["nombre"],
            methodology_snapshot=self._snapshot(),
        )
        payload = api_server._guided_public_state(state)
        assert payload["field_progress"]["key"] == "apodo"
        assert payload["pending_question"] == "¿Apodo?"
