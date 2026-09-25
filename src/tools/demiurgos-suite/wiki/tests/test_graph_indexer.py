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

from wiki.graph_indexer import EntityGraphIndex, GraphReconcileResult  # noqa: E402


def _write_okf(mundo_dir: Path, rel: str, name: str, links: list[str] = ()) -> Path:
    """Write a minimal OKF ficha under a world dir, returning its absolute path."""
    target = (mundo_dir / rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"[[{l}]]" for l in links)
    target.write_text(
        f"---\ntype: personaje\ntitle: {name}\n---\n# {name}\n{body}",
        encoding="utf-8",
    )
    return target


class TestUpdateMany(unittest.TestCase):
    """update_many: bounded bulk graph reconciliation (slice 3, IM-3.1)."""

    def _make_world(self, tmpdir: str) -> tuple[Path, Path]:
        mundos_path = Path(tmpdir) / "mundos"
        mundo_dir = mundos_path / "bulkworld"
        (mundo_dir / "lore").mkdir(parents=True, exist_ok=True)
        return mundos_path, mundo_dir

    def test_empty_paths_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, _ = self._make_world(tmpdir)
            index = EntityGraphIndex(mundos_path)
            result = index.update_many([], "bulkworld")
            self.assertEqual(result, GraphReconcileResult(processed=0, failed=[], batches=0))

    def test_returns_counts_and_reconciles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._make_world(tmpdir)
            p1 = _write_okf(mundo_dir, "lore/A.md", "Alpha", links=["Beta"])
            p2 = _write_okf(mundo_dir, "lore/B.md", "Beta")
            index = EntityGraphIndex(mundos_path)
            result = index.update_many([str(p1), str(p2)], "bulkworld", batch_size=1)
            self.assertEqual(result.processed, 2)
            self.assertEqual(result.failed, [])
            self.assertEqual(result.batches, 2)
            self.assertTrue(index.dirty)
            # Backlinks recomputed across the batch: A links to B.
            beta = index.get_entity("lore/B.md")
            self.assertIsNotNone(beta)
            self.assertEqual(beta.backlinks, ["lore/A.md"])

    def test_nonexistent_files_collected_as_failed_processing_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._make_world(tmpdir)
            good = _write_okf(mundo_dir, "lore/A.md", "Alpha")
            missing = mundo_dir / "lore" / "Missing.md"
            index = EntityGraphIndex(mundos_path)
            result = index.update_many([str(good), str(missing)], "bulkworld")
            self.assertEqual(result.processed, 1)
            self.assertIn("lore/Missing.md", result.failed)
            self.assertEqual(result.batches, 1)
            # The good file still landed in cache.
            self.assertIsNotNone(index.get_entity("lore/A.md"))

    def test_idempotent_same_cache_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._make_world(tmpdir)
            p1 = _write_okf(mundo_dir, "lore/A.md", "Alpha", links=["Beta"])
            p2 = _write_okf(mundo_dir, "lore/B.md", "Beta", links=["Gamma"])
            p3 = _write_okf(mundo_dir, "lore/C.md", "Gamma")
            index = EntityGraphIndex(mundos_path)
            index.update_many([str(p1), str(p2), str(p3)], "bulkworld")
            snapshot1 = {
                rel: (ent["forward_links"], sorted(ent["backlinks"]))
                for rel, ent in index._cache["entities"].items()
            }
            index.update_many([str(p1), str(p2), str(p3)], "bulkworld")
            snapshot2 = {
                rel: (ent["forward_links"], sorted(ent["backlinks"]))
                for rel, ent in index._cache["entities"].items()
            }
            self.assertEqual(snapshot1, snapshot2)
            self.assertEqual(index.entity_count, 3)

    def test_partial_failure_persists_earlier_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._make_world(tmpdir)
            # Batch 0 (A) succeeds; batch 1 (Missing) fails.
            p1 = _write_okf(mundo_dir, "lore/A.md", "Alpha")
            missing = mundo_dir / "lore" / "Missing.md"
            index = EntityGraphIndex(mundos_path)
            result = index.update_many(
                [str(p1), str(missing)], "bulkworld", batch_size=1)
            self.assertEqual(result.processed, 1)
            self.assertIn("lore/Missing.md", result.failed)
            self.assertEqual(result.batches, 2)
            # Earlier batch persisted even though a later batch had a failure.
            self.assertIsNotNone(index.get_entity("lore/A.md"))
            self.assertIsNone(index.get_entity("lore/Missing.md"))

    def test_batch_size_bounds_recomputation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._make_world(tmpdir)
            paths = [_write_okf(mundo_dir, f"lore/E{i}.md", f"E{i}") for i in range(5)]
            index = EntityGraphIndex(mundos_path)
            result = index.update_many([str(p) for p in paths], "bulkworld", batch_size=2)
            self.assertEqual(result.batches, 3)  # 2 + 2 + 1
            self.assertEqual(result.processed, 5)
            self.assertEqual(index.entity_count, 5)

    def test_500_paths_within_budget_no_oom(self) -> None:
        """Performance: 500+ paths reconcile quickly without unbounded growth."""
        import time
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._make_world(tmpdir)
            paths = [
                _write_okf(mundo_dir, f"lore/P{i:04}.md", f"P{i}",
                           links=["P0"])
                for i in range(500)
            ]
            index = EntityGraphIndex(mundos_path)
            start = time.monotonic()
            result = index.update_many([str(p) for p in paths], "bulkworld", batch_size=100)
            elapsed = time.monotonic() - start
            self.assertEqual(result.processed, 500)
            self.assertEqual(result.failed, [])
            self.assertEqual(result.batches, 5)
            self.assertLess(elapsed, 10.0)
            self.assertEqual(index.entity_count, 500)
            # No unbounded growth across repeated runs.
            index.update_many([str(p) for p in paths], "bulkworld", batch_size=100)
            self.assertEqual(index.entity_count, 500)


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


