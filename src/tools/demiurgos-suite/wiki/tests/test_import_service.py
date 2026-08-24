# -*- coding: utf-8 -*-
"""World importer slice 2 — Phase 2 RED tests (approval integrity, merge,
contextual image placement, replacement snapshots, idempotent lifecycle)."""

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_models import (  # noqa: E402
    Approval,
    Candidate,
    ImportJob,
    ImportJobState,
    Provenance,
    TargetResolution,
    utcnow_iso,
)
from import_store import ImportJobStore  # noqa: E402
from import_service import (  # noqa: E402
    ImportService,
    atomic_write,
    digest_of,
    plan_merge,
    plan_placements,
    snapshot_to_papelera,
)
from import_analysis import (  # noqa: E402
    analyze_markdown,
    analyze_source,
    resolve_target,
)


def _job(world: str = "world1", principal: str = "tester") -> ImportJob:
    return ImportJob(
        job_id="job1", world=world, owner_principal=principal,
        state=ImportJobState.REVIEW, source_kind="loose",
        opaque_token="tok", created_at=utcnow_iso(), updated_at=utcnow_iso(),
    )


def _candidate(job_id: str = "job1", ident: str = "A",
               content: str = "---\ntype: personaje\nname: A\n---\nA body",
               images=None, replacement=None) -> Candidate:
    return Candidate(
        candidate_id=f"cand-{ident}", job_id=job_id, world="world1",
        normalized_identity=ident, source_hash=f"sha256:{ident}",
        provenance=Provenance(source_path=f"lore/{ident}.md",
                              source_kind="loose", source_hash=f"sha256:{ident}"),
        content_preview=content, images=images or [], replacement=replacement,
    )


@pytest.fixture
def store():
    return ImportJobStore(":memory:")


@pytest.fixture
def service(store, tmp_path):
    (tmp_path / "world1" / "lore").mkdir(parents=True, exist_ok=True)
    return ImportService(
        store=store, mundos_dir=tmp_path, spool_dir=tmp_path / "spool")


# ---------------------------------------------------------------------------
# 2.1 Approval / digest / token integrity
# ---------------------------------------------------------------------------

class TestApprovalIntegrity:
    def test_stale_digest_denied_zero_writes(self, store, service, tmp_path):
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = service.issue_approval(job, "tester", [])
        # A new candidate lands after review -> aggregate digest changes, so
        # the approval (bound to the reviewed digest) must fail closed.
        store.add_candidate(_candidate(ident="B",
                                       content="---\ntype: personaje\nname: B\n---\nB body"))
        new_digest = service.candidate_digest(job)
        with pytest.raises(ValueError):
            service.validate_approval(job, "tester", new_digest, approval.token)
        assert not (tmp_path / "world1" / "lore" / "A.md").exists()

    def test_expired_token_denied(self, store, service, tmp_path):
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        from datetime import datetime, timedelta, timezone
        approval = Approval(
            approval_id="a", job_id=job.job_id, principal="tester",
            revision=job.revision, digest=service.candidate_digest(job),
            token="tok", issued_at=utcnow_iso(),
            expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        )
        store.save_approval(approval)
        with pytest.raises(ValueError):
            service.validate_approval(job, "tester", approval.digest, "tok")
        assert not (tmp_path / "world1" / "lore" / "A.md").exists()

    def test_replayed_token_denied(self, store, service, tmp_path):
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = service.issue_approval(job, "tester", [])
        store.mark_approval_consumed(job.job_id, approval.token)
        with pytest.raises(ValueError):
            service.validate_approval(job, "tester", approval.digest, approval.token)
        assert not (tmp_path / "world1" / "lore" / "A.md").exists()

    def test_approval_succeeds_only_with_matching_digest(self, store, service, tmp_path):
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = service.issue_approval(job, "tester", [])
        validated = service.validate_approval(job, "tester", approval.digest,
                                              approval.token)
        assert validated.token == approval.token


# ---------------------------------------------------------------------------
# 2.2 Preservation-first merge
# ---------------------------------------------------------------------------

class TestPreservationMerge:
    def test_new_ficha_added(self):
        decision = plan_merge("", "---\ntype: personaje\nname: A\n---\nbody")
        assert decision.action == "add"

    def test_edited_ficha_kept_unchanged(self):
        decision = plan_merge("same", "same")
        assert decision.action == "keep"

    def test_image_only_additions_are_added(self):
        current = "---\ntype: personaje\nname: A\n---\n# Origen\ntexto"
        incoming = ("---\ntype: personaje\nname: A\n---\n# Origen\n"
                    "texto\n\n![retrato](retrato.jpg)")
        decision = plan_merge(current, incoming)
        assert decision.action == "add"

    def test_modified_text_requires_review(self):
        current = "---\ntype: personaje\nname: A\n---\n# Origen\ntexto original"
        incoming = "---\ntype: personaje\nname: A\n---\n# Origen\ntexto CAMBIADO"
        decision = plan_merge(current, incoming)
        assert decision.action == "review"


# ---------------------------------------------------------------------------
# 2.3 Contextual image placement (no silent reorder/append/detach)
# ---------------------------------------------------------------------------

