"""World importer — lifecycle service (Phase 2).

Owns the reviewed/approval/execution lifecycle on top of the durable store.
Analysis stays read-only; only explicit, digest/token-bound approval may
invoke gated merge + gallery registration + replacement snapshots. Every
decision is surfaced for review: the merge is preservation-first (current
fichas authoritative, only missing images/references added, conflicts require
review) and image placement never silently reorders, appends, or detaches.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from import_models import (
    Approval,
    Candidate,
    ExecutionOutcome,
    FrontmatterCandidate,
    FrontmatterState,
    ImportJob,
    ImportJobState,
    ItemOutcome,
    MergeDecision,
    ReplacementRecord,
    TargetResolution,
    utcnow_iso,
)
from import_analysis import resolve_target
from import_intake import BoundedSpool
from import_store import ImportJobStore

if TYPE_CHECKING:
    # Only needed for the type annotation; graph_indexer uses package-relative
    # imports that are unsafe to trigger from the top-level test harness, so
    # the name is never evaluated at runtime (annotations are stringified via
    # ``from __future__ import annotations``).
    from graph_indexer import GraphReconcileResult

logger = logging.getLogger("demiurgos-import")

APPROVAL_TTL_MINUTES = 30
PAPELERA_RETENTION_DAYS = 30
_VALID_SECTIONS = frozenset({"lore", "personajes", "sagas", "referencias"})


def digest_of(content: str) -> str:
    """sha256 hex digest of a string (the confirmation integrity primitive)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _markdown_images(content: str) -> list[str]:
    """All image markdown references in a body, in document order."""
    return re.findall(r"!\[[^\]]*\]\(([^)]+)\)", content or "")


def _classify_entry(entry: dict) -> str:
    """Best-effort: is a serialized suggestion dict a classification or a relationship?

    Slice 2 contract: suggestion dicts carry a ``__type__`` discriminator
    (``"classification"`` / ``"relationship"``) attached at serialization.
    This fallback uses the Pydantic field shape to recover the kind when
    the discriminator is absent (e.g., older persisted payloads). Unknown
    shapes return an empty string and are skipped silently during execute.
    """
    if not isinstance(entry, dict):
        return ""
    explicit = entry.get("__type__")
    if explicit in {"classification", "relationship"}:
        return explicit
    # Relationship shape: has source_candidate_id + relationship_type.
    if "source_candidate_id" in entry and "relationship_type" in entry:
        return "relationship"
    # Classification shape: has candidate_id + type + tags.
    if "candidate_id" in entry and "type" in entry and "tags" in entry:
        return "classification"
    return ""


# Matches the renderer's `#align-size` suffix (e.g. `#left`, `#right-sm`,
# `#center`, `#lg`, `#sm`). The suffix is display metadata, not part of the
# media file path; the underlying file is always the clean base path.
_ALIGN_SIZE_SUFFIX = re.compile(r"#(?:left|right|center|sm|lg)(?:-(?:sm|lg))?$")


def _clean_media_path(ref: str) -> str:
    """Strip a trailing `#align-size` suffix, keeping the media file path.

    ``img.png#left`` -> ``img.png``. The suffix is preserved in the Markdown
    reference the ficha keeps; only the gallery/spool lookup uses the clean
    path. Returns the input unchanged when there is no suffix.
    """
    if not ref:
        return ref
    return _ALIGN_SIZE_SUFFIX.sub("", ref)


# ---------------------------------------------------------------------------
# Preservation-first merge (2.2)
# ---------------------------------------------------------------------------

def plan_merge(current_content: str, incoming_content: str) -> MergeDecision:
    """Decide a merge for one ficha without overwriting edited text.

    - Missing target ficha      -> ``add`` (create it)
    - Incoming text equals current (modulo whitespace) -> ``keep`` (no-op)
    - Incoming ONLY adds missing image/reference lines to an existing ficha
      -> ``add`` (contextual additions, current text untouched)
    - Incoming changes existing prose      -> ``review`` (explicit conflict)
    """
    current = (current_content or "").strip()
    incoming = (incoming_content or "").strip()
    if not current:
        return MergeDecision(target="", mode="add", action="add",
                             reason="new ficha")
    if current == incoming:
        return MergeDecision(target="", mode="add", action="keep",
                             reason="unchanged")

    current_lines = current.split("\n")
    incoming_lines = incoming.split("\n")
    current_images = set(_markdown_images(current))
    incoming_images = set(_markdown_images(incoming))

    # Only additions: every incoming line that is a pure image/reference line
    # not already present is allowed; any line touching existing prose is a
    # conflict.
    added_image_lines = [
        line for line in incoming_lines
        if line.strip().startswith("!") and line not in current_lines
    ]
    if added_image_lines and _only_additions(current_lines, incoming_lines):
        return MergeDecision(target="", mode="add", action="add",
                             reason="contextual image/reference additions")
    return MergeDecision(target="", mode="add", action="review",
                         reason="incoming modifies existing content")


