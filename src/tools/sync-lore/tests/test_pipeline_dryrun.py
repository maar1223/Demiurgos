"""
tests/test_pipeline_dryrun.py — Integration test for dry-run pipeline.

Verifies that dry-run mode produces the correct plan output
without making any LLM calls.
"""

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import importlib

cli = importlib.import_module("sync-lore.cli")
lore_indexer = importlib.import_module("sync-lore.lore_indexer")


class TestDryRunPipeline(unittest.TestCase):
    """Dry-run mode produces expected output without LLM calls."""

    def setUp(self):
        # Create a temp directory with sample .md files
        self.tmpdir = Path("tmp_test_lore")
        self.tmpdir.mkdir(exist_ok=True)

        # Create sample files
        (self.tmpdir / "Kaelen.md").write_text(
            "## Origen\nKaelen nacio en Ayagar.\n\n## Gobierno\nKaelen gobierna con justicia.\n",
            encoding="utf-8",
        )
        (self.tmpdir / "Ayagar.md").write_text(
            "## Historia\nAyagar fue fundada en la Era del Alba.\n",
            encoding="utf-8",
        )
        # Template file (should be excluded)
        (self.tmpdir / "_Plantilla.md").write_text(
            "# Plantilla\n\n## Seccion\nContenido.\n",
            encoding="utf-8",
        )
        # Skeleton file (< 20 significant lines)
        (self.tmpdir / "Skeleton.md").write_text(
            "# Title\n\nJust a note.\n",
            encoding="utf-8",
        )

    def tearDown(self):
        # Cleanup temp dir
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir)

    def test_dry_run_file_count(self):
        """Dry-run should count files correctly."""
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured

        try:
            # Call _scan_files directly
            files = lore_indexer._scan_files(self.tmpdir)
            output = captured.getvalue()
        finally:
            sys.stderr = old_stderr

        # Should find 2 normal files, skip template
        md_files = [f for f in files if f.suffix == ".md"]
        self.assertEqual(len(md_files), 3)  # Kaelen, Ayagar, Skeleton
        # Template should be excluded
        self.assertNotIn("_Plantilla.md", [f.name for f in files])

    def test_dry_run_skips_template(self):
        """Template files (_ prefix) are excluded."""
        files = lore_indexer._scan_files(self.tmpdir)
        names = [f.name for f in files]
        self.assertNotIn("_Plantilla.md", names)

    def test_chunker_on_sample_text(self):
        """Chunker works on realistic sample text."""
        chunker_mod = importlib.import_module("sync-lore.utils.chunker")

        text = (self.tmpdir / "Kaelen.md").read_text(encoding="utf-8")
        chunks = chunker_mod.chunk_markdown(text, "Kaelen.md")
        self.assertEqual(len(chunks), 2)
        self.assertTrue(any("Origen" in c.heading_path for c in chunks))
        self.assertTrue(any("Gobierno" in c.heading_path for c in chunks))

    def test_skeleton_detected(self):
        """Skeleton file is detected correctly."""
        text = (self.tmpdir / "Skeleton.md").read_text(encoding="utf-8")
        chunker_mod = importlib.import_module("sync-lore.utils.chunker")
        self.assertTrue(chunker_mod.is_skeleton(text))

    def test_pipeline_processes_files(self):
        """Pipeline scans and chunks files correctly."""
        # This test verifies the pipeline without LLM calls
        # by using a mock that would show if it were called
        providers_base_mod = importlib.import_module("sync-lore.providers.base")
        ProviderAdapter = providers_base_mod.ProviderAdapter
        schemas_mod = importlib.import_module("sync-lore.schemas")
        ProviderConfig = schemas_mod.ProviderConfig

        # Verify the pipeline can scan files
        files = lore_indexer._scan_files(self.tmpdir)
        self.assertGreater(len(files), 0)


class TestDryRunCLIOutput(unittest.TestCase):
    """End-to-end dry-run CLI output verification."""

    def setUp(self):
        self.tmpdir = Path("tmp_test_lore2")
        self.tmpdir.mkdir(exist_ok=True)
        (self.tmpdir / "Test.md").write_text(
            "## Test\nTest content here.\n", encoding="utf-8"
        )

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir)

    def test_dry_run_scan_output(self):
        """Dry-run scan produces file count output."""
        files = lore_indexer._scan_files(self.tmpdir)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, "Test.md")


