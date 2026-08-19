"""World importer — job lifecycle contracts.

Server-owned data models for the durable import-job service. Slice 1 covers the
backend contracts and bounded intake; later slices (analysis, approval,
execution) build on these. Nothing here writes to canon; intake is read-only
until an explicit gated approval runs (Phase 2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# Importer-specific bounded upload limits (NOT a relaxation of the generic
# 10 MB media cap). Enforced on the server-owned intake path only.
MAX_FILE_BYTES = 500 * 1024 * 1024          # 500 MB per individual file
MAX_JOB_AGGREGATE_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB per job, incl. ZIP


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


class ImagePlacement(BaseModel):
    """First-class contextual image contract (preserved per design)."""

    gallery_asset_id: str
    relative_media_path: str
    alt_text: str = ""
    target_ficha: str = ""
    confidence: float = 0.0
    placement_status: str = "proposed"  # proposed|approved|ambiguous|inserted


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


class ReplacementRecord(BaseModel):
    """Explicit-replacement snapshot for 30-day `.papelera` recovery."""

    prior_snapshot: str
    new_revision: str = ""
    papelera_entry: str = ""
    expiry: str = ""
    recovery_status: str = "pending"


class Candidate(BaseModel):
    """A diagnosed, eligible intake candidate (read-only until approved)."""

    candidate_id: str
    job_id: str
    world: str
    normalized_identity: str
    source_hash: str
    provenance: Provenance
    content_preview: str = ""
    status: str = "pending"     # pending|eligible|conflict|rejected
    okf_issues: list[dict[str, Any]] = Field(default_factory=list)
    size_bytes: int = 0
    images: list[ImagePlacement] = Field(default_factory=list)
    merge: MergeDecision | None = None
    replacement: ReplacementRecord | None = None


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
class ExecutionOutcome(BaseModel):
    """Result of executing one approved candidate (merge/placement/write)."""

    candidate_id: str
    target: str = ""
    action: str = ""            # add|keep|replace|skip|review
    placement_status: str = ""  # proposed|approved|ambiguous|inserted
    written: bool = False
    detail: str = ""
    papelera_entry: str = ""


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

    def model_dump_redacted(self) -> dict[str, Any]:
        """Public view: never leaks the opaque observability token."""
        data = self.model_dump()
        data.pop("opaque_token", None)
        return data