def _only_additions(current_lines: list[str], incoming_lines: list[str]) -> bool:
    """True when incoming is current plus some purely-added lines."""
    cur = [l for l in current_lines if l.strip()]
    inc = [l for l in incoming_lines if l.strip()]
    if len(inc) < len(cur):
        return False
    # every current non-empty line must appear in incoming in order
    it = iter(inc)
    for line in cur:
        for candidate in it:
            if candidate == line:
                break
        else:
            return False
    return True


# ---------------------------------------------------------------------------
# Contextual image placement (2.3)
# ---------------------------------------------------------------------------

def _overlay_alt_text(preview: str, placements: list[dict]) -> str:
    """Overlay vision descriptions as markdown image alt-text (PR3, task 6.5).

    For every approved placement that carries a vision-derived ``alt_text``,
    rewrite the matching ``![old](path)`` reference in the preview to
    ``![description](path)``. The media path is never changed — only the
    alt-text, so source fidelity and gallery resolution are preserved. If the
    reference is absent (e.g. the image came from the media bundle and has no
    markdown ref), the preview is left untouched.
    """
    result = preview or ""
    for placement in placements:
        path = placement.get("relative_media_path") or ""
        alt = placement.get("alt_text") or ""
        if not path or not alt:
            continue
        pattern = re.compile(
            r"!\[[^\]]*\]\(\s*" + re.escape(path) + r"\s*\)"
        )
        result = pattern.sub(f"![{alt}]({path})", result)
    return result


def plan_placements(existing_images: list[str],
                    proposed: list[dict]) -> list[dict]:
    """Resolve proposed image placements without silent reorder/detach.

    Each proposed dict has ``relative_media_path`` and ``target_ficha``. A
    placement is ``skip`` when the image already exists in the target; the
    target is chosen only when unambiguous. Never reorders existing images
    and never appends wholesale — every unresolved/ambiguous case is marked
    ``ambiguous`` (review required).
    """
    seen = {_clean_media_path(img) for img in existing_images}
    results: list[dict] = []
    for prop in proposed:
        ref = prop.get("relative_media_path") or ""
        if not ref:
            results.append({**prop, "placement_status": "ambiguous",
                            "reason": "no media path"})
            continue
        # Dedup on the clean base path: `img.png#left` and `img.png#right`
        # resolve to the same gallery file, so only one placement is admitted.
        clean = _clean_media_path(ref)
        if clean in seen:
            results.append({**prop, "placement_status": "skip",
                            "reason": "already present"})
            continue
        seen.add(clean)
        target = prop.get("target_ficha") or ""
        if not target:
            results.append({**prop, "placement_status": "ambiguous",
                            "reason": "no unambiguous target"})
            continue
        results.append({**prop, "placement_status": "approved",
                        "target_ficha": target})
    return results


# ---------------------------------------------------------------------------
# Replacement snapshot (2.4)
# ---------------------------------------------------------------------------

