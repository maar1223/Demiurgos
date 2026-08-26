"""Durable SQLite state and raw-first capture storage.

Thread ownership contract
-------------------------
SQLite connections must not be shared across threads. ``CaptureStore`` owns ONE
connection PER thread (``threading.local``): the ingress/main thread and each
``CaptureWorker`` pool thread get their own connection to the same database
file, so asynchronous durable processing is safe and deterministic instead of
raising ``sqlite3.ProgrammingError``. A busy timeout serializes concurrent
writers.

Every connection is closed BY THE THREAD THAT OWNS IT (closing a connection
from another thread raises ``sqlite3.ProgrammingError`` and leaks the file
handle on Windows). ``CaptureWorker.close()`` asks its pool threads to close
their connections first; ``CaptureStore.close()`` then closes the calling
thread's connection and drops all tracked references.
"""

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import CaptureRecord, CaptureState, MediaKind, TelegramUpdate

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS captures (
        capture_id TEXT PRIMARY KEY, source TEXT NOT NULL, update_id INTEGER NOT NULL,
        world TEXT, state TEXT NOT NULL, raw_text TEXT NOT NULL, raw_bytes BLOB NOT NULL,
        mime TEXT NOT NULL, media_kind TEXT NOT NULL, slug TEXT NOT NULL,
        attempt INTEGER NOT NULL DEFAULT 0, error TEXT, created_at TEXT NOT NULL,
        media_path TEXT NOT NULL DEFAULT '', media_duration_seconds REAL,
        global_ INTEGER NOT NULL DEFAULT 0,
        UNIQUE(source, update_id)
    );
    CREATE TABLE IF NOT EXISTS outbox (
        topic TEXT PRIMARY KEY, payload TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0
    );
