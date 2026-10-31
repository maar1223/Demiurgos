"""Unit tests for the world-local rejection memory (P2)."""

from __future__ import annotations

import json
from pathlib import Path

from relation_rejections import (
    clear_rejection,
    load_rejected,
    record_rejection,
    store_path,
)


def test_record_then_load_roundtrip(tmp_path: Path) -> None:
    world = tmp_path / "world"

    assert record_rejection(world, "lore::alpha", "lore::beta") is True

    assert load_rejected(world) == {("lore::alpha", "lore::beta")}
    assert store_path(world) == world / ".relations" / "rejected.json"


def test_record_is_idempotent(tmp_path: Path) -> None:
    world = tmp_path / "world"

    assert record_rejection(world, "lore::alpha", "lore::beta") is True
    assert record_rejection(world, "lore::alpha", "lore::beta") is False

    assert load_rejected(world) == {("lore::alpha", "lore::beta")}


def test_clear_removes_only_that_pair(tmp_path: Path) -> None:
    world = tmp_path / "world"
    record_rejection(world, "lore::alpha", "lore::beta")
    record_rejection(world, "lore::alpha", "lore::gamma")

    assert clear_rejection(world, "lore::alpha", "lore::beta") is True

    assert load_rejected(world) == {("lore::alpha", "lore::gamma")}
    assert clear_rejection(world, "lore::alpha", "lore::beta") is False


def test_file_is_sorted_and_deduped(tmp_path: Path) -> None:
    world = tmp_path / "world"
    for target in ("lore::c", "lore::a", "lore::b", "lore::a"):
        record_rejection(world, "lore::alpha", target)

    payload = json.loads(store_path(world).read_text(encoding="utf-8"))

    assert payload == {
        "version": 1,
        "rejected": [
            ["lore::alpha", "lore::a"],
            ["lore::alpha", "lore::b"],
            ["lore::alpha", "lore::c"],
        ],
    }


def test_missing_store_is_empty(tmp_path: Path) -> None:
    assert load_rejected(tmp_path / "nope") == set()


def test_corrupt_store_is_ignored(tmp_path: Path) -> None:
    world = tmp_path / "world"
    path = store_path(world)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert load_rejected(world) == set()
    # A later write repairs the store instead of failing.
    assert record_rejection(world, "lore::alpha", "lore::beta") is True
    assert load_rejected(world) == {("lore::alpha", "lore::beta")}


def test_malformed_entries_are_dropped(tmp_path: Path) -> None:
    world = tmp_path / "world"
    path = store_path(world)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "rejected": [
                    ["lore::a", "lore::b"],
                    ["only-one"],
                    ["", "lore::c"],
                    [1, 2],
                    "nope",
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_rejected(world) == {("lore::a", "lore::b")}
