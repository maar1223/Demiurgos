"""World importer — REST lifecycle router (slice 1: intake).

Server-owned import-job contract: create a job from a source selection
(folders/loose/ZIP), stream durable chunks with resumable offsets, analyze
(fail-closed on malformed/unavailable provider output), fetch redacted job
state, and cancel. Every route requires a trusted principal and resolves the
world through the canonical world authority; no canon write occurs here.

Slice 2 additions (optional Hermes advisory enrichment):
- ``analyze`` accepts ``{"enrich": bool}``; when ``True`` and an ``enricher``
  was injected at composition, the router runs enrichment after the
  deterministic provider and persists the suggestions on each candidate.
- ``review`` includes ``enrichment_status`` and ``suggestions`` per candidate.
- ``/{job_id}/review/decisions`` toggles ``review_state`` per suggestion.
- ``execute`` accepts ``suggestion_ids`` so approved IDs bind to the
  approval/execute gate.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from import_models import (
    ImportJob,
    ImportJobState,
    INTAKE_STATES,
    JobPage,
    Candidate,
    utcnow_iso,
    EnrichmentStatus,
)
from import_intake import (
    BoundedSpool,
    MalformedProviderError,
    UnsafePathError,
    ZipBombError,
    BoundsError,
    extract_zip_bounded,
    reject_unsafe_path,
)
from import_store import ImportJobStore
from import_service import ImportService

logger = logging.getLogger("demiurgos-import-router")


def _disable_enrichment(candidates: list[Candidate]) -> list[Candidate]:
    """Mark a candidate batch as ``disabled`` (used on enricher crash)."""
    out: list[Candidate] = []
    for c in candidates:
        data = c.model_dump()
        data["enrichment_json"] = None
        data["enrichment_status"] = EnrichmentStatus.DISABLED.value
        out.append(Candidate.model_validate(data))
    return out


def _aggregate_status(candidates: list[Candidate]) -> str:
    """Roll a per-batch enrichment status up to a single reviewer-visible label."""
    statuses = {getattr(c, "enrichment_status", "disabled") for c in candidates}
    if "ok" in statuses:
        return EnrichmentStatus.OK.value
    if statuses and statuses != {"disabled"}:
        return EnrichmentStatus.NO_SUGGESTIONS.value
    return EnrichmentStatus.DISABLED.value


class CreateJobRequest(BaseModel):
    source_kind: str = "loose"   # folder | loose | zip
    files: list[str] = []


class StreamChunkRequest(BaseModel):
    relative: str
    offset: int = 0
    data_b64: str = ""


class ApproveRequest(BaseModel):
    digest: str = ""
    token: str = ""
    group_ids: list[str] = []
    # Slice 2: optional IDs of approved suggestions bound to the execution.
    # Absent / empty list preserves the legacy (no enrichment) execute path.
    suggestion_ids: list[str] = []


class AnalyzeRequest(BaseModel):
    """Optional ``enrich`` opt-in (slice 2).

    When ``True`` the analyze flow invokes the injected ``enricher`` after
    deterministic analysis, persisting advisory suggestions on each
    candidate. ``False`` (default) preserves the legacy deterministic path
    with no Hermes call.
    """

    enrich: bool = False


class DecisionItem(BaseModel):
    suggestion_id: str
    decision: str        # "approve" | "reject"


class DecisionsRequest(BaseModel):
    decisions: list[DecisionItem] = []


def create_import_router(
    *,
    require_principal: Callable[[Request], Any],
    mundos_dir: Callable[[], Path],
    spool_dir: Callable[[], Path],
    store: ImportJobStore | Callable[[], ImportJobStore],
    provider: Callable[[ImportJob, list[dict[str, Any]]], list[Candidate]] | None = None,
    enricher: Callable[[list[Candidate]], list[Candidate]] | None = None,
    service: ImportService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/{mundo}/imports", tags=["world-importer"])
    _store = store if isinstance(store, ImportJobStore) else store()
    _service = service

    def guard(request: Request) -> Any:
        principal = require_principal(request)
        if principal is None:
            raise HTTPException(status_code=401, detail="Authentication required.")
        return principal

    def resolve_world(mundo: str) -> Path:
        world_dir = mundos_dir() / mundo
        resolved = world_dir.resolve()
        if not resolved.is_dir() or resolved.parent != mundos_dir().resolve():
            raise HTTPException(status_code=404, detail="Mundo no encontrado")
        if Path(mundo).name != mundo or mundo.startswith((".", "_")):
            raise HTTPException(status_code=404, detail="Mundo no encontrado")
        return resolved

    def spool_for(job_id: str, world: str) -> BoundedSpool:
        return BoundedSpool(spool_dir(), job_id, world)

    @router.post("", status_code=201)
    def create_job(mundo: str, request: Request, body: CreateJobRequest) -> dict:
        principal = guard(request)
        resolve_world(mundo)
        if body.source_kind not in {"folder", "loose", "zip"}:
            raise HTTPException(status_code=400, detail="Invalid source_kind")
        for path in body.files:
            try:
                reject_unsafe_path(path)
            except UnsafePathError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        job = ImportJob(
            job_id=uuid.uuid4().hex,
            world=mundo,
            owner_principal=getattr(principal, "id", str(principal)),
            state=ImportJobState.PENDING,
            source_kind=body.source_kind,
            opaque_token=secrets.token_hex(16),
            created_at=utcnow_iso(),
            updated_at=utcnow_iso(),
        )
        _store.create_job(job)
        _store.add_event(job.job_id, "created")
        return {"job": job.model_dump_redacted()}

    @router.get("", response_model=JobPage)
    def list_jobs(
        mundo: str,
        request: Request,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = Query(None),
    ) -> JobPage:
        """List the caller's jobs in ``mundo``, newest first (slice 2, IM-2.3).

        Authorization is principal-scoped: the query filters on
        ``owner_principal`` so foreign jobs are never returned. The cursor is
        opaque (base64-encoded tuple key) — the server validates it before use
        and returns 400 on a malformed value, never silently serving the
        wrong page. Each entry is pre-redacted (no ``opaque_token``).
        """
        principal = guard(request)
        resolve_world(mundo)
        principal_id = str(getattr(principal, "id", str(principal)))
        try:
            jobs, next_cursor = _store.list_jobs(
                principal=principal_id, world=mundo,
                limit=limit, cursor=cursor,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JobPage(
            jobs=[j.model_dump_redacted() for j in jobs],
            next_cursor=next_cursor,
        )

    @router.post("/{job_id}/stream")
    def stream_chunk(mundo: str, job_id: str, request: Request,
                     body: StreamChunkRequest) -> dict:
        principal = guard(request)
        job = _store.get_job(job_id)
        if job is None or job.world != mundo:
            raise HTTPException(status_code=404, detail="Import job not found")
        if job.owner_principal != getattr(principal, "id", str(principal)):
            raise HTTPException(status_code=403, detail="Not the job owner")
        if job.state not in INTAKE_STATES:
            raise HTTPException(status_code=409, detail="Job not in an intake state")
        if not _store.acquire_lease(job_id, str(principal), job.state):
            raise HTTPException(status_code=409, detail="Job busy (lease held)")
        try:
            spool = spool_for(job_id, mundo)
            data = base64.b64decode(body.data_b64) if body.data_b64 else b""
            spool.begin_file(body.relative, body.offset + len(data))
            spool.write_chunk(body.relative, body.offset, data)
            if job.state == ImportJobState.PENDING:
                _store.update_job(job_id, expected_revision=job.revision,
                                  state=ImportJobState.INTAKING)
        except (UnsafePathError, ValueError) as exc:
            _store.add_event(job_id, f"stream_error:{type(exc).__name__}")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            _store.release_lease(job_id, str(principal))
        return {"job_id": job_id, "offset": body.offset + len(data)}

    @router.post("/{job_id}/analyze")
    def analyze(mundo: str, job_id: str, request: Request,
                body: AnalyzeRequest | None = None) -> dict:
        principal = guard(request)
        job = _store.get_job(job_id)
        if job is None or job.world != mundo:
            raise HTTPException(status_code=404, detail="Import job not found")
        if job.owner_principal != getattr(principal, "id", str(principal)):
            raise HTTPException(status_code=403, detail="Not the job owner")
        if not _store.acquire_lease(job_id, str(principal), job.state):
            raise HTTPException(status_code=409, detail="Job busy or not intaking")
        spool = spool_for(job_id, mundo)
        # Slice 2: ``enrich`` is an opt-in flag; absent body preserves the
        # legacy deterministic flow. The router does not validate the flag's
        # value (Pydantic coerces missing body to defaults).
        enrich = bool(getattr(body, "enrich", False)) if body is not None else False

        # Source-kind dispatch: ZIP sources extract first (bounded), then we
        # analyze the extracted entries; loose/folder sources analyze the
        # spool directly. ZIP extraction reuses the manifest defenses from
        # ``inspect_zip`` (entry count, size, depth, ratio, path safety) and
        # is fail-closed: any violation marks the job FAILED before
        # candidate generation.
        analysis_root: Path = spool.job_dir
        extracted_dir: Path | None = None
        if job.source_kind == "zip":
            zip_files = [
                rel for rel in spool.offsets()
                if rel.lower().endswith(".zip")
            ]
            if not zip_files:
                _store.update_job(job_id, expected_revision=job.revision,
                                  state=ImportJobState.FAILED,
                                  error="no zip archive found in spool")
                _store.add_event(job_id, "failed:missing_zip")
                _store.release_lease(job_id, str(principal))
                return {"job": _store.get_job(job_id).model_dump_redacted()}
            zip_rel = zip_files[0]
            zip_path = spool.job_dir / zip_rel
            extracted_dir = spool.job_dir / "extracted"
            try:
                spool_files = extract_zip_bounded(zip_path, extracted_dir)
            except (ZipBombError, UnsafePathError, BoundsError) as exc:
                _store.update_job(job_id, expected_revision=job.revision,
                                  state=ImportJobState.FAILED,
                                  error=f"zip rejected: {type(exc).__name__}")
                _store.add_event(job_id, "failed:zip_safety")
                _store.release_lease(job_id, str(principal))
                return {"job": _store.get_job(job_id).model_dump_redacted()}
            # Build the files list from the extracted entries (hashed).
            files: list[dict] = []
            for sf in spool_files:
                digest = hashlib.sha256(sf.path.read_bytes()).hexdigest()
                files.append({"relative": sf.relative_path,
                              "sha256": digest, "size": sf.size})
            analysis_root = extracted_dir
        else:
            files = [
                {"relative": rel, "sha256": digest, "size": size}
                for rel in spool.offsets()
                for digest, size in [spool.finalize_file(rel)]
            ]
            files = [f for f in files if f["sha256"]]

        try:
            if provider is not None:
                candidates = provider(job, files)
                if not isinstance(candidates, list):
                    raise MalformedProviderError("provider output is not a candidate list")
            elif _service is not None:
                candidates = _analyze_via_service(
                    job, files, spool,
                    root_dir=analysis_root, mundos_dir=mundos_dir(),
                )
            else:
                raise MalformedProviderError("analysis provider unavailable")
        except MalformedProviderError as exc:
            _store.update_job(job_id, expected_revision=job.revision,
                              state=ImportJobState.FAILED, error=str(exc))
            _store.add_event(job_id, "failed:malformed_provider")
            _store.release_lease(job_id, str(principal))
            return {"job": _store.get_job(job_id).model_dump_redacted()}
        except Exception as exc:  # fail closed on any unexpected provider error
            _store.update_job(job_id, expected_revision=job.revision,
                              state=ImportJobState.FAILED, error=f"{type(exc).__name__}")
            _store.add_event(job_id, "failed:provider_error")
            _store.release_lease(job_id, str(principal))
            return {"job": _store.get_job(job_id).model_dump_redacted()}

        # Slice 2 — optional enrichment: opt-in only, after deterministic
        # candidate construction and BEFORE persistence, so the persisted
        # review row carries the suggestions. The enricher is fail-open: any
        # exception leaves candidates unchanged with status ``disabled``.
        enrichment_status = EnrichmentStatus.DISABLED.value
        if enrich and enricher is not None and candidates:
            try:
                candidates = enricher(list(candidates))
                if not isinstance(candidates, list):
                    raise MalformedProviderError("enricher output is not a candidate list")
            except MalformedProviderError as exc:
                _store.update_job(job_id, expected_revision=job.revision,
                                  state=ImportJobState.FAILED, error=str(exc))
                _store.add_event(job_id, "failed:malformed_enricher")
                _store.release_lease(job_id, str(principal))
                return {"job": _store.get_job(job_id).model_dump_redacted()}
            except Exception as exc:  # noqa: BLE001 — fail-open never breaks analyze
                _store.add_event(job_id, f"enrichment_error:{type(exc).__name__}")
                logger.warning(
                    "enricher raised during analyze (%s); "
                    "candidates persisted without suggestions",
                    type(exc).__name__, exc_info=True)
                candidates = _disable_enrichment(candidates)
            # Aggregate the batch status so the response surfaces a single
            # outcome to the reviewer (ok / no_suggestions / error).
            enrichment_status = _aggregate_status(candidates)

        added = 0
        for candidate in candidates:
            existing = _store.find_candidate(
                candidate.world, candidate.source_hash,
                candidate.normalized_identity)
            if existing is None:
                _store.add_candidate(candidate)
                added += 1
            elif enrich and candidate.enrichment_json is not None:
                # Re-running enrichment on an existing candidate is allowed:
                # the new advisory payload overwrites the prior one. The
                # deterministic identity/digest remains untouched.
                _store.update_candidate_enrichment(
                    existing.candidate_id,
                    candidate.enrichment_json,
                    candidate.enrichment_status)
        _store.update_job(job_id, expected_revision=job.revision,
                          state=ImportJobState.REVIEW, file_count=added)
        _store.add_event(
            job_id,
            f"analysis_complete:{enrichment_status}" if enrich
            else "analysis_complete")
        _store.release_lease(job_id, str(principal))
        return {"job": _store.get_job(job_id).model_dump_redacted(),
                "candidates": added,
                "enrichment_status": enrichment_status}

    @router.get("/{job_id}")
    def get_job(mundo: str, job_id: str, request: Request) -> dict:
        principal = guard(request)
        job = _store.get_job(job_id)
        if job is None or job.world != mundo:
            raise HTTPException(status_code=404, detail="Import job not found")
        if job.owner_principal != getattr(principal, "id", str(principal)):
            raise HTTPException(status_code=403, detail="Not the job owner")
        return {"job": job.model_dump_redacted()}

    @router.get("/{job_id}/review")
    def review(mundo: str, job_id: str, request: Request) -> dict:
        """Read-only reviewed candidates with placements and merge decisions.

        Slice 2: the response also exposes the per-candidate
        ``enrichment_status`` and ``enrichment_json`` (already part of
        ``Candidate.model_dump``) so the reviewer can render advisory cards.
        The deterministic ``digest`` is computed from
        ``normalized_identity:source_hash`` only — enrichment never affects
        it, so approvals remain bound to the same value across the
        analyze/review/execute lifecycle.
        """
        principal = guard(request)
        job = _store.get_job(job_id)
        if job is None or job.world != mundo:
            raise HTTPException(status_code=404, detail="Import job not found")
        if job.owner_principal != getattr(principal, "id", str(principal)):
            raise HTTPException(status_code=403, detail="Not the job owner")
        candidates = _store.candidates_for(job_id)
        suggestions_by_candidate: dict[str, list[dict[str, Any]]] = {}
        enrichment_statuses: list[str] = []
        for c in candidates:
            suggestions_by_candidate[c.candidate_id] = (
                list(c.enrichment_json) if c.enrichment_json else [])
            enrichment_statuses.append(
                getattr(c, "enrichment_status", "disabled"))
        candidates_payload = [c.model_dump() for c in candidates]
        digest = _service.candidate_digest(job) if _service else ""
        return {
            "job": job.model_dump_redacted(),
            "digest": digest,
            "candidates": candidates_payload,
            "enrichment_status": _aggregate_status(candidates),
            "suggestions": suggestions_by_candidate,
        }

    @router.post("/{job_id}/review/decisions")
    def review_decisions(mundo: str, job_id: str, request: Request,
                         body: DecisionsRequest) -> dict:
        """Toggle ``review_state`` on one or more suggestions (slice 2).

        Each decision updates the JSON list on its candidate. A missing
        candidate or unknown suggestion_id is silently skipped (idempotent
        round-trip across retries); the response reports the count of
        accepted decisions for observability. The deterministic digest is
        not recomputed because review is read-only until execute.
        """
        principal = guard(request)
        job = _store.get_job(job_id)
        if job is None or job.world != mundo:
            raise HTTPException(status_code=404, detail="Import job not found")
        if job.owner_principal != getattr(principal, "id", str(principal)):
            raise HTTPException(status_code=403, detail="Not the job owner")
        accepted = 0
        # Map suggestion_id -> (candidate_id, decision) for O(1) lookup.
        decisions_by_candidate: dict[str, list[tuple[str, str]]] = {}
        for item in body.decisions:
            decision = (item.decision or "").strip().lower()
            if decision not in {"approve", "reject"}:
                raise HTTPException(
                    status_code=400,
                    detail=f"invalid decision: {item.decision!r}")
            # Find the candidate that owns this suggestion by scanning the
            # stored enrichment payloads. The list is small per batch.
            owner: str | None = None
            for candidate in _store.candidates_for(job_id):
                payload = candidate.enrichment_json or []
                if any(isinstance(e, dict) and e.get("id") == item.suggestion_id
                       for e in payload):
                    owner = candidate.candidate_id
                    break
            if owner is None:
                continue
            decisions_by_candidate.setdefault(owner, []).append(
                (item.suggestion_id, "approved" if decision == "approve"
                 else "rejected"))
        for candidate_id, updates in decisions_by_candidate.items():
            for suggestion_id, state in updates:
                if _store.update_suggestion_state(
                        candidate_id, suggestion_id, state):
                    accepted += 1
        _store.add_event(job_id, f"review_decisions:{accepted}")
        return {"accepted": accepted}

    @router.post("/{job_id}/approve")
    def approve(mundo: str, job_id: str, request: Request,
                body: ApproveRequest) -> dict:
        principal = guard(request)
        job = _store.get_job(job_id)
        if job is None or job.world != mundo:
            raise HTTPException(status_code=404, detail="Import job not found")
        if job.owner_principal != getattr(principal, "id", str(principal)):
            raise HTTPException(status_code=403, detail="Not the job owner")
        # A failed/terminal job can never be approved (1.2).
        if job.state != ImportJobState.REVIEW:
            raise HTTPException(status_code=409,
                                detail=f"Cannot approve job in state {job.state.value}")
        if _service is None:
            raise HTTPException(status_code=501,
                                detail="Gated approval service not configured")
        try:
            approval = _service.issue_approval(
                job, str(getattr(principal, "id", str(principal))),
                list(body.group_ids), list(body.suggestion_ids))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"approval_id": approval.approval_id,
                "token": approval.token, "digest": approval.digest,
                "expires_at": approval.expires_at}

    @router.post("/{job_id}/execute")
    def execute(mundo: str, job_id: str, request: Request,
                body: ApproveRequest) -> dict:
        principal = guard(request)
        job = _store.get_job(job_id)
        if job is None or job.world != mundo:
            raise HTTPException(status_code=404, detail="Import job not found")
        if job.owner_principal != getattr(principal, "id", str(principal)):
            raise HTTPException(status_code=403, detail="Not the job owner")
        if _service is None:
            raise HTTPException(status_code=501,
                                detail="Execution service not configured")
        try:
            outcomes = _service.execute(
                job, str(getattr(principal, "id", str(principal))),
                body.digest, body.token,
                list(body.suggestion_ids))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"job": _store.get_job(job_id).model_dump_redacted(),
                "outcomes": [o.model_dump() for o in outcomes]}

    @router.post("/{job_id}/cancel")
    def cancel(mundo: str, job_id: str, request: Request) -> dict:
        principal = guard(request)
        job = _store.get_job(job_id)
        if job is None or job.world != mundo:
            raise HTTPException(status_code=404, detail="Import job not found")
        if job.owner_principal != getattr(principal, "id", str(principal)):
            raise HTTPException(status_code=403, detail="Not the job owner")
        if _service is not None:
            job = _service.cancel(job, str(getattr(principal, "id", str(principal))))
            return {"job": job.model_dump_redacted()}
        if job.state not in INTAKE_STATES:
            raise HTTPException(status_code=409, detail="Job not cancellable")
        _store.update_job(job_id, expected_revision=job.revision,
                          state=ImportJobState.CANCELLED)
        _store.add_event(job_id, "cancelled")
        return {"job": _store.get_job(job_id).model_dump_redacted()}

    @router.post("/{job_id}/resume")
    def resume(mundo: str, job_id: str, request: Request) -> dict:
        principal = guard(request)
        job = _store.get_job(job_id)
        if job is None or job.world != mundo:
            raise HTTPException(status_code=404, detail="Import job not found")
        if job.owner_principal != getattr(principal, "id", str(principal)):
            raise HTTPException(status_code=403, detail="Not the job owner")
        if _service is None:
            raise HTTPException(status_code=501, detail="Resume service not configured")
        try:
            job = _service.resume(job, str(getattr(principal, "id", str(principal))))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"job": job.model_dump_redacted()}

    @router.post("/{job_id}/rollback")
    def rollback(mundo: str, job_id: str, request: Request) -> dict:
        principal = guard(request)
        job = _store.get_job(job_id)
        if job is None or job.world != mundo:
            raise HTTPException(status_code=404, detail="Import job not found")
        if job.owner_principal != getattr(principal, "id", str(principal)):
            raise HTTPException(status_code=403, detail="Not the job owner")
        if _service is None:
            raise HTTPException(status_code=501, detail="Rollback service not configured")
        try:
            job = _service.rollback(job, str(getattr(principal, "id", str(principal))))
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"job": job.model_dump_redacted()}

    return router


def _analyze_via_service(job: ImportJob, files: list[dict],
                         spool: BoundedSpool,
                         *, root_dir: Path | None = None,
                         mundos_dir: Path | None = None) -> list[Candidate]:
    """Build ordered candidates from spooled files via the analysis facade.

    Preserves source path, heading, sequence, nearby/image anchors, and source
    order (2.7); server-owned identity/dedup so analysis stays read-only.
    ``root_dir`` allows callers to point analysis at a sub-tree (e.g., the
    extracted directory for ZIP sources); defaults to ``spool.job_dir``.
    ``mundos_dir`` is the worlds root used to resolve canonical targets; it
    is optional because ``resolve_target`` is world-agnostic today.
    """
    from import_analysis import analyze_source, resolve_target
    from import_models import Provenance

    read_root = root_dir or spool.job_dir

    def read_file(relative: str) -> str:
        try:
            return (read_root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def build_candidate(relative: str, digest: str, size: int,
                        analyzed) -> Candidate:
        identity = Path(relative).stem
        provenance = Provenance(
            source_path=relative, source_kind=job.source_kind,
            source_hash=f"sha256:{digest}", source_sequence=0,
            nearby_text_anchor=(analyzed.chunks[0].nearby_text_anchor
                                if analyzed.chunks else ""),
        )
        candidate = Candidate(
            candidate_id=uuid.uuid4().hex,
            job_id=job.job_id, world=job.world,
            normalized_identity=identity,
            source_hash=f"sha256:{digest}",
            provenance=provenance,
            content_preview=analyzed.content_preview(),
            size_bytes=size,
        )
        for chunk in analyzed.chunks:
            candidate.images.extend(chunk.images)
        return candidate

    report = analyze_source(files, read_file)
    candidates = [build_candidate(f.source_path, f.source_hash, f.size_bytes, f)
                  for f in report.files]
    # Server-owned OKF authority: diagnose every candidate against the sole
    # contract so only valid candidates are eligible (2.8).
    import okf_contract
    for candidate in candidates:
        validation = okf_contract.validate(candidate.content_preview)
        candidate.okf_issues = [i.to_dict() for i in validation.issues]
    # Slice 1 (IM-1.2): attach the canonical OKF target resolution so
    # review can surface legacy aliases and unknown subfolders.
    for candidate in candidates:
        resolution = resolve_target(job.world, candidate, mundos_dir=mundos_dir)
        candidate.target_resolution = resolution.model_dump()
    return candidates
