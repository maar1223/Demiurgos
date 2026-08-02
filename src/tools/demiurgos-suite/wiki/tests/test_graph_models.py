"""
tests/test_graph_models.py — Unit tests for graph_models dataclasses.

Covers: EntityHit, EntityDetail, EngramMatch, LoreConflict, TagResult,
and IdeaLinkResult creation, defaults, and serialization via dataclasses.asdict().
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import asdict
from pathlib import Path

# Ensure the wiki package is importable
_SRC_DIR = Path(__file__).resolve().parent.parent.parent  # demiurgos-suite/
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from wiki.graph_models import (  # noqa: E402
    EngramMatch,
    EntityDetail,
    EntityHit,
    IdeaLinkResult,
    LoreConflict,
    TagResult,
)


# =============================================================================
# Existing dataclasses — EntityHit and EntityDetail
# =============================================================================

class TestEntityHit(unittest.TestCase):
    """EntityHit creation and defaults."""

    def test_minimal_creation(self) -> None:
        """Can create EntityHit with required fields only."""
        hit = EntityHit(
            name="Rhyz", type="Ficha", path="personajes/rhyz.md",
            title="Rhyz", description="Guardian", tags=[], link_count=0,
        )
        self.assertEqual(hit.name, "Rhyz")
        self.assertEqual(hit.score, 0.0)  # default

    def test_full_creation(self) -> None:
        """All fields populated correctly."""
        hit = EntityHit(
            name="Vael", type="Personaje", path="personajes/vael.md",
            title="Vael La Silenciadora", description="Silent assassin",
            tags=["importante", "sigilo"], link_count=5, score=12.5,
        )
        self.assertEqual(hit.name, "Vael")
        self.assertEqual(hit.type, "Personaje")
        self.assertEqual(hit.score, 12.5)
        self.assertEqual(len(hit.tags), 2)

    def test_serialization(self) -> None:
        """dataclasses.asdict() produces correct dict."""
        hit = EntityHit(
            name="Test", type="Ficha", path="p/test.md",
            title="T", description="D", tags=["a"], link_count=1, score=3.0,
        )
        d = asdict(hit)
        self.assertEqual(d["name"], "Test")
        self.assertEqual(d["score"], 3.0)
        self.assertEqual(d["tags"], ["a"])


class TestEntityDetail(unittest.TestCase):
    """EntityDetail creation and defaults."""

    def test_minimal_creation(self) -> None:
        """Can create EntityDetail with required fields."""
        detail = EntityDetail(
            name="Rhyz", type="Ficha", path="personajes/rhyz.md",
            title="Rhyz", description="", tags=[], content="Base content.",
        )
        self.assertEqual(detail.name, "Rhyz")
        self.assertEqual(detail.forward_links, [])
        self.assertEqual(detail.backlinks, [])
        self.assertEqual(detail.word_count, 0)

    def test_forward_links_preserved(self) -> None:
        """forward_links and backlinks are stored correctly."""
        detail = EntityDetail(
            name="Rhyz", type="Ficha", path="p/r.md",
            title="Rhyz", description="", tags=[], content="Content",
            forward_links=["Vael", "Ekkor"],
            backlinks=["sagas/ascension.md"],
            word_count=2,
        )
        self.assertEqual(detail.forward_links, ["Vael", "Ekkor"])
        self.assertEqual(detail.backlinks, ["sagas/ascension.md"])

    def test_serialization(self) -> None:
        """asdict() preserves all fields."""
        detail = EntityDetail(
            name="R", type="Ficha", path="p/r.md", title="R",
            description="D", tags=["t"], content="C",
            forward_links=["A"], backlinks=["B"],
            relaciones=[{"tipo": "aliado", "objetivo": "Vael"}],
            word_count=1,
        )
        d = asdict(detail)
        self.assertEqual(d["name"], "R")
        self.assertEqual(d["forward_links"], ["A"])
        self.assertEqual(d["backlinks"], ["B"])
        self.assertEqual(d["relaciones"], [{"tipo": "aliado", "objetivo": "Vael"}])


# =============================================================================
# New dataclasses — EngramMatch, LoreConflict, TagResult, IdeaLinkResult
# =============================================================================

class TestEngramMatch(unittest.TestCase):
    """EngramMatch — search result from Engram memory."""

    def test_creation(self) -> None:
        """All fields populated."""
        match = EngramMatch(id=123, title="Test Memory", preview="Preview text")
        self.assertEqual(match.id, 123)
        self.assertEqual(match.title, "Test Memory")
        self.assertEqual(match.preview, "Preview text")

    def test_default_preview(self) -> None:
        """preview defaults to empty string."""
        match = EngramMatch(id=456, title="Minimal")
        self.assertEqual(match.preview, "")

    def test_serialization(self) -> None:
        """asdict() preserves id, title, preview."""
        match = EngramMatch(id=789, title="Mem", preview="P")
        d = asdict(match)
        self.assertEqual(d["id"], 789)
        self.assertEqual(d["title"], "Mem")
        self.assertEqual(d["preview"], "P")

    def test_deserialization_roundtrip(self) -> None:
        """Can roundtrip through dict."""
        match = EngramMatch(id=42, title="Roundtrip", preview="Roundtrip preview")
        d = asdict(match)
        restored = EngramMatch(**d)
        self.assertEqual(restored.id, match.id)
        self.assertEqual(restored.title, match.title)
        self.assertEqual(restored.preview, match.preview)


class TestLoreConflict(unittest.TestCase):
    """LoreConflict — contradiction between entity and Engram."""

    def test_creation(self) -> None:
        """All fields populated."""
        conflict = LoreConflict(
            claim_a="1450", source_a="personajes/rhyz.md",
            claim_b="1452", source_b="engram#1234",
            conflict_type="date_contradiction",
        )
        self.assertEqual(conflict.claim_a, "1450")
        self.assertEqual(conflict.claim_b, "1452")
        self.assertEqual(conflict.conflict_type, "date_contradiction")

    def test_default_conflict_type(self) -> None:
        """conflict_type defaults to 'unknown'."""
        conflict = LoreConflict(
            claim_a="A", source_a="s1",
            claim_b="B", source_b="s2",
        )
        self.assertEqual(conflict.conflict_type, "unknown")

    def test_serialization(self) -> None:
        """asdict() preserves all five fields."""
        conflict = LoreConflict(
            claim_a="dead", source_a="entity.md",
            claim_b="alive", source_b="engram#55",
            conflict_type="status_contradiction",
        )
        d = asdict(conflict)
        self.assertEqual(d["claim_a"], "dead")
        self.assertEqual(d["source_a"], "entity.md")
        self.assertEqual(d["claim_b"], "alive")
        self.assertEqual(d["source_b"], "engram#55")
        self.assertEqual(d["conflict_type"], "status_contradiction")

    def test_roundtrip(self) -> None:
        """Can roundtrip through dict."""
        conflict = LoreConflict(
            claim_a="X", source_a="A", claim_b="Y", source_b="B",
            conflict_type="name_mismatch",
        )
        restored = LoreConflict(**asdict(conflict))
        self.assertEqual(restored.conflict_type, "name_mismatch")
        self.assertEqual(restored.claim_a, "X")


class TestTagResult(unittest.TestCase):
    """TagResult — auto-tagging output."""

    def test_creation(self) -> None:
        """Entities and themes populated."""
        result = TagResult(
            entities=["Rhyz El Resonante", "Vael La Silenciadora"],
            themes=["entrenamiento", "batalla"],
        )
        self.assertEqual(len(result.entities), 2)
        self.assertIn("Rhyz El Resonante", result.entities)
        self.assertEqual(len(result.themes), 2)
        self.assertIn("batalla", result.themes)

    def test_defaults(self) -> None:
        """Both lists default to empty."""
        result = TagResult()
        self.assertEqual(result.entities, [])
        self.assertEqual(result.themes, [])

    def test_serialization(self) -> None:
        """asdict() roundtrip preserves data."""
        result = TagResult(entities=["E1"], themes=["t1"])
        d = asdict(result)
        self.assertEqual(d["entities"], ["E1"])
        self.assertEqual(d["themes"], ["t1"])

    def test_roundtrip(self) -> None:
        """Can roundtrip through dict."""
        result = TagResult(entities=["X", "Y"], themes=["a", "b"])
        restored = TagResult(**asdict(result))
        self.assertEqual(restored.entities, ["X", "Y"])
        self.assertEqual(restored.themes, ["a", "b"])


class TestIdeaLinkResult(unittest.TestCase):
    """IdeaLinkResult — BM25 match from Idea Bank."""

    def test_creation(self) -> None:
        """All fields populated."""
        result = IdeaLinkResult(
            slug="2026-07-30-sistema-educativo",
            score=0.85,
            preview_80chars="Tengo una idea de un sistema educativo...",
        )
        self.assertEqual(result.slug, "2026-07-30-sistema-educativo")
        self.assertEqual(result.score, 0.85)
        self.assertIn("sistema educativo", result.preview_80chars)

    def test_default_preview(self) -> None:
        """preview_80chars defaults to empty string."""
        result = IdeaLinkResult(slug="test-slug", score=0.5)
        self.assertEqual(result.preview_80chars, "")

    def test_serialization(self) -> None:
        """asdict() preserves slug, score, preview."""
        result = IdeaLinkResult(slug="slug1", score=0.9, preview_80chars="preview")
        d = asdict(result)
        self.assertEqual(d["slug"], "slug1")
        self.assertEqual(d["score"], 0.9)
        self.assertEqual(d["preview_80chars"], "preview")

    def test_roundtrip(self) -> None:
        """Can roundtrip through dict."""
        result = IdeaLinkResult(slug="s", score=0.75, preview_80chars="p")
        restored = IdeaLinkResult(**asdict(result))
        self.assertEqual(restored.slug, "s")
        self.assertEqual(restored.score, 0.75)
        self.assertEqual(restored.preview_80chars, "p")

    def test_float_precision(self) -> None:
        """Score preserves float precision."""
        result = IdeaLinkResult(slug="s", score=0.12345)
        self.assertAlmostEqual(result.score, 0.12345, places=5)


if __name__ == "__main__":
    unittest.main()
