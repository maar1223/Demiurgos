"""
tests/test_graph_indexer.py — Unit tests for wiki.graph_indexer.EntityGraphIndex.

Covers the read-only contract of update(): the index must never write back
to the corpus (regression: CRLF fichas were rewritten on every update,
growing by one empty line per cycle via the updated_at sync side-effect).
Uses unittest (not pytest) for discovery via ``python -m unittest discover``.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure the wiki package is importable
_SRC_DIR = Path(__file__).resolve().parent.parent.parent  # demiurgos-suite/
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from wiki.graph_indexer import EntityGraphIndex  # noqa: E402


class TestUpdateReadOnly(unittest.TestCase):
    """update() must never mutate the corpus files."""

    def test_update_does_not_rewrite_crlf_ficha(self) -> None:
        """Two update() calls on a CRLF ficha leave the file byte-identical."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path = Path(tmpdir) / "mundos"
            mundo_dir = mundos_path / "testmundo"
            personajes_dir = mundo_dir / "personajes"
            personajes_dir.mkdir(parents=True)

            original = (
                b"---\r\n"
                b"type: Personaje\r\n"
                b"title: X\r\n"
                b"updated_at: 2026-01-01T00:00:00+00:00\r\n"
                b"---\r\n"
                b"# Cuerpo\r\n"
            )
            ficha = personajes_dir / "X.md"
            ficha.write_bytes(original)

            index = EntityGraphIndex(mundos_path)
            index.build("testmundo")

            index.update(str(ficha), "testmundo")
            index.update(str(ficha), "testmundo")

            self.assertEqual(
                ficha.read_bytes(),
                original,
                "update() must not rewrite the file (no write side-effect).",
            )
            entity = index.get_entity("personajes/X.md")
            self.assertIsNotNone(entity, "entity should still resolve after update")
            if entity is not None:
                self.assertEqual(entity.type, "Personaje")
                self.assertIn("# Cuerpo", entity.content)

    def test_update_after_build_keeps_cache_consistent(self) -> None:
        """Entity count stays stable after updates and cache still serves data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path = Path(tmpdir) / "mundos"
            mundo_dir = mundos_path / "testmundo"
            personajes_dir = mundo_dir / "personajes"
            personajes_dir.mkdir(parents=True)

            original = (
                b"---\r\n"
                b"type: Personaje\r\n"
                b"title: Y\r\n"
                b"updated_at: 2026-01-01T00:00:00+00:00\r\n"
                b"---\r\n"
                b"# Cuerpo\r\n"
            )
            ficha = personajes_dir / "Y.md"
            ficha.write_bytes(original)

            index = EntityGraphIndex(mundos_path)
            self.assertEqual(index.build("testmundo"), 1)

            index.update(str(ficha), "testmundo")
            index.update(str(ficha), "testmundo")

            self.assertEqual(ficha.read_bytes(), original)
            self.assertEqual(index.entity_count, 1)
            self.assertTrue(index.dirty)


if __name__ == "__main__":
    unittest.main()
