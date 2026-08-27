"""Store tests for WU1 (idea-capture-confirm-queue): AWAITING_CONFIRM foundation.

Covers S-1.1 (the new state exists and ``event_timestamp`` is persisted from the
update), S-1.2 (the ``event_ts`` migration is additive — a pre-existing database
gains the column without data loss) and S-2.x (``pending_confirm`` /
``count_pending_confirm`` / ``list_pending_confirm`` only ever match rows whose
state is exactly ``AWAITING_CONFIRM``).
"""

import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from idea_capture.models import CaptureRecord, CaptureState, MediaInput, MediaKind, TelegramUpdate
from idea_capture.store import CaptureStore


class AwaitingConfirmStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = CaptureStore(self.root / "capture.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def update(self, update_id=1, text="A pending idea", event_timestamp=None):
        return TelegramUpdate(update_id, 7, 8, False,
                              MediaInput(MediaKind.TEXT, text=text),
                              event_timestamp=event_timestamp)

    @staticmethod
    def _park(store, capture_id):
        """Seed AWAITING_CONFIRM via the real park transition (WU2 store method)."""
        store.set_awaiting_confirm(capture_id)

    # -- S-1.1: state + event_timestamp --------------------------------------

    def test_awaiting_confirm_state_and_new_fields_exist(self):
        """S-1.1: the state is a real enum member and the new fields default."""
        self.assertIn("AWAITING_CONFIRM", CaptureState.__members__)
        self.assertEqual(CaptureState.AWAITING_CONFIRM.value, "AWAITING_CONFIRM")
        self.assertIsNone(TelegramUpdate.event_timestamp)
        self.assertEqual(CaptureRecord.event_ts, "")

    def test_reserve_persists_event_timestamp_as_iso(self):
        """S-1.1: reserve() stores update.event_timestamp as ISO-8601 UTC."""
        ts = 1_700_000_000.5
        expected = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        record = self.store.reserve(self.update(event_timestamp=ts))
        self.assertEqual(record.event_ts, expected)

    def test_reserve_without_timestamp_leaves_event_ts_empty(self):
        """Absent timestamp stays empty (wake-up notice treats it as not offline)."""
        record = self.store.reserve(self.update())
        self.assertEqual(record.event_ts, "")

    # -- S-1.2: additive migration --------------------------------------------

    def test_event_ts_migration_is_additive_without_data_loss(self):
        """S-1.2: a pre-existing DB without event_ts gains it; rows are kept."""
        legacy_path = self.root / "legacy.sqlite3"
        conn = sqlite3.connect(legacy_path)
        conn.executescript("""
            CREATE TABLE captures (
                capture_id TEXT PRIMARY KEY, source TEXT NOT NULL, update_id INTEGER NOT NULL,
                world TEXT, state TEXT NOT NULL, raw_text TEXT NOT NULL, raw_bytes BLOB NOT NULL,
                mime TEXT NOT NULL, media_kind TEXT NOT NULL, slug TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0, error TEXT, created_at TEXT NOT NULL,
                media_path TEXT NOT NULL DEFAULT '', media_duration_seconds REAL,
                global_ INTEGER NOT NULL DEFAULT 0,
                UNIQUE(source, update_id)
            );
        """)
        conn.execute(
            "INSERT INTO captures (capture_id,source,update_id,world,state,raw_text,raw_bytes,"
            "mime,media_kind,slug,attempt,error,created_at,media_path,media_duration_seconds,"
            "global_) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("legacy-1", "telegram:7:8:default", 1, None, "RAW_PERSISTED", "raw idea",
             b"raw-bytes", "text/plain", "text", "2026-08-27-legacy", 0, None,
             "2026-08-27T00:00:00+00:00", "", None, 0),
        )
        conn.commit()
        conn.close()

        store = CaptureStore(legacy_path)
        try:
            columns = {row[1] for row in
                       store._connection().execute("PRAGMA table_info(captures)")}
            self.assertIn("event_ts", columns)
            record = store.get("legacy-1")
            self.assertEqual(record.raw_text, "raw idea")  # no data loss
            self.assertEqual(record.raw_bytes, b"raw-bytes")
            self.assertEqual(record.event_ts, "")  # legacy rows default empty
        finally:
            store.close()

    def test_fresh_database_has_event_ts_column(self):
        """New databases created by the store already carry the column."""
        columns = {row[1] for row in
                   self.store._connection().execute("PRAGMA table_info(captures)")}
        self.assertIn("event_ts", columns)

    # -- S-2.x: pending-confirm queries ---------------------------------------

    def test_pending_confirm_filters_only_awaiting_confirm(self):
        """S-2.1: 1 AWAITING_CONFIRM + RAW_PERSISTED + SAVED -> exactly 1 row."""
        parked = self.store.reserve(self.update(1, text="park me"))
        self.store.reserve(self.update(2, text="raw idea"))
        saved = self.store.reserve(self.update(3, text="saved idea"))
        self.store.mark_saved(saved.capture_id, "ideas", {"id": "saved"})
        self._park(self.store, parked.capture_id)

        pending = self.store.pending_confirm()
        self.assertEqual([record.capture_id for record in pending], [parked.capture_id])
        self.assertEqual(pending[0].raw_text, "park me")
        self.assertEqual(pending[0].state, CaptureState.AWAITING_CONFIRM)

    def test_count_pending_confirm_counts_only_parked(self):
        """2 AWAITING_CONFIRM + 1 RAW_PERSISTED -> count is 2."""
        first = self.store.reserve(self.update(1))
        second = self.store.reserve(self.update(2))
        self.store.reserve(self.update(3))
        self._park(self.store, first.capture_id)
        self._park(self.store, second.capture_id)
        self.assertEqual(self.store.count_pending_confirm(), 2)

    def test_list_pending_confirm_matches_pending_confirm(self):
        """The explicit-list variant returns the same rows as pending_confirm."""
        parked = self.store.reserve(self.update(1))
        self.store.reserve(self.update(2))
        self._park(self.store, parked.capture_id)
        self.assertEqual(self.store.list_pending_confirm(),
                         self.store.pending_confirm())

    def test_no_pending_rows_returns_empty(self):
        self.assertEqual(self.store.pending_confirm(), [])
        self.assertEqual(self.store.count_pending_confirm(), 0)

    # -- R-4: park transition (WU2 store method) ------------------------------

    def test_set_awaiting_confirm_parks_capture(self):
        """R-4: set_awaiting_confirm transitions RAW_PERSISTED -> AWAITING_CONFIRM."""
        record = self.store.reserve(self.update(1, text="park via method"))
        parked = self.store.set_awaiting_confirm(record.capture_id)
        self.assertEqual(parked.capture_id, record.capture_id)
        self.assertEqual(parked.state, CaptureState.AWAITING_CONFIRM)
        self.assertEqual(parked.raw_text, "park via method")  # raw data kept
        self.assertEqual(self.store.count_pending_confirm(), 1)

    # -- R-6: boot_captures (WU3 wake-notice N query) --------------------------

    def test_boot_captures_returns_offline_drained_this_boot(self):
        """R-6: event_ts < boot_ts AND created_at >= boot_ts -> in N."""
        boot_ts = 1_700_000_000.0
        drained = self.store.reserve(self.update(1, event_timestamp=boot_ts - 3600))
        self.store.set_awaiting_confirm(drained.capture_id)
        fresh = self.store.reserve(self.update(2, event_timestamp=boot_ts + 60))

        rows = self.store.boot_captures(boot_ts)

        self.assertEqual([record.capture_id for record in rows], [drained.capture_id])
        self.assertEqual(rows[0].state, CaptureState.AWAITING_CONFIRM)

    def test_boot_captures_excludes_rows_without_event_ts(self):
        """R-6: no event_ts -> no offline marker -> excluded from N."""
        boot_ts = 1_700_000_000.0
        self.store.reserve(self.update(1))  # event_timestamp=None -> event_ts=''
        self.assertEqual(self.store.boot_captures(boot_ts), [])

    def test_boot_captures_excludes_previous_boot_captures(self):
        """R-6: created_at before boot (previous boot) never counts in N."""
        boot_ts = time.time()
        previous = self.store.reserve(self.update(1, event_timestamp=boot_ts - 7200))
        self.store.set_awaiting_confirm(previous.capture_id)
        # created_at is "now" (>= boot_ts) in the real flow, so to prove the
        # created_at bound we backdate the row to before boot.
        self.store._connection().execute(
            "UPDATE captures SET created_at=? WHERE capture_id=?",
            (datetime.fromtimestamp(boot_ts - 60, timezone.utc).isoformat(),
             previous.capture_id))
        self.store._connection().commit()
        self.assertEqual(self.store.boot_captures(boot_ts), [])


if __name__ == "__main__":
    unittest.main()