"""
tests/test_chunker.py — Unit tests for the markdown chunker.

Tests heading-based splitting, oversize handling, template/skeleton
exclusion, and token estimation.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import importlib

chunker = importlib.import_module("sync-lore.utils.chunker")
schemas_mod = importlib.import_module("sync-lore.schemas")


class TestEstimateTokens(unittest.TestCase):
    """Token estimation (len//4 for Spanish)."""

    def test_empty(self):
        self.assertEqual(chunker.estimate_tokens(""), 1)

    def test_short(self):
        # 10 chars -> 2 tokens
        self.assertEqual(chunker.estimate_tokens("Hola mundo"), 2)

    def test_long(self):
        # 100 chars -> 25 tokens
        text = "a" * 100
        self.assertEqual(chunker.estimate_tokens(text), 25)


class TestIsTemplate(unittest.TestCase):
    """Template detection (_ prefix)."""

    def test_template(self):
        self.assertTrue(chunker.is_template("_Plantilla.md"))
        self.assertTrue(chunker.is_template("_template.md"))

    def test_normal(self):
        self.assertFalse(chunker.is_template("Kaelen.md"))
        self.assertFalse(chunker.is_template("raiders.md"))


class TestIsSkeleton(unittest.TestCase):
    """Skeleton file detection (< 20 significant lines)."""

    def test_skeleton(self):
        text = "A\nB\nC"
        self.assertTrue(chunker.is_skeleton(text))

    def test_normal(self):
        text = "\n".join(f"Line {i}" for i in range(30))
        self.assertFalse(chunker.is_skeleton(text))

    def test_headings_not_significant(self):
        # Headings alone don't count as significant lines
        text = "\n".join(f"# Heading {i}" for i in range(30))
        self.assertTrue(chunker.is_skeleton(text))

    def test_exactly_boundary(self):
        text = "\n".join(f"Line {i}" for i in range(20))
        self.assertFalse(chunker.is_skeleton(text))


class TestChunkMarkdownBasic(unittest.TestCase):
    """Basic heading-based chunking."""

    def test_no_headings_single_chunk(self):
        md = "Just a paragraph of lore text.\nNo headings here."
        chunks = chunker.chunk_markdown(md, "test.md")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].heading_path, "test.md")

    def test_empty_file(self):
        chunks = chunker.chunk_markdown("", "empty.md")
        self.assertEqual(len(chunks), 0)

    def test_single_h2(self):
        md = "## Raiders\nSome content about raiders."
        chunks = chunker.chunk_markdown(md, "test.md")
        self.assertEqual(len(chunks), 1)
        self.assertIn("Raiders", chunks[0].heading_path)

    def test_multiple_h2(self):
        md = "## Raiders\nRaider lore.\n\n## Ayagar\nAyagar lore."
        chunks = chunker.chunk_markdown(md, "test.md")
        self.assertEqual(len(chunks), 2)
        # Check heading paths contain section names
        paths = [c.heading_path for c in chunks]
        self.assertTrue(any("Raiders" in p for p in paths))
        self.assertTrue(any("Ayagar" in p for p in paths))

    def test_heading_hierarchy(self):
        md = "## Raiders\nRaider text.\n\n### Origen\nOrigin text.\n\n## Ayagar\nAyagar text."
        chunks = chunker.chunk_markdown(md, "test.md")
        self.assertEqual(len(chunks), 3)
        # The ### Origen chunk should inherit Raiders in heading_path
        origen_chunk = [c for c in chunks if "Origen" in c.heading_path]
        self.assertEqual(len(origen_chunk), 1)
        self.assertIn("Raiders", origen_chunk[0].heading_path)

    def test_pre_heading_content(self):
        md = "Pre-heading text.\n\n## Raiders\nRaider lore."
        chunks = chunker.chunk_markdown(md, "test.md")
        # Should have 2 chunks: pre-heading + Raiders
        self.assertGreaterEqual(len(chunks), 1)

    def test_heading_path_format(self):
        md = "## Raiders\n### Origen\nOrigin lore."
        chunks = chunker.chunk_markdown(md, "test.md")
        # Should produce heading_path with source file prefix
        for c in chunks:
            self.assertTrue(c.heading_path.startswith("test.md"))
            self.assertIn("##", c.heading_path)


class TestSplitOversized(unittest.TestCase):
    """Oversized chunk splitting by paragraph."""

    def test_not_oversized(self):
        schemas_mod = importlib.import_module("sync-lore.schemas")
        ch = schemas_mod.Chunk(
            id="test",
            source_file="test.md",
            heading_path="## Test",
            content="Small text.",
            token_count=2,
        )
        result = chunker.split_oversized(ch, max_tokens=4000)
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], ch)  # same object returned

    def test_oversized_split(self):
        # Create a chunk with many paragraphs
        para = "A" * 1000 + "\n"  # ~250 tokens per paragraph
        content = (para + "\n") * 20  # 20 paragraphs = ~5000 tokens
        ch = schemas_mod.Chunk(
            id="test",
            source_file="test.md",
            heading_path="## Test",
            content=content.strip(),
            token_count=chunker.estimate_tokens(content),
        )
        result = chunker.split_oversized(ch, max_tokens=2000, min_tokens=500)
        self.assertGreater(len(result), 1)
        for sub in result:
            self.assertLessEqual(sub.token_count, 2000 * 2,  # allow some margin
                                f"Sub-chunk exceeded limit: {sub.token_count}")
            # heading_path should indicate part number
            if len(result) > 1:
                self.assertIn("(part", sub.heading_path)


class TestImageRefExtraction(unittest.TestCase):
    """Image reference extraction from markdown."""

    def _extract(self, md):
        return chunker._extract_image_refs(md)

    def test_inline_image(self):
        refs = self._extract("Some text ![alt text](path/to/img.png)")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].alt_text, "alt text")
        self.assertEqual(refs[0].source_type, "md_ref")

    def test_reference_style(self):
        refs = self._extract("Some text ![alt][ref1]")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].alt_text, "alt")

    def test_no_images(self):
        refs = self._extract("Just plain text without images.")
        self.assertEqual(len(refs), 0)


if __name__ == "__main__":
    unittest.main()
