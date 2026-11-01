"""Unit tests for the curated-pair memory."""

from __future__ import annotations

import json
from pathlib import Path

from relation_curation import (
    load_curated,
    pin,
    store_path,
    unpin,
)


def test_pin_then_load_roundtrip(tmp_path: Path) -> None:
    world = tmp_path / "world"

    assert pin(world, "lore::alpha", "lore::beta") is True

    assert load_curated(world) == {("lore::alpha", "lore::beta")}
    assert store_path(world) == world / ".relations" / "curated.json"


def test_pin_is_idempotent(tmp_path: Path) -> None:
    world = tmp_path / "world"

    assert pin(world, "lore::alpha", "lore::beta") is True
    assert pin(world, "lore::alpha", "lore::beta") is False
    assert load_curated(world) == {("lore::alpha", "lore::beta")}


def test_unpin_removes_only_that_pair(tmp_path: Path) -> None:
    world = tmp_path / "world"
    pin(world, "lore::alpha", "lore::beta")
    pin(world, "lore::alpha", "lore::gamma")

    assert unpin(world, "lore::alpha", "lore::beta") is True
    assert unpin(world, "lore::alpha", "lore::beta") is False

    assert load_curated(world) == {("lore::alpha", "lore::gamma")}


def test_file_is_sorted_and_deduped(tmp_path: Path) -> None:
    world = tmp_path / "world"
    for target in ("lore::c", "lore::a", "lore::b", "lore::a"):
        pin(world, "lore::alpha", target)

    payload = json.loads(store_path(world).read_text(encoding="utf-8"))

    assert payload["curated"] == [
        ["lore::alpha", "lore::a"],
        ["lore::alpha", "lore::b"],
        ["lore::alpha", "lore::c"],
    ]


def test_corrupt_store_is_ignored_and_repaired(tmp_path: Path) -> None:
    world = tmp_path / "world"
    path = store_path(world)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert load_curated(world) == set()
    assert pin(world, "lore::alpha", "lore::beta") is True
    assert load_curated(world) == {("lore::alpha", "lore::beta")}
