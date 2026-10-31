"""Unit tests for the world-local sweep state (P3)."""

from __future__ import annotations

import json
from pathlib import Path

from relation_state import (
    SweepState,
    load_state,
    mark_swept,
    mute,
    state_path,
    unmute,
)


def test_missing_state_is_empty(tmp_path: Path) -> None:
    state = load_state(tmp_path / "world")

    assert state.swept == {}
    assert state.muted == set()
    assert state.last_sweep_at == ""


def test_mute_and_unmute_are_idempotent(tmp_path: Path) -> None:
    world = tmp_path / "world"

    assert mute(world, "lore/alpha.md") is True
    assert mute(world, "lore/alpha.md") is False
    assert load_state(world).muted == {"lore/alpha.md"}

    assert unmute(world, "lore/alpha.md") is True
    assert unmute(world, "lore/alpha.md") is False
    assert load_state(world).muted == set()


def test_mark_swept_records_digest_and_timestamp(tmp_path: Path) -> None:
    world = tmp_path / "world"

    assert mark_swept(world, "lore/alpha.md", "abc", at="2026-10-31T20:00:00") is True

    state = load_state(world)
    assert state.swept == {"lore/alpha.md": "abc"}
    assert state.last_sweep_at == "2026-10-31T20:00:00"


def test_mark_swept_is_idempotent_for_the_same_digest(tmp_path: Path) -> None:
    world = tmp_path / "world"
    mark_swept(world, "lore/alpha.md", "abc", at="t1")

    assert mark_swept(world, "lore/alpha.md", "abc") is False
    assert mark_swept(world, "lore/alpha.md", "abc", at="t1") is False
    assert mark_swept(world, "lore/alpha.md", "def") is True


def test_file_is_sorted(tmp_path: Path) -> None:
    world = tmp_path / "world"
    mute(world, "lore/zeta.md")
    mute(world, "lore/alpha.md")
    mark_swept(world, "lore/beta.md", "d2")
    mark_swept(world, "lore/alpha.md", "d1")

    payload = json.loads(state_path(world).read_text(encoding="utf-8"))

    assert payload["muted"] == ["lore/alpha.md", "lore/zeta.md"]
    assert list(payload["swept"]) == ["lore/alpha.md", "lore/beta.md"]


def test_corrupt_state_is_ignored_and_repaired(tmp_path: Path) -> None:
    world = tmp_path / "world"
    path = state_path(world)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert load_state(world) == SweepState()
    assert mute(world, "lore/alpha.md") is True
    assert load_state(world).muted == {"lore/alpha.md"}
