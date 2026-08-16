"""
tests/test_schemas.py — Unit tests for sync-lore dataclasses.

Validates defaults, field constraints, CLOSED entity types,
and Enum behavior.
"""

import sys
import unittest
import tempfile
import hashlib
from pathlib import Path

# HACK: add parent's parent to path so we can import the sync-lore package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Import from the hyphenated package via importlib
import importlib

schemas = importlib.import_module("sync-lore.schemas")
index_builder = importlib.import_module("sync-lore.index_builder")


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


class TestOkfNormalization(unittest.TestCase):
    """OKF v1 normalization: identity, minimums (character first), relations."""

    def test_character_minimums_defined_first(self):
        groups = schemas.OKF_MINIMUM_GROUPS_BY_TYPE["personaje"]
        self.assertGreaterEqual(len(groups), 2)  # identity + desire anchors

    def test_non_okf_returns_none(self):
        self.assertIsNone(schemas.normalize_okf_v1({"title": "X"}))
        self.assertIsNone(schemas.normalize_okf_v1(None))
        self.assertIsNone(schemas.normalize_okf_v1({"type": "   "}))

    def test_character_missing_desire_surfaces_missing_group(self):
        normalized = schemas.normalize_okf_v1(
            {"type": "Personaje", "title": "Anisa"}, body="## Cuerpo\n"
        )
        self.assertIsNotNone(normalized)
        missing = {frozenset(g) for g in normalized.missing_minimum_groups}
        self.assertIn(schemas.MINIMUM_DESIRE_FIELDS, missing)
        self.assertNotIn(schemas.MINIMUM_IDENTITY_FIELDS, missing)

    def test_extracts_body_and_relaciones_wikilinks(self):
        normalized = schemas.normalize_okf_v1(
            {"type": "Personaje", "title": "Anisa", "relaciones": ["[[Bira]] (complementa)"]},
            body="Conoce a [[Bira]] desde siempre.\n",
        )
        self.assertIsNotNone(normalized)
        self.assertEqual(set(normalized.forward_links), {"Bira"})

    def test_normalization_is_pure(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        normalized = schemas.normalize_okf_v1({"type": "Personaje", "title": "X"})
        self.assertIsNotNone(normalized)
        self.assertEqual(list(Path(tmp.name).iterdir()), [])


class TestApprovedCharacterGatedWrite(unittest.TestCase):
    """Approved character writes are digest-gated and never touch the filesystem."""

    CONTENT = "---\ntype: Personaje\ntitle: Aria\ndesire: volar\n---\nCuerpo.\n"

    @staticmethod
    def _digest() -> str:
        return hashlib.sha256(TestApprovedCharacterGatedWrite.CONTENT.encode("utf-8")).hexdigest()

    def test_approval_requires_matching_digest(self):
        with self.assertRaises(ValueError):
            schemas.ApprovedCharacterWrite.approve(
                self.CONTENT, "personajes/aria.md", edit_id="p-1",
                confirmation_token="tok", confirmation_digest="0" * 64,
            )

    def test_approval_requires_personajes_target(self):
        with self.assertRaises(ValueError):
            schemas.ApprovedCharacterWrite.approve(
                self.CONTENT, "lore/aria.md", edit_id="p-1",
                confirmation_token="tok", confirmation_digest=self._digest(),
            )

    def test_valid_approval_creates_payload_without_writing(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        approved = schemas.ApprovedCharacterWrite.approve(
            self.CONTENT, "personajes/aria.md", world="vibrantes",
            edit_id="p-1", confirmation_token="tok",
            confirmation_digest=self._digest(),
        )
        self.assertEqual(approved.target, "personajes/aria.md")
        self.assertEqual(approved.content_digest, self._digest())
        self.assertEqual(approved.world, "vibrantes")
        self.assertEqual(list(Path(tmp.name).iterdir()), [])


class FakeIndex:
    """Minimal graph stub for reconciliation idempotency tests."""

    def __init__(self, dirty: bool = False, visible: bool = True, fail: bool = False):
        self.dirty = dirty
        self.visible = visible
        self.fail = fail
        self.builds = 0

    def build(self, mundo: str) -> int:
        self.builds += 1
        if self.fail:
            raise RuntimeError("index outage")
        self.dirty = False
        return 1

    def get_entity(self, path: str):
        return {"path": path} if self.visible else None


class TestApprovedCharacterGraphReconcile(unittest.TestCase):
    """Reconciling an approved character against the graph is idempotent and gated."""

    CONTENT = "---\ntype: Personaje\ntitle: Aria\ndesire: volar\n---\nCuerpo.\n"

    @staticmethod
    def _digest() -> str:
        return hashlib.sha256(TestApprovedCharacterGraphReconcile.CONTENT.encode("utf-8")).hexdigest()

    def _coordinator(self, tmpdir, index):
        target = Path(tmpdir) / "vibrantes" / "personajes" / "aria.md"
        target.parent.mkdir(parents=True)
        target.write_text(self.CONTENT, encoding="utf-8")
        return index_builder.ApprovedCharacterReconciler(Path(tmpdir), lambda mundo: index)

    def test_reconcile_is_idempotent(self):
        index = FakeIndex()
        with tempfile.TemporaryDirectory() as tmpdir:
            reconciler = self._coordinator(tmpdir, index)
            approved = schemas.ApprovedCharacterWrite.approve(
                self.CONTENT, "personajes/aria.md", world="vibrantes",
                edit_id="p-1", confirmation_token="tok",
                confirmation_digest=self._digest(),
            )
            first = reconciler.reconcile(approved)
            second = reconciler.reconcile(approved)
        self.assertEqual(first.index_status, "indexed")
        self.assertEqual(second.index_status, "indexed")
        self.assertEqual(index.builds, 1, "reconciliation must not duplicate builds")

    def test_reconcile_fails_closed_on_digest_mismatch(self):
        index = FakeIndex()
        with tempfile.TemporaryDirectory() as tmpdir:
            reconciler = self._coordinator(tmpdir, index)
            approved = schemas.ApprovedCharacterWrite(
                content="---\ntype: Personaje\n---\n", target="personajes/aria.md",
                world="vibrantes", content_digest="0" * 64,
            )
            result = reconciler.reconcile(approved)
        self.assertNotEqual(result.index_status, "indexed")
        self.assertTrue(result.retryable is False)


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