class TestContextualPlacement:
    def test_already_present_image_skipped(self):
        results = plan_placements(["a.jpg"], [{"relative_media_path": "a.jpg",
                                               "target_ficha": "X"}])
        assert results[0]["placement_status"] == "skip"

    def test_missing_target_is_ambiguous_review(self):
        results = plan_placements([], [{"relative_media_path": "a.jpg",
                                        "target_ficha": ""}])
        assert results[0]["placement_status"] == "ambiguous"

    def test_unambiguous_target_approved(self):
        results = plan_placements([], [{"relative_media_path": "a.jpg",
                                        "target_ficha": "Origen"}])
        assert results[0]["placement_status"] == "approved"

    def test_align_size_suffix_dedups_on_clean_base(self):
        # `img.png#left` resolves to the same gallery file as an existing
        # `img.png#right`: the second placement is skipped, never re-added.
        results = plan_placements(
            ["img.png#right"],
            [{"relative_media_path": "img.png#left", "target_ficha": "X"}])
        assert results[0]["placement_status"] == "skip"

    def test_align_size_suffix_dedups_against_bare_path(self):
        # Existing bare `img.png` vs incoming `img.png#left` -> same file.
        results = plan_placements(
            ["img.png"],
            [{"relative_media_path": "img.png#left", "target_ficha": "X"}])
        assert results[0]["placement_status"] == "skip"

    def test_align_size_suffix_preserved_on_approved_placement(self):
        # A new `#align-size` reference stays intact (markdown keeps the
        # suffix) while being admitted.
        results = plan_placements(
            [], [{"relative_media_path": "img.png#left", "target_ficha": "X"}])
        assert results[0]["placement_status"] == "approved"
        assert results[0]["relative_media_path"] == "img.png#left"

    def test_analysis_preserves_source_order_and_anchors(self):
        text = ("# Origen\nprimera linea de contexto\n\n"
                "## Llegada\nsegundo bloque ![img](pic.png)")
        file = analyze_markdown(text, "lore/A.md", "h", 10)
        assert len(file.chunks) == 2
        assert file.chunks[0].source_sequence == 0
        assert file.chunks[0].heading_path == "Origen"
        assert "primera linea" in file.chunks[0].nearby_text_anchor
        assert file.chunks[1].source_sequence == 1
        assert file.chunks[1].images[0].relative_media_path == "pic.png"

    def test_gallery_registration_uses_job_spool_and_clean_path(self, store, tmp_path):
        # A candidate carrying an approved `#align-size` placement registers the
        # clean base file from the job-scoped spool via the media contract.
        from import_models import ImagePlacement
        spool = tmp_path / "spool"
        (spool / "job1").mkdir(parents=True, exist_ok=True)
        (spool / "job1" / "img.png").write_bytes(b"img-bytes")
        registered = []
        svc = ImportService(
            store=store, mundos_dir=tmp_path, spool_dir=spool,
            register_gallery=lambda world, src, rel: registered.append(
                (world, str(src), rel)),
        )
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate(
            images=[ImagePlacement(gallery_asset_id="", relative_media_path="img.png#left",
                                   alt_text="r", target_ficha="X",
                                   confidence=1.0, placement_status="proposed")]))
        approval = svc.issue_approval(job, "tester", [])
        svc.execute(job, "tester", approval.digest, approval.token)
        assert registered, "gallery registration should have been invoked"
        _, src, rel = registered[0]
        assert rel == "img.png"                       # clean path, no suffix
        assert src == str(spool / "job1" / "img.png")  # job-scoped spool file


# ---------------------------------------------------------------------------
# 2.4 Replacement snapshot via .papelera (30-day recovery)
# ---------------------------------------------------------------------------

class TestReplacementSnapshot:
    def test_replacement_snapshots_prior_ficha(self, tmp_path):
        (tmp_path / "lore").mkdir(parents=True, exist_ok=True)
        prior = "---\ntype: personaje\nname: A\n---\nold body"
        rec = snapshot_to_papelera(tmp_path, "lore", "A.md", prior, "world1")
        assert rec.papelera_entry
        assert rec.recovery_status == "available"
        meta = (tmp_path / ".papelera" / "lore" / rec.papelera_entry
                / "meta.json").read_text(encoding="utf-8")
        assert '"original_path": "A.md"' in meta
        assert rec.expiry > "2000"

    def test_import_surfaces_papelera_entry_on_replacement(self, store, service, tmp_path):
        job = _job()
        store.create_job(job)
        target = tmp_path / "world1" / "lore" / "A.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("old ficha", encoding="utf-8")
        candidate = _candidate(
            content="new ficha",
            replacement=__import__("import_models", fromlist=["ReplacementRecord"])
            .ReplacementRecord(prior_snapshot="A.md", recovery_status="replace"))
        store.add_candidate(candidate)
        approval = service.issue_approval(job, "tester", [])
        outcomes = service.execute(job, "tester", approval.digest, approval.token)
        assert outcomes[0].written
        assert outcomes[0].papelera_entry


# ---------------------------------------------------------------------------
# 2.5 Idempotent cancel / resume / rollback
# ---------------------------------------------------------------------------

