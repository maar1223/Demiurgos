"""World importer — durable SQLite store.

Persists import jobs, candidates, item outcomes, and an event trail, following
the project's ``data/`` SQLite convention (stdlib sqlite3, thread lock,
optimistic revision, unique ``(world, source_hash, normalized_identity)``
dedupe). Leases prevent concurrent intake; recovery re-opens jobs an
interrupted process left mid-flight.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from import_models import (  # noqa: F401
    Approval,
    ImportJob,
    ImportJobState,
    Candidate,
    ItemOutcome,
    ImagePlacement,
    utcnow_iso,
)
# PR2 (sync-lore-in-importer): the vision content cache persists
# :class:`import_vision.VisionResult` payloads keyed by image SHA-256.
# ``import_vision`` imports only stdlib at module level, so this does not
# pull sync_lore or the assistant-settings chain into the store.
from import_vision import VisionResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY, world TEXT NOT NULL, owner_principal TEXT NOT NULL,
    state TEXT NOT NULL, source_kind TEXT NOT NULL DEFAULT 'loose',
    aggregate_uncompressed_bytes INTEGER NOT NULL DEFAULT 0,
    aggregate_compressed_bytes INTEGER NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '', opaque_token TEXT NOT NULL DEFAULT '',
    lease_owner TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, world TEXT NOT NULL,
    normalized_identity TEXT NOT NULL, source_hash TEXT NOT NULL,
    provenance_json TEXT NOT NULL, content_preview TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending', okf_issues_json TEXT NOT NULL DEFAULT '[]',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    images_json TEXT NOT NULL DEFAULT '[]',
    merge_json TEXT,
    replacement_json TEXT,
    target_resolution_json TEXT,
    enrichment_json TEXT,
    enrichment_status TEXT NOT NULL DEFAULT 'disabled',
    UNIQUE (world, source_hash, normalized_identity));
CREATE TABLE IF NOT EXISTS items (
    item_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'pending', detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
    event TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, principal TEXT NOT NULL,
    revision INTEGER NOT NULL, digest TEXT NOT NULL, token TEXT NOT NULL,
    group_ids_json TEXT NOT NULL DEFAULT '[]', issued_at TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL DEFAULT '', consumed INTEGER NOT NULL DEFAULT 0,
    UNIQUE (job_id, token));
-- PR2 (sync-lore-in-importer, Phase 4): persistent vision content cache.
-- Global by design — the key is the SHA-256 of the original image bytes and
-- the result describes image content, not world canon, so it is safe to
-- reuse across worlds and jobs. ``CREATE TABLE IF NOT EXISTS`` keeps the
-- bootstrap idempotent on every open (legacy databases included).
CREATE TABLE IF NOT EXISTS vision_cache (
    hash TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL);
"""

