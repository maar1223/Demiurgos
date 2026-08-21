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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from import_models import (
    ImportJob,
    ImportJobState,
    INTAKE_STATES,
    JobPage,
    Candidate,
    ImagePlacement,
    FrontmatterCandidate,
    FrontmatterState,
    utcnow_iso,
    EnrichmentStatus,
)

if TYPE_CHECKING:
    from sync_lore.schemas import ImageEntry
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


def _ficha_anchor(body: str) -> str:
    """First meaningful body line (up to 120 chars) as a nearby-text anchor.

    Heading lines and image lines are skipped so the anchor points at prose,
    never the section title or an image markdown. Mirrors the analysis facade's
    ``_first_anchor`` so ficha candidates carry a stable nearby-text anchor.
    """
    for line in (body or "").split("\n"):
        stripped = line.strip().lstrip("#").strip()
        if not stripped or stripped.startswith("!"):
            continue
        if line.strip().startswith("#"):
            continue
        return stripped[:120]
    return ""


@dataclass
class VisionMediaEntry:
    """One extracted image tied to its owning candidate (PR3 vision seam).

    The router preserves the PR1 media bundle through analysis so the vision
    seam can attribute each analysis back to the candidate that owns it and to
    the spool-relative path where the original bytes were stored. The sync_lore
    ``ImageEntry`` annotation is import-time lazy (``TYPE_CHECKING`` only) —
    this module stays importable without sync_lore installed.
    """

    candidate_id: str
    image: ImageEntry
    spool_relative_path: str


