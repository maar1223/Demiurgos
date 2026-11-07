"""Focused tests for the product-owned assistant memory store."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import assistant_memory_store  # noqa: E402
from assistant_memory_store import (  # noqa: E402
    AssistantMemoryStore,
    SCHEMA_VERSION,
)


def _save(store: AssistantMemoryStore, *, topic: str = "world/vibrantes/ganic", **overrides):
    payload = {
        "world": "Vibrantes",
        "kind": "canon",
        "topic_key": topic,
        "statement": "Ganic llegó de fuera a un pueblo de interior.",
        "confidence": 0.9,
        "status": "accepted",
    }
    payload.update(overrides)
    return store.upsert(**payload)


def test_fresh_store_creates_schema_and_version(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path / "memory.sqlite3")
    version = store._conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION
    tables = {
        row[0]
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    assert "memory_entries" in tables
    store.close()


def test_upsert_dedupes_by_topic_key(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path / "memory.sqlite3")
    first = _save(store)
    second = _save(
        store,
        statement="Ganic llegó de fuera y oculta por qué.",
        confidence=0.8,
    )
    assert second.id == first.id
    assert second.revision_count == 2
    assert second.statement == "Ganic llegó de fuera y oculta por qué."
    assert len(store.list(world="Vibrantes")) == 1
    store.close()


def test_upsert_keeps_accepted_when_a_later_proposal_arrives(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path / "memory.sqlite3")
    _save(store, status="accepted")
    proposal = _save(store, statement="Ganic es el hermano de Rhyz.", status="proposal")
    assert proposal.status == "accepted"
    store.close()


def test_search_finds_spanish_phrase(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path / "memory.sqlite3")
    _save(store)
    _save(
        store,
        topic="world/vibrantes/ekkor",
        statement="El vibrastal de Ekkor canaliza el tiempo.",
    )
    hits = store.search("Ganic", world="Vibrantes")
    assert [entry.topic_key for entry in hits] == ["world/vibrantes/ganic"]
    store.close()


def test_search_filters_world_and_global_scope(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path / "memory.sqlite3")
    _save(store, world="Vibrantes", statement="Ganic vive en Vibrantes.")
    _save(
        store,
        world="Atherr",
        topic="world/atherr/ganic",
        statement="Ganic vive en Atherr.",
    )
    _save(
        store,
        world="",
        scope="global",
        topic="preference/language",
        statement="El Autor prefiere español neutro.",
        kind="preference",
    )
    assert {e.world for e in store.search("Ganic", world="Vibrantes")} == {"Vibrantes"}
    assert {e.world for e in store.search("Ganic", world="Atherr")} == {"Atherr"}
    assert [e.topic_key for e in store.search("español", world="Atherr")] == [
        "preference/language"
    ]
    store.close()


def test_search_excludes_proposals_by_default(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path / "memory.sqlite3")
    _save(store, status="proposal", statement="Ganic podría ser hermano de Rhyz.")
    assert store.search("Ganic", world="Vibrantes") == []
    assert [e.status for e in store.search(
        "Ganic", world="Vibrantes", include_proposals=True)] == ["proposal"]
    store.close()


def test_forget_soft_and_hard_delete(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path / "memory.sqlite3")
    entry = _save(store)
    assert store.forget(entry.id) is True
    assert store.get(entry.id).deleted_at is not None
    assert store.search("Ganic", world="Vibrantes") == []
    assert store.forget(entry.id, hard=True) is True
    assert store.get(entry.id) is None
    store.close()


def test_like_fallback_when_fts_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(assistant_memory_store, "_detect_fts_mode", lambda _conn: "like")
    store = AssistantMemoryStore(tmp_path / "memory.sqlite3")
    assert store.fts_mode == "like"
    _save(store)
    assert [e.topic_key for e in store.search("Ganic", world="Vibrantes")] == [
        "world/vibrantes/ganic"
    ]
    store.close()


def test_default_db_path_uses_state_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        assistant_memory_store, "resolve_state_dir", lambda: tmp_path,
    )
    assert assistant_memory_store.default_db_path() == tmp_path / "assistant-memory.sqlite3"


def test_schema_survives_reopen(tmp_path: Path) -> None:
    db = tmp_path / "memory.sqlite3"
    first = AssistantMemoryStore(db)
    _save(first)
    first.close()

    restarted = AssistantMemoryStore(db)
    assert restarted._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert [e.topic_key for e in restarted.search("Ganic", world="Vibrantes")] == [
        "world/vibrantes/ganic"
    ]
    restarted.close()