class TestIdempotentLifecycle:
    def test_cancel_deletes_job_automatically(self, store, service):
        """Opción A — cancel is terminal and reaps the DB row immediately.

        A cancelled job carries no audit value, so it is auto-deleted (job +
        cascade) instead of being kept for history. ``resume`` is therefore
        no longer meaningful for a cancelled job.
        """
        job = _job()
        store.create_job(job)
        cancelled = service.cancel(job, "tester")
        assert cancelled.state == ImportJobState.CANCELLED
        assert store.get_job(job.job_id) is None

    def test_rollback_deletes_job_automatically(self, store, service):
        """Opción A — rollback is terminal and reaps the DB row immediately."""
        job = _job()
        store.create_job(job)
        job = store.update_job(job.job_id, expected_revision=job.revision,
                               state=ImportJobState.EXECUTING)
        rolled = service.rollback(job, "tester")
        assert rolled.state == ImportJobState.ROLLED_BACK
        assert store.get_job(job.job_id) is None

    @pytest.mark.parametrize("initial_state", [
        ImportJobState.INTAKING,
        ImportJobState.ANALYZING,
        ImportJobState.EXECUTING,
    ])
    def test_resume_from_intermediate_state_transitions_to_review(
        self, store, service, initial_state
    ):
        """Jobs stuck in intaking/analyzing/executing must resume to review."""
        job = _job()
        store.create_job(job)
        job = store.update_job(
            job.job_id, expected_revision=job.revision, state=initial_state)
        resumed = service.resume(job, "tester")
        assert resumed.state == ImportJobState.REVIEW

    def test_cancel_is_idempotent(self, store, service):
        job = _job()
        store.create_job(job)
        job = service.cancel(job, "tester")
        job2 = service.cancel(job, "tester")  # already cancelled -> no-op
        assert job2.state == ImportJobState.CANCELLED

    def test_rollback_compensates_importer_changes(self, store, service):
        job = _job()
        store.create_job(job)
        job = store.update_job(job.job_id, expected_revision=job.revision,
                               state=ImportJobState.EXECUTING)
        rolled = service.rollback(job, "tester")
        assert rolled.state == ImportJobState.ROLLED_BACK

    def test_execute_marks_completed_and_records_items(self, store, service, tmp_path):
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = service.issue_approval(job, "tester", [])
        service.execute(job, "tester", approval.digest, approval.token)
        done = store.get_job(job.job_id)
        assert done.state == ImportJobState.COMPLETED
        assert (tmp_path / "world1" / "lore" / "A.md").exists()


# ---------------------------------------------------------------------------
# 2.9 Graph reconciliation before success
# ---------------------------------------------------------------------------

class TestGraphReconciliation:
    def test_execute_reconciles_graph_before_success(self, store, tmp_path):
        # The graph index must be reconciled for each written ficha *before*
        # the job is reported complete (entities queryable before success).
        spool = tmp_path / "spool"
        (spool / "job1").mkdir(parents=True, exist_ok=True)
        reconciled = []
        svc = ImportService(
            store=store, mundos_dir=tmp_path, spool_dir=spool,
            graph_reconcile=lambda rel, mundo: reconciled.append((rel, mundo)),
        )
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = svc.issue_approval(job, "tester", [])
        svc.execute(job, "tester", approval.digest, approval.token)
        assert reconciled, "graph reconcile must run during execute"
        rel, mundo = reconciled[0]
        assert mundo == "world1"
        assert rel.endswith("lore/A.md")
        done = store.get_job(job.job_id)
        assert done.state == ImportJobState.COMPLETED


# ---------------------------------------------------------------------------
# Slice 3 — bulk graph reconciliation (IM-3.1/IM-3.2)
# ---------------------------------------------------------------------------