# PR3 (sync-lore-in-importer): the vision seam runs after deterministic
# analysis + text enrichment and before candidate persistence. It receives the
# candidates and the preserved media bundle and returns candidates whose
# ``enrichment_json`` carries advisory ``vision`` suggestions. It is
# fail-open: any exception leaves the candidates unchanged and records a
# diagnostic event, so the import never blocks on vision.
VisionCallable = Callable[[list[Candidate], list[VisionMediaEntry]], list[Candidate]]


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
    vision: VisionCallable | None = None,
    service: ImportService | None = None,
    structure_inference: Callable[[str], Any] | None = None,
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
        try:
            spool = spool_for(job_id, mundo)

            # The job is now actively processing: surface the true state so a
            # live client polling GET sees ``analyzing`` (not a misleading
            # ``pending``) while the long synchronous work runs below.
            _store.update_job(
                job_id, expected_revision=job.revision,
                state=ImportJobState.ANALYZING,
                progress_stage="Preparando análisis", progress_pct=5)
            _store.add_event(job_id, "analyzing")

            def _mark_failed(job_id: str, error: str,
                             event_tag: str) -> None:
                """Fail the job, record the event, and clean up the spool.

                The current revision is read just before the terminal write so
                the earlier ``analyzing`` transition (which bumped the
                revision) never trips the optimistic guard. Cleanup is
                best-effort: a spool that cannot be removed must never mask
                the FAILED transition nor abort analyze, so it is always
                performed after the terminal transition is persisted.
                """
                current = _store.get_job(job_id)
                _store.update_job(
                    job_id, expected_revision=current.revision,
                    state=ImportJobState.FAILED, error=error)
                _store.add_event(job_id, event_tag)
                spool.cleanup()

            # Slice 2: ``enrich`` is an opt-in flag; absent body preserves the
            # legacy deterministic flow. The router does not validate the flag's
            # value (Pydantic coerces missing body to defaults).
            enrich = bool(getattr(body, "enrich", False)) if body is not None else False

            # PR3 (sync-lore-in-importer): the media bundle from the analysis
            # facade is preserved through the router so the vision seam can
            # attribute results to their owning candidate. The ``provider``
            # path yields no media bundle, so vision is skipped there.
            media_bundle: list[VisionMediaEntry] = []

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
                    _mark_failed(job_id,
                                 "no zip archive found in spool", "failed:missing_zip")
                    return {"job": _store.get_job(job_id).model_dump_redacted()}
                zip_rel = zip_files[0]
                zip_path = spool.job_dir / zip_rel
                extracted_dir = spool.job_dir / "extracted"
                try:
                    spool_files = extract_zip_bounded(zip_path, extracted_dir)
                except (ZipBombError, UnsafePathError, BoundsError) as exc:
                    _mark_failed(job_id,
                                 f"zip rejected: {type(exc).__name__}", "failed:zip_safety")
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
                _store.update_progress(job_id, "Analizando fuentes", 30)
                if provider is not None:
                    candidates = provider(job, files)
                    if not isinstance(candidates, list):
                        raise MalformedProviderError("provider output is not a candidate list")
                elif _service is not None:
                    candidates, media_bundle = _analyze_via_service(
                        job, files, spool,
                        root_dir=analysis_root, mundos_dir=mundos_dir(),
                        structure_inference=structure_inference,
                    )
                else:
                    raise MalformedProviderError("analysis provider unavailable")
            except MalformedProviderError as exc:
                _mark_failed(job_id, str(exc), "failed:malformed_provider")
                return {"job": _store.get_job(job_id).model_dump_redacted()}
            except Exception as exc:  # fail closed on any unexpected provider error
                _mark_failed(job_id, f"{type(exc).__name__}",
                             "failed:provider_error")
                return {"job": _store.get_job(job_id).model_dump_redacted()}

            _store.update_progress(job_id, "Construyendo fichas", 60)

            # Conversion-failure gate (PR: no silent empty previews). A
            # convertible source (.docx/.pdf) whose markdown conversion failed
            # yields an empty content_preview. Never let that silently reach
            # REVIEW as an empty candidate (which surfaces as a confusing
            # "missing frontmatter 'type'" OKF error) — fail the job with a
            # clear message and record a diagnostic event so the user sees a
            # real, actionable error.
            failed_conversions = [
                c for c in candidates
                if not c.content_preview
                and any(d in ("conversion_failed", "conversion_unavailable")
                        for d in c.diagnostics)
            ]
            if failed_conversions:
                # Distinguish "converter not installed" (environment, actionable
                # install hint) from "converter ran but produced nothing"
                # (suspect file), so the user sees the actual cause instead of a
                # generic "too large or corrupt" guess.
                if any("conversion_unavailable" in c.diagnostics
                       for c in failed_conversions):
                    error = (
                        "Conversion unavailable: the document converter "
                        "(.docx/.pdf) is not installed on the server. "
                        "Install it with: pip install 'markitdown[docx]'"
                    )
                else:
                    error = (
                        "Conversion failed: the .docx/.pdf file could not be "
                        "converted (the file may be too large or corrupt)"
                    )
                _mark_failed(
                    job_id, error,
                    "failed:conversion",
                )
                return {"job": _store.get_job(job_id).model_dump_redacted()}

            # Slice 2 — optional enrichment: opt-in only, after deterministic
            # candidate construction and BEFORE persistence, so the persisted
            # review row carries the suggestions. The enricher is fail-open: any
            # exception leaves candidates unchanged with status ``disabled``.
            #
            # Enrichment cache: before calling the enricher, check which
            # candidates already have enrichment from a prior import (same
            # world + source_hash + normalized_identity). Reuse that cached
            # enrichment instead of re-running Hermes — this saves tokens on
            # re-imports of identical content.
            enrichment_status = EnrichmentStatus.DISABLED.value
            enriched_from_cache = 0
            cache_hit_ids: set[str] = set()
            if enrich and enricher is not None and candidates:
                _store.update_progress(job_id, "Consultando asistente", 80)
                # Partition candidates into cache-hit vs cache-miss.
                cache_hits: list[Candidate] = []
                cache_misses: list[Candidate] = []
                for candidate in candidates:
                    existing = _store.find_candidate(
                        candidate.world, candidate.source_hash,
                        candidate.normalized_identity)
                    if (existing is not None
                            and existing.enrichment_json is not None
                            and existing.enrichment_status != "disabled"):
                        # Reuse cached enrichment + funnel metadata — patch the
                        # in-memory candidate so review shows the persisted
                        # summary/frontmatter without re-running Hermes.
                        cache_hits.append(candidate.model_copy(update={
                            "enrichment_json": existing.enrichment_json,
                            "enrichment_status": existing.enrichment_status,
                            "summary": existing.summary or candidate.summary,
                            "frontmatter": existing.frontmatter
                            or candidate.frontmatter,
                            "display_title": existing.display_title
                            or candidate.display_title,
                            "media_diagnostics": existing.media_diagnostics
                            or candidate.media_diagnostics,
                        }))
                        cache_hit_ids.add(candidate.candidate_id)
                        enriched_from_cache += 1
                    else:
                        cache_misses.append(candidate)

                # Only run the enricher on candidates without cached enrichment.
                if cache_misses:
                    try:
                        enriched_misses = enricher(list(cache_misses))
                        if not isinstance(enriched_misses, list):
                            raise MalformedProviderError(
                                "enricher output is not a candidate list")
                    except MalformedProviderError as exc:
                        _mark_failed(job_id, str(exc),
                                     "failed:malformed_enricher")
                        return {"job": _store.get_job(job_id).model_dump_redacted()}
                    except Exception as exc:  # noqa: BLE001 — fail-open never breaks analyze
                        _store.add_event(job_id, f"enrichment_error:{type(exc).__name__}")
                        logger.warning(
                            "enricher raised during analyze (%s); "
                            "candidates persisted without suggestions",
                            type(exc).__name__, exc_info=True)
                        enriched_misses = _disable_enrichment(cache_misses)
                    # Merge cache hits + newly enriched misses.
                    candidates = cache_hits + list(enriched_misses)
                else:
                    # All candidates were cache hits — no enricher call needed.
                    candidates = cache_hits
                # Aggregate the batch status so the response surfaces a single
                # outcome to the reviewer (ok / no_suggestions / error).
                enrichment_status = _aggregate_status(candidates)

            # PR3 — optional vision enrichment: extracted media goes through
            # the injected vision seam AFTER deterministic analysis + text
            # enrichment and BEFORE persistence, so the persisted review row
            # carries the advisory vision suggestions. Fail-open: any vision
            # failure (exception or malformed output) leaves the candidates
            # unchanged and records a diagnostic event — the import never
            # blocks on vision, and a text-only assistant (``vision=None``)
            # runs exactly as before.
            if vision is not None and media_bundle and candidates:
                try:
                    vision_result = vision(candidates, media_bundle)
                    if not isinstance(vision_result, list):
                        raise MalformedProviderError(
                            "vision output is not a candidate list")
                    candidates = vision_result
                except Exception as exc:  # noqa: BLE001 — fail-open never breaks analyze
                    _store.add_event(job_id, f"vision_error:{type(exc).__name__}")
                    logger.warning(
                        "vision raised during analyze (%s); "
                        "candidates persisted without vision data",
                        type(exc).__name__, exc_info=True)
                else:
                    # The batch status must reflect the vision outcome even
                    # when text enrichment was not requested.
                    enrichment_status = _aggregate_status(candidates)

            added = 0
            for candidate in candidates:
                existing = _store.find_candidate(
                    candidate.world, candidate.source_hash,
                    candidate.normalized_identity)
                if existing is None:
                    _store.add_candidate(candidate)
                    added += 1
                elif candidate.candidate_id in cache_hit_ids:
                    # Cache hit: re-point the existing candidate row at the
                    # current job so candidates_for(job_id) returns it for
                    # review/execute. The UNIQUE constraint on
                    # (world, source_hash, normalized_identity) prevents a
                    # duplicate insert; reassignment is the correct operation.
                    _store.reassign_candidate_to_job(
                        existing.candidate_id, job.job_id)
                    # PR3: when vision ran, the in-memory candidate carries
                    # fresh vision suggestions on top of the cached text
                    # enrichment — persist them so review sees the new
                    # advisory payload.
                    if vision is not None and candidate.enrichment_json is not None:
                        _store.update_candidate_enrichment(
                            existing.candidate_id,
                            candidate.enrichment_json,
                            candidate.enrichment_status)
                    # Backfill the media bundle when the cached row predates
                    # media extraction (e.g., before python-docx was
                    # installed) but the fresh analysis extracted images.
                    if not existing.images and candidate.images:
                        _store.update_candidate_images(
                            existing.candidate_id, candidate.images)
                    added += 1
                elif (enrich or vision is not None) \
                        and candidate.enrichment_json is not None:
                    # No cached enrichment (first import or was disabled).
                    # Persist the new enrichment payload (text suggestions
                    # and/or PR3 vision suggestions).
                    _store.update_candidate_enrichment(
                        existing.candidate_id,
                        candidate.enrichment_json,
                        candidate.enrichment_status)
                    # Persist the fresh funnel metadata (frontmatter/summary/
                    # media diagnostics) so the review row carries it.
                    _store.update_candidate_funnel(
                        existing.candidate_id, candidate)
                    # Re-assign to the current job so candidates_for(job_id)
                    # returns it for review/execute.
                    _store.reassign_candidate_to_job(
                        existing.candidate_id, job.job_id)
                    # Backfill the media bundle on the same condition.
                    if not existing.images and candidate.images:
                        _store.update_candidate_images(
                            existing.candidate_id, candidate.images)
                    added += 1
                else:
                    # Candidate exists but no enrichment was requested/available.
                    # Re-assign to the current job so it appears in review.
                    _store.reassign_candidate_to_job(
                        existing.candidate_id, job.job_id)
                    # If the existing candidate has empty content (e.g., was
                    # created before markitdown was installed), update it with
                    # the newly extracted content.
                    if not existing.content_preview and candidate.content_preview:
                        _store.update_candidate_content(
                            existing.candidate_id, candidate.content_preview)
                    # Same for the media bundle: a candidate created while
                    # media extraction was unavailable (e.g., before
                    # python-docx was installed) carries no image placements;
                    # backfill them from the fresh analysis.
                    if not existing.images and candidate.images:
                        _store.update_candidate_images(
                            existing.candidate_id, candidate.images)
                    added += 1
            current = _store.get_job(job_id)
            _store.update_job(job_id, expected_revision=current.revision,
                              state=ImportJobState.REVIEW, file_count=added)
            _store.add_event(
                job_id,
                f"analysis_complete:{enrichment_status}:cached={enriched_from_cache}"
                if enrich else "analysis_complete")
            return {"job": _store.get_job(job_id).model_dump_redacted(),
                    "candidates": added,
                    "enrichment_status": enrichment_status,
                    "enriched_from_cache": enriched_from_cache}

        finally:
            _store.release_lease(job_id, str(principal))

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
        cancelled = _store.get_job(job_id)
        _store.add_event(job_id, "cancelled")
        spool_for(job_id, mundo).cleanup()
        # Opción A — the direct-cancel fallback reaps the DB row too. Capture
        # the CANCELLED job before deletion so the response stays honest.
        _store.delete_job(job_id)
        return {"job": cancelled.model_dump_redacted()}

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

    @router.delete("/{job_id}")
    def delete_job(mundo: str, job_id: str, request: Request) -> dict:
        """Manually delete a terminal job (Opción A reaping).

        Only the owner may delete. Allowed states: ``completed`` /
        ``failed`` / ``rolled_back`` (audit/debug kept by default but
        deletable on demand) and an empty ``review`` (no candidates). A
        ``review`` job with candidates is never deletable — the review is
        pending approval. The spool is cleaned best-effort first; a spool
        that cannot be removed must never mask the DB delete.
        """
        principal = guard(request)
        job = _store.get_job(job_id)
        if job is None or job.world != mundo:
            raise HTTPException(status_code=404, detail="Import job not found")
        if job.owner_principal != getattr(principal, "id", str(principal)):
            raise HTTPException(status_code=403, detail="Not the job owner")

        allowed_states = {
            ImportJobState.COMPLETED,
            ImportJobState.FAILED,
            ImportJobState.ROLLED_BACK,
        }
        if job.state == ImportJobState.REVIEW:
            # Allow deleting an empty review (no candidates to lose); a review
            # with candidates is pending approval and must be kept.
            if len(_store.candidates_for(job_id)) > 0:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot delete review job with candidates")
        elif job.state not in allowed_states:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete job in state {job.state.value}")

        # Best-effort spool cleanup — never masks the DB delete.
        spool_for(job_id, mundo).cleanup()

        _store.delete_job(job_id)
        return {"success": True}

    return router


