"""
tests/test_okf_contract.py — RED/unit tests for wiki.okf_contract.

Covers the OKF v1 contract: identity, ``[[Name]]``/``relaciones`` relationship
conventions, extensible per-entity minimums (characters first), and surfacing
of missing minimums and ambiguous references.  The contract is read-only:
validation must never write to canon or to the filesystem.

Uses unittest for discovery via ``python -m unittest discover``.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent  # demiurgos-suite/
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from wiki.okf_contract import (  # noqa: E402
    OKF_VERSION,
    OkfValidation,
    OkfIssue,
    OkfDocument,
    parse_document,
    register_minimums,
    minimums_for,
    validate,
)


def _personaje_missing_desire() -> str:
    return (
        "---\n"
        "type: Personaje\n"
        "title: Anisa\n"
        "---\n"
        "## Cuerpo\n"
        "Algo de contenido.\n"
    )


def _personaje_complete() -> str:
    return (
        "---\n"
        "type: Personaje\n"
        "name: Anisa\n"
        "desire: completar a Bira\n"
        "relaciones:\n"
        "  - '[[Bira]] (complementa)'\n"
        "---\n"
        "Conoce a [[Bira]] desde siempre.\n"
    )


class TestOkfIdentity(unittest.TestCase):
    """OKF v1 identity detection from frontmatter ``type``."""

    def test_document_with_type_is_okf(self) -> None:
        doc = parse_document(_personaje_complete())
        self.assertIsNotNone(doc)
        if doc is not None:
            self.assertEqual(doc.entity_type, "Personaje")
            self.assertEqual(doc.version, None)

    def test_document_without_frontmatter_is_not_okf(self) -> None:
        self.assertIsNone(parse_document("# Solo cuerpo\n\nSin frontmatter.\n"))

    def test_document_without_type_is_not_okf(self) -> None:
        content = "---\ntitle: X\n---\nCuerpo\n"
        self.assertIsNone(parse_document(content))

    def test_version_mismatch_surfaces_issue(self) -> None:
        content = "---\nokf_version: 2\ntype: Personaje\ntitle: X\n---\n"
        doc = parse_document(content)
        self.assertIsNotNone(doc)
        validation = validate(content)
        self.assertFalse(validation.ok)
        codes = {issue.code for issue in validation.issues}
        self.assertIn("version", codes)


class TestOkfRelationships(unittest.TestCase):
    """Relationship conventions: ``[[Name]]`` body links + ``relaciones`` frontmatter."""

    def test_body_wikilinks_and_relaciones_are_collected(self) -> None:
        doc = parse_document(_personaje_complete())
        self.assertIsNotNone(doc)
        if doc is not None:
            # Body [[Bira]] + relaciones [[Bira]] collapse to one unique link.
            self.assertEqual(doc.forward_links, ("Bira",))

    def test_distinct_body_and_relaciones_links_are_both_kept(self) -> None:
        content = (
            "---\ntype: Personaje\ntitle: X\nrelaciones:\n  - '[[Otro]] (aliado)'\n---\n"
            "Conoce a [[Bira]].\n"
        )
        doc = parse_document(content)
        self.assertIsNotNone(doc)
        if doc is not None:
            self.assertEqual(set(doc.forward_links), {"Bira", "Otro"})

    def test_plain_text_relationship_is_not_a_link(self) -> None:
        content = (
            "---\ntype: Personaje\ntitle: X\n---\n"
            "Su hermano se llama Y sin corchetes.\n"
        )
        doc = parse_document(content)
        self.assertIsNotNone(doc)
        if doc is not None:
            self.assertEqual(doc.forward_links, ())


class TestOkfMinimums(unittest.TestCase):
    """Extensible per-entity minimums, characters first."""

    def test_character_minimums_are_defined_first(self) -> None:
        groups = minimums_for("personaje")
        self.assertEqual(len(groups), 2, "characters require identity + desire")

    def test_character_missing_desire_surfaces(self) -> None:
        validation = validate(_personaje_missing_desire())
        self.assertFalse(validation.ok)
        codes = {issue.code for issue in validation.issues}
        self.assertIn("missing-minimum", codes)
        desire_issue = next(
            (i for i in validation.issues if i.code == "missing-minimum"
             and i.field and "desire" in i.field), None
        )
        self.assertIsNotNone(desire_issue, "desire group must be reported missing")

    def test_complete_character_validates_clean(self) -> None:
        validation = validate(_personaje_complete())
        self.assertTrue(validation.ok, validation.issues)

    def test_minimums_are_extensible_per_type(self) -> None:
        register_minimums("lugar", ("poblacion",))
        try:
            groups = minimums_for("lugar")
            self.assertIn(frozenset({"poblacion"}), groups)
            validation = validate(
                "---\ntype: Lugar\ntitle: Ciudad\n---\nCuerpo\n"
            )
            codes = {issue.code for issue in validation.issues}
            self.assertIn("missing-minimum", codes)
        finally:
            # Restore the registry so other tests stay deterministic.
            from wiki.okf_contract import OKF_MINIMUM_GROUPS_BY_TYPE
            OKF_MINIMUM_GROUPS_BY_TYPE.pop("lugar", None)


class TestOkfReferences(unittest.TestCase):
    """Ambiguous and unresolved references surface instead of failing silently."""

    def _resolver(self, mapping: dict[str, list[str]]):
        return lambda link: mapping.get(link, [])

    def test_ambiguous_reference_surfaces(self) -> None:
        resolver = self._resolver({"Bira": ["personajes/Bira_A.md", "lore/Bira_B.md"]})
        validation = validate(_personaje_complete(), resolve=resolver)
        codes = {issue.code for issue in validation.issues}
        self.assertIn("ambiguous-reference", codes)
        issue = next(i for i in validation.issues if i.code == "ambiguous-reference")
        self.assertEqual(issue.reference, "Bira")

    def test_unresolved_reference_surfaces(self) -> None:
        resolver = self._resolver({})
        validation = validate(_personaje_complete(), resolve=resolver)
        codes = {issue.code for issue in validation.issues}
        self.assertIn("unresolved-reference", codes)

    def test_resolvable_reference_is_clean(self) -> None:
        resolver = self._resolver({"Bira": ["personajes/Bira.md"]})
        validation = validate(_personaje_complete(), resolve=resolver)
        self.assertTrue(validation.ok, validation.issues)


class TestNoSilentWrite(unittest.TestCase):
    """Validation and identity parsing must never write anywhere."""

    def test_validate_never_writes_to_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            probe = Path(tmpdir) / "sentinel.md"
            before = sorted(p.name for p in Path(tmpdir).iterdir())
            validation = validate(_personaje_missing_desire(), resolve=lambda _: [])
            self.assertFalse(validation.ok)
            after = sorted(p.name for p in Path(tmpdir).iterdir())
            self.assertEqual(before, after)
            self.assertFalse(probe.exists(), "validation must not create files")

    def test_validation_result_is_surfaced_not_hidden(self) -> None:
        validation = validate(_personaje_missing_desire())
        self.assertIsInstance(validation, OkfValidation)
        self.assertTrue(all(isinstance(i, OkfIssue) for i in validation.issues))


class TestGraphIndexerIntegration(unittest.TestCase):
    """graph_indexer surfaces OKF diagnostics while keeping tolerant indexing."""

    def _index(self, files: dict[str, str]):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mundos = Path(tmp.name) / "mundos"
        for rel, content in files.items():
            path = mundos / "testmundo" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        from wiki.graph_indexer import EntityGraphIndex
        index = EntityGraphIndex(mundos)
        index.build("testmundo")
        return index

    def test_entity_carries_okf_diagnostics(self) -> None:
        index = self._index({
            "personajes/Anisa.md": (
                "---\ntype: Personaje\ntitle: Anisa\n---\nCuerpo\n"
            ),
        })
        entity = index.get_entity("personajes/Anisa.md")
        self.assertIsNotNone(entity)
        self.assertEqual(entity.type, "Personaje")
        # Tolerant: the entity is still indexed despite the missing minimum.
        self.assertEqual(index.entity_count, 1)

    def test_minimum_issues_surface_without_blocking_index(self) -> None:
        index = self._index({
            "personajes/Anisa.md": (
                "---\ntype: Personaje\ntitle: Anisa\n---\nCuerpo\n"
            ),
        })
        validation = index.okf_validation("personajes/Anisa.md")
        self.assertIsNotNone(validation)
        if validation is not None:
            codes = {issue.code for issue in validation.issues}
            self.assertIn("missing-minimum", codes)
            self.assertFalse(validation.ok)

    def test_ambiguous_reference_surfaces_via_index(self) -> None:
        index = self._index({
            "personajes/Bira_A.md": (
                "---\ntype: Personaje\ntitle: Bira\n---\nCuerpo\n"
            ),
            "lore/Bira_B.md": (
                "---\ntype: Concepto\ntitle: Bira\n---\nCuerpo\n"
            ),
            "personajes/Anisa.md": (
                "---\ntype: Personaje\ntitle: Anisa\n---\n"
                "Conoce a [[Bira]].\n"
            ),
        })
        validation = index.okf_validation("personajes/Anisa.md")
        self.assertIsNotNone(validation)
        if validation is not None:
            codes = {issue.code for issue in validation.issues}
            self.assertIn("ambiguous-reference", codes)


if __name__ == "__main__":
    unittest.main()
