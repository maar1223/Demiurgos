"""
tests/test_schemas.py — Unit tests for sync-lore dataclasses.

Validates defaults, field constraints, CLOSED entity types,
and Enum behavior.
"""

import sys
import unittest
from pathlib import Path

# HACK: add parent's parent to path so we can import the sync-lore package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Import from the hyphenated package via importlib
import importlib

schemas = importlib.import_module("sync-lore.schemas")


class TestProviderConfig(unittest.TestCase):
    """ProviderConfig defaults and field types."""

    def test_defaults(self):
        cfg = schemas.ProviderConfig()
        self.assertEqual(cfg.provider, "opencode-go")
        self.assertEqual(cfg.endpoint, "https://opencode.ai/zen/go/v1")
        self.assertEqual(cfg.model, "deepseek-v4-flash")
        self.assertEqual(cfg.timeout, 60)
        self.assertEqual(cfg.api_key_env, "OPENCODE_GO_API_KEY")

    def test_custom_values(self):
        cfg = schemas.ProviderConfig(
            provider="openai",
            endpoint="https://api.openai.com/v1",
            model="gpt-4o",
            timeout=120,
            api_key_env="OPENAI_API_KEY",
        )
        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.timeout, 120)


class TestChunk(unittest.TestCase):
    """Chunk dataclass and full_context()."""

    def test_defaults(self):
        c = schemas.Chunk(
            id="abc-123",
            source_file="test.md",
            heading_path="## Test",
            content="Hello world",
            token_count=2,
        )
        self.assertEqual(c.id, "abc-123")
        self.assertEqual(c.source_file, "test.md")
        self.assertEqual(c.heading_path, "## Test")
        self.assertEqual(c.content, "Hello world")
        self.assertEqual(c.token_count, 2)
        self.assertEqual(c.images, [])

    def test_full_context(self):
        c = schemas.Chunk(
            id="abc",
            source_file="test.md",
            heading_path="## Raiders > ### Origen",
            content="Some lore text.",
            token_count=3,
        )
        ctx = c.full_context()
        self.assertIn("## Raiders > ### Origen", ctx)
        self.assertIn("Some lore text.", ctx)


class TestChunkResult(unittest.TestCase):
    """ChunkResult default empty lists."""

    def test_empty_defaults(self):
        cr = schemas.ChunkResult()
        self.assertEqual(cr.entities, [])
        self.assertEqual(cr.terms, [])
        self.assertEqual(cr.contradictions, [])
        self.assertIsNone(cr.raw_response)

    def test_with_data(self):
        cr = schemas.ChunkResult(
            entities=[{"name": "Kaelen"}],
            terms=[{"term": "Staler"}],
            contradictions=[{"entity": "Kaelen", "claim": "died"}],
        )
        self.assertEqual(len(cr.entities), 1)
        self.assertEqual(len(cr.terms), 1)
        self.assertEqual(len(cr.contradictions), 1)


class TestEntityType(unittest.TestCase):
    """CLOSED EntityType enum."""

    def test_all_types_present(self):
        expected = {
            "personaje", "criatura", "objeto", "lugar",
            "concepto", "evento", "organizacion", "especie",
        }
        actual = {e.value for e in schemas.EntityType}
        self.assertEqual(actual, expected)

    def test_enum_access(self):
        self.assertEqual(schemas.EntityType.PERSONAJE.value, "personaje")
        self.assertEqual(schemas.EntityType.LUGAR.value, "lugar")


class TestStalTier(unittest.TestCase):
    """Staler immutability tiers."""

    def test_tiers(self):
        self.assertEqual(schemas.StalTier.T1.value, "T1")
        self.assertEqual(schemas.StalTier.T2.value, "T2")
        self.assertEqual(schemas.StalTier.T3.value, "T3")


class TestVeredicto(unittest.TestCase):
    """Image veredict enum."""

    def test_values(self):
        self.assertEqual(schemas.Veredicto.CONFIRMA.value, "confirma")
        self.assertEqual(schemas.Veredicto.CONTRADICE.value, "contradice")
        self.assertEqual(schemas.Veredicto.NO_APLICA.value, "no_aplica")