def _analyze_via_service(job: ImportJob, files: list[dict],
                         spool: BoundedSpool,
                         *, root_dir: Path | None = None,
                         mundos_dir: Path | None = None,
                         structure_inference: Callable[[str], Any] | None = None
                         ) -> tuple[list[Candidate], list[VisionMediaEntry]]:
    """Build ordered candidates + the preserved media bundle from spooled files.

    Preserves source path, heading, sequence, nearby/image anchors, and source
    order (2.7); server-owned identity/dedup so analysis stays read-only.
    ``root_dir`` allows callers to point analysis at a sub-tree (e.g., the
    extracted directory for ZIP sources); defaults to ``spool.job_dir``.
    ``mundos_dir`` is the worlds root used to resolve canonical targets; it
    is optional because ``resolve_target`` is world-agnostic today.
    ``structure_inference`` (importador-auto-frontmatter, task 1.2 seam) is the
    concrete Hermes H1-H5 inference callable used only when the deterministic
    scan finds no headings; wired from the composition layer.

    importador-auto-frontmatter (Phase 2): candidates are now built ONE PER
    complete ficha from the deterministic H1-H5 tree splitter (Step 0/1), so a
    single source file yields one candidate per ficha instead of one oversized
    file-sized candidate. Each candidate carries the parent-qualified
    ``canonical_id``, ``display_title``, the original ficha body, reference-
    image diagnostics, and a ``manual`` frontmatter the enrichment funnel
    (Step 2-4) upgrades.

    PR3 (sync-lore-in-importer): ``analyze_source`` receives the ``file_path``
    resolver and the job spool root so ``.docx``/``.pdf`` sources are converted
    and their extracted media is persisted under the spool (tasks 5.5). The
    returned ``media_bundle`` ties every extracted image to its owning
    candidate so the router can hand it to the vision seam.
    """
    from import_analysis import analyze_source, resolve_target, split_heading_tree
    from import_models import Provenance

    read_root = root_dir or spool.job_dir

    def read_file(relative: str) -> str:
        try:
            return (read_root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def build_ficha_candidate(relative: str, digest: str, size: int,
                              analyzed, ficha) -> Candidate:
        """Build one Candidate per complete-ficha node (importador-auto-
        frontmatter).

        ``content_preview`` is the ficha's ORIGINAL body (preservation-first);
        ``canonical_id`` and ``display_title`` carry the ficha identity;
        ``media_diagnostics`` surface the reference-image placements
        (``![][key]``). Frontmatter starts ``manual`` (title = display title)
        — the enrichment funnel upgrades it to ``generated``/``fallback``.
        An implicit ficha (no usable headings) falls back to the file stem so
        the legacy single-candidate path keeps its identity/digest semantics.
        """
        identity = ficha.canonical_id or Path(relative).stem
        display_title = ficha.title or Path(relative).stem
        provenance = Provenance(
            source_path=relative, source_kind=job.source_kind,
            source_hash=f"sha256:{digest}",
            source_sequence=ficha.source_order,
            nearby_text_anchor=_ficha_anchor(ficha.body),
        )
        return Candidate(
            candidate_id=uuid.uuid4().hex,
            job_id=job.job_id, world=job.world,
            normalized_identity=identity,
            canonical_id=ficha.canonical_id,
            display_title=display_title,
            source_hash=f"sha256:{digest}",
            provenance=provenance,
            content_preview=ficha.body,
            size_bytes=len(ficha.body),
            diagnostics=list(analyzed.diagnostics),
            media_diagnostics=list(ficha.media_diagnostics),
            frontmatter=FrontmatterCandidate(
                title=display_title, type=None, description="", relaciones=[],
                state=FrontmatterState.MANUAL),
        )

    report = analyze_source(
        files,
        read_file,
        file_path=lambda relative: read_root / relative,
        spool_root=spool.job_dir,
    )
    candidates: list[Candidate] = []
    media_bundle: list[VisionMediaEntry] = []
    for f in report.files:
        text = f.content_preview()
        tree = split_heading_tree(text, structure_inference=structure_inference)
        fichas = tree.fichas
        if not fichas:
            continue
        # One candidate per ficha, in source order.
        ficha_candidates: list[Candidate] = []
        for ficha in fichas:
            ficha_candidates.append(
                build_ficha_candidate(f.source_path, f.source_hash,
                                      f.size_bytes, f, ficha))
        # Distribute the file's inline image placements to the ficha whose body
        # references them; unmatched placements fold into the first ficha
        # (preservation-first — an extracted image is never dropped).
        inline = [p for chunk in f.chunks for p in chunk.images]
        unmatched: list[ImagePlacement] = []
        for placement in inline:
            owner = next(
                (c for c in ficha_candidates
                 if placement.relative_media_path
                 and placement.relative_media_path in c.content_preview),
                None)
            if owner is None:
                unmatched.append(placement)
            else:
                owner.images.append(placement)
        for placement in unmatched:
            ficha_candidates[0].images.append(placement)
        # PR3 — attach extracted media to the owning ficha (by spool path) and
        # preserve the media bundle tied to the candidate that owns each image.
        for media in f.media:
            owner = next(
                (c for c in ficha_candidates
                 if media.spool_relative_path in c.content_preview),
                ficha_candidates[0])
            if not any(p.relative_media_path == media.spool_relative_path
                       for p in owner.images):
                owner.images.append(ImagePlacement(
                    gallery_asset_id="",
                    relative_media_path=media.spool_relative_path,
                    alt_text="",
                    target_ficha=owner.canonical_id,
                    confidence=1.0,
                    placement_status="proposed",
                ))
            media_bundle.append(VisionMediaEntry(
                candidate_id=owner.candidate_id,
                image=media.image,
                spool_relative_path=media.spool_relative_path,
            ))
        candidates.extend(ficha_candidates)
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
    return candidates, media_bundle
