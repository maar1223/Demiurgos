# -*- coding: utf-8 -*-
"""Grounded relation extraction — importer relations must come from the body.

The defect this covers (odd/tasks/importer-relaciones-grounding.md, L1/L4):
relations used to be generated from batch summaries, producing complete graphs
for batch mates and empty lists for single-ficha documents.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _path in (str(_WIKI), str(_SUITE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import import_service
from import_models import (
    Candidate,
    FrontmatterCandidate,
    FrontmatterState,
    ImportJob,
    ImportJobState,
    Provenance,
    utcnow_iso,
)
from import_relations import (
    GroundedRelation,
    RelationTarget,
    build_relation_targets,
    grounded_relations,
    relation_quality,
)
from import_service import ImportService
from import_store import ImportJobStore
from relation_candidates import scan_candidates
from relation_evidence import load_evidence
from relation_state import load_state

HUB_A = RelationTarget(
    canonical_id="Familia A",
    name="Familia A",
    path="lore/familia-a/familia-a.md",
)
A_ONE = RelationTarget(
    canonical_id="Familia A::Elemento 1",
    name="Elemento 1",
    path="lore/familia-a/elemento-1.md",
)
A_TWO = RelationTarget(
    canonical_id="Familia A::Elemento 2",
    name="Elemento 2",
    path="lore/familia-a/elemento-2.md",
)
A_THREE = RelationTarget(
    canonical_id="Familia A::Elemento 3",
    name="Elemento 3",
    path="lore/familia-a/elemento-3.md",
)

HUB_B = RelationTarget(
    canonical_id="Familia B",
    name="Familia B",
    path="lore/familia-b/familia-b.md",
)
B_ONE = RelationTarget(
    canonical_id="Familia B::Elemento 1 – Enlace",
    name="Elemento 1 – Enlace",
    path="lore/familia-b/elemento-1-enlace.md",
)
B_TWO = RelationTarget(
    canonical_id="Familia B::Elemento 2 – Impulso",
    name="Elemento 2 – Impulso",
    path="lore/familia-b/elemento-2-impulso.md",
)


def test_siblings_without_mentions_produce_no_clique():
    # The old defect: a batch of siblings linked every pair. Nothing in the
    # body names the others, so nothing may be written.
    relations = grounded_relations(
        body="El Elemento 2 estabiliza las vibraciones de su entorno.",
        source_id=A_TWO.canonical_id,
        source_path=A_TWO.path,
        targets=[HUB_A, A_ONE, A_THREE],
        max_relations=12,
    )

    # Only the folder index (belonging), never the siblings.
    assert relations == [
        GroundedRelation(canonical_id=HUB_A.canonical_id, evidence="folder-index")
    ]


def test_only_the_mentioned_sibling_is_linked():
    body = "Como el Elemento 3, este Elemento 2 canaliza la energía."
    relations = grounded_relations(
        body=body,
        source_id=A_TWO.canonical_id,
        source_path=A_TWO.path,
        targets=[HUB_A, A_ONE, A_THREE],
    )

    assert relations == [
        GroundedRelation(
            canonical_id=A_THREE.canonical_id,
            evidence="full-name",
        ),
        GroundedRelation(canonical_id=HUB_A.canonical_id, evidence="folder-index"),
    ]


def test_the_folder_index_is_derived_from_the_path():
    relations = grounded_relations(
        body="Un elemento cualquiera.",
        source_id=A_TWO.canonical_id,
        source_path=A_TWO.path,
        targets=[HUB_A, A_ONE, A_THREE],
    )

    assert relations == [
        GroundedRelation(canonical_id=HUB_A.canonical_id, evidence="folder-index")
    ]


def test_the_folder_index_lists_its_members():
    other_folder = RelationTarget(
        canonical_id="Otro::Fuera",
        name="Fuera",
        path="lore/otro/fuera.md",
    )
    relations = grounded_relations(
        body="Índice de la familia.",
        source_id=HUB_A.canonical_id,
        source_path=HUB_A.path,
        targets=[A_ONE, A_TWO, A_THREE, other_folder],
    )

    assert [relation.canonical_id for relation in relations] == [
        A_ONE.canonical_id,
        A_TWO.canonical_id,
        A_THREE.canonical_id,
    ]
    assert all(relation.evidence == "folder-index" for relation in relations)


def test_alias_after_a_dash_is_evidence():
    body = "Su vínculo con el Enlace es profundo."
    relations = grounded_relations(
        body=body,
        source_id=B_TWO.canonical_id,
        source_path=B_TWO.path,
        targets=[B_ONE],
    )

    assert relations == [
        GroundedRelation(canonical_id=B_ONE.canonical_id, evidence="alias")
    ]


def test_filename_stem_token_is_evidence():
    target = RelationTarget(
        canonical_id="Grupo::Elemento Bravo",
        name="Elemento Bravo",
        path="lore/grupo/elemento-bravo.md",
    )
    body = "El término bravo busca autonomía."
    relations = grounded_relations(
        body=body,
        source_id="Grupo::Elemento Alfa",
        source_path="lore/grupo/elemento-alfa.md",
        targets=[target],
    )

    assert relations == [
        GroundedRelation(canonical_id=target.canonical_id, evidence="stem")
    ]


def test_generic_tokens_are_not_evidence():
    # "elemento" is shared by the source folder; it must not link the whole
    # family. Only a distinctive token can.
    target = RelationTarget(
        canonical_id="Grupo::Elemento Zeta",
        name="Elemento Zeta",
        path="lore/grupo/elemento-zeta.md",
    )
    relations = grounded_relations(
        body="Este elemento describe un temperamento calmado.",
        source_id="Grupo::Elemento Eta",
        source_path="lore/grupo/elemento-eta.md",
        targets=[target],
    )

    assert relations == []


def test_ordinal_evidence():
    target = RelationTarget(
        canonical_id="Escala::3er Nivel – Ascendente",
        name="3er Nivel – Ascendente",
        path="lore/escala/3er-nivel.md",
    )
    relations = grounded_relations(
        body="El 3er nivel proyecta la energía hacia el entorno.",
        source_id="Escala::1er Nivel – Base",
        source_path="lore/escala/1er-nivel.md",
        targets=[target],
    )

    assert relations == [
        GroundedRelation(canonical_id=target.canonical_id, evidence="ordinal")
    ]


def test_self_is_never_related():
    relations = grounded_relations(
        body="Elemento 2 habla de Elemento 2.",
        source_id=A_TWO.canonical_id,
        source_path=A_TWO.path,
        targets=[A_TWO],
    )

    assert relations == []


def test_result_is_capped_and_deterministic():
    targets = [
        RelationTarget(
            canonical_id=f"C{i}",
            name=f"Concepto {i}",
            path=f"lore/c/concepto-{i}.md",
        )
        for i in range(20)
    ]
    body = " ".join(target.name for target in targets)
    first = grounded_relations(
        body=body,
        source_id="source",
        source_path="lore/c/source.md",
        targets=targets,
        max_relations=5,
    )
    second = grounded_relations(
        body=body,
        source_id="source",
        source_path="lore/c/source.md",
        targets=targets,
        max_relations=5,
    )

    assert len(first) == 5
    assert first == second
    assert [relation.canonical_id for relation in first] == sorted(
        relation.canonical_id for relation in first
    )


def test_accent_and_case_insensitive_name_match():
    relations = grounded_relations(
        body="El elemento 1 enlace aparece aquí.",
        source_id="otro",
        source_path="lore/otro.md",
        targets=[B_ONE],
    )

    assert relations == [
        GroundedRelation(
            canonical_id=B_ONE.canonical_id, evidence="full-name"
        )
    ]


def test_build_targets_from_candidate_like_objects():
    class Candidate:
        canonical_id = "X::Uno"
        normalized_identity = "uno"
        display_title = "Uno"
        materialized_path = "lore/uno.md"

    targets = build_relation_targets(
        [
            Candidate(),
            {
                "canonical_id": "X::Dos",
                "name": "Dos",
                "path": "lore/dos.md",
            },
        ]
    )

    assert targets == [
        RelationTarget("X::Uno", "Uno", "lore/uno.md"),
        RelationTarget("X::Dos", "Dos", "lore/dos.md"),
    ]


def test_relation_quality_classifies_orphans():
    class Candidate:
        def __init__(self, cid, preview, relaciones, graph=True):
            self.candidate_id = cid
            self.canonical_id = cid
            self.normalized_identity = cid
            self.display_title = cid
            self.materialized_path = f"lore/{cid}.md"
            self.content_preview = preview
            self.frontmatter = {
                "relaciones": relaciones,
                "graph": graph,
            }

    candidates = [
        Candidate("lore/alfa.md", "Alfa menciona a Bravo.", ["lore/bravo.md"]),
        Candidate("lore/bravo.md", "Bravo no menciona a nadie.", []),
        Candidate("lore/charlie.md", "Charlie menciona a Bravo.", []),
        Candidate("lore/meta.md", "Una nota de trabajo.", [], graph=False),
    ]
    report = relation_quality(candidates)

    assert report["lore/alfa.md"] == []
    assert report["lore/bravo.md"] == ["standalone"]
    assert report["lore/charlie.md"] == ["false-orphan"]
    assert report["lore/meta.md"] == ["non-entity"]


# ---------------------------------------------------------------------------
# S6 — the importer feeds the shared evidence memory at materialization
# ---------------------------------------------------------------------------


def _evidence_job() -> ImportJob:
    return ImportJob(
        job_id="job1", world="world1", owner_principal="tester",
        state=ImportJobState.REVIEW, source_kind="loose",
        created_at=utcnow_iso(), updated_at=utcnow_iso(),
    )


def _evidence_candidate(
    candidate_id: str,
    identity: str,
    canonical_id: str,
    body: str,
    enrichment_json: list[dict] | None = None,
    status: str = "ok",
) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        job_id="job1",
        world="world1",
        normalized_identity=identity,
        canonical_id=canonical_id,
        display_title=identity,
        source_hash=f"sha256:{identity}",
        provenance=Provenance(
            source_path=f"lore/{identity}.md",
            source_kind="loose",
            source_hash=f"sha256:{identity}"),
        content_preview=body,
        frontmatter=FrontmatterCandidate(
            title=identity, type="concepto", description="desc",
            relaciones=[], state=FrontmatterState.GENERATED),
        enrichment_json=enrichment_json,
        enrichment_status=status,
    )


def _verified_relationship_entry(quote: str, verified: bool) -> dict:
    return {
        "__type__": "relationship",
        "verified": verified,
        "source_candidate_id": "cand-alpha",
        "target_candidate_id": "cand-beta",
        "relationship_type": "aliado-de",
        "confidence": 0.9,
        "evidence": quote,
    }


def _service_and_store(tmp_path):
    store = ImportJobStore(":memory:")
    (tmp_path / "world1" / "lore").mkdir(parents=True, exist_ok=True)
    service = ImportService(
        store=store, mundos_dir=tmp_path, spool_dir=tmp_path / "spool")
    return service, store


def test_materialization_records_verified_evidence(tmp_path):
    """A verified funnel relation lands in ``.relations/evidenced.json``."""
    service, store = _service_and_store(tmp_path)
    job = _evidence_job()
    store.create_job(job)
    alpha = _evidence_candidate(
        "cand-alpha", "Alpha", "G::Alpha",
        "Alpha reconoce a su aliada.",
        [_verified_relationship_entry("reconoce a su aliada", verified=True)])
    beta = _evidence_candidate(
        "cand-beta", "Beta", "G::Beta", "Beta no nombra a nadie.")
    store.add_candidate(beta)
    store.add_candidate(alpha)

    outcome = service._execute_candidate(job, alpha)

    assert outcome.written is True
    stored = load_evidence(tmp_path / "world1")
    evidence = stored[("G::Alpha", "G::Beta")]
    assert evidence.side == "G::Alpha"
    assert evidence.quote == "reconoce a su aliada"


def test_materialization_ignores_unverified_relations(tmp_path):
    service, store = _service_and_store(tmp_path)
    job = _evidence_job()
    store.create_job(job)
    alpha = _evidence_candidate(
        "cand-alpha", "Alpha", "G::Alpha",
        "Alpha no menciona a nadie.",
        [_verified_relationship_entry("reconoce a su aliada", verified=False)])
    beta = _evidence_candidate(
        "cand-beta", "Beta", "G::Beta", "Beta no nombra a nadie.")
    store.add_candidate(beta)
    store.add_candidate(alpha)

    outcome = service._execute_candidate(job, alpha)

    assert outcome.written is True
    assert load_evidence(tmp_path / "world1") == {}


def test_evidence_store_oserror_does_not_fail_the_import(tmp_path, monkeypatch):
    """Recording evidence is best-effort: an OSError never blocks the write."""
    service, store = _service_and_store(tmp_path)
    job = _evidence_job()
    store.create_job(job)
    alpha = _evidence_candidate(
        "cand-alpha", "Alpha", "G::Alpha",
        "Alpha reconoce a su aliada.",
        [_verified_relationship_entry("reconoce a su aliada", verified=True)])
    beta = _evidence_candidate(
        "cand-beta", "Beta", "G::Beta", "Beta no nombra a nadie.")
    store.add_candidate(beta)
    store.add_candidate(alpha)

    def boom(*_args, **_kwargs):
        raise OSError("store unavailable")

    monkeypatch.setattr(import_service, "record_evidence", boom)

    outcome = service._execute_candidate(job, alpha)

    assert outcome.written is True
    assert (tmp_path / "world1" / "lore" / "Alpha.md").is_file()


# ---------------------------------------------------------------------------
# S10 — importing reads the text, so the ficha is already reviewed
# ---------------------------------------------------------------------------


def test_materialization_marks_the_ficha_reviewed(tmp_path):
    """A pass that answered marks the ficha swept: the sweep must not re-read it."""
    service, store = _service_and_store(tmp_path)
    job = _evidence_job()
    store.create_job(job)
    alpha = _evidence_candidate(
        "cand-alpha", "Alpha", "G::Alpha", "Alpha menciona a Beta.")
    beta = _evidence_candidate(
        "cand-beta", "Beta", "G::Beta", "Beta es una ficha aparte.")
    store.add_candidate(beta)
    store.add_candidate(alpha)

    outcome = service._execute_candidate(job, alpha)

    assert outcome.written is True
    assert "lore/Alpha.md" in load_state(tmp_path / "world1").swept


def test_an_unanswered_pass_does_not_mark_the_ficha(tmp_path):
    """A provider outage leaves the ficha for the sweep instead of hiding it."""
    service, store = _service_and_store(tmp_path)
    job = _evidence_job()
    store.create_job(job)
    alpha = _evidence_candidate(
        "cand-alpha", "Alpha", "G::Alpha", "Alpha menciona a Beta.",
        status="error")
    beta = _evidence_candidate(
        "cand-beta", "Beta", "G::Beta", "Beta es una ficha aparte.")
    store.add_candidate(beta)
    store.add_candidate(alpha)

    service._execute_candidate(job, alpha)

    assert "lore/Alpha.md" not in load_state(tmp_path / "world1").swept


class _DiskIndex:
    """Index built from the written files, split exactly like the indexer.

    ``graph_indexer`` cannot be imported from this flat test harness (it uses
    package-relative imports), so this reproduces its body split. The import
    path uses the same expression, which is what makes the digests agree.
    """

    def __init__(self, entities: list[dict]) -> None:
        self._entities = entities

    def entities(self) -> list[dict]:
        return self._entities


def _sweep_paths(tmp_path) -> list[str]:
    world = tmp_path / "world1"
    entities = []
    for md in sorted(world.rglob("*.md")):
        body = import_service._body_after_frontmatter(md.read_text(encoding="utf-8"))
        entities.append({
            "path": md.relative_to(world).as_posix(),
            "id": f"G::{md.stem}",
            "name": md.stem,
            "content": body,
            "relaciones": [],
        })
    index = _DiskIndex(entities)
    return [
        candidate.path
        for candidate in scan_candidates(
            mundo="world1", mundos_dir=tmp_path, index=index)
    ]


def test_a_reviewed_ficha_is_not_a_sweep_candidate(tmp_path):
    """End to end through the real indexer: no double work after an import."""
    service, store = _service_and_store(tmp_path)
    job = _evidence_job()
    store.create_job(job)
    alpha = _evidence_candidate(
        "cand-alpha", "Alpha", "G::Alpha", "Alpha menciona a Beta.")
    beta = _evidence_candidate(
        "cand-beta", "Beta", "G::Beta", "Beta es una ficha aparte.")
    store.add_candidate(beta)
    store.add_candidate(alpha)
    service._execute_candidate(job, alpha)
    service._execute_candidate(job, beta)

    assert "lore/Alpha.md" not in _sweep_paths(tmp_path)


def test_an_unreviewed_ficha_stays_a_sweep_candidate(tmp_path):
    """The guard for the guard: an unanswered pass must remain reviewable."""
    service, store = _service_and_store(tmp_path)
    job = _evidence_job()
    store.create_job(job)
    alpha = _evidence_candidate(
        "cand-alpha", "Alpha", "G::Alpha", "Alpha menciona a Beta.",
        status="error")
    beta = _evidence_candidate(
        "cand-beta", "Beta", "G::Beta", "Beta es una ficha aparte.")
    store.add_candidate(beta)
    store.add_candidate(alpha)
    service._execute_candidate(job, alpha)
    service._execute_candidate(job, beta)

    assert "lore/Alpha.md" in _sweep_paths(tmp_path)