class TestCanonicalIdParsing(unittest.TestCase):
    """importador-auto-frontmatter (3.3) — the graph index parses the OKF
    canonical ``id`` and resolves relationship identities consistently with
    ``okf_contract.is_canonical_id``."""

    def _world(self, tmpdir: str) -> tuple[Path, Path]:
        mundos_path = Path(tmpdir) / "mundos"
        mundo_dir = mundos_path / "canonworld"
        (mundo_dir / "lore").mkdir(parents=True, exist_ok=True)
        return mundos_path, mundo_dir

    def _write(self, mundo_dir: Path, rel: str, content: str) -> Path:
        target = mundo_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def test_entity_exposes_canonical_id_from_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._world(tmpdir)
            self._write(
                mundo_dir, "lore/Ayagares.md",
                "---\ntype: personaje\ntitle: Ayagares\n"
                "id: Ayagares::Descripción Física\n---\n# Ayagares\n")
            index = EntityGraphIndex(mundos_path)
            index.build("canonworld")
            ent = index.get_entity("lore/Ayagares.md")
            self.assertIsNotNone(ent)
            self.assertEqual(index._cache["entities"]["lore/Ayagares.md"]["id"],
                             "Ayagares::Descripción Física")

    def test_forward_links_from_bare_canonical_id_relaciones(self) -> None:
        """A bare canonical-id ``relaciones`` entry (no ``[[ ]]`` wrapper)
        is indexed as a forward link and resolves by ``id``."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._world(tmpdir)
            self._write(
                mundo_dir, "lore/Ayagares.md",
                "---\ntype: lugar\ntitle: Ayagares\n"
                "id: Ayagares::Descripción Física\n"
                "relaciones: [Ayagares::Palacios]\n---\n# Ayagares\n")
            self._write(
                mundo_dir, "lore/Palacios.md",
                "---\ntype: lugar\ntitle: Palacios\n"
                "id: Ayagares::Palacios\n---\n# Palacios\n")
            index = EntityGraphIndex(mundos_path)
            index.build("canonworld")
            ayagares = index.get_entity("lore/Ayagares.md")
            self.assertIn("Ayagares::Palacios", ayagares.forward_links)
            # Backlink computed across the canonical-id boundary.
            palacios = index.get_entity("lore/Palacios.md")
            self.assertIn("lore/Ayagares.md", palacios.backlinks)

    def test_link_resolves_by_canonical_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._world(tmpdir)
            self._write(
                mundo_dir, "lore/Ayagares.md",
                "---\ntype: lugar\ntitle: Ayagares\n"
                "id: Ayagares::Descripción Física\n---\n"
                "# Ayagares\n\n[[Ayagares::Palacios]]\n")
            self._write(
                mundo_dir, "lore/Palacios.md",
                "---\ntype: lugar\ntitle: Palacios\n"
                "id: Ayagares::Palacios\n---\n# Palacios\n")
            index = EntityGraphIndex(mundos_path)
            index.build("canonworld")
            forward = index.get_links("lore/Ayagares.md", kind="forward")
            self.assertTrue(
                any(l["path"] == "lore/Palacios.md" for l in forward))

    def test_non_canonical_id_not_treated_as_identity(self) -> None:
        """A non-canonical ``id`` value (double whitespace — not a canonical
        identity) is not exposed as the relationship key; the entity still
        indexes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._world(tmpdir)
            self._write(
                mundo_dir, "lore/A.md",
                "---\ntype: personaje\ntitle: A\nid: Dos  Espacios\n---\n# A\n")
            index = EntityGraphIndex(mundos_path)
            index.build("canonworld")
            ent = index._cache["entities"]["lore/A.md"]
            self.assertEqual(ent["id"], "")


