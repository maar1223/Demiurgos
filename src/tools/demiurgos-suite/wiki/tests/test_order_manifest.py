# -*- coding: utf-8 -*-
"""Unit tests for the per-section order manifest helpers (order_manifest.py)."""

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from order_manifest import (  # noqa: E402
    append_order,
    read_order,
    remove_from_order,
    replace_prefix_order,
    write_order,
)


def test_read_order_missing_file(tmp_path: Path):
    assert read_order(tmp_path / "lore") == []


def test_read_order_malformed_json(tmp_path: Path):
    section = tmp_path / "lore"
    section.mkdir()
    (section / "_order.json").write_text("{ not json", encoding="utf-8")
    assert read_order(section) == []


def test_write_order_atomic(tmp_path: Path):
    section = tmp_path / "lore" / "nested"
    write_order(section, ["intro.md", "chapter-1/foundation.md"])
    assert (section / "_order.json").is_file()
    assert read_order(section) == ["intro.md", "chapter-1/foundation.md"]
    # no temp file left behind
    assert not (section / "_order.json.tmp").exists()


def test_append_order_dedupes(tmp_path: Path):
    section = tmp_path / "lore"
    section.mkdir()
    write_order(section, ["a.md", "b.md"])
    append_order(section, ["c.md", "a.md", "c.md"])
    assert read_order(section) == ["a.md", "b.md", "c.md"]


def test_remove_from_order_noop(tmp_path: Path):
    section = tmp_path / "lore"
    section.mkdir()
    write_order(section, ["a.md"])
    remove_from_order(section, "z.md")
    assert read_order(section) == ["a.md"]
    # no manifest at all → still a no-op (no file created)
    empty = tmp_path / "otra"
    empty.mkdir()
    remove_from_order(empty, "a.md")
    assert not (empty / "_order.json").exists()


def test_replace_prefix_order_basic(tmp_path: Path):
    section = tmp_path / "lore"
    section.mkdir()
    write_order(section, ["reptiles/snake.md", "reptiles/lizard.md", "dvin/b1.md"])
    replace_prefix_order(
        section, "reptiles/", ["reptiles/snake_v2.md", "reptiles/lizard_v2.md"]
    )
    assert read_order(section) == ["dvin/b1.md", "reptiles/snake_v2.md", "reptiles/lizard_v2.md"]


def test_replace_prefix_order_empty_prefix(tmp_path: Path):
    section = tmp_path / "lore"
    section.mkdir()
    write_order(section, ["old-1.md", "old-2.md"])
    replace_prefix_order(section, "", ["new-a.md", "new-b.md"])
    assert read_order(section) == ["new-a.md", "new-b.md"]


def test_replace_prefix_order_no_trailing_slash(tmp_path: Path):
    section = tmp_path / "lore"
    section.mkdir()
    write_order(section, ["reptiles/snake.md", "reptiles.md", "reptiles2/x.md", "dvin/c.md"])
    replace_prefix_order(section, "reptiles", ["reptiles/new.md"])
    assert read_order(section) == ["reptiles.md", "reptiles2/x.md", "dvin/c.md", "reptiles/new.md"]
    # a shorter prefix must not match entries under a longer one
    write_order(section, ["reptiles/snake.md", "dvin/c.md"])
    replace_prefix_order(section, "rep", ["rep/new.md"])
    assert read_order(section) == ["reptiles/snake.md", "dvin/c.md", "rep/new.md"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])