# Bootstrap migration: SQLite cannot ALTER TABLE ADD COLUMN with a default
# for legacy databases created before slice 2. Each block is idempotent; the
# column is added once, then the pragma confirms the schema is current.
_BOOTSTRAP_COLUMNS = (
    ("images_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("merge_json", "TEXT"),
    ("replacement_json", "TEXT"),
    ("target_resolution_json", "TEXT"),
    ("enrichment_json", "TEXT"),
    ("enrichment_status", "TEXT NOT NULL DEFAULT 'disabled'"),
)


def default_db_path() -> Path:
    return Path(__file__).resolve().parents[4] / "data" / "import-jobs.sqlite3"


def _json(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


def _unjson(raw: str) -> Any:
    import json
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return []


def _encode_cursor(created_at: str, job_id: str) -> str:
    """Encode the (created_at, job_id) DESC tuple key as an opaque cursor.

    The cursor is opaque to clients: it is a URL-safe base64 payload of
    ``{"c": created_at, "j": job_id}``. Padding is stripped so cursors stay
    compact; ``_decode_cursor`` restores it before decoding.
    """
    import base64
    import json

    payload = json.dumps({"c": created_at, "j": job_id},
                         separators=(",", ":"), ensure_ascii=True)
    return base64.urlsafe_b64encode(
        payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    """Decode an opaque cursor back into the (created_at, job_id) tuple key.

    Validates the payload shape — never trust the client. A malformed cursor
    raises ``ValueError`` so callers can return HTTP 400 instead of silently
    returning the wrong page.
    """
    import base64
    import json

    pad = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + pad).decode("utf-8")
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"malformed cursor: {exc}") from exc
    if (not isinstance(payload, dict)
            or set(payload.keys()) != {"c", "j"}):
        raise ValueError("cursor must encode exactly {c, j} keys")
    return str(payload["c"]), str(payload["j"])


class ImportJobStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = default_db_path()
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._bootstrap_columns()

    def _bootstrap_columns(self) -> None:
        """Idempotently add nullable enrichment columns to legacy databases.

        Each column is added only when the live pragma doesn't already report
        it, so the migration is safe to run on every open. Defaults match the
        in-memory schema: ``enrichment_json`` NULL, ``enrichment_status``
        ``"disabled"``. Slice 2 contract: legacy rows deserialize to
        ``None``/``disabled`` and downstream code MUST treat absence as
        "no suggestions".
        """
        with self._lock:
            existing = {
                row["name"] for row in self._conn.execute(
                    "PRAGMA table_info(candidates)").fetchall()
            }
            for name, decl in _BOOTSTRAP_COLUMNS:
                if name in existing:
                    continue
                self._conn.execute(
                    f"ALTER TABLE candidates ADD COLUMN {name} {decl}")
            self._conn.commit()

    # -- jobs --------------------------------------------------------------

    def create_job(self, job: ImportJob, *, lease_owner: str | None = None) -> ImportJob:
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (job_id, world, owner_principal, state, source_kind,"
                " aggregate_uncompressed_bytes, aggregate_compressed_bytes, file_count,"
                " revision, error, opaque_token, lease_owner, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job.job_id, job.world, job.owner_principal, job.state.value,
                 job.source_kind, job.aggregate_uncompressed_bytes,
                 job.aggregate_compressed_bytes, job.file_count, job.revision,
                 job.error, job.opaque_token, lease_owner, job.created_at, job.updated_at),
            )
            self._conn.commit()
            return self.get_job(job.job_id)

    def get_job(self, job_id: str) -> ImportJob | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return self._job_from_row(row) if row else None

    def _job_from_row(self, row: sqlite3.Row) -> ImportJob:
        return ImportJob(
            job_id=row["job_id"], world=row["world"],
            owner_principal=row["owner_principal"],
            state=ImportJobState(row["state"]), source_kind=row["source_kind"],
            aggregate_uncompressed_bytes=row["aggregate_uncompressed_bytes"],
            aggregate_compressed_bytes=row["aggregate_compressed_bytes"],
            file_count=row["file_count"], revision=row["revision"],
            error=row["error"], opaque_token=row["opaque_token"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def update_job(self, job_id: str, *, expected_revision: int | None,
                   **fields: Any) -> ImportJob:
        """Optimistic revision-guarded update; raises ValueError on mismatch."""
        _ALLOWED = {"state", "source_kind", "aggregate_uncompressed_bytes",
                    "aggregate_compressed_bytes", "file_count", "error",
                    "opaque_token", "lease_owner"}
        with self._lock:
            row = self._conn.execute(
                "SELECT revision FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if expected_revision is not None and expected_revision != row["revision"]:
                raise ValueError(
                    f"stale revision {expected_revision} != {row['revision']} ({job_id})")
            sets, values = [], []
            for key, value in fields.items():
                if key not in _ALLOWED:
                    raise ValueError(f"unsupported job field: {key}")
                value = value.value if isinstance(value, ImportJobState) else value
                sets.append(f"{key}=?"); values.append(value)
            sets.append("revision=revision+1"); sets.append("updated_at=?")
            values.append(utcnow_iso()); values.append(job_id)
            self._conn.execute(
                f"UPDATE jobs SET {', '.join(sets)} WHERE job_id=?", values)
            self._conn.commit()
            return self.get_job(job_id)

    def list_jobs(self, *, principal: str, world: str, limit: int = 50,
                  cursor: str | None = None) -> tuple[list[ImportJob], str | None]:
        """Principal-scoped, cursor-paginated job history (slice 2, IM-2.2)."""
        try:
            requested = int(limit)
        except (TypeError, ValueError):
            requested = 50
        if requested <= 0:
            requested = 50  # treat invalid as the default, not zero
        bounded = max(1, min(requested, 100))
        params: list[Any] = [principal, world]
        where = "owner_principal=? AND world=?"
        if cursor:
            try:
                ca, jid = _decode_cursor(cursor)
            except ValueError as exc:
                raise ValueError(f"invalid cursor: {exc}") from exc
            where += " AND (created_at < ? OR (created_at = ? AND job_id < ?))"
            params.extend([ca, ca, jid])
        params.append(bounded + 1)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM jobs WHERE {where}"
                f" ORDER BY created_at DESC, job_id DESC LIMIT ?",
                params,
            ).fetchall()
        has_more = len(rows) > bounded
        jobs = [self._job_from_row(r) for r in rows[:bounded]]
        next_cursor: str | None = None
        if has_more and jobs:
            last = jobs[-1]
            next_cursor = _encode_cursor(last.created_at, last.job_id)
        return jobs, next_cursor

    def delete_job(self, job_id: str) -> None:
        """Delete a job and all cascade-associated rows (terminal reaping)."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM items WHERE candidate_id IN"
                " (SELECT candidate_id FROM candidates WHERE job_id=?)",
                (job_id,),
            )
            self._conn.execute(
                "DELETE FROM candidates WHERE job_id=?", (job_id,))
            self._conn.execute(
                "DELETE FROM events WHERE job_id=?", (job_id,))
            self._conn.execute(
                "DELETE FROM approvals WHERE job_id=?", (job_id,))
            self._conn.execute(
                "DELETE FROM jobs WHERE job_id=?", (job_id,))
            self._conn.commit()

    def delete_jobs_for_world(self, world: str) -> int:
        """Delete every import job bound to *world*; returns the number removed.
        Manual cascade (items -> candidates -> events -> approvals -> jobs).
        Used when a world is deleted or purged so its import jobs stop resolving.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT job_id FROM jobs WHERE world=?", (world,),
            ).fetchall()
            doomed = [row["job_id"] for row in rows]
            for job_id in doomed:
                self._conn.execute(
                    "DELETE FROM items WHERE candidate_id IN"
                    " (SELECT candidate_id FROM candidates WHERE job_id=?)",
                    (job_id,),
                )
                self._conn.execute(
                    "DELETE FROM candidates WHERE job_id=?", (job_id,))
                self._conn.execute(
                    "DELETE FROM events WHERE job_id=?", (job_id,))
                self._conn.execute(
                    "DELETE FROM approvals WHERE job_id=?", (job_id,))
                self._conn.execute(
                    "DELETE FROM jobs WHERE job_id=?", (job_id,))
            self._conn.commit()
            return len(doomed)

    # -- candidates --------------------------------------------------------

    def find_candidate(self, world: str, source_hash: str,
                       normalized_identity: str) -> Candidate | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM candidates WHERE world=? AND source_hash=? AND"
                " normalized_identity=?", (world, source_hash, normalized_identity),
            ).fetchone()
        return self._candidate_from_row(row) if row else None

    def add_candidate(self, candidate: Candidate) -> Candidate:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO candidates (candidate_id, job_id, world,"
                " normalized_identity, source_hash, provenance_json, content_preview,"
                " status, okf_issues_json, size_bytes, images_json, merge_json,"
                " replacement_json, target_resolution_json,"
                " enrichment_json, enrichment_status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (candidate.candidate_id, candidate.job_id, candidate.world,
                 candidate.normalized_identity, candidate.source_hash,
                 candidate.provenance.model_dump_json(), candidate.content_preview,
                 candidate.status, _json(candidate.okf_issues), candidate.size_bytes,
                 _json([i.model_dump() for i in candidate.images]),
                 candidate.merge.model_dump_json() if candidate.merge else None,
                 candidate.replacement.model_dump_json()
                 if candidate.replacement else None,
                 _json(candidate.target_resolution)
                 if candidate.target_resolution else None,
                 _json(candidate.enrichment_json)
                 if candidate.enrichment_json is not None else None,
                 candidate.enrichment_status),
            )
            self._conn.commit()
        return (self.find_candidate(candidate.world, candidate.source_hash,
                                    candidate.normalized_identity) or candidate)

    def update_candidate_enrichment(self, candidate_id: str,
                                    enrichment_json: list[dict] | None,
                                    enrichment_status: str) -> None:
        """Persist the enrichment JSON list + status onto one candidate.

        Called by the analyze flow after the optional Hermes batch. The
        candidate's deterministic identity/digest is untouched; only the
        advisory fields are written. Idempotent: re-running enrichment
        overwrites the prior payload.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE candidates SET enrichment_json=?, enrichment_status=?"
                " WHERE candidate_id=?",
                (_json(enrichment_json) if enrichment_json is not None else None,
                 enrichment_status, candidate_id),
            )
            self._conn.commit()

    def reassign_candidate_to_job(self, candidate_id: str,
                                  new_job_id: str) -> None:
        """Re-point a candidate at a different job (cache-hit re-import).

        The UNIQUE constraint on ``(world, source_hash, normalized_identity)``
        prevents inserting a duplicate row for the same content. When a
        re-import hits the enrichment cache, we reuse the existing candidate
        row but update its ``job_id`` so ``candidates_for(new_job_id)``
        returns it for review/execute. The prior job loses the candidate
        from its review surface — acceptable because the prior job already
        completed or was superseded by this re-import.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE candidates SET job_id=? WHERE candidate_id=?",
                (new_job_id, candidate_id))
            self._conn.commit()

    def update_candidate_content(self, candidate_id: str,
                                 content_preview: str) -> None:
        """Update the content preview of an existing candidate.

        Used when a candidate was previously created with empty content
        (e.g., before markitdown was installed) and a re-import extracts
        the actual content. Only updates if the new content is non-empty.
        """
        if not content_preview:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE candidates SET content_preview=? WHERE candidate_id=?",
                (content_preview, candidate_id))
            self._conn.commit()

    def update_candidate_images(self, candidate_id: str,
                                images: list[ImagePlacement]) -> None:
        """Backfill the image placements of an existing candidate.

        Mirrors ``update_candidate_content`` for the media bundle: a
        candidate created while media extraction was unavailable (e.g.,
        before python-docx was installed) carries ``images_json = []`` even
        though a re-import now extracts real images. A re-import that finds
        the same (world, source_hash, identity) reassigns the row; this
        update persists the newly extracted placements so review/execute
        see them. Only updates when the new list is non-empty.
        """
        if not images:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE candidates SET images_json=? WHERE candidate_id=?",
                (_json([i.model_dump() for i in images]), candidate_id))
            self._conn.commit()

    def update_suggestion_state(self, candidate_id: str, suggestion_id: str,
                                review_state: str) -> bool:
        """Toggle the ``review_state`` of one suggestion inside the JSON list.

        Returns True when the suggestion was found and updated, False when
        no matching candidate/suggestion exists. The JSON list is decoded,
        patched in place, and re-serialized; the row's other fields are
        untouched.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT enrichment_json FROM candidates WHERE candidate_id=?",
                (candidate_id,)).fetchone()
            if row is None or not row["enrichment_json"]:
                return False
            try:
                payload = _unjson(row["enrichment_json"])
            except (TypeError, ValueError):
                return False
            if not isinstance(payload, list):
                return False
            updated = False
            for entry in payload:
                if isinstance(entry, dict) and entry.get("id") == suggestion_id:
                    entry["review_state"] = review_state
                    updated = True
                    break
            if not updated:
                return False
            self._conn.execute(
                "UPDATE candidates SET enrichment_json=? WHERE candidate_id=?",
                (_json(payload), candidate_id))
            self._conn.commit()
            return True

    def candidates_for(self, job_id: str) -> list[Candidate]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM candidates WHERE job_id=?", (job_id,)
            ).fetchall()
        return [self._candidate_from_row(r) for r in rows]

    def _candidate_from_row(self, row: sqlite3.Row) -> Candidate:
        from import_models import Provenance
        images = [
            __import__("import_models", fromlist=["ImagePlacement"])
            .ImagePlacement.model_validate(i)
            for i in _unjson(row["images_json"])
        ]
        merge = None
        if row["merge_json"]:
            merge = __import__("import_models", fromlist=["MergeDecision"]) \
                .MergeDecision.model_validate_json(row["merge_json"])
        replacement = None
        if row["replacement_json"]:
            replacement = __import__("import_models", fromlist=["ReplacementRecord"]) \
                .ReplacementRecord.model_validate_json(row["replacement_json"])
        target_resolution = None
        # ``target_resolution_json`` was added in slice 1; legacy rows may
        # not have the column (older databases). Use a defensive lookup.
        try:
            tr_json = row["target_resolution_json"]
        except (IndexError, KeyError):
            tr_json = None
        if tr_json:
            target_resolution = _unjson(tr_json)
        # Slice 2: enrichment columns are nullable; legacy rows must
        # deserialize to ``None``/``disabled`` and never raise.
        try:
            ej_raw = row["enrichment_json"]
            es_raw = row["enrichment_status"]
        except (IndexError, KeyError):
            ej_raw, es_raw = None, "disabled"
        enrichment_json = _unjson(ej_raw) if ej_raw else None
        if not isinstance(enrichment_json, list):
            enrichment_json = None
        return Candidate(
            candidate_id=row["candidate_id"], job_id=row["job_id"],
            world=row["world"], normalized_identity=row["normalized_identity"],
            source_hash=row["source_hash"],
            provenance=Provenance.model_validate_json(row["provenance_json"]),
            content_preview=row["content_preview"], status=row["status"],
            okf_issues=_unjson(row["okf_issues_json"]), size_bytes=row["size_bytes"],
            images=images, merge=merge, replacement=replacement,
            target_resolution=target_resolution,
            enrichment_json=enrichment_json,
            enrichment_status=es_raw or "disabled")

    # -- items / events ----------------------------------------------------

    def add_item(self, item: ItemOutcome) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO items (item_id, candidate_id, outcome, detail,"
                " created_at) VALUES (?,?,?,?,?)",
                (item.item_id, item.candidate_id, item.outcome, item.detail,
                 item.created_at or ""),
            )
            self._conn.commit()

    def add_event(self, job_id: str, event: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (job_id, event, at) VALUES (?,?,?)",
                (job_id, event, utcnow_iso()))
            self._conn.commit()

    # -- observability ------------------------------------------------------

    def observability(self, opaque_token: str) -> dict | None:
        """Structured, redacted observability keyed by the opaque job ID.

        The opaque token is the job-observability key operators hold
        out-of-band; the public REST surface never returns it
        (``ImportJob.model_dump_redacted`` strips it). The returned payload is
        redacted: no content previews, no candidate internals, no approval
        tokens or digests — only job identity, state, bounds/accounting,
        timestamps, the event trail, and per-outcome item counts. Returns None
        when no job carries the given opaque token.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE opaque_token=?", (opaque_token,)
            ).fetchone()
            if row is None:
                return None
            events = self._conn.execute(
                "SELECT event, at FROM events WHERE job_id=? ORDER BY event_id",
                (row["job_id"],),
            ).fetchall()
            outcomes = self._conn.execute(
                "SELECT outcome, COUNT(*) AS n FROM items i"
                " JOIN candidates c ON c.candidate_id=i.candidate_id"
                " WHERE c.job_id=? GROUP BY outcome",
                (row["job_id"],),
            ).fetchall()
            approvals = self._conn.execute(
                "SELECT COUNT(*) AS n FROM approvals WHERE job_id=?",
                (row["job_id"],),
            ).fetchone()
        return {
            "job_id": row["job_id"],
            "world": row["world"],
            "state": row["state"],
            "source_kind": row["source_kind"],
            "file_count": row["file_count"],
            "aggregate_uncompressed_bytes": row["aggregate_uncompressed_bytes"],
            "aggregate_compressed_bytes": row["aggregate_compressed_bytes"],
            "revision": row["revision"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "events": [{"event": e["event"], "at": e["at"]} for e in events],
            "item_outcomes": {o["outcome"]: o["n"] for o in outcomes},
            "approval_count": (approvals["n"] if approvals else 0),
        }

    # -- leases / recovery -------------------------------------------------

    def acquire_lease(self, job_id: str, owner: str,
                      expected_state: ImportJobState) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT state, lease_owner FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None or row["state"] != expected_state.value:
                return False
            if row["lease_owner"] is not None and row["lease_owner"] != owner:
                return False
            self._conn.execute(
                "UPDATE jobs SET lease_owner=? WHERE job_id=?", (owner, job_id))
            self._conn.commit()
            return True

    def release_lease(self, job_id: str, owner: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET lease_owner=NULL WHERE job_id=? AND lease_owner=?",
                (job_id, owner))
            self._conn.commit()

    def recover_interrupted(self, world: str) -> int:
        """Re-open in-progress jobs with no live lease (a restart)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT job_id FROM jobs WHERE world=? AND state IN (?,?,?)"
                " AND lease_owner IS NULL",
                (world, "intaking", "analyzing", "executing")).fetchall()
            for row in rows:
                self._conn.execute(
                    "UPDATE jobs SET state='pending', lease_owner=NULL,"
                    " revision=revision+1, updated_at=? WHERE job_id=?",
                    (utcnow_iso(), row["job_id"]))
            self._conn.commit()
            return len(rows)

    # -- approvals ---------------------------------------------------------

    def save_approval(self, approval: Approval) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO approvals (approval_id, job_id, principal, revision,"
                " digest, token, group_ids_json, issued_at, expires_at, consumed)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (approval.approval_id, approval.job_id, approval.principal,
                 approval.revision, approval.digest, approval.token,
                 _json(approval.group_ids), approval.issued_at,
                 approval.expires_at, 1 if approval.consumed else 0),
            )
            self._conn.commit()

    def find_approval(self, job_id: str, token: str) -> Approval | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM approvals WHERE job_id=? AND token=?", (job_id, token)
            ).fetchone()
        return self._approval_from_row(row) if row else None

    def mark_approval_consumed(self, job_id: str, token: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE approvals SET consumed=1 WHERE job_id=? AND token=?",
                (job_id, token))
            self._conn.commit()

    def _approval_from_row(self, row: sqlite3.Row) -> Approval:
        return Approval(
            approval_id=row["approval_id"], job_id=row["job_id"],
            principal=row["principal"], revision=row["revision"],
            digest=row["digest"], token=row["token"],
            group_ids=_unjson(row["group_ids_json"]),
            issued_at=row["issued_at"], expires_at=row["expires_at"],
            consumed=bool(row["consumed"]),
        )

    def items_for(self, candidate_id: str) -> list[ItemOutcome]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM items WHERE candidate_id=?", (candidate_id,)
            ).fetchall()
        return [
            ItemOutcome(item_id=r["item_id"], candidate_id=r["candidate_id"],
                        outcome=r["outcome"], detail=r["detail"])
            for r in rows
        ]

    # -- vision cache (PR2, sync-lore-in-importer) --------------------------

    def vision_cache_lookup(self, image_hash: str) -> VisionResult | None:
        """Return the cached vision result for an image hash, or ``None``.

        The cache is global by design: the key is the SHA-256 of the
        original image bytes and the result describes image content, not
        world canon, so it is safe to reuse across worlds and jobs. Missing
        or corrupt rows degrade to ``None`` so the vision flow stays
        fail-open (a corrupt cache entry never blocks an import).
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT result_json FROM vision_cache WHERE hash=?", (image_hash,)
            ).fetchone()
        if row is None:
            return None
        try:
            return VisionResult.from_json_dict(_unjson(row["result_json"]), image_hash)
        except Exception:  # noqa: BLE001 — cache is advisory, never fatal
            return None

    def vision_cache_store(self, image_hash: str, result: VisionResult) -> None:
        """Persist a vision result keyed by the image SHA-256.

        Idempotent: re-storing the same hash replaces the prior row (the
        freshest analysis wins). Only successful analyses reach the cache —
        callers must never store failures.
        """
        payload = result.to_json_dict()
        payload["image_hash"] = payload.get("image_hash") or image_hash
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO vision_cache (hash, result_json, created_at)"
                " VALUES (?,?,?)",
                (image_hash, _json(payload), utcnow_iso()),
            )
            self._conn.commit()