class TestEntityStatus(unittest.TestCase):
    """Entity dict carries the OKF ``status`` (BLOQUE 4, D4)."""

    def _world(self, tmpdir: str) -> tuple[Path, Path]:
        mundos_path = Path(tmpdir) / "mundos"
        mundo_dir = mundos_path / "statusworld"
        (mundo_dir / "lore").mkdir(parents=True, exist_ok=True)
        (mundo_dir / "personajes").mkdir(parents=True, exist_ok=True)
        return mundos_path, mundo_dir

    def test_status_from_frontmatter_and_default_draft(self) -> None:
        """``status: stable`` frontmatter is indexed; missing status -> draft."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._world(tmpdir)
            (mundo_dir / "lore" / "A.md").write_text(
                "---\ntype: lugar\ntitle: Alpha\nstatus: stable\n---\n# Alpha\n",
                encoding="utf-8",
            )
            (mundo_dir / "lore" / "B.md").write_text(
                "---\ntype: lugar\ntitle: Beta\n---\n# Beta\n",
                encoding="utf-8",
            )
            index = EntityGraphIndex(mundos_path)
            index.build("statusworld")
            entities = index._cache["entities"]
            self.assertEqual(entities["lore/A.md"]["status"], "stable")
            self.assertEqual(entities["lore/B.md"]["status"], "draft")

    def test_get_entity_populates_id_and_status(self) -> None:
        """EntityDetail built by get_entity carries id and status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._world(tmpdir)
            (mundo_dir / "personajes" / "Rhyz.md").write_text(
                "---\ntype: personaje\ntitle: Rhyz\n"
                "id: Sistema Stal::Rhyz\nstatus: stable\n---\n# Rhyz\n",
                encoding="utf-8",
            )
            index = EntityGraphIndex(mundos_path)
            index.build("statusworld")
            detail = index.get_entity("personajes/Rhyz.md")
            self.assertIsNotNone(detail)
            self.assertEqual(detail.id, "Sistema Stal::Rhyz")
            self.assertEqual(detail.status, "stable")

    def test_get_entity_legacy_defaults(self) -> None:
        """Legacy entities without id/status fall back to "" and "draft"."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._world(tmpdir)
            (mundo_dir / "lore" / "B.md").write_text(
                "---\ntype: lugar\ntitle: Beta\n---\n# Beta\n",
                encoding="utf-8",
            )
            index = EntityGraphIndex(mundos_path)
            index.build("statusworld")
            detail = index.get_entity("lore/B.md")
            self.assertIsNotNone(detail)
            self.assertEqual(detail.id, "")
            self.assertEqual(detail.status, "draft")


class TestIdeasBankCanonSafety(unittest.TestCase):
    """R-IB-05 — the top-level ``ideas/`` bank is never scanned as canon.

    Structural guarantee: the graph indexer is scoped to ``mundos/{mundo}/``
    (``_scan_mundo`` walks only ``lore``/``personajes`` under a world root), so
    a top-level ``ideas/`` sibling of ``mundos/`` is structurally invisible —
    no graph node is ever created for an idea file, regardless of its content.
    """

    def _make_world(self, tmpdir: str) -> tuple[Path, Path, Path]:
        root = Path(tmpdir)
        mundos_path = root / "mundos"
        mundo_dir = mundos_path / "canonworld"
        (mundo_dir / "lore").mkdir(parents=True, exist_ok=True)
        ideas_dir = root / "ideas"  # sibling of mundos/, per R-IB-02
        ideas_dir.mkdir(parents=True, exist_ok=True)
        return mundos_path, mundo_dir, ideas_dir

    def test_top_level_ideas_never_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir, ideas_dir = self._make_world(tmpdir)
            # A canon ficha that MUST be indexed.
            _write_okf(mundo_dir, "lore/A.md", "Alpha")
            # An idea file with OKF-shaped frontmatter that MUST NOT be
            # indexed (it would be, if the indexer ever scanned ideas/).
            (ideas_dir / "arquero-ciego.md").write_text(
                "---\ntype: personaje\ntitle: Arquero Ciego\n"
                "id: Arquero Ciego\nstatus: fresh\nused_in: []\n"
                "---\n# Arquero Ciego\n",
                encoding="utf-8",
            )
            index = EntityGraphIndex(mundos_path)
            self.assertEqual(index.build("canonworld"), 1)
            entities = index._cache["entities"]
            # Only the canon ficha is indexed.
            self.assertEqual(list(entities), ["lore/A.md"])
            # The idea is not resolvable as an entity by any key.
            self.assertIsNone(index.get_entity("ideas/arquero-ciego.md"))
            self.assertIsNone(index.get_entity("arquero-ciego.md"))
            self.assertIsNone(index.get_entity("Arquero Ciego"))


class TestEntitiesEnumeration(unittest.TestCase):
    """``entities()`` — the read-only whole-world enumeration seam (WU9/BUG-B).

    ``search("*")`` and ``search("")`` both return [] by design (zero-token /
    zero-score fast paths), so grounding/id-enumeration callers (R-IM-03/06)
    use ``entities()``: every cached entity, in ``_scan_mundo`` build order.
    """

    def _make_world(self, tmpdir: str) -> tuple[Path, Path]:
        mundos_path = Path(tmpdir) / "mundos"
        mundo_dir = mundos_path / "enumworld"
        (mundo_dir / "lore").mkdir(parents=True, exist_ok=True)
        return mundos_path, mundo_dir

    def test_entities_returns_all_in_build_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._make_world(tmpdir)
            _write_okf(mundo_dir, "lore/B.md", "Beta")
            _write_okf(mundo_dir, "lore/A.md", "Alpha")
            index = EntityGraphIndex(mundos_path)
            index.build("enumworld")
            # search("*") returns [] against a real index (zero-score fast
            # path) — the enumeration seam is the only whole-world query.
            self.assertEqual(index.search("*"), [])
            entities = index.entities()
            self.assertEqual([e["path"] for e in entities], ["lore/A.md", "lore/B.md"])
            self.assertEqual([e["id"] for e in entities], ["", ""])
            self.assertEqual(entities[0]["title"], "Alpha")

    def test_entities_returns_copies_not_cache_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._make_world(tmpdir)
            _write_okf(mundo_dir, "lore/A.md", "Alpha")
            index = EntityGraphIndex(mundos_path)
            index.build("enumworld")
            first = index.entities()[0]
            first["title"] = "MUTATED"
            self.assertEqual(index._cache["entities"]["lore/A.md"]["title"], "Alpha")

    def test_entities_reflects_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mundos_path, mundo_dir = self._make_world(tmpdir)
            _write_okf(mundo_dir, "lore/A.md", "Alpha")
            index = EntityGraphIndex(mundos_path)
            index.build("enumworld")
            self.assertEqual(len(index.entities()), 1)
            _write_okf(mundo_dir, "lore/C.md", "Gamma")
            index.build("enumworld")
            self.assertEqual([e["path"] for e in index.entities()], ["lore/A.md", "lore/C.md"])


if __name__ == "__main__":
    unittest.main()
