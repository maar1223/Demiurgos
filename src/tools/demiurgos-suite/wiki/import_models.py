"""World importer — job lifecycle contracts.

Server-owned data models for the durable import-job service. Slice 1 covers the
backend contracts and bounded intake; later slices (analysis, approval,
execution) build on these. Nothing here writes to canon; intake is read-only
until an explicit gated approval runs (Phase 2).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from import_analysis import AnalysisReport

# Importer-specific bounded upload limits (NOT a relaxation of the generic
# 10 MB media cap). Enforced on the server-owned intake path only.
MAX_FILE_BYTES = 500 * 1024 * 1024          # 500 MB per individual file
MAX_JOB_AGGREGATE_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB per job, incl. ZIP


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Canonical identity contract (importador-auto-frontmatter, Phase 1).
#
# ``normalized_identity`` becomes a parent-qualified ID: NFC-normalized,
# whitespace-collapsed heading segments joined by ``::``; duplicate
# same-title siblings receive deterministic ``#2``, ``#3`` ordinals in source
# order (design identity decision). ``Candidate.canonical_id`` is the single
# relationship key; ``normalized_identity`` remains its uniqueness-compatible
# alias for legacy rows.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Canonical identity contract (importador-auto-frontmatter, Phase 1).
# ---------------------------------------------------------------------------

# Markdown noise stripping for heading-derived identities (see
# ``normalize_identity_segment``). Matches the splitter cleaning in
# ``import_analysis`` so identities and titles agree.
_RE_IDENTITY_INLINE_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")
_RE_IDENTITY_REF_IMAGE = re.compile(r"!\[([^\]]*)\]\[([^\]]*)\]")
_RE_IDENTITY_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_RE_IDENTITY_BOLD_UNDER = re.compile(r"__(.+?)__", re.S)
_RE_IDENTITY_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_RE_IDENTITY_ITALIC_UNDER = re.compile(r"(?<!_)_([^_\n]+?)_(?!_)")
_RE_IDENTITY_CODE = re.compile(r"`([^`\n]+?)`")


def normalize_identity_segment(text: str) -> str:
    """NFC-normalize and whitespace-collapse one heading segment.

    This is the identity contract's per-segment normalization. ``#N``
    ordinal markers added for duplicate same-title siblings survive
    normalization unchanged (``Descripción Física#2`` stays as-is).

    Markdown formatting noise from converted sources (``.docx``/``.pdf`` via
    markitdown) is stripped so identities never carry ``**bold**`` markers or
    inline image payloads (e.g. a heading that is only a logo image). Only
    the formatting markers are removed; the underlying text (or image alt)
    is preserved.
    """
    if not text:
        return ""
    # Inline images `![alt](url)` and reference images `![alt][key]` → alt
    # text (fall back to empty when no alt is present).
    text = _RE_IDENTITY_REF_IMAGE.sub(lambda m: m.group(1).strip(), text)
    text = _RE_IDENTITY_INLINE_IMAGE.sub(lambda m: m.group(1).strip(), text)
    # An image-only heading leaves orphaned wrapping markers (``**``) with
    # no inner text; drop the marker characters outright.
    text = text.replace("**", "").replace("__", "")
    # Unwrap emphasis markers: **bold**, __bold__, *italic*, _italic_, `code`.
    text = _RE_IDENTITY_BOLD.sub(r"\1", text)
    text = _RE_IDENTITY_BOLD_UNDER.sub(r"\1", text)
    text = _RE_IDENTITY_ITALIC.sub(r"\1", text)
    text = _RE_IDENTITY_ITALIC_UNDER.sub(r"\1", text)
    text = _RE_IDENTITY_CODE.sub(r"\1", text)
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def canonical_identity_from_segments(segments: list[str]) -> str:
    """Parent-qualified canonical identity from heading segments.

    Joins the normalized segments with ``::``; empty segments are dropped so
    an implicit document root (no heading segments) yields ``""``.
    """
    return "::".join(
        s for s in (normalize_identity_segment(x) for x in segments) if s)


class ImportJobState(str, Enum):
    PENDING = "pending"
    INTAKING = "intaking"
    ANALYZING = "analyzing"
    REVIEW = "review"          # approvable (gated, Phase 2)
    FAILED = "failed"          # terminal, never approvable
    CANCELLED = "cancelled"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"


# States from which intake is permitted to stream/resume.
INTAKE_STATES = frozenset({ImportJobState.PENDING, ImportJobState.INTAKING})

# States that can never transition to REVIEW (approvable).
TERMINAL_OR_LOCKED = frozenset({
    ImportJobState.FAILED,
    ImportJobState.CANCELLED,
    ImportJobState.COMPLETED,
    ImportJobState.ROLLED_BACK,
})


class Provenance(BaseModel):
    """Source provenance for one candidate/chunk (source-order preserved)."""

    source_path: str
    source_kind: str            # folder | loose | zip
    source_hash: str
    heading_path: str = ""
    source_sequence: int = 0
    chunk_id: str | None = None
    nearby_text_anchor: str = ""
    image_anchor: str = ""
    source_order: int = 0
    # --- Notion export provenance (additive; legacy values remain valid) ---
    source_folder: str = ""     # folder-relative source folder of the origin file
    csv_row: int | None = None  # 1-based CSV row number when derived from a row
    source_column: str = ""     # source column that produced this candidate


# ---------------------------------------------------------------------------
# Notion adapter contracts (additive; nothing here affects legacy intake).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MediaAsset:
    """Deduplicated media identity inside a Notion export.

    Equal bytes share one ``sha256``; ``canonical_path`` is the POSIX-relative
    canonical media path used by OKF review; ``references`` keeps every
    original source path that pointed at these bytes so no reference is lost
    when duplicate bytes collapse into a single asset.
    """

    sha256: str
    canonical_path: str
    size_bytes: int = 0
    references: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NotionAnalysis:
    """Full analysis of a recognized Notion export (adapter orchestrator).

    ``report`` carries the shared candidate analysis in source order;
    ``media`` is the deduplicated media index; ``diagnostics`` holds fail-open
    warnings (missing headings, unresolved links, malformed CSV rows);
    out_of_scope lists complex/unsupported Notion features (views, filters,
    relations, interactive metadata, HTML/API export, sync artifacts) that are
    explicitly reported as out of scope rather than guessed into OKF semantics.
    """

    report: AnalysisReport
    media: list[MediaAsset] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)


class ImagePlacement(BaseModel):
    """First-class contextual image contract (preserved per design)."""

    gallery_asset_id: str
    relative_media_path: str
    alt_text: str = ""
    target_ficha: str = ""
    confidence: float = 0.0
    placement_status: str = "proposed"  # proposed|approved|ambiguous|inserted
    # --- DOCX position contract (additive; excluded from identity/digest) ---
    # Mirrors the sync_lore ImageEntry position fields so review/placement
    # consumers keep the structural source position without touching the
    # media path or the candidate digest.
    document_order: int = 0          # 1-based global order of extracted images
    paragraph_index: int = 0         # 0-based index of the containing w:p
    anchor_type: str = ""            # "inline" | "anchor" ("" when unknown)
    structural_path: str = ""        # e.g. body/p[3]/r[1]/inline[0]
    heading_path: str = ""           # heading hierarchy at extraction time
    context_text: str = ""           # paragraph/heading text around the image
    warnings: list[str] = Field(default_factory=list)  # per-image notes


class MergeDecision(BaseModel):
    """Preservation-first merge decision (execution, Phase 2)."""

    target: str
    base_revision: str = ""
    mode: str = "add"           # add|replace
    action: str = ""            # add|keep|replace|skip|review
    reason: str = ""
    approver: str = ""
    approval_digest: str = ""
    outcome: str = "pending"


class TargetResolution(BaseModel):
    """Canonical OKF target mapping for a candidate (slice 1, IM-1.2).

    Carries the canonical relative target, the normalized source, and a
    status (``resolved``/``review``/``rejected``) with a diagnostic. Legacy
    uppercase sections (``Lore``/``Personajes``) and supported subfolder
    aliases are normalized here; unknown sections, unknown subfolders, or
    unsafe paths produce a non-resolved status — never a guessed target.
    """

    canonical_path: str = ""
    normalized_source: str = ""
    status: str = "resolved"    # resolved|review|rejected
    diagnostic: str = ""
    alias_used: str = ""        # e.g., "Lore/Places" -> "lugares"

    def is_resolved(self) -> bool:
        return self.status == "resolved"

    def model_dump_safe(self) -> dict[str, Any]:
        """Serialization helper (status + paths only)."""
        return self.model_dump()


class ReplacementRecord(BaseModel):
    """Explicit-replacement snapshot for 30-day `.papelera` recovery."""

    prior_snapshot: str
    new_revision: str = ""
    papelera_entry: str = ""
    expiry: str = ""
    recovery_status: str = "pending"


# ---------------------------------------------------------------------------
# Enrichment contracts (slice 2 — optional Hermes advisory suggestions).
#
# Suggestions are NON-AUTHORITATIVE: they ride on a Candidate but never modify
# its deterministic identity/digest, are surfaced in review as advisory, and
# only materialize during a gated execute. Status + JSON list are persisted on
# the candidate so legacy rows remain importable when enrichment is disabled.
# ---------------------------------------------------------------------------


class EnrichmentStatus(str, Enum):
    """Diagnostic state of an enrichment attempt (slice 2)."""

    DISABLED = "disabled"          # enrichment not requested or not configured
    OK = "ok"                      # one or more suggestions produced
    NO_SUGGESTIONS = "no_suggestions"  # gateway reachable, nothing valid returned
    ERROR = "error"                # timeout / malformed / unavailable gateway


class ClassificationSuggestion(BaseModel):
    """Hermes-suggested classification for one candidate.

    ``provenance`` is server-attached (provider, model, prompt version) so
    reviewers can attribute the suggestion. ``review_state`` is initially
    ``pending`` and toggled to ``approved``/``rejected`` via the decisions
    endpoint. ``review_state`` is preserved in ``enrichment_json`` so the
    round-trip survives a process restart.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    candidate_id: str
    type: str = ""                # normalized EntityType value (e.g., "personaje")
    tags: list[str] = Field(default_factory=list)
    confidence: float = 0.0       # in [0, 1]
    evidence: str = ""
    provenance: dict[str, str] = Field(default_factory=dict)
    review_state: str = "pending" # pending|approved|rejected


class RelationshipSuggestion(BaseModel):
    """Hermes-suggested relationship between candidates (or to a named target).

    ``target_candidate_id`` is set when the target is another candidate in
    the same batch; ``target_name`` then carries that candidate's human
    title (``display_title``) so the frontend shows a readable name instead
    of the internal id. When Hermes names an entity NOT present in the
    batch, ``target_name`` holds the grounded name (validation rejects
    ungrounded names). Self-links are rejected. ``review_state`` round-trips
    through ``enrichment_json``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    source_candidate_id: str
    target_candidate_id: str | None = None
    target_name: str | None = None
    relationship_type: str = ""
    confidence: float = 0.0
    evidence: str = ""
    provenance: dict[str, str] = Field(default_factory=dict)
    review_state: str = "pending"


# ---------------------------------------------------------------------------
# Analysis contracts (importador-auto-frontmatter, Phase 1).
#
# Reviewable frontmatter and reference-image diagnostics produced by the
# analysis funnel. Candidates retain the original body; these contracts
# expose the analyzed metadata without ever replacing author text.
# ---------------------------------------------------------------------------


class FrontmatterState(str, Enum):
    """Enrichment state of a frontmatter candidate (design Step 4)."""

    GENERATED = "generated"   # produced by Hermes enrichment
    MANUAL = "manual"         # author decision / no enrichment requested
    FALLBACK = "fallback"     # fail-open: timeout/malformed/unavailable


class FrontmatterCandidate(BaseModel):
    """Reviewable OKF frontmatter for one ficha.

    ``relaciones`` carry canonical ids (``::``-qualified), never ambiguous
    leaf names. ``state`` records generated/manual/fallback so review can
    attribute the metadata. The candidate body remains the original source
    text — frontmatter never replaces it.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    type: str | None = None
    description: str = ""
    relaciones: list[str] = Field(default_factory=list)
    state: FrontmatterState = FrontmatterState.MANUAL


class MediaDiagnostic(BaseModel):
    """Diagnostic for one reference-style image placement (``![..][key]``).

    The original span is preserved verbatim in ``reference`` so execution can
    render it untouched. ``status`` is ``resolved`` when a matching
    ``[key]: path`` definition exists in the same ficha, otherwise
    ``unresolved`` — that placement is excluded from gallery registration but
    never blocks the ficha or the job (review warning only).
    """

    model_config = ConfigDict(extra="forbid")

    reference: str            # verbatim span, e.g. "![][image1]"
    image_key: str            # e.g. "image1"
    alt_text: str = ""
    status: str = "unresolved"  # resolved|unresolved
    target_path: str = ""     # definition target when resolved
    target_ficha: str = ""    # canonical id of the owning ficha
    message: str = ""         # human-readable diagnostic for review


class Candidate(BaseModel):
    """A diagnosed, eligible intake candidate (read-only until approved)."""

    candidate_id: str
    job_id: str
    world: str
    normalized_identity: str
    canonical_id: str = ""  # parent-qualified "::"-joined identity (analysis)
    source_hash: str
    provenance: Provenance
    content_preview: str = ""
    # importador-auto-frontmatter (Phase 2 — enrichment funnel): candidates
    # retain the ficha's display title, the dense per-ficha summary (Step 2),
    # the reviewable ``FrontmatterCandidate`` (Step 4), and the reference-image
    # diagnostics (``![][key]`` spans). All are advisory metadata produced by
    # the funnel; ``content_preview`` stays the original body text and is never
    # replaced. ``display_title`` also covers the implicit single-ficha path
    # (a document with no usable headings) via the file stem.
    display_title: str = ""
    summary: str = ""
    frontmatter: FrontmatterCandidate | None = None
    media_diagnostics: list[MediaDiagnostic] = Field(default_factory=list)
    # Fail-open conversion/extraction diagnostic tokens (e.g.
    # "conversion_unavailable", "conversion_failed", "media_extraction_failed").
    # In-memory only (not persisted to the candidates table) — used to gate
    # the job out of REVIEW when a convertible source failed to convert.
    # Empty when no conversion was attempted.
    diagnostics: list[str] = Field(default_factory=list)
    status: str = "pending"     # pending|eligible|conflict|rejected
    okf_issues: list[dict[str, Any]] = Field(default_factory=list)
    size_bytes: int = 0
    images: list[ImagePlacement] = Field(default_factory=list)
    merge: MergeDecision | None = None
    replacement: ReplacementRecord | None = None
    target_resolution: dict[str, Any] | None = None  # TargetResolution-as-dict
    # Slice 2 (optional Hermes advisory suggestions): enrichment is opt-in and
    # never affects deterministic identity/digest. Legacy candidates without
    # enrichment deserialize with ``None``/``disabled``; downstream code MUST
    # treat absence as "no suggestions", not as an error.
    enrichment_json: list[dict[str, Any]] | None = None
    enrichment_status: str = "disabled"   # EnrichmentStatus value
    # Classifier (BLOQUE 1 piece 1): author-chosen target section
    # (``lore``/``personajes``/``referencias``) stamped at build time from the
    # job's ``sections`` map. Empty for legacy jobs or files without a map
    # entry — ``resolve_target`` then falls through to the source-path branch.
    section: str = ""
    # Tree-aware materialized path (import folder rule): the exact relative
    # target computed at analysis from the heading tree (folder only when the
    # heading has children or is H1; a childless heading at level > 1 lands
    # as a loose file in the nearest ancestor's folder). Empty → resolve_target
    # falls back to the folder-per-heading per-segment derivation.
    materialized_path: str = ""


class ItemOutcome(BaseModel):
    """Outcome of one executed/cancelled item (Phase 2 + cancellation)."""

    item_id: str
    candidate_id: str
    outcome: str = "pending"    # pending|completed|skipped|failed|compensated
    detail: str = ""
    created_at: str = ""


class Approval(BaseModel):
    """Explicit group-scoped approval bound to an immutable digest + token.

    Approval is only valid for the exact reviewed candidate digest and
    job revision; any changed digest, stale/expired/replayed token, or a
    different group set fails closed with zero writes (2.1).
    """

    approval_id: str
    job_id: str
    principal: str
    revision: int
    digest: str
    token: str
    group_ids: list[str] = Field(default_factory=list)
    issued_at: str = ""
    expires_at: str = ""
    consumed: bool = False
    # Slice 2: optional IDs of approved suggestions. Bound to the approval
    # so a replayed token cannot resurrect a prior decision. Empty list
    # preserves the legacy no-enrichment path.
    suggestion_ids: list[str] = Field(default_factory=list)
class ExecutionOutcome(BaseModel):
    """Result of executing one approved candidate (merge/placement/write)."""

    candidate_id: str
    target: str = ""
    action: str = ""            # add|keep|replace|skip|review
    placement_status: str = ""  # proposed|approved|ambiguous|inserted
    written: bool = False
    detail: str = ""
    papelera_entry: str = ""
    # importador-auto-frontmatter (Phase 3): non-blocking review warnings for
    # unresolved reference-style media (``![][key]`` with no definition).
    # The ficha/job still succeeds; these surface for review only.
    media_warnings: list[str] = Field(default_factory=list)


class ImportJob(BaseModel):
    """Durable import job. ``opaque_token`` keys observability, never returned."""

    job_id: str
    world: str
    owner_principal: str
    state: ImportJobState = ImportJobState.PENDING
    source_kind: str = "loose"  # folder | loose | zip
    aggregate_uncompressed_bytes: int = 0
    aggregate_compressed_bytes: int = 0
    file_count: int = 0
    revision: int = 0
    error: str = ""
    opaque_token: str = ""
    created_at: str = ""
    updated_at: str = ""
    # Server-owned analysis progress (surfaced to the live Web App). ``stage``
    # is a human-readable phase; ``pct`` is an honest estimate (0..100) or
    # ``None`` when the phase has no countable total (indeterminate).
    progress_stage: str = ""
    progress_pct: int | None = None
    # Classifier (BLOQUE 1 piece 1): author-chosen section per relative source
    # path (``{relative_path: section}``). Persisted as ``sections_json`` so a
    # resumed job re-stamps its candidates with the same sections. Empty for
    # legacy jobs.
    sections: dict[str, str] = {}
    # Reimport marker (order manifest): set during analysis when any candidate
    # matches an existing row with the same ``source_hash`` +
    # ``normalized_identity`` in this world's import history. The import
    # pipeline uses it to replace only the reimported document's manifest
    # subtree (prefix-based replacement) instead of appending, preserving
    # disjoint documents that share the section. Never derived from manifest
    # existence or the job ``revision`` counter (a job-level optimistic lock).
    reimport: bool = False

    def model_dump_redacted(self) -> dict[str, Any]:
        """Public view: never leaks the opaque observability token."""
        data = self.model_dump()
        data.pop("opaque_token", None)
        return data


class JobPage(BaseModel):
    """Cursor-paginated slice of an import-job history (slice 2, IM-2.2).

    Each entry is a pre-redacted dict (no ``opaque_token``); ``next_cursor``
    is opaque to clients and absent when there is no further page. The cursor
    encodes the (created_at, job_id) tuple of the last row so the next page
    seeks strictly past it under DESC ordering.
    """

    jobs: list[dict[str, Any]] = Field(default_factory=list)
    next_cursor: str | None = None