def snapshot_to_papelera(mundo_dir: Path, section: str, rel_path: str,
                         content: str, world: str) -> ReplacementRecord:
    """Snapshot a ficha's prior bytes into ``.papelera`` for 30-day recovery.

    Mirrors the existing papelera layout (``.papelera/{section}/{id12}/`` +
    ``meta.json``) so the standard list/restore/purge endpoints can recover it
    within the retention window. Audit/provenance stays in the store.
    """
    entry_id = uuid.uuid4().hex[:12]
    entry_dir = mundo_dir / ".papelera" / section / entry_id
    entry_dir.mkdir(parents=True, exist_ok=True)
    (entry_dir / Path(rel_path).name).write_text(content, encoding="utf-8")
    meta = {
        "entry_id": entry_id,
        "original_path": rel_path,
        "kind": "file",
        "deleted_at": _utcnow().isoformat().replace("+00:00", "Z"),
        "size": len(content.encode("utf-8")),
        "source": f"import:{world}",
    }
    (entry_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    expiry = (_utcnow() + timedelta(days=PAPELERA_RETENTION_DAYS)).isoformat()
    return ReplacementRecord(
        prior_snapshot=rel_path,
        papelera_entry=entry_id,
        expiry=expiry,
        recovery_status="available",
    )


def atomic_write(full: Path, content: str) -> None:
    """Same-directory atomic replace (crash-safe, no partial ficha)."""
    tmp = full.with_name(f".{full.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        tmp.replace(full)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Approved-only frontmatter materialization (importador-auto-frontmatter, 3.1)
# ---------------------------------------------------------------------------

def render_frontmatter_document(
    frontmatter: FrontmatterCandidate,
    body: str,
    canonical_id: str = "",
) -> str:
    """Render an approved OKF document: frontmatter + the untouched body.

    Approved execution materializes the reviewable ``FrontmatterCandidate``
    as the OKF frontmatter block (``title``/``type``/``description``/
    ``status``/``relaciones``) followed by the ficha's original body verbatim
    — never a truncated or generated replacement of author text. Approved
    materialization always emits ``status: draft`` so imported fichas enter
    as borrador (BLOQUE 2), which the tree/graph/panel can consume.
    ``relaciones`` are serialized as OKF ``[[canonical_id]]`` wikilinks. When
    the candidate carries a parent-qualified ``canonical_id``, it is emitted
    as the ``id`` so the OKF/graph identity contract recognizes the same key
    (task 3.3).

    ``canonical_id`` is omitted when empty or not a canonical identity (e.g.
    an implicit single-ficha candidate), so the emitted document stays a
    valid OKF document whose identity the graph can parse.
    """
    lines = ["---"]
    if canonical_id:
        lines.append(f"id: {canonical_id}")
    lines.append(f"title: {frontmatter.title}")
    if frontmatter.type:
        lines.append(f"type: {frontmatter.type}")
    if frontmatter.description:
        lines.append(f"description: {frontmatter.description}")
    # BLOQUE 2 — imported fichas always enter as borrador: the tree badge,
    # the graph and the Relaciones y Canon panel consume this status.
    lines.append("status: draft")
    if frontmatter.relaciones:
        # Block-form quoted wikilinks (matching the existing OKF corpus) so the
        # YAML is unambiguous: each entry is a ``[[canonical_id]]`` string that
        # both okf_contract and the graph index parse as one link.
        lines.append("relaciones:")
        for relation in frontmatter.relaciones:
            lines.append(f'  - "[[{relation}]]"')
    lines.append("---")
    head = "\n".join(lines)
    body_clean = (body or "").lstrip("\n")
    return f"{head}\n\n{body_clean}"


def _unresolved_media_warnings(candidate: Candidate) -> list[str]:
    """Non-blocking review warnings for unresolved reference-style media.

    Reference-style placements (``![][key]``) with no matching ``[key]: path``
    definition are isolated: they are never part of ``candidate.images`` (the
    inline-placement/gallery path), never fail the ficha or the job, and each
    surfaces as a review warning only (design: media isolation, 3.2).
    """
    return [
        d.message or f"unresolved media reference [{d.image_key}]"
        for d in candidate.media_diagnostics
        if d.status == "unresolved"
    ]


def _is_funnel_frontmatter(candidate: Candidate) -> bool:
    """True when the candidate carries funnel-produced reviewable frontmatter.

    The enrichment funnel (``analyze_ficha_funnel``) guarantees every analyzed
    candidate has a ``FrontmatterCandidate`` in ``generated`` (Step 4 produced
    it) or ``fallback`` (enrichment attempted but failed — fail-open) state.
    Those are materialized during execute (task 3.1). A ``manual`` frontmatter
    is the legacy default stub (no enrichment requested, or the legacy
    ``enrich_candidates`` enricher) and keeps the legacy suggestion-patch /
    body-only write path.
    """
    if candidate.frontmatter is None:
        return False
    return candidate.frontmatter.state in (
        FrontmatterState.GENERATED, FrontmatterState.FALLBACK,
    )


# ---------------------------------------------------------------------------
# Lifecycle service
# ---------------------------------------------------------------------------

class ImportService:
    """Server-owned import lifecycle: approve / execute / cancel / rollback."""

    def __init__(self, *, store: ImportJobStore, mundos_dir: Path,
                 spool_dir: Path,
                 read_file: Callable[[str], str] | None = None,
                 graph_reconcile: Callable[[str, str], None] | None = None,
                 graph_reconcile_many: Callable[[list[str], str], GraphReconcileResult] | None = None,
                 register_gallery: Callable[[str, Path, str], str] | None = None,
                 now: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.mundos_dir = Path(mundos_dir)
        self.spool_dir = Path(spool_dir)
        self._read_file = read_file or (lambda _rel: "")
        self._graph_reconcile = graph_reconcile
        self._graph_reconcile_many = graph_reconcile_many
        self._register_gallery = register_gallery
        self._now = now or _utcnow

    def _mundo_dir(self, world: str) -> Path:
        return self.mundos_dir / world

    def _target_for(self, world: str, candidate: Candidate) -> Path:
        """Resolve the target ficha path from a candidate's identity.

        Slice 1 (IM-1.2): delegates to ``resolve_target`` so legacy uppercase
        sections and supported OKF subfolder aliases are normalized, and
        ambiguous mappings produce a ``review`` outcome instead of a guess.
        Kept for backwards compatibility with callers that only want the path;
        prefer ``_resolve_candidate_target`` when the status matters.
        """
        resolution = resolve_target(world, candidate, mundos_dir=self.mundos_dir)
        return self._mundo_dir(world) / resolution.canonical_path

    def _resolve_candidate_target(self, world: str,
                                  candidate: Candidate) -> TargetResolution:
        """Return the ``TargetResolution`` (path + status) for one candidate.

        Use this when the caller needs to surface ``review``/``rejected``
        status (e.g., execution must short-circuit on a non-resolved mapping).
        """
        resolution = resolve_target(world, candidate, mundos_dir=self.mundos_dir)
        if not resolution.canonical_path:
            return resolution
        # Re-anchor the canonical path against this instance's mundos_dir so
        # the caller can use it directly without an extra join.
        from pathlib import Path as _P
        anchored = _P(resolution.canonical_path)
        del anchored  # canonical_path is always relative; callers can join.
        return resolution

    def candidate_digest(self, job: ImportJob) -> str:
        """Immutable digest over the reviewed candidates (group-scoped)."""
        candidates = self.store.candidates_for(job.job_id)
        ordered = "|".join(
            f"{c.normalized_identity}:{c.source_hash}" for c in candidates)
        return digest_of(ordered)

    def issue_approval(self, job: ImportJob, principal: str,
                       group_ids: list[str],
                       suggestion_ids: list[str] | None = None) -> Approval:
        """Issue a server-owned, digest-bound, expiring approval token.

        ``suggestion_ids`` (slice 2) is bound to the approval so a stale,
        expired, or replayed token cannot resurrect a prior decision. An
        absent/empty list preserves the legacy no-enrichment path; the
        deterministic digest stays over ``identity:source_hash`` only.
        """
        digest = self.candidate_digest(job)
        token = secrets.token_hex(16)
        issued = self._now().isoformat()
        expires = (self._now() + timedelta(minutes=APPROVAL_TTL_MINUTES)).isoformat()
        approval = Approval(
            approval_id=uuid.uuid4().hex,
            job_id=job.job_id, principal=principal, revision=job.revision,
            digest=digest, token=token, group_ids=list(group_ids),
            suggestion_ids=list(suggestion_ids or []),
            issued_at=issued, expires_at=expires,
        )
        self.store.save_approval(approval)
        return approval

    def validate_approval(self, job: ImportJob, principal: str,
                          digest: str, token: str) -> Approval:
        """Fails closed (raises ValueError) on stale/expired/replayed/mismatch.

        The approval must match this job, this principal, the current job
        revision, the reviewed digest, and an unexpired, unconsumed token.
        Any violation means zero writes.
        """
        approval = self.store.find_approval(job.job_id, token)
        if approval is None:
            raise ValueError("unknown approval token")
        if approval.consumed:
            raise ValueError("approval token already consumed (replay)")
        if approval.principal != principal:
            raise ValueError("approval bound to another principal")
        if approval.revision != job.revision:
            raise ValueError("approval revision is stale")
        if approval.digest != digest:
            raise ValueError("reviewed digest changed since approval")
        try:
            expires = datetime.fromisoformat(approval.expires_at)
        except ValueError as exc:
            raise ValueError("approval has no valid expiry") from exc
        if expires < self._now():
            raise ValueError("approval token expired")
        return approval

    def execute(self, job: ImportJob, principal: str, digest: str,
                token: str, suggestion_ids: list[str] | None = None) -> list[ExecutionOutcome]:
        """Gated execution: merge + gallery + replacement + graph reconcile.

        Only proceeds after ``validate_approval`` passes; each candidate is
        written through the gated merge, image placements are registered in
        the gallery, explicit replacements snapshot the prior ficha, and the
        graph is reconciled before success.

        ``suggestion_ids`` (slice 2) is bound to the approval token: only the
        IDs listed at approve time can materialize, and only the matching
        classification + relationship suggestions on each candidate are
        applied. The patched ``content_preview`` is the single source of
        truth fed to the canonical write.
        """
        self.validate_approval(job, principal, digest, token)
        approved_ids = list(suggestion_ids or [])
        self.store.mark_approval_consumed(job.job_id, token)
        self.store.update_job(job.job_id, expected_revision=job.revision,
                              state=ImportJobState.EXECUTING)
        # Resolve approved suggestions ONCE up front so per-candidate
        # execution reuses the cached lists (a single batch can produce
        # many suggestions; classification + relationships are kept
        # separate because they patch different frontmatter keys).
        try:
            from import_enrichment import (
                ClassificationSuggestion,
                RelationshipSuggestion,
                apply_approved_suggestions,
            )
        except Exception:  # noqa: BLE001 — never break execute on import drift
            ClassificationSuggestion = None  # type: ignore
            RelationshipSuggestion = None  # type: ignore
            apply_approved_suggestions = None  # type: ignore
        classifications: list = []
        relationships: list = []
        if approved_ids and ClassificationSuggestion is not None:
            for candidate in self.store.candidates_for(job.job_id):
                payload = candidate.enrichment_json or []
                for entry in payload:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("id") not in approved_ids:
                        continue
                    kind = entry.get("__type__") or _classify_entry(entry)
                    # Strip the wire-side discriminator before re-validation:
                    # ``ClassificationSuggestion`` / ``RelationshipSuggestion``
                    # both use ``extra="forbid"`` and would otherwise reject
                    # the ``__type__`` key that ``enrich_candidates`` attaches
                    # for shape-based fallback classification.
                    wire_entry = {k: v for k, v in entry.items() if k != "__type__"}
                    try:
                        if kind == "classification":
                            classifications.append(
                                ClassificationSuggestion.model_validate(wire_entry))
                        elif kind == "relationship":
                            relationships.append(
                                RelationshipSuggestion.model_validate(wire_entry))
                    except Exception:  # noqa: BLE001 — skip malformed entries
                        continue
        # PR3 — approved vision suggestions: only image suggestions whose id is
        # bound to the approval token may materialize. ``vision_by_path`` maps
        # EVERY vision entry (by media path) so execution can distinguish
        # "approved with description" from "pending/rejected (excluded)" from
        # "no vision result (reviewable with fallback alt-text)".
        vision_by_path: dict[str, dict] = {}
        approved_vision_ids: set[str] = set()
        if approved_ids:
            for candidate in self.store.candidates_for(job.job_id):
                payload = candidate.enrichment_json or []
                for entry in payload:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("__type__") != "vision":
                        continue
                    path = str(entry.get("relative_media_path") or "")
                    if path:
                        vision_by_path[path] = entry
                    if entry.get("id") in approved_ids:
                        approved_vision_ids.add(str(entry.get("id") or ""))
        outcomes: list[ExecutionOutcome] = []
        try:
            for candidate in self.store.candidates_for(job.job_id):
                # Apply approved suggestions to a copy of the candidate so
                # the gated write sees the patched preview; the stored
                # candidate row remains advisory-only (digest unchanged).
                working = candidate
                # importador-auto-frontmatter (3.1): only the LEGACY path (a
                # candidate with no funnel frontmatter — ``manual`` stub or
                # ``frontmatter`` None, e.g. a body that already carries its
                # own frontmatter) is patched by approved suggestions. Funnel
                # candidates carry ``generated``/``fallback`` frontmatter;
                # their approved metadata is materialized from
                # ``candidate.frontmatter`` instead, never from a suggestion
                # patch onto the raw body.
                if (approved_ids and apply_approved_suggestions is not None
                        and (classifications or relationships)
                        and not _is_funnel_frontmatter(candidate)):
                    patched = apply_approved_suggestions(
                        candidate,
                        classifications=classifications,
                        relationships=relationships,
                        approved_classification_ids=approved_ids,
                        approved_relationship_ids=approved_ids,
                    )
                    if patched and patched != candidate.content_preview:
                        working = candidate.model_copy(update={"content_preview": patched})
                outcome = self._execute_candidate(
                    job, working,
                    vision_by_path=vision_by_path,
                    approved_vision_ids=approved_vision_ids,
                )
                outcomes.append(outcome)
                self.store.add_item(ItemOutcome(
                    item_id=uuid.uuid4().hex,
                    candidate_id=candidate.candidate_id,
                    outcome=("completed" if outcome.written else
                             outcome.action if outcome.action in ("skip", "keep")
                             else "failed"),
                    detail=outcome.detail,
                ))
        except Exception as exc:  # dependency outage -> fail closed, no false success
            # Record the failed candidate(s) and transition the job to FAILED
            # (never COMPLETED) with an actionable, redacted error. Writes that
            # occurred before the outage remain tracked by the failed job; no
            # untracked canon write escapes the gated flow.
            for candidate in self.store.candidates_for(job.job_id):
                if not any(o.candidate_id == candidate.candidate_id
                           for o in outcomes):
                    self.store.add_item(ItemOutcome(
                        item_id=uuid.uuid4().hex,
                        candidate_id=candidate.candidate_id,
                        outcome="failed",
                        detail=f"{type(exc).__name__}",
                    ))
            self.store.add_event(job.job_id, f"execution_failed:{type(exc).__name__}")
            self.store.update_job(job.job_id, expected_revision=job.revision + 1,
                                  state=ImportJobState.FAILED,
                                  error=f"execution dependency failed: {type(exc).__name__}")
            BoundedSpool(self.spool_dir, job.job_id, job.world).cleanup()
            raise ValueError(
                f"execution failed closed: {type(exc).__name__}") from exc
        # Bulk graph reconciliation (slice 3, IM-3.1): after preservation-first
        # writes complete, reconcile all written canonical fichas through the
        # bounded bulk boundary once. Graph state is secondary to canon writes:
        # a bulk failure falls back to per-file reconcile and never fails the
        # job (unresolved items are surfaced as observability events).
        self._reconcile_after_execution(job, outcomes)
        self.store.add_event(job.job_id, "execution_complete")
        self.store.update_job(job.job_id, expected_revision=job.revision + 1,
                              state=ImportJobState.COMPLETED)
        BoundedSpool(self.spool_dir, job.job_id, job.world).cleanup()
        return outcomes

    def _reconcile_after_execution(
        self, job: ImportJob, outcomes: list[ExecutionOutcome]
    ) -> None:
        """Reconcile written fichas through the bulk boundary (IM-3.1/IM-3.2).

        ``graph_reconcile_many`` takes precedence: it runs once over all
        written paths in bounded batches. When it is unavailable, the legacy
        per-file ``graph_reconcile`` already ran inside ``_execute_candidate``
        and nothing more happens here. Bulk failure falls back to per-file
        reconcile for each written path; if both fail, the job still completes
        (canon writes are authoritative) and the failure is emitted as an
        observability event.
        """
        written: list[str] = []
        for o in outcomes:
            if o.written and o.target:
                try:
                    rel = str(Path(o.target).relative_to(self.mundos_dir)).replace("\\", "/")
                    written.append(rel)
                except ValueError:
                    continue
        if self._graph_reconcile_many is None:
            # Legacy per-file reconcile already ran inline during execution.
            return
        if not written:
            # No written fichas -> no-op reconciliation, no false failures.
            return

        try:
            result = self._graph_reconcile_many(written, job.world)
        except Exception as exc:  # noqa: BLE001 — graph is a non-critical side effect
            logger.warning(
                "graph_reconcile_many failed for job %s (%d paths): %s",
                job.job_id, len(written), type(exc).__name__, exc_info=True,
            )
            self.store.add_event(job.job_id, "graph_reconcile_failed")
            # Fall back to per-file reconcile for each written path.
            if self._graph_reconcile is not None:
                for rel in written:
                    try:
                        self._graph_reconcile(rel, job.world)
                    except Exception as per_exc:  # noqa: BLE001
                        logger.warning(
                            "per-file graph reconcile failed for %s: %s",
                            rel, type(per_exc).__name__, exc_info=True,
                        )
            return

        self.store.add_event(
            job.job_id,
            f"graph_reconciled:{result.processed}:{result.batches}",
        )
        if result.failed:
            self.store.add_event(
                job.job_id,
                f"graph_reconcile_partial:{len(result.failed)}",
            )

    def _execute_candidate(self, job: ImportJob, candidate: Candidate,
                           vision_by_path: dict[str, dict] | None = None,
                           approved_vision_ids: set[str] | None = None
                           ) -> ExecutionOutcome:
        # Slice 1 (IM-1.2): resolve the canonical OKF target first; only a
        # ``resolved`` mapping is allowed to write. ``review``/``rejected``
        # mappings surface the diagnostic and never mutate canon.
        resolution = self._resolve_candidate_target(job.world, candidate)
        if not resolution.is_resolved():
            target = self._mundo_dir(job.world) / resolution.canonical_path
            return ExecutionOutcome(
                candidate_id=candidate.candidate_id, target=str(target),
                action="review", written=False,
                placement_status="ambiguous",
                detail=(f"target not resolved ({resolution.status}): "
                        f"{resolution.diagnostic}"),
            )
        target = self._mundo_dir(job.world) / resolution.canonical_path
        current = ""
        if target.exists():
            try:
                current = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return ExecutionOutcome(
                    candidate_id=candidate.candidate_id, target=str(target),
                    action="failed", written=False,
                    detail="unable to read current ficha")

        # importador-auto-frontmatter (3.2): unresolved reference-style media
        # never fails the ficha or the job — it is isolated from gallery
        # registration and surfaced as a review warning on the outcome.
        media_warnings = _unresolved_media_warnings(candidate)

        # PR3 — admission gate: a placement whose image has a vision suggestion
        # is eligible only when that suggestion id is bound to the approval
        # token ("execute admits only approved image suggestion ids").
        # Approved descriptions overlay the placement alt-text; images without
        # a vision result stay reviewable with fallback alt-text (task 6.9).
        proposed: list[dict] = []
        for p in candidate.images:
            entry = (vision_by_path or {}).get(p.relative_media_path)
            if entry is not None and entry.get("id") not in (
                    approved_vision_ids or set()):
                continue  # pending/rejected vision suggestion → not eligible
            if entry is not None:
                desc = str(entry.get("description") or "")
                if desc:
                    p = p.model_copy(update={"alt_text": desc})
            proposed.append({
                "relative_media_path": p.relative_media_path,
                "target_ficha": p.target_ficha,
                "alt_text": p.alt_text,
            })

        # Resolve placement statuses against the target's current images.
        placements = plan_placements(_markdown_images(current), proposed)
        if any(p["placement_status"] == "ambiguous" for p in placements):
            return ExecutionOutcome(
                candidate_id=candidate.candidate_id, target=str(target),
                action="review", placement_status="ambiguous", written=False,
                detail="ambiguous image placement requires review",
                media_warnings=media_warnings)

        # PR3 — the approved placements carry vision descriptions; overlay
        # them as alt-text on the markdown the ficha keeps. Computed after
        # ``plan_placements`` so only placements that will actually be written
        # are overlaid (a ``skip`` image already present keeps its preview
        # byte-for-byte, so the merge decision is unaffected).
        approved_placements = [
            p for p in placements if p["placement_status"] == "approved"
        ]
        preview = _overlay_alt_text(candidate.content_preview,
                                    approved_placements)

        # importador-auto-frontmatter (3.1): approved-only frontmatter
        # materialization. A candidate with funnel-produced frontmatter
        # (``generated``/``fallback``) renders the approved metadata + the
        # untouched original body; a legacy candidate (``manual`` stub or
        # ``frontmatter`` None) writes its body as-is (possibly patched by
        # approved suggestions).
        if _is_funnel_frontmatter(candidate):
            document = render_frontmatter_document(
                candidate.frontmatter, preview,
                canonical_id=candidate.canonical_id or "")
        else:
            document = preview

        # Explicit replacement (candidate carries a replacement record): the
        # prior ficha is snapshotted to .papelera, then the new content is
        # written. This is the ONLY path that overwrites existing prose.
        is_replace = (candidate.replacement is not None
                      and candidate.replacement.recovery_status == "replace")
        if is_replace:
            replacement = snapshot_to_papelera(
                self._mundo_dir(job.world),
                str(target.parent.name),
                str(target.relative_to(self._mundo_dir(job.world))),
                current, job.world)
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(target, document)
            self._register_placements(job.world, job.job_id, placements)
            if self._graph_reconcile_many is None and self._graph_reconcile is not None:
                rel = str(target.relative_to(self.mundos_dir)).replace("\\", "/")
                self._graph_reconcile(rel, job.world)
            return ExecutionOutcome(
                candidate_id=candidate.candidate_id, target=str(target),
                action="replace", placement_status="inserted",
                written=True, detail=replacement.papelera_entry,
                papelera_entry=replacement.papelera_entry,
                media_warnings=media_warnings)

        decision = plan_merge(current, document)
        if decision.action == "keep":
            return ExecutionOutcome(
                candidate_id=candidate.candidate_id, target=str(target),
                action="keep", written=False, detail="ficha unchanged",
                media_warnings=media_warnings)
        if decision.action == "review":
            return ExecutionOutcome(
                candidate_id=candidate.candidate_id, target=str(target),
                action="review", written=False,
                detail="incoming modifies existing content; requires review",
                media_warnings=media_warnings)

        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, document)
        self._register_placements(job.world, job.job_id, placements)
        if self._graph_reconcile_many is None and self._graph_reconcile is not None:
            rel = str(target.relative_to(self.mundos_dir)).replace("\\", "/")
            self._graph_reconcile(rel, job.world)
        return ExecutionOutcome(
            candidate_id=candidate.candidate_id, target=str(target),
            action=decision.action,
            placement_status="inserted" if placements else "approved",
            written=True,
            detail="", papelera_entry="",
            media_warnings=media_warnings,
        )

    def _register_placements(self, world: str, job_id: str,
                             placements: list[dict]) -> None:
        """Register approved gallery images via the media contract.

        Spooled source files live under ``spool_dir/{job_id}/{clean}`` (the
        job-scoped ``BoundedSpool`` layout); the clean path strips any
        ``#align-size`` suffix from the Markdown reference.

        Reference-style media (``![][key]``) is ISOLATED from this gallery
        path by construction: only inline ``![alt](path)`` placements from
        ``candidate.images`` reach ``placements``, never the reference-style
        spans carried in ``candidate.media_diagnostics``. Unresolved
        reference placements are therefore never registered and never fail
        the job (task 3.2).
        """
        if self._register_gallery is None:
            return
        for placement in placements:
            if placement["placement_status"] != "approved":
                continue
            ref = placement["relative_media_path"]
            clean = _clean_media_path(ref)
            src = self.spool_dir / job_id / clean
            if src.is_file():
                self._register_gallery(world, src, clean)

    # -- idempotent cancel / resume / rollback (2.5) -----------------------

    def cancel(self, job: ImportJob, principal: str) -> ImportJob:
        """Cancel at item boundaries; completed work stays recorded."""
        if job.owner_principal != principal:
            raise PermissionError("not the job owner")
        if job.state in (ImportJobState.COMPLETED, ImportJobState.ROLLED_BACK,
                         ImportJobState.CANCELLED):
            return job
        self.store.add_event(job.job_id, "cancelled")
        updated = self.store.update_job(job.job_id, expected_revision=job.revision,
                                        state=ImportJobState.CANCELLED)
        BoundedSpool(self.spool_dir, job.job_id, job.world).cleanup()
        # Opción A — ``cancelled`` is terminal with no audit value: reap the
        # DB row (and its cascade) now that the spool is reclaimed. The
        # in-memory ``updated`` job is still returned for the response.
        self.store.delete_job(job.job_id)
        return updated

    def resume(self, job: ImportJob, principal: str) -> ImportJob:
        """Resume only uncommitted boundaries after revalidation (idempotent).

        Handles every non-terminal intermediate state: ``intaking`` (streaming
        completed but analysis never ran), ``analyzing`` (analysis in flight
        when the process died), ``executing`` (execution interrupted), plus
        the explicit terminal ``cancelled``/``failed`` states that the UI
        allows the user to reopen. ``review`` is already terminal-for-approve
        and returns as-is.
        """
        if job.owner_principal != principal:
            raise PermissionError("not the job owner")
        if job.state == ImportJobState.REVIEW:
            return job  # already ready to approve; nothing to resume
        if job.state in (
            ImportJobState.CANCELLED,
            ImportJobState.FAILED,
            ImportJobState.INTAKING,
            ImportJobState.ANALYZING,
            ImportJobState.EXECUTING,
        ):
            self.store.add_event(job.job_id, f"resumed_from:{job.state.value}")
            return self.store.update_job(
                job.job_id, expected_revision=job.revision,
                state=ImportJobState.REVIEW)
        return job

    def rollback(self, job: ImportJob, principal: str) -> ImportJob:
        """Compensate importer-created changes; keep audit/provenance."""
        if job.owner_principal != principal:
            raise PermissionError("not the job owner")
        if job.state not in (ImportJobState.EXECUTING, ImportJobState.COMPLETED):
            raise ValueError(f"job not rollback-able in state {job.state.value}")
        self.store.add_event(job.job_id, "rolled_back")
        updated = self.store.update_job(job.job_id, expected_revision=job.revision,
                                        state=ImportJobState.ROLLED_BACK)
        # Opción A — ``rolled_back`` is terminal with no audit value: reclaim
        # the spool (best-effort) and reap the DB row + cascade. The in-memory
        # ``updated`` job is still returned for the response.
        BoundedSpool(self.spool_dir, job.job_id, job.world).cleanup()
        self.store.delete_job(job.job_id)
        return updated