class TestBulkGraphReconciliation:
    def _service(self, store, tmp_path, *, many=None, per_file=None):
        spool = tmp_path / "spool"
        (spool / "job1").mkdir(parents=True, exist_ok=True)
        return ImportService(
            store=store, mundos_dir=tmp_path, spool_dir=spool,
            graph_reconcile=per_file,
            graph_reconcile_many=many,
        )

    def _events(self, store, job):
        obs = store.observability(job.opaque_token)
        return [e["event"] for e in obs["events"]]

    def test_bulk_reconcile_called_once_all_written_paths(self, store, tmp_path):
        called = []
        many = lambda paths, mundo: (called.append((list(paths), mundo))
                                     or _Result(2, [], 1))
        svc = self._service(store, tmp_path, many=many)
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        store.add_candidate(_candidate(ident="B",
                                       content="---\ntype: personaje\nname: B\n---\nB body"))
        approval = svc.issue_approval(job, "tester", [])
        svc.execute(job, "tester", approval.digest, approval.token)
        assert len(called) == 1, "bulk reconcile must run exactly once"
        paths, mundo = called[0]
        assert mundo == "world1"
        assert any(p.endswith("lore/A.md") for p in paths)
        assert any(p.endswith("lore/B.md") for p in paths)
        done = store.get_job(job.job_id)
        assert done.state == ImportJobState.COMPLETED
        events = self._events(store, job)
        assert any(e.startswith("graph_reconciled:") for e in events)

    def test_bulk_partial_failure_emits_partial_event_job_completes(self, store, tmp_path):
        svc = self._service(
            store, tmp_path,
            many=lambda paths, mundo: _Result(1, ["lore/Missing.md"], 1))
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = svc.issue_approval(job, "tester", [])
        svc.execute(job, "tester", approval.digest, approval.token)
        done = store.get_job(job.job_id)
        assert done.state == ImportJobState.COMPLETED
        events = self._events(store, job)
        assert any(e.startswith("graph_reconciled:") for e in events)
        assert "graph_reconcile_partial:1" in events

    def test_bulk_failure_falls_back_to_per_file_job_completes(self, store, tmp_path, caplog):
        per_file = []
        def failing_many(paths, mundo):
            raise RuntimeError("graph index unavailable")

        svc = self._service(
            store, tmp_path, many=failing_many,
            per_file=lambda rel, mundo: per_file.append(rel))
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = svc.issue_approval(job, "tester", [])
        svc.execute(job, "tester", approval.digest, approval.token)
        done = store.get_job(job.job_id)
        assert done.state == ImportJobState.COMPLETED
        # Per-file fallback ran for the written path.
        assert any(p.endswith("lore/A.md") for p in per_file)
        events = self._events(store, job)
        assert "graph_reconcile_failed" in events

    def test_bulk_and_per_file_both_fail_job_still_completes(self, store, tmp_path):
        def failing_many(paths, mundo):
            raise RuntimeError("graph index unavailable")
        def failing_per_file(rel, mundo):
            raise RuntimeError("graph index unavailable")

        svc = self._service(store, tmp_path, many=failing_many,
                            per_file=failing_per_file)
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = svc.issue_approval(job, "tester", [])
        svc.execute(job, "tester", approval.digest, approval.token)
        done = store.get_job(job.job_id)
        assert done.state == ImportJobState.COMPLETED
        events = self._events(store, job)
        assert "graph_reconcile_failed" in events

    def test_no_written_fichas_is_noop_no_bulk_call(self, store, tmp_path):
        # A candidate whose merge is "keep" writes nothing -> no bulk reconcile.
        calls = []
        svc = self._service(
            store, tmp_path, many=lambda paths, mundo: calls.append(1) or _Result(0, [], 0))
        job = _job()
        store.create_job(job)
        # Pre-create the target so the merge is "keep" (ficha unchanged).
        target = tmp_path / "world1" / "lore" / "A.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("---\ntype: personaje\nname: A\n---\nA body", encoding="utf-8")
        store.add_candidate(_candidate(content="---\ntype: personaje\nname: A\n---\nA body"))
        approval = svc.issue_approval(job, "tester", [])
        svc.execute(job, "tester", approval.digest, approval.token)
        assert calls == []
        done = store.get_job(job.job_id)
        assert done.state == ImportJobState.COMPLETED


class _Result:
    """Minimal stand-in for GraphReconcileResult in service tests."""

    def __init__(self, processed, failed, batches):
        self.processed = processed
        self.failed = failed
        self.batches = batches


# ---------------------------------------------------------------------------
# Slice 1 — resolve_target: legacy uppercase -> canonical OKF
# ---------------------------------------------------------------------------

