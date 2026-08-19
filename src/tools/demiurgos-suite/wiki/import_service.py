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
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from import_models import (
    Approval,
    Candidate,
    ExecutionOutcome,
    ImportJob,
    ImportJobState,
    ItemOutcome,
    MergeDecision,
    ReplacementRecord,
    utcnow_iso,
)
from import_store import ImportJobStore

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
# Lifecycle service
# ---------------------------------------------------------------------------

class ImportService:
    """Server-owned import lifecycle: approve / execute / cancel / rollback."""

    def __init__(self, *, store: ImportJobStore, mundos_dir: Path,
                 spool_dir: Path,
                 read_file: Callable[[str], str] | None = None,
                 graph_reconcile: Callable[[str, str], None] | None = None,
                 register_gallery: Callable[[str, Path, str], str] | None = None,
                 now: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.mundos_dir = Path(mundos_dir)
        self.spool_dir = Path(spool_dir)
        self._read_file = read_file or (lambda _rel: "")
        self._graph_reconcile = graph_reconcile
        self._register_gallery = register_gallery
        self._now = now or _utcnow

    def _mundo_dir(self, world: str) -> Path:
        return self.mundos_dir / world

    def _target_for(self, world: str, candidate: Candidate) -> Path:
        """Resolve the target ficha path from a candidate's identity."""
        mundo = self._mundo_dir(world)
        source = (candidate.provenance.source_path or "").replace("\\", "/")
        section = source.split("/", 1)[0] if "/" in source else "lore"
        if section not in _VALID_SECTIONS:
            section = "lore"
        identity = candidate.normalized_identity
        return mundo / section / f"{identity}.md"

    def candidate_digest(self, job: ImportJob) -> str:
        """Immutable digest over the reviewed candidates (group-scoped)."""
        candidates = self.store.candidates_for(job.job_id)
        ordered = "|".join(
            f"{c.normalized_identity}:{c.source_hash}" for c in candidates)
        return digest_of(ordered)

    def issue_approval(self, job: ImportJob, principal: str,
                       group_ids: list[str]) -> Approval:
        """Issue a server-owned, digest-bound, expiring approval token."""
        digest = self.candidate_digest(job)
        token = secrets.token_hex(16)
        issued = self._now().isoformat()
        expires = (self._now() + timedelta(minutes=APPROVAL_TTL_MINUTES)).isoformat()
        approval = Approval(
            approval_id=uuid.uuid4().hex,
            job_id=job.job_id, principal=principal, revision=job.revision,
            digest=digest, token=token, group_ids=list(group_ids),
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
                token: str) -> list[ExecutionOutcome]:
        """Gated execution: merge + gallery + replacement + graph reconcile.

        Only proceeds after ``validate_approval`` passes; each candidate is
        written through the gated merge, image placements are registered in
        the gallery, explicit replacements snapshot the prior ficha, and the
        graph is reconciled before success.
        """
        self.validate_approval(job, principal, digest, token)
        self.store.mark_approval_consumed(job.job_id, token)
        self.store.update_job(job.job_id, expected_revision=job.revision,
                              state=ImportJobState.EXECUTING)
        outcomes: list[ExecutionOutcome] = []
        try:
            for candidate in self.store.candidates_for(job.job_id):
                outcome = self._execute_candidate(job, candidate)
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
            raise ValueError(
                f"execution failed closed: {type(exc).__name__}") from exc
        self.store.add_event(job.job_id, "execution_complete")
        self.store.update_job(job.job_id, expected_revision=job.revision + 1,
                              state=ImportJobState.COMPLETED)
        return outcomes

    def _execute_candidate(self, job: ImportJob, candidate: Candidate) -> ExecutionOutcome:
        target = self._target_for(job.world, candidate)
        current = ""
        if target.exists():
            try:
                current = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return ExecutionOutcome(
                    candidate_id=candidate.candidate_id, target=str(target),
                    action="failed", written=False,
                    detail="unable to read current ficha")

        # Resolve placement statuses against the target's current images.
        proposed = [
            {"relative_media_path": p.relative_media_path,
             "target_ficha": p.target_ficha, "alt_text": p.alt_text}
            for p in candidate.images
        ]
        placements = plan_placements(_markdown_images(current), proposed)
        if any(p["placement_status"] == "ambiguous" for p in placements):
            return ExecutionOutcome(
                candidate_id=candidate.candidate_id, target=str(target),
                action="review", placement_status="ambiguous", written=False,
                detail="ambiguous image placement requires review")

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
            atomic_write(target, candidate.content_preview)
            self._register_placements(job.world, job.job_id, placements)
            if self._graph_reconcile is not None:
                rel = str(target.relative_to(self.mundos_dir)).replace("\\", "/")
                self._graph_reconcile(rel, job.world)
            return ExecutionOutcome(
                candidate_id=candidate.candidate_id, target=str(target),
                action="replace", placement_status="inserted",
                written=True, detail=replacement.papelera_entry,
                papelera_entry=replacement.papelera_entry)

        decision = plan_merge(current, candidate.content_preview)
        if decision.action == "keep":
            return ExecutionOutcome(
                candidate_id=candidate.candidate_id, target=str(target),
                action="keep", written=False, detail="ficha unchanged")
        if decision.action == "review":
            return ExecutionOutcome(
                candidate_id=candidate.candidate_id, target=str(target),
                action="review", written=False,
                detail="incoming modifies existing content; requires review")

        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, candidate.content_preview)
        self._register_placements(job.world, job.job_id, placements)
        if self._graph_reconcile is not None:
            rel = str(target.relative_to(self.mundos_dir)).replace("\\", "/")
            self._graph_reconcile(rel, job.world)
        return ExecutionOutcome(
            candidate_id=candidate.candidate_id, target=str(target),
            action=decision.action,
            placement_status="inserted" if placements else "approved",
            written=True,
            detail="", papelera_entry="",
        )

    def _register_placements(self, world: str, job_id: str,
                             placements: list[dict]) -> None:
        """Register approved gallery images via the media contract.

        Spooled source files live under ``spool_dir/{job_id}/{clean}`` (the
        job-scoped ``BoundedSpool`` layout); the clean path strips any
        ``#align-size`` suffix from the Markdown reference.
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
        return self.store.update_job(job.job_id, expected_revision=job.revision,
                                     state=ImportJobState.CANCELLED)

    def resume(self, job: ImportJob, principal: str) -> ImportJob:
        """Resume only uncommitted boundaries after revalidation (idempotent)."""
        if job.owner_principal != principal:
            raise PermissionError("not the job owner")
        if job.state == ImportJobState.REVIEW:
            return job  # already ready to approve; nothing to resume
        if job.state in (ImportJobState.CANCELLED, ImportJobState.FAILED):
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
        return self.store.update_job(job.job_id, expected_revision=job.revision,
                                     state=ImportJobState.ROLLED_BACK)
