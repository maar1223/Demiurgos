"""SQLite-backed conversation memory store for the non-guided assistant path.

Stores conversational turns (user/assistant) per session together with an
optional distilled state: a compact LLM-generated summary refreshed every
``DISTILL_REFRESH_INTERVAL`` turns so long conversations stay within the
prompt budget while keeping key context.

Mechanism choice: stdlib ``sqlite3`` with a single file-backed database.
``db_path`` selects the location; when it is ``None`` the store resolves the
durable repo-local default ``<repo>/data/conversation-memory.sqlite3`` (the
same ``data/`` convention as ``guided-sessions.sqlite3``), so memory survives a
restart without any environment override. ``db_path=":memory:"`` remains
available explicitly for hermetic use. A thread lock guards the single
connection; ``check_same_thread=False`` lets the FastAPI thread pool and event
loop share it. Expired turns are discarded lazily on every write and eagerly on
startup (mirrors the durable guided-session store pattern).
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

TURN_TTL = timedelta(hours=24)
"""Turns older than this are discarded as expired memory."""

MEMORY_WINDOW = 10
"""Default number of recent turns injected into the assistant prompt."""

DISTILL_REFRESH_INTERVAL = 5
"""Refresh the distilled state every N session turns (lazy on write)."""

DISTILL_MAX_TOKENS = 500
"""Token budget the caller must respect when generating a distilled summary."""

CONSENT_FLAG_TTL = timedelta(hours=24)
"""Guided-flow consent declines older than this are forgotten (re-nagging window)."""

_VALID_ROLES = frozenset({"user", "assistant"})

# SQLite's stdlib driver (Python 3.12+) executes one statement per call, so
# the schema is a tuple of standalone DDL statements run in order.
from data_root import resolve_data_root

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS conversation_turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        mundo TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user','assistant')),
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        skill_id TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_turns_session
    ON conversation_turns(session_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS distilled_states (
        session_id TEXT PRIMARY KEY,
        mundo TEXT NOT NULL,
        summary TEXT NOT NULL,
        turn_count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guided_consent_flags (
        session_id TEXT NOT NULL,
        mundo TEXT NOT NULL,
        declined_at TEXT NOT NULL,
        PRIMARY KEY (session_id, mundo)
    )
    """,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def default_db_path() -> Path:
    """Durable default for the conversation-memory database.

    Resolved from the data root on every call (WU-2), never at import time, so
    the suite can point ``DEMIURGOS_DATA_ROOT`` at a throwaway root instead of
    the repo ``data/`` directory.
    """
    return resolve_data_root() / "data" / "conversation-memory.sqlite3"


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Turn:
    """One stored conversational turn."""

    id: int
    session_id: str
    mundo: str
    role: str
    content: str
    created_at: str
    skill_id: str | None = None


@dataclass(frozen=True)
class DistilledState:
    """The compact summary state distilled from a session's turns."""

    session_id: str
    mundo: str
    summary: str
    turn_count: int
    updated_at: str


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #


class ConversationMemoryStore:
    """SQLite-backed conversational memory with TTL cleanup and distilled state.

    All mutations are serialized through ``self._lock``; the single connection
    is shared across threads (``check_same_thread=False``). Expired turns are
    removed lazily on every ``add_turn()`` and eagerly on construction.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = default_db_path()
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        for statement in _SCHEMA_STATEMENTS:
            self._conn.execute(statement)
        self._conn.commit()
        # Startup sweep: drop turns that expired while the server was offline.
        self.discard_expired()

    # -- public API ----------------------------------------------------------

    def add_turn(
        self,
        session_id: str,
        mundo: str,
        role: str,
        content: str,
        *,
        skill_id: str | None = None,
    ) -> int:
        """Store one turn and return its row id.

        Expired turns are swept lazily before the insert so the window always
        reflects fresh memory only.
        """
        if role not in _VALID_ROLES:
            raise ValueError(f"invalid role {role!r}; expected 'user' or 'assistant'")
        with self._lock:
            self._discard_expired(_utcnow())
            cursor = self._conn.execute(
                "INSERT INTO conversation_turns "
                "(session_id, mundo, role, content, created_at, skill_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, mundo, role, content, _utcnow().isoformat(), skill_id),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def get_recent_turns(
        self, session_id: str, *, limit: int = MEMORY_WINDOW,
    ) -> list[Turn]:
        """Return the most recent turns for a session, oldest first.

        ``limit`` caps how many turns are returned (default ``MEMORY_WINDOW``).
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM conversation_turns WHERE session_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (session_id, max(0, int(limit))),
            ).fetchall()
        turns = [self._turn_from(row) for row in rows]
        turns.reverse()  # chronological order for prompt injection
        return turns

    def get_distilled_state(self, session_id: str) -> DistilledState | None:
        """Return the distilled state for a session, or ``None`` when absent."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM distilled_states WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return self._distilled_from(row) if row is not None else None

    def should_refresh_distilled(self, session_id: str) -> bool:
        """True when the session turn count is a positive multiple of
        ``DISTILL_REFRESH_INTERVAL`` — the signal to regenerate the summary."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM conversation_turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        count = int(row["n"])
        return count > 0 and count % DISTILL_REFRESH_INTERVAL == 0

    def update_distilled_state(
        self, session_id: str, mundo: str, summary: str, turn_count: int,
    ) -> None:
        """Insert or replace the distilled state for a session (upsert)."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO distilled_states "
                "(session_id, mundo, summary, turn_count, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "mundo = excluded.mundo, "
                "summary = excluded.summary, "
                "turn_count = excluded.turn_count, "
                "updated_at = excluded.updated_at",
                (session_id, mundo, summary, turn_count, _utcnow().isoformat()),
            )
            self._conn.commit()

    def record_guided_consent_decline(self, session_id: str, mundo: str) -> None:
        """Upsert a TTL-scoped consent decline for ``(session_id, mundo)``.

        The flag is server-authoritative consent memory (REQ-GFC-06): a declined
        session never receives another guided suggestion until the flag expires
        or is overwritten. The empty-string session never names a real
        conversation, so it is a deliberate no-op (fricción 4).
        """
        if not session_id:
            return
        now = _utcnow()
        cutoff = (now - CONSENT_FLAG_TTL).isoformat()
        with self._lock:
            self._conn.execute(
                "DELETE FROM guided_consent_flags WHERE declined_at < ?", (cutoff,),
            )
            self._conn.execute(
                "INSERT INTO guided_consent_flags (session_id, mundo, declined_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(session_id, mundo) DO UPDATE SET "
                "declined_at = excluded.declined_at",
                (session_id, mundo, now.isoformat()),
            )
            self._conn.commit()

    def guided_consent_declined(self, session_id: str, mundo: str) -> bool:
        """True when a non-expired decline exists for ``(session_id, mundo)``."""
        if not session_id:
            return False
        cutoff = (_utcnow() - CONSENT_FLAG_TTL).isoformat()
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM guided_consent_flags "
                "WHERE session_id = ? AND mundo = ? AND declined_at >= ?",
                (session_id, mundo, cutoff),
            ).fetchone()
        return row is not None

    def discard_expired(self) -> int:
        """Delete turns older than ``TURN_TTL``; returns the number removed.

        Distilled states whose sessions no longer have any turn are removed
        with them (the summary would only describe expired memory).
        """
        with self._lock:
            return self._discard_expired(_utcnow())

    def close(self) -> None:
        """Close the underlying connection. The store is unusable afterwards."""
        with self._lock:
            self._conn.close()

    # -- low-level helpers (call under self._lock) ---------------------------

    def _discard_expired(self, now: datetime) -> int:
        cutoff = (now - TURN_TTL).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM conversation_turns WHERE created_at < ?", (cutoff,),
        )
        removed = max(0, cursor.rowcount)
        if removed:
            self._conn.execute(
                "DELETE FROM distilled_states WHERE session_id NOT IN "
                "(SELECT DISTINCT session_id FROM conversation_turns)",
            )
        # Consent declines have their own TTL; sweep them independently so a
        # retired flag never suppresses a future guided suggestion.
        self._conn.execute(
            "DELETE FROM guided_consent_flags WHERE declined_at < ?",
            ((now - CONSENT_FLAG_TTL).isoformat(),),
        )
        self._conn.commit()
        return removed

    @staticmethod
    def _turn_from(row: sqlite3.Row) -> Turn:
        return Turn(
            id=int(row["id"]),
            session_id=row["session_id"],
            mundo=row["mundo"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
            skill_id=row["skill_id"],
        )

    @staticmethod
    def _distilled_from(row: sqlite3.Row) -> DistilledState:
        return DistilledState(
            session_id=row["session_id"],
            mundo=row["mundo"],
            summary=row["summary"],
            turn_count=int(row["turn_count"]),
            updated_at=row["updated_at"],
        )