class TestResolveTarget:
    """RED tests for ``resolve_target``.

    Maps a candidate's source path to its canonical OKF target. Legacy
    uppercase sections (Lore/Personajes) and known OKF subfolder aliases
    (Places->lugares, Rules->reglas, etc.) are normalized; unknown sections
    or subfolders produce ``status="review"`` with a diagnostic — never a
    guessed target.
    """

    def _candidate(self, ident: str, source_path: str,
                   section: str = "", canonical_id: str = "") -> Candidate:
        return Candidate(
            candidate_id=f"cand-{ident}", job_id="job1", world="world1",
            normalized_identity=ident, source_hash=f"sha256:{ident}",
            provenance=Provenance(source_path=source_path, source_kind="loose",
                                  source_hash=f"sha256:{ident}"),
            section=section,
            canonical_id=canonical_id,
        )

    def test_uppercase_lore_normalized_to_lowercase(self, tmp_path):
        cand = self._candidate("A", "Lore/A.md")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert isinstance(r, TargetResolution)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/A.md"
        assert r.normalized_source == "lore/A.md"
        assert r.alias_used == ""

    def test_uppercase_personajes_normalized_to_lowercase(self, tmp_path):
        cand = self._candidate("B", "Personajes/B.md")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == "personajes/B.md"
        assert r.normalized_source == "personajes/B.md"

    def test_canonical_okf_passthrough(self, tmp_path):
        # Already in canonical OKF form -> unchanged, no alias recorded.
        cand = self._candidate("A", "lore/A.md")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/A.md"
        assert r.alias_used == ""

    def test_legacy_alias_places_to_lugares(self, tmp_path):
        cand = self._candidate("City", "Lore/Places/City.md")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/lugares/City.md"
        assert r.alias_used == "Lore/Places"

    def test_legacy_alias_rules_to_reglas(self, tmp_path):
        cand = self._candidate("X", "Lore/Rules/X.md")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/reglas/X.md"
        assert r.alias_used == "Lore/Rules"

    def test_legacy_alias_case_insensitive_section(self, tmp_path):
        # `LORE` and `lore` should both normalize to canonical OKF.
        cand = self._candidate("A", "LORE/A.md")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/A.md"

    def test_legacy_alias_case_insensitive_subfolder(self, tmp_path):
        # Subfolder name is matched case-insensitively too.
        cand = self._candidate("A", "Lore/PLACES/A.md")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/lugares/A.md"

    def test_unknown_subfolder_under_lore_returns_review(self, tmp_path):
        # A subfolder that is NOT a known OKF alias must be reported for
        # review — never silently guessed.
        cand = self._candidate("X", "Lore/Random/X.md")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "review"
        assert r.canonical_path == "lore/Random/X.md"
        assert "Random" in r.diagnostic or "unknown" in r.diagnostic.lower()

    def test_unknown_section_returns_review(self, tmp_path):
        cand = self._candidate("X", "Mystery/X.md")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "review"
        assert r.canonical_path == "Mystery/X.md"
        assert "Mystery" in r.diagnostic or "unknown" in r.diagnostic.lower()

    def test_empty_source_returns_rejected(self, tmp_path):
        cand = Candidate(
            candidate_id="cand-x", job_id="job1", world="world1",
            normalized_identity="x", source_hash="sha256:x",
            provenance=Provenance(source_path="", source_kind="loose",
                                  source_hash="sha256:x"),
        )
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "rejected"
        assert r.diagnostic

    def test_unsafe_path_returns_rejected(self, tmp_path):
        cand = self._candidate("x", "../etc/passwd")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "rejected"
        assert r.diagnostic

    def test_personajes_with_subfolder_returns_review(self, tmp_path):
        # `personajes` does not have OKF subfolders; an unknown subfolder
        # there must be reported for review, never guessed.
        cand = self._candidate("X", "Personajes/Random/X.md")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "review"
        assert "personajes/Random" in r.canonical_path

    def test_is_resolved_predicate(self, tmp_path):
        from import_models import TargetResolution
        cand = self._candidate("A", "Lore/Places/A.md")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        # The predicate must be true for resolved and false for review.
        assert r.status == "resolved"
        rev = self._candidate("X", "Lore/Random/X.md")
        rr = resolve_target("world1", rev, mundos_dir=tmp_path)
        assert rr.status == "review"
        assert rr.status != "resolved"

    def test_author_section_wins_over_source_path(self, tmp_path):
        # BLOQUE 1 piece 1 — the classifier's author-chosen section roots the
        # canonical target, even when the legacy source-path derivation would
        # have produced a different (or unknown) section.
        cand = self._candidate("Enciclopedia", "Enciclopedia.md",
                               section="personajes")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == "personajes/Enciclopedia.md"
        assert r.alias_used == ""

    def test_author_section_wins_over_legacy_alias(self, tmp_path):
        # A conflicting legacy alias path (Lore/Places → lore/lugares) must
        # NOT win when the author chose a different section explicitly.
        cand = self._candidate("City", "Lore/Places/City.md",
                               section="referencias")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == "referencias/City.md"
        assert r.alias_used == ""

    def test_empty_section_falls_back_to_legacy_source_path(self, tmp_path):
        # Empty section (legacy jobs / files with no map entry) → the legacy
        # source-path branch runs unchanged.
        cand = self._candidate("Dottua", "Lore/Dottua.md", section="")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/Dottua.md"

    # BLOQUE 1 piece 2 — canonical_id hierarchy (identity-path-mapping):
    # section + valid canonical_id → slugged subfolder chain + filename;
    # empty/invalid canonical_id → piece-1 fallback.

    def test_section_with_canonical_id_multi_segment(self, tmp_path):
        cand = self._candidate(
            "Enciclopedia de los Vibrantes.md",
            "Enciclopedia de los Vibrantes.md", section="lore",
            canonical_id="Áyagars::Impacto Social::Áyagar del 9no Stal")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == \
            "lore/ayagars/impacto-social/ayagar-del-9no-stal.md"
        assert r.normalized_source == r.canonical_path
        assert r.alias_used == ""

    def test_section_with_empty_canonical_id_piece1_fallback(self, tmp_path):
        cand = self._candidate(
            "Enciclopedia de los Vibrantes.md",
            "Enciclopedia de los Vibrantes.md", section="lore",
            canonical_id="")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/Enciclopedia de los Vibrantes.md"

    def test_section_with_invalid_canonical_id_fallback(self, tmp_path):
        cand = self._candidate(
            "Enciclopedia de los Vibrantes.md",
            "Enciclopedia de los Vibrantes.md", section="lore",
            canonical_id=":::broken")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/Enciclopedia de los Vibrantes.md"

    def test_section_with_ordinal(self, tmp_path):
        cand = self._candidate(
            "Enciclopedia de los Vibrantes.md",
            "Enciclopedia de los Vibrantes.md", section="lore",
            canonical_id="Sistema Stal::1er Stal#2")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/sistema-stal/1er-stal-2.md"

    def test_section_with_accent(self, tmp_path):
        cand = self._candidate(
            "Enciclopedia de los Vibrantes.md",
            "Enciclopedia de los Vibrantes.md", section="lore",
            canonical_id="Política | Distribución Y Territorios::Dottua")
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "resolved"
        assert r.canonical_path == \
            "lore/politica-distribucion-y-territorios/dottua.md"


