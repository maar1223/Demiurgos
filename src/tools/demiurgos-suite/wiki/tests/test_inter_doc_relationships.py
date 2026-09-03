# -*- coding: utf-8 -*-
"""Inter-document relationship post-process tests (unit + integration).

Unit coverage (PR 1 slice): candidate generation (id/name/tags+type grouping,
cross-document filter, max_pairs cap), prompt payload shape/vocab, response
parsing, relationship write-back (idempotency, body preservation, bidirectional
write), and ``run_post_process`` fail-open behavior.

Integration coverage (PR 2 slice): the ``execute()`` auto-trigger hook, the
manual reconcile endpoint (shape + idempotent re-call), and the ``referencias``
graph-indexing fix.
"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_enrichment import _REL_VOCAB_DEFAULT  # noqa: E402
import api_server  # noqa: E402
from inter_doc_relationships import (  # noqa: E402
    PostProcessResult,
    _append_relaciones,
    _build_pair_prompt,
    _candidate_pairs,
    _direction_pair,
    _extract_relaciones,
    _parse_relationship_response,
    _write_relationship,
    run_post_process,
)


def _entity(path, *, cid="", name="", etype="personaje", tags=(), description="",
            relaciones=()):
    """Build an entity dict matching the EntityGraphIndex cache shape."""
    return {
        "name": name,
        "id": cid,
        "status": "draft",
        "type": etype,
        "path": path,
        "title": name,
        "description": description,
        "tags": list(tags),
        "forward_links": [],
        "backlinks": [],
        "relaciones": list(relaciones),
        "content": "",
        "word_count": 0,
    }


class _StubGraph:
    """Minimal EntityGraphIndex stand-in: entities cache + update_many spy."""

    def __init__(self, entities, mundos_path):
        self._cache = {"entities": entities}
        self._mundos_path = Path(mundos_path)
        self.updated: list[tuple[list[str], str]] = []

    def _path_from_absolute(self, abs_path, mundo):
        try:
            return str(Path(abs_path).relative_to(self._mundos_path / mundo)).replace("\\", "/")
        except ValueError:
            return None

    def update_many(self, paths, mundo):
        self.updated.append((list(paths), mundo))
        return None


# ---------------------------------------------------------------------------
# _candidate_pairs
# ---------------------------------------------------------------------------

class TestCandidatePairs:
    def test_matching_by_canonical_id_across_documents(self):
        entities = {
            "lore/a.md": _entity("lore/a.md", cid="World::A", name="A"),
            "personajes/b.md": _entity("personajes/b.md", cid="World::A", name="B"),
        }
        pairs = _candidate_pairs(entities)
        assert len(pairs) == 1
        a, b, signal = pairs[0]
        assert signal == "id"
        assert {a["path"], b["path"]} == {"lore/a.md", "personajes/b.md"}

    def test_same_document_pairs_excluded(self):
        entities = {
            "lore/a.md": _entity("lore/a.md", cid="World::A", name="A"),
            "lore/a2.md": _entity("lore/a2.md", cid="World::A", name="A2"),
        }
        assert _candidate_pairs(entities) == []

    def test_matching_by_normalized_name_across_documents(self):
        entities = {
            "lore/rhyz.md": _entity("lore/rhyz.md", name="Rhyz_El_Resonante"),
            "personajes/rhyz.md": _entity("personajes/rhyz.md", name="rhyz el resonante"),
        }
        pairs = _candidate_pairs(entities)
        assert len(pairs) == 1
        assert pairs[0][2] == "name"

    def test_matching_by_shared_tags_and_type(self):
        entities = {
            "lore/a.md": _entity("lore/a.md", etype="criatura", tags=["vibrante"], name="A"),
            "personajes/b.md": _entity("personajes/b.md", etype="criatura", tags=["vibrante"], name="B"),
        }
        pairs = _candidate_pairs(entities)
        assert len(pairs) == 1
        assert pairs[0][2] == "tags+type"

    def test_different_type_never_candidates_on_tags(self):
        entities = {
            "lore/a.md": _entity("lore/a.md", etype="criatura", tags=["vibrante"], name="A"),
            "personajes/b.md": _entity("personajes/b.md", etype="personaje", tags=["vibrante"], name="B"),
        }
        assert _candidate_pairs(entities) == []

    def test_no_plausible_matches_produce_no_candidates(self):
        entities = {
            "lore/a.md": _entity("lore/a.md", cid="World::A", name="Alpha",
                                 etype="criatura", tags=["x"]),
            "personajes/b.md": _entity("personajes/b.md", cid="World::B", name="Beta",
                                       etype="personaje", tags=["y"]),
        }
        assert _candidate_pairs(entities) == []

    def test_max_pairs_cap_keeps_strongest_signals(self):
        entities = {
            f"lore/name{i}.md": _entity(
                f"lore/name{i}.md", name=f"Shared Name {i}") for i in range(5)
        }
        entities.update({
            f"personajes/name{i}.md": _entity(
                f"personajes/name{i}.md", name=f"Shared Name {i}") for i in range(5)
        })
        entities["personajes/dup.md"] = _entity(
            "personajes/dup.md", cid="World::SAME", name="Dup")
        entities["referencias/dup.md"] = _entity(
            "referencias/dup.md", cid="World::SAME", name="Dup")
        # 5 name pairs (signal "name") + 1 id pair (signal "id"); cap at 3.
        pairs = _candidate_pairs(entities, max_pairs=3)
        assert len(pairs) == 3
        # The id pair (strongest signal) must be first.
        assert pairs[0][2] == "id"
        assert {p[2] for p in pairs} <= {"id", "name"}

    def test_dedupe_keeps_strongest_signal_for_same_pair(self):
        entities = {
            "lore/a.md": _entity("lore/a.md", cid="World::A", name="A", tags=["t"], etype="criatura"),
            "personajes/a.md": _entity("personajes/a.md", cid="World::A", name="A", tags=["t"], etype="criatura"),
        }
        pairs = _candidate_pairs(entities)
        assert len(pairs) == 1
        assert pairs[0][2] == "id"  # id outranks name and tags+type


# ---------------------------------------------------------------------------
# _build_pair_prompt / _parse_relationship_response / _direction_pair
# ---------------------------------------------------------------------------

class TestBuildPairPrompt:
    def test_payload_shape(self):
        a = _entity("lore/a.md", cid="World::A", name="A", etype="criatura",
                    tags=["vibrante"], description="desc")
        b = _entity("personajes/b.md", cid="World::B", name="B")
        payload = _build_pair_prompt(a, b)
        assert set(payload) == {"entity_a", "entity_b", "rel_vocab", "instructions"}
        assert payload["entity_a"] == {
            "id": "World::A", "name": "A", "type": "criatura",
            "description": "desc", "tags": ["vibrante"],
        }
        assert payload["entity_b"]["id"] == "World::B"

    def test_vocab_inclusion_sorted(self):
        a = _entity("lore/a.md", name="A")
        b = _entity("personajes/b.md", name="B")
        payload = _build_pair_prompt(a, b)
        assert payload["rel_vocab"] == sorted(_REL_VOCAB_DEFAULT)

    def test_description_truncated_to_budget(self):
        long_desc = "x" * 500
        a = _entity("lore/a.md", name="A", description=long_desc)
        b = _entity("personajes/b.md", name="B")
        payload = _build_pair_prompt(a, b)
        assert len(payload["entity_a"]["description"]) == 200


class TestParseRelationshipResponse:
    def test_valid_json(self):
        raw = json.dumps({"relationship_type": "crea", "direction": "a_to_b"})
        assert _parse_relationship_response(raw) == ("crea", "a_to_b")

    def test_fenced_json(self):
        raw = '```json\n{"relationship_type": "aliado-de", "direction": "bidirectional"}\n```'
        assert _parse_relationship_response(raw) == ("aliado-de", "bidirectional")

    def test_null_relationship(self):
        assert _parse_relationship_response('{"relationship_type": null, "direction": "a_to_b"}') == (None, "a_to_b")

    def test_invalid_direction_defaults_to_a_to_b(self):
        assert _parse_relationship_response('{"relationship_type": "crea", "direction": "sideways"}') == ("crea", "a_to_b")

    def test_garbage_returns_none(self):
        assert _parse_relationship_response("not json at all") == (None, None)
        assert _parse_relationship_response("") == (None, None)
        assert _parse_relationship_response(None) == (None, None)


class TestDirectionPair:
    def test_a_to_b_crea_mirrors_to_creado_por(self):
        assert _direction_pair("crea", "a_to_b") == ("crea", "creado-por")

    def test_bidirectional_uses_relacionado_con(self):
        assert _direction_pair("aliado-de", "bidirectional") == ("relacionado-con", "relacionado-con")

    def test_b_to_a_swaps(self):
        assert _direction_pair("crea", "b_to_a") == ("creado-por", "crea")


# ---------------------------------------------------------------------------
# _write_relationship
# ---------------------------------------------------------------------------

class TestWriteRelationship:
    def _ficha(self, tmp_path, rel, relaciones=()):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["---", "id: \"World::X\"", "title: X", "type: personaje",
                 "status: draft"]
        if relaciones:
            lines.append("relaciones:")
            lines.extend(f'  - "[[{r}]]"' for r in relaciones)
        lines.append("---")
        lines.append("")
        lines.append("# Body line one")
        lines.append("Body line two")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_bidirectional_write_patches_both_fichas(self, tmp_path):
        a = self._ficha(tmp_path, "lore/a.md")
        b = self._ficha(tmp_path, "personajes/b.md")
        changed = _write_relationship(a, b, "aliado-de", "bidirectional",
                                      "World::A", "World::B")
        assert sorted(changed) == sorted([str(a), str(b)])
        assert '  - "[[World::B]]"' in a.read_text(encoding="utf-8")
        assert '  - "[[World::A]]"' in b.read_text(encoding="utf-8")

    def test_idempotent_second_run_writes_nothing(self, tmp_path):
        a = self._ficha(tmp_path, "lore/a.md")
        b = self._ficha(tmp_path, "personajes/b.md")
        _write_relationship(a, b, "aliado-de", "bidirectional", "World::A", "World::B")
        changed = _write_relationship(a, b, "aliado-de", "bidirectional",
                                      "World::A", "World::B")
        assert changed == []
        content = a.read_text(encoding="utf-8")
        assert content.count('"[[World::B]]"') == 1

    def test_body_preserved_verbatim(self, tmp_path):
        a = self._ficha(tmp_path, "lore/a.md")
        b = self._ficha(tmp_path, "personajes/b.md")
        _write_relationship(a, b, "crea", "a_to_b", "World::A", "World::B")
        content = a.read_text(encoding="utf-8")
        assert "# Body line one" in content
        assert "Body line two" in content
        # The body text is unchanged; only the frontmatter gained a line.
        assert content.rstrip("\n").endswith("Body line two")

    def test_flow_form_relaciones_normalized_on_patch(self, tmp_path):
        path = tmp_path / "lore/a.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '---\nid: "World::A"\ntitle: A\ntype: personaje\nstatus: draft\n'
            "relaciones: [\"[[World::OLD]]\"]\n---\n\nBody\n",
            encoding="utf-8",
        )
        b = self._ficha(tmp_path, "personajes/b.md")
        _write_relationship(path, b, "aliado-de", "bidirectional",
                            "World::A", "World::B")
        content = path.read_text(encoding="utf-8")
        assert '"[[World::OLD]]"' in content
        assert '"[[World::B]]"' in content
        assert content.count("relaciones:") == 1

    def test_missing_relaciones_header_appends_section(self, tmp_path):
        path = tmp_path / "lore/a.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '---\nid: "World::A"\ntitle: A\ntype: personaje\nstatus: draft\n---\n\nBody\n',
            encoding="utf-8",
        )
        b = self._ficha(tmp_path, "personajes/b.md")
        _write_relationship(path, b, "aliado-de", "bidirectional",
                            "World::A", "World::B")
        content = path.read_text(encoding="utf-8")
        assert "relaciones:" in content
        assert '  - "[[World::B]]"' in content

    def test_extract_relaciones_handles_both_forms(self):
        block = 'id: "X"\nrelaciones:\n  - "[[World::A]]"\n  - "[[World::B]]"\nstatus: draft'
        assert _extract_relaciones(block) == ["World::A", "World::B"]
        flow = 'id: "X"\nrelaciones: ["[[World::A]]", "[[World::B]]"]\nstatus: draft'
        assert _extract_relaciones(flow) == ["World::A", "World::B"]

    def test_append_relaciones_idempotent_entries(self):
        block = 'id: "X"\nrelaciones:\n  - "[[World::A]]"'
        patched = _append_relaciones(block, ["World::A"])
        assert patched.count('"[[World::A]]"') == 1


# ---------------------------------------------------------------------------
# run_post_process (fail-open)
# ---------------------------------------------------------------------------

class TestRunPostProcess:
    def test_no_hermes_runner_returns_empty(self, tmp_path):
        entities = {
            "lore/a.md": _entity("lore/a.md", cid="World::A", name="A"),
            "personajes/b.md": _entity("personajes/b.md", cid="World::A", name="B"),
        }
        graph = _StubGraph(entities, tmp_path)
        result = run_post_process("world", graph, hermes_runner=None)
        assert result == PostProcessResult(pairs_evaluated=0, relationships_written=0)

    def test_raising_hermes_runner_fails_open(self, tmp_path):
        entities = {
            "lore/a.md": _entity("lore/a.md", cid="World::A", name="A"),
            "personajes/b.md": _entity("personajes/b.md", cid="World::A", name="B"),
        }
        graph = _StubGraph(entities, tmp_path)

        def boom(_prompt, _session):
            raise RuntimeError("gateway down")

        result = run_post_process("world", graph, hermes_runner=boom)
        assert result.pairs_evaluated == 1  # pair was attempted
        assert result.relationships_written == 0
        assert result.fichas_modified == []

    def test_null_relationship_skips_pair(self, tmp_path):
        entities = {
            "lore/a.md": _entity("lore/a.md", cid="World::A", name="A"),
            "personajes/b.md": _entity("personajes/b.md", cid="World::A", name="B"),
        }
        graph = _StubGraph(entities, tmp_path)
        runner = lambda _p, _s: json.dumps({"relationship_type": None, "direction": "a_to_b"})
        result = run_post_process("world", graph, hermes_runner=runner)
        assert result.pairs_evaluated == 1
        assert result.relationships_written == 0

    def test_out_of_vocabulary_type_skipped(self, tmp_path):
        entities = {
            "lore/a.md": _entity("lore/a.md", cid="World::A", name="A"),
            "personajes/b.md": _entity("personajes/b.md", cid="World::A", name="B"),
        }
        graph = _StubGraph(entities, tmp_path)
        runner = lambda _p, _s: json.dumps({"relationship_type": "odio-con", "direction": "a_to_b"})
        result = run_post_process("world", graph, hermes_runner=runner)
        assert result.pairs_evaluated == 1
        assert result.relationships_written == 0

    def test_happy_path_writes_relationships_and_reconciles(self, tmp_path):
        world = tmp_path / "world"
        a = world / "lore" / "a.md"
        b = world / "personajes" / "b.md"
        a.parent.mkdir(parents=True, exist_ok=True)
        b.parent.mkdir(parents=True, exist_ok=True)
        a.write_text('---\nid: "World::A"\ntitle: A\ntype: personaje\nstatus: draft\n---\n\nBody A\n', encoding="utf-8")
        b.write_text('---\nid: "World::A"\ntitle: B\ntype: personaje\nstatus: draft\n---\n\nBody B\n', encoding="utf-8")

        from wiki.graph_indexer import EntityGraphIndex
        graph = EntityGraphIndex(mundos_path=tmp_path)
        graph.build("world")

        runner = lambda _p, _s: json.dumps({"relationship_type": "aliado-de", "direction": "bidirectional"})
        result = run_post_process("world", graph, hermes_runner=runner)
        assert result.pairs_evaluated == 1
        assert result.relationships_written == 2
        assert sorted(result.fichas_modified) == ["lore/a.md", "personajes/b.md"]
        # Graph cache reconciled: both entities now carry the new forward link.
        ent_a = graph.get_entity("lore/a.md")
        assert ent_a is not None and "World::A" in ent_a.forward_links

    def test_empty_entities_returns_empty(self, tmp_path):
        graph = _StubGraph({}, tmp_path)
        result = run_post_process("world", graph, hermes_runner=lambda _p, _s: "x")
        assert result == PostProcessResult(pairs_evaluated=0, relationships_written=0)


# ---------------------------------------------------------------------------
# Integration — execute() auto-trigger hook
# ---------------------------------------------------------------------------

class TestExecuteHookIntegration:
    def test_execute_triggers_post_process_after_reconcile(self, tmp_path):
        from import_models import (
            Candidate,
            ImportJob,
            ImportJobState,
            Provenance,
            utcnow_iso,
        )
        from import_store import ImportJobStore
        from import_service import ImportService

        store = ImportJobStore(":memory:")
        (tmp_path / "world1" / "lore").mkdir(parents=True, exist_ok=True)
        triggered: list[str] = []
        service = ImportService(
            store=store, mundos_dir=tmp_path, spool_dir=tmp_path / "spool",
            inter_doc_post_process=lambda mundo: triggered.append(mundo),
        )
        job = ImportJob(
            job_id="job1", world="world1", owner_principal="tester",
            state=ImportJobState.REVIEW, source_kind="loose",
            opaque_token="tok", created_at=utcnow_iso(), updated_at=utcnow_iso(),
        )
        store.create_job(job)
        store.add_candidate(Candidate(
            candidate_id="cand-A", job_id="job1", world="world1",
            normalized_identity="A", source_hash="sha256:A",
            provenance=Provenance(source_path="lore/A.md", source_kind="loose",
                                  source_hash="sha256:A"),
            content_preview="---\ntype: personaje\nname: A\n---\nA body",
            images=[], replacement=None,
        ))
        approval = service.issue_approval(job, "tester", [])
        outcomes = service.execute(job, "tester", approval.digest, approval.token)
        assert outcomes[0].written
        assert triggered == ["world1"]
        assert store.get_job("job1").state == ImportJobState.COMPLETED

    def test_execute_never_fails_when_post_process_raises(self, tmp_path):
        from import_models import (
            Candidate,
            ImportJob,
            ImportJobState,
            Provenance,
            utcnow_iso,
        )
        from import_store import ImportJobStore
        from import_service import ImportService

        store = ImportJobStore(":memory:")
        (tmp_path / "world1" / "lore").mkdir(parents=True, exist_ok=True)
        service = ImportService(
            store=store, mundos_dir=tmp_path, spool_dir=tmp_path / "spool",
            inter_doc_post_process=lambda mundo: (_ for _ in ()).throw(
                RuntimeError("boom")),
        )
        job = ImportJob(
            job_id="job1", world="world1", owner_principal="tester",
            state=ImportJobState.REVIEW, source_kind="loose",
            opaque_token="tok", created_at=utcnow_iso(), updated_at=utcnow_iso(),
        )
        store.create_job(job)
        store.add_candidate(Candidate(
            candidate_id="cand-A", job_id="job1", world="world1",
            normalized_identity="A", source_hash="sha256:A",
            provenance=Provenance(source_path="lore/A.md", source_kind="loose",
                                  source_hash="sha256:A"),
            content_preview="---\ntype: personaje\nname: A\n---\nA body",
            images=[], replacement=None,
        ))
        approval = service.issue_approval(job, "tester", [])
        outcomes = service.execute(job, "tester", approval.digest, approval.token)
        assert outcomes[0].written
        # Post-process failure is an observability event, never a job failure.
        assert store.get_job("job1").state == ImportJobState.COMPLETED
        rows = store._conn.execute(
            "SELECT event FROM events WHERE job_id='job1'").fetchall()
        assert "inter_doc_post_process_failed" in {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Integration — manual reconcile endpoint
# ---------------------------------------------------------------------------

class TestEndpointIntegration:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        import api_server
        from fastapi.testclient import TestClient

        mundos = tmp_path / "mundos"
        world = mundos / "test_mundo"
        (world / "lore").mkdir(parents=True)
        (world / "personajes").mkdir(parents=True)
        (world / "referencias").mkdir(parents=True)
        (world / "lore" / "dvin.md").write_text(
            '---\nid: "Mundo::Dvin"\ntitle: Dvin\ntype: concepto\nstatus: draft\n'
            "description: Estado resonante de un enlace vibrante.\n"
            "tags: [vibrante]\n---\n\n# Dvin\n\nCuerpo del dvin.\n",
            encoding="utf-8",
        )
        (world / "personajes" / "stal.md").write_text(
            '---\nid: "Mundo::Stal"\ntitle: Stal\ntype: concepto\nstatus: draft\n'
            "description: Clasificacion de poder vibrante.\n"
            "tags: [vibrante]\n---\n\n# Stal\n\nCuerpo del stal.\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
        monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
        monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
        monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", None)
        api_server._graph_indices.clear()
        api_server._confirmation_store.clear()
        api_server._GUIDED_PENDING_PROPOSALS.clear()
        api_server._GUIDED_INDEX_REQUESTS.clear()
        api_server._METHODOLOGY_LIBRARY = None
        api_server._METHODOLOGY_QUARANTINE = None
        with api_server._local_session_lock:
            api_server._local_sessions.clear()
        api_server._target_locks.clear()

        scripted = {
            "relationship_type": "relacionado-con",
            "direction": "bidirectional",
        }
        monkeypatch.setattr(
            api_server, "_sync_hermes_enricher",
            lambda _prompt, _session: json.dumps(scripted),
        )
        return TestClient(api_server.app, client=("127.0.0.1", 50000))

    def test_endpoint_returns_expected_shape_and_is_idempotent(self, client):
        first = client.post("/api/worlds/test_mundo/relationships/reconcile")
        assert first.status_code == 200
        body = first.json()
        assert set(body) == {"status", "pairs_evaluated", "relationships_written"}
        assert body["status"] == "ok"
        assert body["pairs_evaluated"] >= 1
        assert body["relationships_written"] >= 2

        second = client.post("/api/worlds/test_mundo/relationships/reconcile")
        assert second.status_code == 200
        second_body = second.json()
        assert second_body["status"] == "ok"
        assert second_body["relationships_written"] == 0  # idempotent re-call

    def test_endpoint_writes_bidirectional_links_to_both_fichas(self, client):
        client.post("/api/worlds/test_mundo/relationships/reconcile")
        dvin = (Path(api_server.MUNDOS_DIR) / "test_mundo" / "lore" / "dvin.md")
        stal = (Path(api_server.MUNDOS_DIR) / "test_mundo" / "personajes" / "stal.md")
        assert '"[[Mundo::Stal]]"' in dvin.read_text(encoding="utf-8")
        assert '"[[Mundo::Dvin]]"' in stal.read_text(encoding="utf-8")

    def test_endpoint_404_for_missing_world(self, client):
        resp = client.post("/api/worlds/no_such_world/relationships/reconcile")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Integration — referencias section indexing
# ---------------------------------------------------------------------------

class TestReferenciasIndexIntegration:
    def test_referencias_fichas_indexed_as_graph_entities(self, tmp_path):
        from wiki.graph_indexer import EntityGraphIndex

        world = tmp_path / "mundo"
        (world / "lore").mkdir(parents=True)
        (world / "personajes").mkdir(parents=True)
        (world / "referencias").mkdir(parents=True)
        (world / "lore" / "a.md").write_text(
            '---\nid: "Mundo::A"\ntitle: A\ntype: personaje\nstatus: draft\n---\n\nBody A\n',
            encoding="utf-8",
        )
        (world / "referencias" / "ref.md").write_text(
            '---\nid: "Mundo::Ref"\ntitle: Ref\ntype: concepto\nstatus: draft\n---\n\nBody Ref\n',
            encoding="utf-8",
        )
        graph = EntityGraphIndex(mundos_path=tmp_path)
        count = graph.build("mundo")
        assert count == 2
        assert graph.get_entity("lore/a.md") is not None
        ref = graph.get_entity("referencias/ref.md")
        assert ref is not None
        assert ref.id == "Mundo::Ref"