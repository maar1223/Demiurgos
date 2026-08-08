"""Shared fixtures: path bootstrap, malformed Idea, tree snapshot guard."""

import sys
from pathlib import Path

import pytest

SRC_TOOLS = Path(__file__).resolve().parents[2]
if str(SRC_TOOLS) not in sys.path:
    sys.path.insert(0, str(SRC_TOOLS))

# Mirrors real drift: numeric id and epoch timestamp violate the schema.
MALFORMED_IDEA = """---
id: 71
title: Portal stones
timestamp: 1779711257
---

Portal stones connect the vaults.
"""


@pytest.fixture
def malformed_idea_file(tmp_path):
    path = tmp_path / "portal-stones.md"
    path.write_text(MALFORMED_IDEA, encoding="utf-8")
    return path


@pytest.fixture
def tree_snapshot():
    def snap(root: Path):
        return sorted((p.relative_to(root).as_posix(), p.stat().st_size,
                       p.stat().st_mtime_ns) for p in root.rglob("*"))

    return snap