# ---------------------------------------------------------------------------
# PR3 (sync-lore-in-importer) — vision-gated execution (tasks 6.1-6.9)
# ---------------------------------------------------------------------------


class TestVisionExecution:
    """Approved vision suggestions gate gallery registration and overlay their
    description as markdown alt-text; pending/rejected suggestions are not
    eligible; images without vision results stay reviewable (fallback)."""

    _CONTENT = ("---\ntype: personaje\nname: A\n---\n# Origen\n"
                "body\n\n![retrato](media/A/retrato.png)")

    def _cand(self, images, enrichment):
        from import_models import ImagePlacement
        cand = _candidate(content=self._CONTENT, images=images or [
            ImagePlacement(gallery_asset_id="",
                           relative_media_path="media/A/retrato.png",
                           alt_text="", target_ficha="Origen",
                           confidence=1.0, placement_status="proposed"),
        ])
        cand.enrichment_json = enrichment
        cand.enrichment_status = "ok" if enrichment else "disabled"
        return cand

    def _vision_entry(self, vid="vision:abc", review_state="pending",
                      desc="Retrato de A",
                      path="media/A/retrato.png"):
        return {
            "__type__": "vision", "id": vid, "candidate_id": "cand-A",
            "relative_media_path": path, "description": desc,
            "verdict": "confirma", "analysis": "analisis", "tags": ["retrato"],
            "confidence": 0.0, "provenance": {"provider": "vision"},
            "evidence": f"image:{path}",
            "review_state": review_state,
        }

    def _svc(self, store, tmp_path, registered):
        spool = tmp_path / "spool"
        (spool / "job1" / "media" / "A").mkdir(parents=True, exist_ok=True)
        (spool / "job1" / "media" / "A" / "retrato.png").write_bytes(b"img")
        (tmp_path / "world1" / "lore").mkdir(parents=True, exist_ok=True)
        return ImportService(
            store=store, mundos_dir=tmp_path, spool_dir=spool,
            register_gallery=lambda world, src, rel: registered.append(
                (world, str(src), rel)),
        )

    def test_approved_vision_registers_original_and_overlays_alt_text(
            self, store, tmp_path):
        """Task 6.7 — approved image → gallery registration with ORIGINAL
        spool bytes + vision description as the markdown alt-text."""
        cand = self._cand(
            images=None,
            enrichment=[self._vision_entry(review_state="approved")],
        )
        registered = []
        svc = self._svc(store, tmp_path, registered)
        job = _job()
        store.create_job(job)
        store.add_candidate(cand)
        approval = svc.issue_approval(job, "tester", ["vision:abc"])
        outcomes = svc.execute(job, "tester", approval.digest, approval.token,
                               suggestion_ids=["vision:abc"])
        assert outcomes[0].written
        assert registered, "approved image must be registered in the gallery"
        _, src, rel = registered[0]
        assert rel == "media/A/retrato.png"
        assert src == str(tmp_path / "spool" / "job1" / "media" / "A"
                          / "retrato.png")
        ficha = (tmp_path / "world1" / "lore" / "A.md").read_text(
            encoding="utf-8")
        assert "![Retrato de A](media/A/retrato.png)" in ficha
        assert "![retrato](media/A/retrato.png)" not in ficha

    @pytest.mark.parametrize("state", ["pending", "rejected"])
    def test_non_approved_vision_suggestion_not_eligible(
            self, store, tmp_path, state):
        """Tasks 6.2/6.8 — pending or rejected suggestions are not admitted:
        the image is neither placed nor registered in the gallery."""
        cand = self._cand(
            images=None,
            enrichment=[self._vision_entry(review_state=state)],
        )
        registered = []
        svc = self._svc(store, tmp_path, registered)
        job = _job()
        store.create_job(job)
        store.add_candidate(cand)
        # The token binds a DIFFERENT suggestion id: the vision suggestion is
        # therefore not approved and its image must not materialize.
        approval = svc.issue_approval(job, "tester", ["vision:other"])
        outcomes = svc.execute(job, "tester", approval.digest, approval.token,
                               suggestion_ids=["vision:other"])
        assert outcomes[0].written
        assert registered == [], "unapproved image must not be registered"
        ficha = (tmp_path / "world1" / "lore" / "A.md").read_text(
            encoding="utf-8")
        assert "Retrato de A" not in ficha  # no vision overlay

    def test_image_without_vision_result_placed_with_fallback(
            self, store, tmp_path):
        """Task 6.9 — no vision result: image remains reviewable and is
        placed with its (fallback) alt-text when the job is approved."""
        cand = self._cand(images=None, enrichment=None)
        registered = []
        svc = self._svc(store, tmp_path, registered)
        job = _job()
        store.create_job(job)
        store.add_candidate(cand)
        approval = svc.issue_approval(job, "tester", [])
        outcomes = svc.execute(job, "tester", approval.digest, approval.token,
                               suggestion_ids=[])
        assert outcomes[0].written
        assert registered, "image without vision result must still be placed"
        ficha = (tmp_path / "world1" / "lore" / "A.md").read_text(
            encoding="utf-8")
        assert "![retrato](media/A/retrato.png)" in ficha  # unchanged

    def test_legacy_approval_without_ids_preserves_placement_flow(
            self, store, tmp_path):
        """Legacy approve without ``suggestion_ids``: no vision gating — the
        existing placement flow is preserved (image registered, no overlay)."""
        cand = self._cand(
            images=None,
            enrichment=[self._vision_entry(review_state="pending")],
        )
        registered = []
        svc = self._svc(store, tmp_path, registered)
        job = _job()
        store.create_job(job)
        store.add_candidate(cand)
        approval = svc.issue_approval(job, "tester", [])
        outcomes = svc.execute(job, "tester", approval.digest, approval.token)
        assert outcomes[0].written
        assert registered, "legacy flow must keep placing images"
        ficha = (tmp_path / "world1" / "lore" / "A.md").read_text(
            encoding="utf-8")
        assert "Retrato de A" not in ficha  # no overlay without approval ids

    def test_multiple_images_independent_approval(self, store, tmp_path):
        """Spec scenario — approve one image, reject another: only the
        approved original is registered; the rejected one is not."""
        from import_models import ImagePlacement
        cand = _candidate(
            content=("---\ntype: personaje\nname: A\n---\n# Origen\nbody\n\n"
                     "![retrato](media/A/retrato.png)\n\n"
                     "![mapa](media/A/mapa.png)"),
            images=[
                ImagePlacement(gallery_asset_id="",
                               relative_media_path="media/A/retrato.png",
                               alt_text="", target_ficha="Origen",
                               confidence=1.0, placement_status="proposed"),
                ImagePlacement(gallery_asset_id="",
                               relative_media_path="media/A/mapa.png",
                               alt_text="", target_ficha="Origen",
                               confidence=1.0, placement_status="proposed"),
            ],
        )
        cand.enrichment_json = [
            self._vision_entry(vid="vision:abc",
                               review_state="approved",
                               desc="Retrato de A",
                               path="media/A/retrato.png"),
            self._vision_entry(vid="vision:def",
                               review_state="rejected",
                               desc="Mapa del mundo",
                               path="media/A/mapa.png"),
        ]
        cand.enrichment_status = "ok"
        spool = tmp_path / "spool"
        (spool / "job1" / "media" / "A").mkdir(parents=True, exist_ok=True)
        (spool / "job1" / "media" / "A" / "retrato.png").write_bytes(b"r")
        (spool / "job1" / "media" / "A" / "mapa.png").write_bytes(b"m")
        (tmp_path / "world1" / "lore").mkdir(parents=True, exist_ok=True)
        registered = []
        svc = ImportService(
            store=store, mundos_dir=tmp_path, spool_dir=spool,
            register_gallery=lambda world, src, rel: registered.append(rel),
        )
        job = _job()
        store.create_job(job)
        store.add_candidate(cand)
        approval = svc.issue_approval(job, "tester", ["vision:abc"])
        outcomes = svc.execute(job, "tester", approval.digest, approval.token,
                               suggestion_ids=["vision:abc"])
        assert outcomes[0].written
        assert "media/A/retrato.png" in registered
        assert "media/A/mapa.png" not in registered
        ficha = (tmp_path / "world1" / "lore" / "A.md").read_text(
            encoding="utf-8")
        assert "![Retrato de A](media/A/retrato.png)" in ficha
        assert "![Mapa del mundo](media/A/mapa.png)" not in ficha