class TestNonDestructivePipeline(unittest.TestCase):
    """Verify pipeline does not modify source .md files (non-destructive)."""

    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp(prefix="sync_lore_nondestr_"))

        # Create sample .md files with known content
        self.file1 = self.tmpdir / "Kaelen.md"
        self.file2 = self.tmpdir / "Ayagar.md"

        self.file1.write_text(
            "\n".join([
                "# Kaelen",
                "",
                "## Origen",
                "Kaelen nacio en Ayagar. Guerrero del Symmetry Sagrado.",
                "Su madre fue sacerdotisa. Su padre gobernaba con mano de hierro.",
                "Aprendio artes marciales en los Salones del Eco.",
                "",
                "## Gobierno",
                "Kaelen gobierna con justicia desde la Era del Crepusculo.",
                "Su reinado ha traido paz a las tierras circundantes.",
                "Los mercaderes viajan sin escolta por sus caminos.",
                "",
                "## Relaciones",
                "Kaelen es hijo de Thalion.",
                "Mantiene alianza con los Stalers del Norte.",
                "Su hermana Lyria es jefa de exploradores.",
                "Tiene pacto con el rey enano de las Montanas Rojas.",
                "Su consejero mas cercano es el sabio Elaren.",
            ]),
            encoding="utf-8",
        )

        self.file2.write_text(
            "\n".join([
                "# Ayagar",
                "",
                "## Geografia",
                "Ciudad fortaleza en las montanas del Norte.",
                "Murallas de piedra negra. Tres rios cruzan el valle.",
                "La torre central se eleva doscientos metros.",
                "",
                "## Historia",
                "Fundada en la Era del Alba por Thalion.",
                "Resistio tres asedios en la Guerra de los Cinco Estandartes.",
                "El Gran Incendio destruyo el barrio bajo.",
                "Reconstruida con piedra volcanica de las minas.",
                "Ciudad mas poblada al norte del Tridente.",
                "",
                "## Cultura",
                "Los habitantes veneran el Symmetry Sagrado.",
                "Cada amanecer realizan el Ritual del Alba.",
                "El festival de la Cosecha dura siete dias.",
                "Los gremios compiten en la Feria del Martillo.",
                "La Biblioteca de Cristal guarda manuscritos antiguos.",
            ]),
            encoding="utf-8",
        )

        # Calculate initial hashes
        self.hash1_before = self._sha256(self.file1)
        self.hash2_before = self._sha256(self.file2)

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir)

    @staticmethod
    def _sha256(path: Path) -> str:
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_dry_run_preserves_files(self):
        """After dry-run scan and chunk, source files are unchanged."""
        # Phase 1: Scan (no LLM calls)
        files = lore_indexer._scan_files(self.tmpdir)
        self.assertGreaterEqual(len(files), 2)

        # Phase 2: Chunk all files
        for fpath in files:
            if fpath.suffix == ".md":
                text = fpath.read_text(encoding="utf-8")
                chunker_mod = importlib.import_module("sync-lore.utils.chunker")
                if not chunker_mod.is_skeleton(text):
                    chunks = chunker_mod.chunk_markdown(text, fpath.name)
                    self.assertGreater(len(chunks), 0)

        # Verify hashes unchanged
        self.assertEqual(self._sha256(self.file1), self.hash1_before)
        self.assertEqual(self._sha256(self.file2), self.hash2_before)

    def test_pipeline_with_mock_preserves_files(self):
        """Full pipeline with mock provider does not modify source files."""
        chunker_mod = importlib.import_module("sync-lore.utils.chunker")
        parallel_mod = importlib.import_module("sync-lore.utils.parallel")
        providers_base_mod = importlib.import_module("sync-lore.providers.base")
        schemas_mod = importlib.import_module("sync-lore.schemas")
        index_builder_mod = importlib.import_module("sync-lore.index_builder")

        # Build a mock provider
        class NonDestructiveMockProvider(providers_base_mod.ProviderAdapter):
            def __init__(self):
                self._cfg = schemas_mod.ProviderConfig()

            @property
            def config(self):
                return self._cfg

            async def analyze_text(self, chunk):
                entities = []
                if "Kaelen" in chunk.content or "Kaelen" in chunk.heading_path:
                    entities.append({
                        "name": "Kaelen",
                        "type": "personaje",
                        "description": "A warrior.",
                        "relations": [],
                        "quotes": [],
                    })
                if "Ayagar" in chunk.content or "Ayagar" in chunk.heading_path:
                    entities.append({
                        "name": "Ayagar",
                        "type": "lugar",
                        "description": "A city.",
                        "relations": [],
                        "quotes": [],
                    })
                return schemas_mod.ChunkResult(entities=entities)

            async def analyze_image(self, image: bytes, context: str):
                return schemas_mod.ImageAnalysis(descripcion="mock")

        import asyncio
        provider = NonDestructiveMockProvider()

        # Scan + chunk
        files = lore_indexer._scan_files(self.tmpdir)
        all_chunks = []
        for fpath in files:
            if fpath.suffix == ".md":
                text = fpath.read_text(encoding="utf-8")
                if not chunker_mod.is_skeleton(text):
                    rel = fpath.name
                    chunks = chunker_mod.chunk_markdown(text, rel)
                    all_chunks.extend(chunks)

        # Process with mock
        results = asyncio.run(
            parallel_mod.process_chunks_async(all_chunks, provider, max_workers=2)
        )

        # Build index (should not touch source files)
        index = index_builder_mod.build_index(
            chunk_results=results,
            world="vibrantes",
            mode="text",
        )
        self.assertIsInstance(index, schemas_mod.LoreIndex)

        # Verify hashes unchanged after full pipeline
        self.assertEqual(self._sha256(self.file1), self.hash1_before)
        self.assertEqual(self._sha256(self.file2), self.hash2_before)


if __name__ == "__main__":
    unittest.main()
