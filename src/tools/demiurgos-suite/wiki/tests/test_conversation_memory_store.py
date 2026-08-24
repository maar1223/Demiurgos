"""RED/unit tests for the SQLite-backed ConversationMemoryStore.

Covers: add_turn persistence and role validation, the recent-turn window
limit and ordering, TTL cleanup (discard_expired + lazy sweep on add_turn,
including orphaned distilled states), the distilled-state refresh trigger
(should_refresh_distilled at multiples of DISTILL_REFRESH_INTERVAL), the
distilled-state upsert, and concurrent access from multiple threads.
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import conversation_memory_store  # noqa: E402
from conversation_memory_store import (  # noqa: E402
    DISTILL_REFRESH_INTERVAL,
    MEMORY_WINDOW,
    TURN_TTL,
    ConversationMemoryStore,
    DistilledState,
    Turn,
    default_db_path,
)

_EPOCH = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def store(tmp_path: Path) -> ConversationMemoryStore:
    created = ConversationMemoryStore(tmp_path / "memory.sqlite3")
    yield created
    created.close()


def _clock(monkeypatch: pytest.MonkeyPatch, start: datetime = _EPOCH) -> dict:
    """Install a controllable clock and return its mutable holder."""
    holder = {"now": start}

    def fake_now() -> datetime:
        return holder["now"]

    monkeypatch.setattr(conversation_memory_store, "_utcnow", fake_now)
    return holder


class TestAddTurn:
    def test_add_turn_returns_id_and_persists(self, store: ConversationMemoryStore) -> None:
        turn_id = store.add_turn("s-1", "nec", "user", "hello there", skill_id="narrative-idea")
        assert isinstance(turn_id, int) and turn_id > 0
        turns = store.get_recent_turns("s-1")
        assert len(turns) == 1
        turn = turns[0]
        assert isinstance(turn, Turn)
        assert turn.id == turn_id
        assert turn.session_id == "s-1"
        assert turn.mundo == "nec"
        assert turn.role == "user"
        assert turn.content == "hello there"
        assert turn.skill_id == "narrative-idea"
        assert turn.created_at  # ISO timestamp recorded

    def test_add_turn_records_assistant_turn_without_skill(self, store: ConversationMemoryStore) -> None:
        store.add_turn("s-1", "nec", "user", "hello")
        assistant_id = store.add_turn("s-1", "nec", "assistant", "hi!")
        assert assistant_id > 1
        turns = store.get_recent_turns("s-1")
        assert [t.role for t in turns] == ["user", "assistant"]
        assert turns[1].skill_id is None

    def test_add_turn_rejects_invalid_role(self, store: ConversationMemoryStore) -> None:
        with pytest.raises(ValueError):
            store.add_turn("s-1", "nec", "system", "nope")

    def test_turns_are_scoped_per_session(self, store: ConversationMemoryStore) -> None:
        store.add_turn("s-1", "nec", "user", "in session one")
        store.add_turn("s-2", "nec", "user", "in session two")
        contents = [t.content for t in store.get_recent_turns("s-1")]
        assert contents == ["in session one"]


class TestGetRecentTurns:
    def test_window_limit_defaults_to_memory_window(self, store: ConversationMemoryStore) -> None:
        for i in range(15):
            store.add_turn("s-1", "nec", "user", f"msg {i}")
        turns = store.get_recent_turns("s-1")
        assert len(turns) == MEMORY_WINDOW

    def test_explicit_limit_respected(self, store: ConversationMemoryStore) -> None:
        for i in range(15):
            store.add_turn("s-1", "nec", "user", f"msg {i}")
        turns = store.get_recent_turns("s-1", limit=3)
        assert [t.content for t in turns] == ["msg 12", "msg 13", "msg 14"]

    def test_recent_turns_are_chronological(self, store: ConversationMemoryStore) -> None:
        store.add_turn("s-1", "nec", "user", "first")
        store.add_turn("s-1", "nec", "assistant", "second")
        store.add_turn("s-1", "nec", "user", "third")
        assert [t.content for t in store.get_recent_turns("s-1")] == [
            "first", "second", "third",
        ]

    def test_unknown_session_returns_empty(self, store: ConversationMemoryStore) -> None:
        assert store.get_recent_turns("missing") == []


class TestTTLCleanup:
    def test_discard_expired_removes_old_turns(self, monkeypatch, store: ConversationMemoryStore) -> None:
        clock = _clock(monkeypatch)
        store.add_turn("s-1", "nec", "user", "old turn")
        store.add_turn("s-2", "nec", "user", "another old turn")
        assert len(store.get_recent_turns("s-1")) == 1
        clock["now"] += TURN_TTL + timedelta(seconds=1)
        removed = store.discard_expired()
        assert removed == 2
        assert store.get_recent_turns("s-1") == []
        assert store.get_recent_turns("s-2") == []

    def test_turns_within_ttl_survive(self, monkeypatch, store: ConversationMemoryStore) -> None:
        clock = _clock(monkeypatch)
        store.add_turn("s-1", "nec", "user", "fresh turn")
        clock["now"] += TURN_TTL - timedelta(seconds=1)
        assert store.discard_expired() == 0
        assert len(store.get_recent_turns("s-1")) == 1

    def test_lazy_cleanup_on_add_turn(self, monkeypatch, store: ConversationMemoryStore) -> None:
        clock = _clock(monkeypatch)
        store.add_turn("s-1", "nec", "user", "old turn")
        assert len(store.get_recent_turns("s-1")) == 1
        clock["now"] += TURN_TTL + timedelta(seconds=1)
        store.add_turn("s-1", "nec", "assistant", "new turn")
        turns = store.get_recent_turns("s-1")
        assert [t.content for t in turns] == ["new turn"]

    def test_discard_expired_drops_orphan_distilled_states(self, monkeypatch, store: ConversationMemoryStore) -> None:
        clock = _clock(monkeypatch)
        store.add_turn("s-1", "nec", "user", "hello")
        store.update_distilled_state("s-1", "nec", "summary", 1)
        assert store.get_distilled_state("s-1") is not None
        clock["now"] += TURN_TTL + timedelta(seconds=1)
        store.discard_expired()
        assert store.get_distilled_state("s-1") is None


class TestDistilledState:
    def test_should_refresh_distilled_at_multiples_of_interval(self, store: ConversationMemoryStore) -> None:
        assert store.should_refresh_distilled("s-1") is False  # no turns yet
        for i in range(1, 11):
            store.add_turn("s-1", "nec", "user", f"msg {i}")
            expected = i % DISTILL_REFRESH_INTERVAL == 0
            assert store.should_refresh_distilled("s-1") is expected, i

    def test_update_distilled_state_upserts(self, store: ConversationMemoryStore) -> None:
        store.update_distilled_state("s-1", "nec", "first summary", 5)
        state = store.get_distilled_state("s-1")
        assert isinstance(state, DistilledState)
        assert state.session_id == "s-1"
        assert state.summary == "first summary"
        assert state.turn_count == 5
        assert state.updated_at

        store.update_distilled_state("s-1", "nec", "refreshed summary", 10)
        state = store.get_distilled_state("s-1")
        assert state is not None
        assert state.summary == "refreshed summary"
        assert state.turn_count == 10
        assert store.get_distilled_state("s-1") is not None  # still one row

    def test_get_distilled_state_for_unknown_session(self, store: ConversationMemoryStore) -> None:
        assert store.get_distilled_state("missing") is None


class TestConcurrency:
    def test_concurrent_add_turn_is_thread_safe(self, store: ConversationMemoryStore) -> None:
        workers = 8
        turns_per_worker = 25
        expected = workers * turns_per_worker
        errors: list[BaseException] = []
        barrier = threading.Barrier(workers)

        def worker(worker_id: int) -> None:
            try:
                barrier.wait(timeout=10)
                for i in range(turns_per_worker):
                    store.add_turn("shared", "nec", "user", f"w{worker_id}-m{i}")
            except BaseException as exc:  # pragma: no cover - failure probe
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors
        turns = store.get_recent_turns("shared", limit=expected + 10)
        assert len(turns) == expected
        # Every id is unique: the serialized writer never lost or duplicated a turn.
        assert len({t.id for t in turns}) == expected


class TestDefaultPath:
    def test_default_db_path_follows_data_convention(self) -> None:
        resolved = default_db_path()
        assert str(resolved).endswith("data/conversation-memory.sqlite3")
        assert ":memory:" not in str(resolved)

    def test_no_argument_store_resolves_to_default(self, monkeypatch, tmp_path: Path) -> None:
        default = tmp_path / "data" / "conversation-memory.sqlite3"
        monkeypatch.setattr(conversation_memory_store, "default_db_path", lambda: default)
        created = ConversationMemoryStore()
        assert created._db_path == str(default)  # noqa: SLF001
        assert default.exists()
        created.close()

    def test_in_memory_path_is_hermetic(self) -> None:
        created = ConversationMemoryStore(":memory:")
        turn_id = created.add_turn("s-1", "nec", "user", "ephemeral")
        assert turn_id > 0
        created.close()