class TestImageAnalysis(unittest.TestCase):
    """ImageAnalysis defaults."""

    def test_defaults(self):
        ia = schemas.ImageAnalysis()
        self.assertEqual(ia.descripcion, "")
        self.assertEqual(ia.veredicto, "no_aplica")
        self.assertEqual(ia.tags, [])
        self.assertEqual(ia.analisis, "")

    def test_custom(self):
        ia = schemas.ImageAnalysis(
            descripcion="A dark castle",
            veredicto="confirma",
            tags=["castle", "dark"],
            analisis="Matches the text.",
        )
        self.assertEqual(ia.descripcion, "A dark castle")
        self.assertEqual(ia.veredicto, "confirma")
        self.assertIn("castle", ia.tags)


class TestLoreEntity(unittest.TestCase):
    """LoreEntity with StalTier immutability derivation."""

    def test_immutable_derived(self):
        e = schemas.LoreEntity(
            id="abc",
            name="Kaelen",
            type="personaje",
            stal_tier="T1",
        )
        self.assertTrue(e.immutable)

    def test_mutable_by_default(self):
        e = schemas.LoreEntity(
            id="abc",
            name="Kaelen",
            type="personaje",
        )
        self.assertFalse(e.immutable)

    def test_t2_not_immutable(self):
        e = schemas.LoreEntity(
            id="abc",
            name="Kaelen",
            type="personaje",
            stal_tier="T2",
        )
        self.assertFalse(e.immutable)

    def test_full_entity(self):
        e = schemas.LoreEntity(
            id="uuid-1",
            name="Kaelen",
            type="personaje",
            world="vibrantes",
            source_file="Ayagars/Kaelen.md",
            chunk_ref="Ayagars/Kaelen.md##Origen",
            description="A warrior of the Sacred Symmetry.",
            relations=[{"target": "Ayagar", "type": "gobierna", "strength": 1.0}],
            terms=["Sacred Symmetry"],
            stal_tier="T1",
            quotes=["Kaelen raised his blade."],
            contradictions=["contra-1"],
        )
        self.assertEqual(e.name, "Kaelen")
        self.assertTrue(e.immutable)
        self.assertEqual(len(e.relations), 1)
        self.assertEqual(len(e.quotes), 1)


class TestContradictionEntry(unittest.TestCase):
    """ContradictionEntry structure."""

    def test_defaults(self):
        c = schemas.ContradictionEntry(
            id="abc",
            entity="Kaelen",
        )
        self.assertEqual(c.entity_id, "")
        self.assertEqual(c.chunk_a, {"file": "", "heading": "", "claim": ""})
        self.assertFalse(c.stal_conflict)

    def test_stal_conflict(self):
        c = schemas.ContradictionEntry(
            id="abc",
            entity="Kaelen",
            stal_conflict=True,
        )
        self.assertTrue(c.stal_conflict)


class TestLoreIndex(unittest.TestCase):
    """LoreIndex top-level container."""

    def test_empty_index(self):
        index = schemas.LoreIndex()
        self.assertEqual(index.meta.tool, "sync-lore")
        self.assertEqual(index.entities, [])
        self.assertEqual(index.terms, [])
        self.assertEqual(index.images, [])
        self.assertEqual(index.contradictions, [])


class TestImageEntry(unittest.TestCase):
    """ImageEntry with image_bytes not in repr."""

    def test_image_bytes_not_repr(self):
        ie = schemas.ImageEntry(
            id="abc",
            source_file="test.md",
            image_bytes=b"\x89PNG",
        )
        self.assertNotIn("image_bytes", repr(ie))

    def test_full_entry(self):
        ia = schemas.ImageAnalysis(descripcion="test")
        ie = schemas.ImageEntry(
            id="abc",
            source_file="test.md",
            page=1,
            chunk_ref="test.md##Section",
            context_text="Some text",
            filename="img.png",
            image_bytes=b"data",
            analysis=ia,
        )
        self.assertEqual(ie.page, 1)
        self.assertEqual(ie.filename, "img.png")
        self.assertIsNotNone(ie.analysis)


if __name__ == "__main__":
    unittest.main()