# ---------------------------------------------------------------------------
# Phase 3 (importador-auto-frontmatter) — importer H1 scope authority (3.4)
# ---------------------------------------------------------------------------

class TestImporterScopeAuthority:
    """world_authority.is_importer_scope_permitted permits only canonical OKF
    content sections; system/transversal dirs are never permitted."""

    def _permitted(self, section):
        from world_authority import is_importer_scope_permitted
        return is_importer_scope_permitted(section)

    def test_canonical_sections_permitted(self):
        for section in ("lore", "personajes", "referencias"):
            assert self._permitted(section)
        # Case-insensitive on input.
        assert self._permitted("Lore")

    def test_system_and_transversal_dirs_rejected(self):
        for section in ("_context", ".history", ".papelera",
                        "relaciones", "canon", "conflictos", "propuestas",
                        "ideas", "unknown"):
            assert not self._permitted(section)

    def test_unknown_section_rejected_by_resolve_target(self, tmp_path):
        # resolve_target now routes through the shared authority: an unknown
        # top-level section is reported for review (never guessed).
        cand = Candidate(
            candidate_id="cand-x", job_id="job1", world="world1",
            normalized_identity="x", source_hash="sha256:x",
            provenance=Provenance(source_path="Mystery/X.md",
                                  source_kind="loose", source_hash="sha256:x"),
        )
        r = resolve_target("world1", cand, mundos_dir=tmp_path)
        assert r.status == "review"


