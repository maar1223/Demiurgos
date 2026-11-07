"""Product-owned cross-session memory for the Demiurgos assistant.

A small SQLite store modelled on Engram's working-memory semantics: one row per
stable ``topic_key`` (upsert, not an audit trail), a normalized hash for exact
duplicates, soft delete, review/expiry metadata, and FTS5 retrieval. It is
deliberately NOT the coding agent's Engram database: the product owns this file
in its state directory, so a fresh install works with no external daemon.

Proposal-vs-canon is first class because the guided flow is authoritative: a
provider ``delta`` is stored as ``proposal`` until the Author accepts it, and
only ``accepted_canon`` reaches ``accepted`` memory.

Retrieval uses the trigram tokenizer when the bundled SQLite supports it (it
does on the shipped python-build-standalone runtime), falls back to plain FTS5,
and finally to a LIKE scan, so a packaging difference never breaks the
assistant.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from state_paths import resolve_state_dir

SCHEMA_VERSION = 1

VALID_SCOPES = frozenset({"project", "global"})
VALID_STATUSES = frozenset({"accepted", "proposal", "rumor", "conflict"})

_WORD_RE = re.compile(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]+", re.UNICODE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime | None = None) -> str:
    return (moment or _utcnow()).isoformat()


def normalize_topic_key(topic_key: str) -> str:
    """Lowercase, trim and collapse whitespace in a stable topic key."""
    return " ".join(str(topic_key or "").strip().lower().split())


def normalize_statement(statement: str) -> str:
    """Collapse whitespace so equivalent statements hash the same."""
    return " ".join(str(statement or "").strip().split())


def _hash(scope: str, world: str, topic_key: str, statement: str) -> str:
    payload = "\0".join((scope, world, topic_key, statement))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fts_query(query: str) -> str:
    """Build a safe FTS5 MATCH expression from free text.

    Terms shorter than three characters cannot match the trigram tokenizer, so
    they are dropped (the caller falls back to LIKE when nothing remains).
    """
    terms = [term for term in _WORD_RE.split(query or "") if len(term) >= 3]
    return " OR ".join(f'"{term}"' for term in terms)


@dataclass(frozen=True)
class MemoryEntry:
    """One durable memory row."""

    id: int
    world: str
    scope: str
    kind: str
    entity: str
    topic_key: str
    statement: str
    confidence: float
    status: str
    importance: int
    source_session: str
    source_turn: str
    created_at: str
    updated_at: str
    expires_at: str | None = None
    superseded_by: int | None = None
    deleted_at: str | None = None
    revision_count: int = 1


class AssistantMemoryStore:
    """SQLite-backed memory store with FTS5 retrieval and upsert semantics."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = default_db_path()
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._fts_mode = "like"
        self._initialize()

    # -- schema --------------------------------------------------------------

    def _initialize(self) -> None:
        with self._lock:
            version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if version == 0:
                self._create_schema()
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self._conn.commit()
            elif version != SCHEMA_VERSION:
                raise RuntimeError(
                    f"unsupported assistant-memory schema version {version}; "
                    f"expected {SCHEMA_VERSION}"
                )
            self._fts_mode = _detect_fts_mode(self._conn)
            if self._fts_mode != "like":
                self._install_fts(self._fts_mode)
                # External-content FTS must mirror the content table, including
                # rows written before an FTS-capable runtime opened this file.
                self._conn.execute(
                    "INSERT INTO memory_entries_fts(memory_entries_fts) "
                    "VALUES ('rebuild')"
                )
                self._conn.commit()

    def _create_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                world TEXT NOT NULL DEFAULT '',
                scope TEXT NOT NULL DEFAULT 'project',
                kind TEXT NOT NULL,
                entity TEXT NOT NULL DEFAULT '',
                topic_key TEXT NOT NULL,
                statement TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'accepted',
                importance INTEGER NOT NULL DEFAULT 0,
                source_session TEXT NOT NULL DEFAULT '',
                source_turn TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                superseded_by INTEGER,
                deleted_at TEXT,
                normalized_hash TEXT NOT NULL,
                revision_count INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_topic "
            "ON memory_entries(scope, world, topic_key) WHERE deleted_at IS NULL"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_world "
            "ON memory_entries(world, scope, status)"
        )

    def _install_fts(self, mode: str) -> None:
        tokenizer = "trigram" if mode == "trigram" else "unicode61"
        self._conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_entries_fts
            USING fts5(
                statement,
                entity,
                topic_key,
                tokenize='{tokenizer}',
                content='memory_entries',
                content_rowid='id'
            )
            """
        )
        self._conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memory_entries_ai
            AFTER INSERT ON memory_entries BEGIN
                INSERT INTO memory_entries_fts(rowid, statement, entity, topic_key)
                VALUES (new.id, new.statement, new.entity, new.topic_key);
            END
            """
        )
        self._conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memory_entries_ad
            AFTER DELETE ON memory_entries BEGIN
                INSERT INTO memory_entries_fts(
                    memory_entries_fts, rowid, statement, entity, topic_key
                ) VALUES ('delete', old.id, old.statement, old.entity, old.topic_key);
            END
            """
        )
        self._conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memory_entries_au
            AFTER UPDATE ON memory_entries BEGIN
                INSERT INTO memory_entries_fts(
                    memory_entries_fts, rowid, statement, entity, topic_key
                ) VALUES ('delete', old.id, old.statement, old.entity, old.topic_key);
                INSERT INTO memory_entries_fts(rowid, statement, entity, topic_key)
                VALUES (new.id, new.statement, new.entity, new.topic_key);
            END
            """
        )

    # -- writes --------------------------------------------------------------

    def upsert(
        self,
        *,
        world: str,
        kind: str,
        topic_key: str,
        statement: str,
        scope: str = "project",
        entity: str = "",
        confidence: float = 0.0,
        status: str = "accepted",
        importance: int = 0,
        source_session: str = "",
        source_turn: str = "",
        expires_at: str | None = None,
    ) -> MemoryEntry:
        """Insert or evolve one topic.

        The same ``(scope, world, topic_key)`` is updated in place; an accepted
        row is never demoted by a later proposal on the same topic.
        """
        scope = str(scope or "project").strip().lower()
        status = str(status or "accepted").strip().lower()
        if scope not in VALID_SCOPES:
            raise ValueError(f"invalid scope {scope!r}")
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}")
        world = str(world or "").strip()
        kind = str(kind or "").strip()
        if not kind:
            raise ValueError("kind must not be empty")
        topic_key = normalize_topic_key(topic_key)
        if not topic_key:
            raise ValueError("topic_key must not be empty")
        statement = normalize_statement(statement)
        if not statement:
            raise ValueError("statement must not be empty")
        entity = " ".join(str(entity or "").split())
        digest = _hash(scope, world, topic_key, statement)
        now = _iso()

        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memory_entries WHERE scope = ? AND world = ? "
                "AND topic_key = ? AND deleted_at IS NULL",
                (scope, world, topic_key),
            ).fetchone()
            if row is None:
                cursor = self._conn.execute(
                    """
                    INSERT INTO memory_entries (
                        world, scope, kind, entity, topic_key, statement,
                        confidence, status, importance, source_session,
                        source_turn, created_at, updated_at, expires_at,
                        normalized_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        world, scope, kind, entity, topic_key, statement,
                        float(confidence), status, int(importance),
                        source_session, source_turn, now, now, expires_at,
                        digest,
                    ),
                )
                self._conn.commit()
                return self._entry_by_id(int(cursor.lastrowid))

            existing_id = int(row["id"])
            existing_hash = str(row["normalized_hash"])
            existing_status = str(row["status"])
            if existing_hash == digest:
                self._conn.execute(
                    "UPDATE memory_entries SET confidence = MAX(confidence, ?), "
                    "importance = MAX(importance, ?), updated_at = ? "
                    "WHERE id = ?",
                    (float(confidence), int(importance), now, existing_id),
                )
                self._conn.commit()
                return self._entry_by_id(existing_id)

            next_status = (
                "accepted"
                if existing_status == "accepted" or status == "accepted"
                else status
            )
            self._conn.execute(
                """
                UPDATE memory_entries SET
                    kind = ?, entity = ?, statement = ?, confidence = ?,
                    status = ?, importance = MAX(importance, ?),
                    source_session = ?, source_turn = ?, updated_at = ?,
                    expires_at = COALESCE(?, expires_at),
                    normalized_hash = ?, revision_count = revision_count + 1
                WHERE id = ?
                """,
                (
                    kind, entity, statement, float(confidence), next_status,
                    int(importance), source_session, source_turn, now,
                    expires_at, digest, existing_id,
                ),
            )
            self._conn.commit()
            return self._entry_by_id(existing_id)

    def forget(self, entry_id: int, *, hard: bool = False) -> bool:
        """Soft-delete an entry, or remove it permanently with ``hard``."""
        with self._lock:
            if hard:
                cursor = self._conn.execute(
                    "DELETE FROM memory_entries WHERE id = ?", (int(entry_id),),
                )
            else:
                cursor = self._conn.execute(
                    "UPDATE memory_entries SET deleted_at = ?, updated_at = ? "
                    "WHERE id = ? AND deleted_at IS NULL",
                    (_iso(), _iso(), int(entry_id)),
                )
            self._conn.commit()
            return cursor.rowcount > 0

    # -- reads ---------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        world: str = "",
        limit: int = 5,
        include_proposals: bool = False,
        now: datetime | None = None,
    ) -> list[MemoryEntry]:
        """Return the most relevant live entries for a free-text query."""
        world = str(world or "").strip()
        limit = max(0, int(limit))
        if limit == 0:
            return []
        now_iso = _iso(now)
        filters = [
            "e.deleted_at IS NULL",
            "(e.expires_at IS NULL OR e.expires_at > ?)",
            "(e.scope = 'global' OR e.world = ?)",
        ]
        params: list[object] = [now_iso, world]
        if not include_proposals:
            filters.append("e.status != 'proposal'")

        match = _fts_query(query)
        with self._lock:
            if self._fts_mode != "like" and match:
                sql = (
                    "SELECT e.* FROM memory_entries e "
                    "JOIN memory_entries_fts f ON f.rowid = e.id "
                    "WHERE " + " AND ".join(filters) +
                    " AND memory_entries_fts MATCH ? "
                    "ORDER BY bm25(memory_entries_fts), e.importance DESC, "
                    "e.updated_at DESC LIMIT ?"
                )
                rows = self._conn.execute(
                    sql, [*params, match, limit],
                ).fetchall()
            elif str(query or "").strip():
                like = f"%{str(query).strip()}%"
                sql = (
                    "SELECT e.* FROM memory_entries e WHERE " +
                    " AND ".join(filters) +
                    " AND (e.statement LIKE ? OR e.entity LIKE ? "
                    "OR e.topic_key LIKE ?) "
                    "ORDER BY e.importance DESC, e.updated_at DESC LIMIT ?"
                )
                rows = self._conn.execute(
                    sql, [*params, like, like, like, limit],
                ).fetchall()
            else:
                sql = (
                    "SELECT e.* FROM memory_entries e WHERE " +
                    " AND ".join(filters) +
                    " ORDER BY e.importance DESC, e.updated_at DESC LIMIT ?"
                )
                rows = self._conn.execute(sql, [*params, limit]).fetchall()
        return [self._entry_from(row) for row in rows]

    def list(
        self,
        *,
        world: str = "",
        limit: int = 50,
        include_proposals: bool = True,
        include_deleted: bool = False,
    ) -> list[MemoryEntry]:
        """List entries for the management API (newest first)."""
        world = str(world or "").strip()
        filters = ["1 = 1"]
        params: list[object] = []
        if not include_deleted:
            filters.append("deleted_at IS NULL")
        if world:
            filters.append("(scope = 'global' OR world = ?)")
            params.append(world)
        if not include_proposals:
            filters.append("status != 'proposal'")
        sql = (
            "SELECT * FROM memory_entries WHERE " + " AND ".join(filters) +
            " ORDER BY importance DESC, updated_at DESC LIMIT ?"
        )
        params.append(max(0, int(limit)))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._entry_from(row) for row in rows]

    def get(self, entry_id: int) -> MemoryEntry | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memory_entries WHERE id = ?", (int(entry_id),),
            ).fetchone()
        return None if row is None else self._entry_from(row)

    def find(
        self,
        *,
        topic_key: str,
        world: str = "",
        scope: str = "project",
    ) -> MemoryEntry | None:
        """Return the live entry for an exact ``(scope, world, topic_key)``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memory_entries WHERE scope = ? AND world = ? "
                "AND topic_key = ? AND deleted_at IS NULL",
                (scope, world, normalize_topic_key(topic_key)),
            ).fetchone()
        return None if row is None else self._entry_from(row)

    @property
    def fts_mode(self) -> str:
        """``trigram``, ``fts5`` or ``like`` — the active retrieval strategy."""
        return self._fts_mode

    # -- helpers -------------------------------------------------------------

    def _entry_by_id(self, entry_id: int) -> MemoryEntry:
        entry = self.get(entry_id)
        if entry is None:  # pragma: no cover - the row was just written
            raise RuntimeError(f"memory entry {entry_id} disappeared")
        return entry

    @staticmethod
    def _entry_from(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            id=int(row["id"]),
            world=row["world"],
            scope=row["scope"],
            kind=row["kind"],
            entity=row["entity"],
            topic_key=row["topic_key"],
            statement=row["statement"],
            confidence=float(row["confidence"]),
            status=row["status"],
            importance=int(row["importance"]),
            source_session=row["source_session"],
            source_turn=row["source_turn"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            superseded_by=row["superseded_by"],
            deleted_at=row["deleted_at"],
            revision_count=int(row["revision_count"]),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _detect_fts_mode(conn: sqlite3.Connection) -> str:
    """Pick the best available retrieval strategy for this SQLite build."""
    for mode, tokenizer in (("trigram", "trigram"), ("fts5", "unicode61")):
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS _memory_fts_probe "
                f"USING fts5(x, tokenize='{tokenizer}')"
            )
            conn.execute("DROP TABLE IF EXISTS _memory_fts_probe")
            conn.commit()
            return mode
        except sqlite3.OperationalError:
            try:
                conn.execute("DROP TABLE IF EXISTS _memory_fts_probe")
                conn.commit()
            except sqlite3.OperationalError:  # pragma: no cover - defensive
                pass
    return "like"


def default_db_path() -> Path:
    """Durable default, resolved on every call so tests can relocate state."""
    return resolve_state_dir() / "assistant-memory.sqlite3"
