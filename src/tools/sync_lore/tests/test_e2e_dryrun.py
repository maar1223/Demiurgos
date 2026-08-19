"""
tests/test_e2e_dryrun.py — End-to-end test with real .md files.

Creates a temporary directory with realistic lore files and
runs the full dry-run pipeline against them.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import importlib

schemas = importlib.import_module("sync-lore.schemas")
chunker = importlib.import_module("sync-lore.utils.chunker")
lore_indexer = importlib.import_module("sync-lore.lore_indexer")
index_builder = importlib.import_module("sync-lore.index_builder")
persistence = importlib.import_module("sync-lore.persistence")
providers_base = importlib.import_module("sync-lore.providers.base")


class MockProvider(providers_base.ProviderAdapter):
    """Full mock provider returning rich entities."""

    def __init__(self):
        self._config = schemas.ProviderConfig()
        self.text_calls = 0

    @property
    def config(self):
        return self._config

    async def analyze_text(self, chunk):
        self.text_calls += 1
        # Return different entities based on chunk content
        entities = []
        terms = []

        if "Kaelen" in chunk.content or "Kaelen" in chunk.heading_path:
            entities.append({
                "name": "Kaelen",
                "type": "personaje",
                "description": "Un guerrero del Symmetry Sagrado.",
                "relations": [{"target": "Ayagar", "type": "gobierna", "strength": 1.0}],
                "quotes": ["Kaelen alzo su espada."],
            })
            terms.append({
                "term": "Symmetry Sagrado",
                "definition": "Orden cosmico que rige Ayagar.",
                "context_snippet": "...el Symmetry Sagrado...",
            })

        if "Ayagar" in chunk.content or "Ayagar" in chunk.heading_path:
            entities.append({
                "name": "Ayagar",
                "type": "lugar",
                "description": "Ciudad fortaleza en las montanas.",
                "relations": [],
                "quotes": ["Ayagar resplandece al amanecer."],
            })

        return providers_base.ChunkResult(
            entities=entities,
            terms=terms,
        )

    async def analyze_image(self, image: bytes, context: str):
        return providers_base.ImageAnalysis(
            descripcion="Mock image",
            veredicto="no_aplica",
            tags=["test"],
        )


class TestE2EDryRun(unittest.TestCase):
    """End-to-end test: create lore files, run pipeline, verify output."""

    def setUp(self):
        # Create temp dir with realistic lore files
        self.tmpdir = Path(tempfile.mkdtemp(prefix="sync_lore_e2e_"))
        self.output_dir = self.tmpdir / "output"

        # File 1: Kaelen character lore (20+ significant lines)
        (self.tmpdir / "Kaelen.md").write_text(
            "\n".join([
                "# Kaelen",
                "",
                "## Origen",
                "Kaelen nacio en las llanuras de Ayagar. Desde joven mostro",
                "una conexion profunda con el Symmetry Sagrado, el orden cosmico",
                "que rige el universo de Vibrantes.",
                "Su madre fue una sacerdotisa del templo antiguo.",
                "Su padre, Thalion, gobernaba Ayagar con mano de hierro.",
                "Kaelen crecio entre los Salones del Eco, aprendiendo las artes",
                "marciales y los secretos del Symmetry.",
                "A los quince anos, derroto a su primer Staler en combate.",
                "A los veinte, fue nombrado Guardian del Umbral Norte.",
                "",
                "## Gobierno",
                "Kaelen gobierna Ayagar con justicia desde la Era del Crepusculo.",
                "Su reinado ha traido paz a las tierras circundantes.",
                "Los mercaderes del Sur viajan sin escolta por sus caminos.",
                "Las cosechas abundan y los gremios prosperan.",
                "El Consejo de Ancianos respalda cada una de sus decisiones.",
                "Ningun ejercito enemigo ha cruzado las murallas en su reinado.",
                "",
                "## Relaciones",
                "Kaelen es hijo de Thalion, el anterior gobernante de Ayagar.",
                "Mantiene una alianza con los Stalers del Norte.",
                "Su hermana Lyria es la jefa de los exploradores del Este.",
                "Tiene un pacto de sangre con el rey enano de las Montanas Rojas.",
                "Su consejero mas cercano es el sabio Elaren, maestro del Symmetry.",
            ]),
            encoding="utf-8",
        )

        # File 2: Ayagar location lore (20+ significant lines)
        (self.tmpdir / "Ayagar.md").write_text(
            "\n".join([
                "# Ayagar",
                "",
                "## Geografia",
                "Ayagar es una ciudad fortaleza ubicada en las montanas del",
                "Norte. Sus murallas de piedra negra han resistido incontables",
                "asedios.",
                "El clima es frio y seco, con vientos que bajan de las cumbres.",
                "Tres rios cruzan el valle donde se asienta la ciudad.",
                "Los puentes de arco son famosos en todo el continente.",
                "La torre central se eleva doscientos metros sobre la plaza.",
                "",
                "## Historia",
                "Fundada en la Era del Alba por Thalion, Ayagar se convirtio",
                "en el centro del poder en el Norte.",
                "Durante la Guerra de los Cinco Estandartes, resistio tres asedios.",
                "El Gran Incendio de la Era Media destruyo el barrio bajo.",
                "Fue reconstruida con piedra volcanica extraida de las minas.",
                "En la actualidad, es la ciudad mas poblada al norte del Tridente.",
                "",
                "## Cultura",
                "Los habitantes de Ayagar veneran el Symmetry Sagrado.",
                "Cada amanecer, los ciudadanos realizan el Ritual del Alba.",
                "El festival de la Cosecha dura siete dias y siete noches.",
                "Los gremios de artesanos compiten en la Feria del Martillo.",
                "La Biblioteca de Cristal guarda manuscritos de todas las eras.",
                "Los jovenes son entrenados en el arte de la forja desde ninos.",
            ]),
            encoding="utf-8",
        )

        # File 3: A contradiction file (20+ significant lines)
        (self.tmpdir / "Contradiccion.md").write_text(
            "\n".join([
                "# Notas Sueltas",
                "",
                "## Muerte",
                "Kaelen murio en la Batalla de los Lamentos en el ano 1200.",
                "Su cuerpo fue encontrado entre las ruinas del templo.",
                "Los testigos afirman que cayo luchando contra tres Stalers.",
                "Fue enterrado con honores en la Cripta de los Heroes.",
                "Su espada, Rompealbas, fue colocada sobre su tumba.",
                "Los juglares aun cantan la Balada de su Ultima Batalla.",
                "",
                "## Leyenda",
                "Algunos dicen que Kaelen aun vaga por las montanas como espiritu.",
                "Los pastores juran haberlo visto en las noches de luna llena.",
                "Una luz azulada recorre los valles donde el combatio.",
                "Los ancianos cuentan que volvera cuando Ayagar lo necesite.",
                "Hay quienes creen que nunca murio, que fue un engano.",
                "Las cronicas del templo mencionan un ritual de resurreccion.",
                "El sabio Elaren nego siempre estas historias como herejia.",
            ]),
            encoding="utf-8",
        )

        # Template file (should be excluded)
        (self.tmpdir / "_Plantilla.md").write_text(
            "# Plantilla de Personaje\n\n## Nombre\n\n## Origen\n",
            encoding="utf-8",
        )

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir)

    def test_scan_excludes_template(self):
        """Template files (_ prefix) are excluded from scan."""
        files = lore_indexer._scan_files(self.tmpdir)
        names = [f.name for f in files]
        self.assertNotIn("_Plantilla.md", names)

    def test_chunk_count(self):
        """Files are correctly chunked by headings."""
        for fname in ["Kaelen.md", "Ayagar.md", "Contradiccion.md"]:
            fpath = self.tmpdir / fname
            text = fpath.read_text(encoding="utf-8")
            chunks = chunker.chunk_markdown(text, fname)
            self.assertGreater(len(chunks), 0, f"{fname} should produce chunks")

        # Kaelen.md has # Kaelen + 3 ## headings + pre-heading content = 4+ chunks
        text = (self.tmpdir / "Kaelen.md").read_text(encoding="utf-8")
        chunks = chunker.chunk_markdown(text, "Kaelen.md")
        self.assertGreaterEqual(len(chunks), 3)  # at least 3 heading-based chunks (plus oversize splits)

    def test_full_pipeline_with_mock(self):
        """Full pipeline with mock provider produces valid index."""
        import asyncio
        parallel = importlib.import_module("sync-lore.utils.parallel")
        process_chunks_async = parallel.process_chunks_async

        provider = MockProvider()

        # Phase 1: Scan + chunk
        files = lore_indexer._scan_files(self.tmpdir)
        self.assertGreaterEqual(len(files), 3)

        all_chunks = []
        for fpath in files:
            if fpath.suffix == ".md":
                text = fpath.read_text(encoding="utf-8")
                if chunker.is_skeleton(text):
                    continue
                rel_path = str(fpath.relative_to(Path.cwd())) if fpath.is_relative_to(Path.cwd()) else fpath.name
                chunks = chunker.chunk_markdown(text, rel_path)
                all_chunks.extend(chunks)

        self.assertGreater(len(all_chunks), 0)

        # Phase 2: Process with mock
        chunk_results = asyncio.run(
            process_chunks_async(all_chunks, provider, max_workers=3)
        )
        self.assertEqual(len(chunk_results), len(all_chunks))

        # Phase 3: Build index
        index = index_builder.build_index(
            chunk_results=chunk_results,
            world="vibrantes",
            mode="text",
        )

        # Phase 4: Verify
        self.assertIsInstance(index, schemas.LoreIndex)
        self.assertGreater(index.meta.entities_extracted, 0)
        self.assertEqual(index.meta.world, "vibrantes")
        self.assertEqual(index.meta.mode, "text")

        # Should have entities for Kaelen and Ayagar
        entity_names = [e.name for e in index.entities]
        self.assertIn("Kaelen", entity_names)
        self.assertIn("Ayagar", entity_names)

        # Should have terms
        self.assertGreater(len(index.terms), 0)
        term_names = [t["term"] for t in index.terms]
        self.assertIn("Symmetry Sagrado", term_names)

        # The legacy lore-index.json file is RETIRED (world-importer IM6):
        # the builder produces an in-memory index for reporting only, and the
        # retired writer fails loudly instead of writing the orphaned file.
        output_path = self.output_dir
        with self.assertRaises(persistence.RetiredLegacyIndexError):
            persistence.write_lore_index(index, output_path)
        self.assertFalse((output_path / "lore-index.json").exists())

    def test_entity_dedup(self):
        """Entities with same name+type+world are merged."""
        cr1 = providers_base.ChunkResult(
            entities=[{
                "name": "Kaelen",
                "type": "personaje",
                "description": "Short desc.",
                "relations": [{"target": "Ayagar", "type": "gobierna", "strength": 0.5}],
                "quotes": ["Quote 1"],
            }],
        )
        cr2 = providers_base.ChunkResult(
            entities=[{
                "name": "Kaelen",
                "type": "personaje",
                "description": "A much longer description of Kaelen the warrior.",
                "relations": [{"target": "Ayagar", "type": "gobierna", "strength": 1.0}],
                "quotes": ["Quote 2"],
            }],
        )

        chunk1 = schemas.Chunk(
            id="c1", source_file="a.md", heading_path="## A", content="A", token_count=1,
        )
        chunk2 = schemas.Chunk(
            id="c2", source_file="b.md", heading_path="## B", content="B", token_count=1,
        )

        index = index_builder.build_index(
            chunk_results=[(chunk1, cr1), (chunk2, cr2)],
            world="vibrantes",
            mode="text",
        )

        # Should have 1 entity (merged)
        self.assertEqual(len(index.entities), 1)
        e = index.entities[0]
        # Description should be the longer one
        self.assertIn("much longer", e.description)
        # Relations should be merged with highest strength
        self.assertEqual(len(e.relations), 1)
        self.assertEqual(e.relations[0]["strength"], 1.0)
        # Quotes should be deduped (both present)
        self.assertEqual(len(e.quotes), 2)

    def test_contradiction_detection(self):
        """Different claims about the same entity are flagged."""
        cr1 = providers_base.ChunkResult(
            entities=[{
                "name": "Kaelen",
                "type": "personaje",
                "description": "Kaelen murio en la Batalla de los Lamentos.",
            }],
        )
        cr2 = providers_base.ChunkResult(
            entities=[{
                "name": "Kaelen",
                "type": "personaje",
                "description": "Kaelen gobierna Ayagar en la Era del Crepusculo.",
            }],
        )

        chunk1 = schemas.Chunk(
            id="c1", source_file="a.md", heading_path="## Muerte", content="A", token_count=1,
        )
        chunk2 = schemas.Chunk(
            id="c2", source_file="b.md", heading_path="## Gobierno", content="B", token_count=1,
        )

        index = index_builder.build_index(
            chunk_results=[(chunk1, cr1), (chunk2, cr2)],
            world="vibrantes",
            mode="text",
        )

        self.assertGreaterEqual(index.meta.contradictions_found, 1)
        self.assertGreater(len(index.contradictions), 0)
        contra = index.contradictions[0]
        self.assertEqual(contra.entity, "Kaelen")

    def test_print_report_no_crash(self):
        """print_report() runs without exceptions."""
        index = schemas.LoreIndex()
        index.meta = schemas.LoreIndexMeta(
            world="vibrantes",
            mode="text",
            chunks_processed=10,
            entities_extracted=5,
            contradictions_found=0,
        )

        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured

        try:
            persistence.print_report(
                index=index,
                output_path=Path("/tmp/lore-index.json"),
                engram_ok=False,
                files_processed=3,
                files_omitted=1,
                chunks_failed=0,
                images_processed=0,
            )
            output = captured.getvalue()
            self.assertIn("sync-lore Report", output)
            self.assertIn("vibrantes", output)
        finally:
            sys.stderr = old_stderr


if __name__ == "__main__":
    unittest.main()