# ---------------------------------------------------------------------------
# Spool cleanup — terminal states reclaim the job spool (best-effort)
# ---------------------------------------------------------------------------

class TestSpoolCleanupLifecycle:
    def _spooled(self, tmp_path):
        """Create a job-scoped spool dir with nested content."""
        spool_dir = tmp_path / "spool"
        job_dir = spool_dir / "job1" / "lore"
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "a.md").write_bytes(b"abc")
        return spool_dir

    def test_execute_completed_removes_spool_dir(self, store, tmp_path):
        spool_dir = self._spooled(tmp_path)
        (tmp_path / "world1" / "lore").mkdir(parents=True, exist_ok=True)
        svc = ImportService(store=store, mundos_dir=tmp_path, spool_dir=spool_dir)
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = svc.issue_approval(job, "tester", [])
        svc.execute(job, "tester", approval.digest, approval.token)
        assert store.get_job(job.job_id).state == ImportJobState.COMPLETED
        assert not (spool_dir / "job1").exists()

    def test_execute_failed_removes_spool_dir(self, store, tmp_path, monkeypatch):
        spool_dir = self._spooled(tmp_path)
        (tmp_path / "world1" / "lore").mkdir(parents=True, exist_ok=True)
        svc = ImportService(store=store, mundos_dir=tmp_path, spool_dir=spool_dir)

        def _boom(self, *args, **kwargs):
            raise RuntimeError("dependency down")

        monkeypatch.setattr(ImportService, "_execute_candidate", _boom)
        job = _job()
        store.create_job(job)
        store.add_candidate(_candidate())
        approval = svc.issue_approval(job, "tester", [])
        with pytest.raises(ValueError):
            svc.execute(job, "tester", approval.digest, approval.token)
        assert store.get_job(job.job_id).state == ImportJobState.FAILED
        assert not (spool_dir / "job1").exists()

    def test_cancel_removes_spool_dir(self, store, tmp_path):
        spool_dir = self._spooled(tmp_path)
        svc = ImportService(store=store, mundos_dir=tmp_path, spool_dir=spool_dir)
        job = _job()
        store.create_job(job)
        job = svc.cancel(job, "tester")
        assert job.state == ImportJobState.CANCELLED
        assert not (spool_dir / "job1").exists()

    def test_cleanup_failure_does_not_mask_state_or_raise(
            self, store, tmp_path, monkeypatch):
        spool_dir = self._spooled(tmp_path)
        svc = ImportService(store=store, mundos_dir=tmp_path, spool_dir=spool_dir)
        import import_intake as _intake

        def _boom(path):
            raise OSError("nope")

        monkeypatch.setattr(_intake.shutil, "rmtree", _boom)
        job = _job()
        store.create_job(job)
        # The CANCELLED transition + DB reap must still happen and cancel must
        # not raise even though spool cleanup fails.
        job = svc.cancel(job, "tester")
        assert job.state == ImportJobState.CANCELLED
        # Opción A — the DB row is reaped regardless of the spool failure.
        assert store.get_job(job.job_id) is None
        assert (spool_dir / "job1").exists()  # cleanup failed but DB reaped


# ---------------------------------------------------------------------------
# BLOQUE 3 — shared plan_merge helper + execute backstop (collision design)
# ---------------------------------------------------------------------------


class TestCollisionSharedHelper:
    def test_plan_merge_shared_helper_analyze_and_execute(self):
        """BLOQUE 3 — the analyze-time path preflight (import_router stamping)
        and the execute-time backstop (import_service._execute_candidate) call
        the SAME module-level ``plan_merge`` — no duplicated merge logic."""
        import import_router
        import import_service as import_service_mod
        # Both call sites import the identical function object from
        # import_service; drift between analyze prediction and execute
        # enforcement is structurally impossible.
        assert import_router.plan_merge is import_service_mod.plan_merge

    def test_execute_backstop_unchanged(self, store, service, tmp_path):
        """BLOQUE 3 — execute-time plan_merge enforcement is byte-identical:
        a candidate approved despite an analyze-time path-collision advisory
        is still refused at execute time when plan_merge says review (spec:
        Execute still enforces plan_merge)."""
        job = _job()
        store.create_job(job)
        target = tmp_path / "world1" / "lore" / "A.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        prior = "---\ntype: personaje\nname: A\n---\nold body"
        target.write_text(prior, encoding="utf-8")
        candidate = _candidate()
        # Simulate the analyze-time collision stamp: the candidate reached
        # review with a path-collision advisory and status=conflict, and the
        # Author approved it anyway. Execute must STILL enforce plan_merge.
        candidate.okf_issues = [{
            "code": "path-collision",
            "message": "Target ficha exists with different content; "
                       "merge requires review.",
            "field": "target",
            "reference": "lore/A.md",
        }]
        candidate.status = "conflict"
        store.add_candidate(candidate)
        approval = service.issue_approval(job, "tester", [])
        outcomes = service.execute(job, "tester", approval.digest,
                                   approval.token)
        assert outcomes[0].action == "review"
        assert not outcomes[0].written
        assert target.read_text(encoding="utf-8") == prior  # no canon write
