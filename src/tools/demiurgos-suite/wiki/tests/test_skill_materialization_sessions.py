# -*- coding: utf-8 -*-
"""skill-materialization-sessions — (world, revision) epoch keying + TTL.

``skill_session_epochs`` binds a deterministic session/epoch id to the pair
``(active world, materialization revision)`` and records it in a durable,
atomically-written store with lazy TTL pruning. Covered scenarios (spec
``skill-materialization-sessions``):

- Session identity is keyed by ``(world, revision)`` (unchanged reuses, a
  revision change allocates a new epoch, a world change allocates a new epoch).
- The durable store is atomic and versioned and degrades safely when corrupt.
- TTL pruning drops a stale world and keeps the active one.
- The registry is exercised inertly: its only production references live inside
  the ``api_server`` materialization helper, never on the live ``/v1/runs`` path.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from skill_session_epochs import (
    SCHEMA_VERSION,
    SESSION_EPOCH_TTL_DAYS,
    SessionEpochRegistry,
    session_key_for,
)

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_API_SERVER = _WIKI / "api_server.py"


def _store(tmp_path: Path) -> Path:
    return tmp_path / "data" / "methodology" / "materialization-sessions.json"


def _registry(tmp_path: Path) -> SessionEpochRegistry:
    return SessionEpochRegistry(_store(tmp_path))


def _read_store(tmp_path: Path) -> dict:
    return json.loads(_store(tmp_path).read_text(encoding="utf-8"))


def _old_stamp(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _entry(revision: str, epoch_id: str, stamp: str) -> dict:
    return {
        "revision": revision,
        "epoch_id": epoch_id,
        "created_at": stamp,
        "last_seen_at": stamp,
    }


# -- Keying (spec: Session identity is keyed by (world, revision)) ------------


def test_session_key_deterministic_and_pair_sensitive():
    """The key is deterministic for a pair and changes when either half changes."""
    assert session_key_for("W", "R") == session_key_for("W", "R")
    assert session_key_for("W", "R") != session_key_for("W", "R2")
    assert session_key_for("W", "R") != session_key_for("W2", "R")
    assert session_key_for("W", "R").startswith("demiurgos-")


def test_unchanged_world_revision_reuses_epoch(tmp_path):
    """Spec 'Unchanged (world, revision) reuses the session': the stored epoch
    is returned unchanged and only its last-seen stamp is refreshed."""
    registry = _registry(tmp_path)
    first = registry.observe("W", "R")
    created = _read_store(tmp_path)["worlds"]["W"]["created_at"]

    second = registry.observe("W", "R")

    assert second == first
    entry = _read_store(tmp_path)["worlds"]["W"]
    assert entry["epoch_id"] == first
    assert entry["created_at"] == created  # a reuse never recreates the epoch
    assert entry["last_seen_at"] >= created  # but it is refreshed


def test_revision_change_allocates_new_epoch(tmp_path):
    """Spec 'A revision change forces a new session': R' yields a new key."""
    registry = _registry(tmp_path)
    first = registry.observe("W", "R")

    second = registry.observe("W", "R2")

    assert second != first
    assert second == session_key_for("W", "R2")
    assert _read_store(tmp_path)["worlds"]["W"]["revision"] == "R2"


def test_world_change_allocates_new_epoch(tmp_path):
    """Spec 'A world change forces a new session': W2 yields a new key."""
    registry = _registry(tmp_path)
    first = registry.observe("W1", "R")

    second = registry.observe("W2", "R")

    assert second != first
    assert second == session_key_for("W2", "R")
    assert set(_read_store(tmp_path)["worlds"]) == {"W1", "W2"}


# -- TTL ----------------------------------------------------------------------


def test_observe_prunes_stale_world_and_keeps_active(tmp_path):
    """Lazy TTL prune on ``observe``: a stale world is dropped while the world
    being observed survives and is refreshed (never expires)."""
    stale = _old_stamp(SESSION_EPOCH_TTL_DAYS + 1)
    store = _store(tmp_path)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "worlds": {
                    "W_active": _entry("R", session_key_for("W_active", "R"), stale),
                    "W_stale": _entry("R", session_key_for("W_stale", "R"), stale),
                },
            }
        ),
        encoding="utf-8",
    )

    epoch = SessionEpochRegistry(store).observe("W_active", "R")

    assert epoch == session_key_for("W_active", "R")  # reused despite staleness
    worlds = _read_store(tmp_path)["worlds"]
    assert "W_stale" not in worlds
    assert "W_active" in worlds
    assert worlds["W_active"]["last_seen_at"] > stale  # refreshed


def test_prune_removes_stale_entries(tmp_path):
    """``prune`` drops every world older than the TTL and reports the count."""
    now = datetime.now(timezone.utc)
    stale = _entry(
        "R",
        session_key_for("W_old", "R"),
        (now - timedelta(days=SESSION_EPOCH_TTL_DAYS + 1)).isoformat(),
    )
    fresh = _entry(
        "R", session_key_for("W_fresh", "R"), now.isoformat()
    )
    store = _store(tmp_path)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "worlds": {"W_old": stale, "W_fresh": fresh},
            }
        ),
        encoding="utf-8",
    )

    removed = SessionEpochRegistry(store).prune(now=now)

    assert removed == 1
    worlds = _read_store(tmp_path)["worlds"]
    assert "W_old" not in worlds
    assert "W_fresh" in worlds


# -- Persistence --------------------------------------------------------------


def test_store_write_is_atomic_and_versioned(tmp_path):
    """The store is written atomically (no temp leftovers) and carries
    ``schema_version: 1``."""
    registry = _registry(tmp_path)

    registry.observe("W", "R")

    store = _store(tmp_path)
    assert store.is_file()
    assert list(store.parent.glob(".tmp-*")) == []
    assert _read_store(tmp_path)["schema_version"] == SCHEMA_VERSION == 1


def test_corrupt_store_degrades_to_empty_registry(tmp_path):
    """A malformed store never raises: the registry resets and records fresh."""
    store = _store(tmp_path)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("{not valid json", encoding="utf-8")

    epoch = SessionEpochRegistry(store).observe("W", "R")

    assert epoch == session_key_for("W", "R")
    assert _read_store(tmp_path)["worlds"]["W"]["revision"] == "R"


# -- Inert wiring (spec: Session-revision keying is assistant-invisible) ------


def _function_body(text: str, header: str) -> list[str]:
    """Return the header line plus every indented line of a module-level def."""
    lines = text.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith(header))
    body = [lines[start]]
    for line in lines[start + 1 :]:
        if line and not line[0].isspace():
            break
        body.append(line)
    return body


def test_registry_is_exercised_inertly_not_on_the_run_path():
    """The registry is only referenced from the api_server materialization
    helper, never from the ``/v1/runs`` submission path (inert plumbing)."""
    text = _API_SERVER.read_text(encoding="utf-8")
    helper = _function_body(text, "def _materialize_skills(")

    assert any("SkillMaterializer" in line for line in helper)
    assert any("SessionEpochRegistry" in line for line in helper)
    assert any(".observe(" in line for line in helper)
    assert not any("/v1/runs" in line for line in helper)

    total = sum(
        1
        for line in text.splitlines()
        if "SessionEpochRegistry" in line or "session_key_for" in line
    )
    in_helper = sum(
        1
        for line in helper
        if "SessionEpochRegistry" in line or "session_key_for" in line
    )
    assert total == in_helper, "registry references leaked outside the inert helper"