"""


class CaptureStore:
    def __init__(self, path: str | Path, busy_timeout_seconds: float = 10.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._busy_timeout = busy_timeout_seconds
        self._lock = threading.Lock()
        # id(connection) -> (connection, owner thread ident); connections are
        # always closed on their owning thread (see close_own_thread_connections).
        self._connections: dict[int, tuple[sqlite3.Connection, int]] = {}
        self._local = threading.local()
        self._connection()  # create the schema from the owning thread

    def _connection(self) -> sqlite3.Connection:
        """Return this thread's private connection, creating it on first use."""
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=self._busy_timeout)
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(captures)")}
            if "media_path" not in columns:
                conn.execute("ALTER TABLE captures ADD COLUMN media_path TEXT NOT NULL DEFAULT ''")
            if "media_duration_seconds" not in columns:
                conn.execute("ALTER TABLE captures ADD COLUMN media_duration_seconds REAL")
            if "global_" not in columns:
                conn.execute("ALTER TABLE captures ADD COLUMN global_ INTEGER NOT NULL DEFAULT 0")
            conn.commit()
            self._local.connection = conn
            with self._lock:
                self._connections[id(conn)] = (conn, threading.get_ident())
        return conn

    def reserve(self, update: TelegramUpdate) -> CaptureRecord:
        db = self._connection()
        source = update.binding_key
        existing = db.execute("SELECT * FROM captures WHERE source=? AND update_id=?",
                              (source, update.update_id)).fetchone()
        if existing:
            return self._record(existing)
        capture_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source}:{update.update_id}"))
        digest = hashlib.sha256(update.media.data or update.media.text.encode()).hexdigest()[:12]
        slug = f"{datetime.now(timezone.utc):%Y-%m-%d}-{digest}"
        db.execute(
            "INSERT INTO captures "
            "(capture_id,source,update_id,world,state,raw_text,raw_bytes,mime,"
            "media_kind,slug,attempt,error,created_at,media_path,media_duration_seconds) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (capture_id, source, update.update_id, None,
             CaptureState.RAW_PERSISTED.value, update.media.text,
             update.media.data, update.media.mime, update.media.kind.value,
             slug, 0, None, datetime.now(timezone.utc).isoformat(),
             update.media.path, update.media.duration_seconds),
        )
        db.commit()
        return self.get(capture_id)

    def find_by_source_update(self, update: TelegramUpdate) -> CaptureRecord | None:
        row = self._connection().execute(
            "SELECT * FROM captures WHERE source=? AND update_id=?",
            (update.binding_key, update.update_id),
        ).fetchone()
        return self._record(row) if row is not None else None

    def get(self, capture_id: str) -> CaptureRecord:
        row = self._connection().execute("SELECT * FROM captures WHERE capture_id=?",
                                         (capture_id,)).fetchone()
        if row is None:
            raise KeyError(capture_id)
        return self._record(row)

    def set_world(self, capture_id: str, world: str | None) -> CaptureRecord:
        state = CaptureState.CANCELLED if world is None else CaptureState.PROCESSING
        self._connection().execute("UPDATE captures SET world=?, state=? WHERE capture_id=?",
                                   (world, state.value, capture_id))
        self._connection().commit()
        return self.get(capture_id)

    def set_global(self, capture_id: str) -> CaptureRecord:
        """Flag a capture for the global bank: no world, durable processing.

        Additive to the per-world flow: it clears any world, sets the ``global_``
        flag and transitions to PROCESSING so the worker persists it to the
        global ``ideas/`` root. It never touches the SAVE/CHANGE_WORLD path.
        """
        self._connection().execute(
            "UPDATE captures SET world=NULL, global_=1, state=? WHERE capture_id=?",
            (CaptureState.PROCESSING.value, capture_id))
        self._connection().commit()
        return self.get(capture_id)

    def delete_for_world(self, world: str) -> int:
        """Permanently delete every capture row scoped to *world*.

        Returns the number of rows removed. Used by the world recycle-bin
        purge so idea-capture entries of a purged world are cleaned.
        """
        db = self._connection()
        cursor = db.execute("DELETE FROM captures WHERE world=?", (world,))
        db.commit()
        return cursor.rowcount

    def mark_retryable(self, capture_id: str, error: str) -> CaptureRecord:
        record = self.get(capture_id)
        state = CaptureState.ERROR if record.attempt + 1 >= 5 else CaptureState.RETRYABLE
        self._connection().execute(
            "UPDATE captures SET state=?, attempt=attempt+1, error=? WHERE capture_id=?",
            (state.value, error[:500], capture_id))
        self._connection().commit()
        return self.get(capture_id)

    def mark_saved(self, capture_id: str, topic: str, payload: dict) -> CaptureRecord:
        db = self._connection()
        db.execute("UPDATE captures SET state=?, error=NULL WHERE capture_id=?",
                   (CaptureState.SAVED.value, capture_id))
        db.execute("INSERT OR IGNORE INTO outbox(topic,payload) VALUES(?,?)",
                   (topic, json.dumps(payload, sort_keys=True)))
        db.commit()
        return self.get(capture_id)

    def pending_outbox(self):
        return self._connection().execute(
            "SELECT topic,payload FROM outbox WHERE published=0 ORDER BY topic").fetchall()

    def publish_outbox(self, topic: str):
        self._connection().execute("UPDATE outbox SET published=1 WHERE topic=?", (topic,))
        self._connection().commit()

    def count(self):
        return self._connection().execute("SELECT COUNT(*) FROM captures").fetchone()[0]

    def list_capture_ids(self) -> list[str]:
        rows = self._connection().execute(
            "SELECT capture_id FROM captures ORDER BY created_at").fetchall()
        return [row["capture_id"] for row in rows]

    def close(self):
        """Close the calling thread's connection and drop all tracked refs.

        Foreign-thread connections must already be closed by their owners
        (CaptureWorker.close runs ``close_own_thread_connections`` on its pool
        threads first); here we only drop the registry references so their
        finalizers can release the database file.
        """
        self.close_own_thread_connections()
        with self._lock:
            self._connections.clear()
        try:
            del self._local.connection
        except AttributeError:
            pass

    def close_own_thread_connections(self):
        """Close every connection owned by the CALLING thread (safe from any
        thread: other threads' connections are left untouched)."""
        owner = threading.get_ident()
        with self._lock:
            own = [conn for conn, conn_owner in self._connections.values()
                   if conn_owner == owner]
        for conn in own:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            with self._lock:
                self._connections.pop(id(conn), None)

    @staticmethod
    def _record(row):
        return CaptureRecord(
            row["capture_id"], row["update_id"], row["world"],
            CaptureState(row["state"]), row["raw_text"], row["raw_bytes"],
            row["mime"], MediaKind(row["media_kind"]), row["slug"],
            row["attempt"], row["error"], row["created_at"], row["source"],
            row["media_path"], row["media_duration_seconds"], bool(row["global_"]),
        )
