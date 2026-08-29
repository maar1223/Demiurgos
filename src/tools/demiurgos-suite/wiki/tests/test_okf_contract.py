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
from unittest import mock

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
from wiki.world_authority import (  # noqa: E402
    CANONICAL_DIRS,
    OC8_LORE_SKELETON,
    WorldResultKind,
    _same_physical_dir,
    create_world,
    detect_legacy_layout,
    normalize_world_name,
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


class TestWorldNameValidation(unittest.TestCase):
    """ONB-1.2 — safe world names; unsafe names explain without mutation."""

    def _mundos(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "mundos"

    def test_valid_names_normalize(self) -> None:
        self.assertEqual(normalize_world_name("  mi-mundo  "), "mi-mundo")
        self.assertEqual(normalize_world_name("Mi Mundo"), "Mi Mundo")
        self.assertEqual(normalize_world_name("a1_b2"), "a1_b2")

    def test_unsafe_names_are_rejected(self) -> None:
        for raw in ["", "  ", "..", ".", "...", "a/b", "a\\b", "a b/c",
                    "/abs", "sub/../../x", ".hidden", "_privado", "Ideas"]:
            self.assertIsNone(normalize_world_name(raw), raw)

    def test_non_string_name_is_rejected(self) -> None:
        self.assertIsNone(normalize_world_name(None))
        self.assertIsNone(normalize_world_name(42))

    def test_invalid_name_returns_result_without_mutation(self) -> None:
        mundos = self._mundos()
        result = create_world(mundos, "../escape")
        self.assertEqual(result.kind, WorldResultKind.INVALID_NAME)
        self.assertFalse(mundos.exists())


class TestWorldCreateIdempotencyCollision(unittest.TestCase):
    """ONB-1.2 — repeats are harmless; differing collisions rejected."""

    def _mundos(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "mundos"

    def test_create_produces_canonical_tree(self) -> None:
        mundos = self._mundos()
        result = create_world(mundos, "tierra-media")
        self.assertEqual(result.kind, WorldResultKind.CREATED)
        root = result.path
        self.assertIsNotNone(root)
        for sub in CANONICAL_DIRS:
            self.assertTrue((root / sub).is_dir(), sub)
        self.assertEqual(sorted(p.name for p in root.iterdir()), sorted(CANONICAL_DIRS))

    def test_repeat_same_request_is_idempotent(self) -> None:
        mundos = self._mundos()
        first = create_world(mundos, "tierra-media", lore_skeleton=True)
        self.assertEqual(first.kind, WorldResultKind.CREATED)
        second = create_world(mundos, "tierra-media", lore_skeleton=True)
        self.assertEqual(second.kind, WorldResultKind.ALREADY_EXISTS)
        # No extra mutation on the repeat.
        self.assertEqual(sorted(p.name for p in first.path.iterdir()), sorted(CANONICAL_DIRS))

    def test_collision_with_author_tree_rejected_without_mutation(self) -> None:
        mundos = self._mundos()
        existing = mundos / "autor"
        existing.mkdir(parents=True)
        (existing / "lore").mkdir()
        (existing / "lore" / "mi_canon.md").write_text("# X\n", encoding="utf-8")
        result = create_world(mundos, "autor")
        self.assertEqual(result.kind, WorldResultKind.COLLISION)
        self.assertTrue((existing / "lore" / "mi_canon.md").exists(),
                        "Author-owned tree must never be mutated")

    def test_collision_with_legacy_uppercase_folders_rejected(self) -> None:
        mundos = self._mundos()
        legacy = mundos / "legacy"
        legacy.mkdir(parents=True)
        (legacy / "Lore").mkdir()
        result = create_world(mundos, "legacy")
        self.assertEqual(result.kind, WorldResultKind.COLLISION)
        self.assertTrue((legacy / "Lore").is_dir(), "legacy folders never auto-renamed")

    def test_collision_with_plain_file_rejected(self) -> None:
        mundos = self._mundos()
        mundos.mkdir(parents=True)
        (mundos / "archivo").write_text("x", encoding="utf-8")
        result = create_world(mundos, "archivo")
        self.assertEqual(result.kind, WorldResultKind.COLLISION)


class TestWorldCanonicalFolderSet(unittest.TestCase):
    """ONB-1.5 — OC8 skeleton exactly; never system/transversal folders."""

    def _mundos(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "mundos"

    def test_optional_skeleton_creates_exactly_oc8_folders(self) -> None:
        mundos = self._mundos()
        result = create_world(mundos, "nuevo", lore_skeleton=True)
        self.assertEqual(result.kind, WorldResultKind.CREATED)
        lore = result.path / "lore"
        self.assertEqual(
            sorted(p.name for p in lore.iterdir()),
            sorted(OC8_LORE_SKELETON),
        )
        # Folders must be EMPTY — no invented content.
        for sub in OC8_LORE_SKELETON:
            self.assertEqual(list((lore / sub).iterdir()), [], sub)

    def test_system_and_transversal_folders_never_created(self) -> None:
        mundos = self._mundos()
        result = create_world(mundos, "limpio", lore_skeleton=True)
        self.assertEqual(result.kind, WorldResultKind.CREATED)
        for forbidden in ("_context", ".history", ".papelera",
                          "relaciones", "canon", "conflictos", "propuestas"):
            self.assertFalse((result.path / forbidden).exists(), forbidden)

    def test_no_skeleton_means_only_canonical_dirs(self) -> None:
        mundos = self._mundos()
        result = create_world(mundos, "basico")
        self.assertEqual(result.kind, WorldResultKind.CREATED)
        lore = result.path / "lore"
        self.assertEqual(list(lore.iterdir()), [])


class TestWorldTraversalSymlink(unittest.TestCase):
    """ONB-1.5 — traversal/symlink escapes are rejected without mutation."""

    def _mundos(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "mundos"

    def test_symlink_world_escape_rejected(self) -> None:
        mundos = self._mundos()
        mundos.mkdir(parents=True)
        outside = Path(mundos).parent / "outside"
        outside.mkdir()
        (mundos / "link").symlink_to(outside, target_is_directory=True)
        result = create_world(mundos, "link")
        self.assertEqual(result.kind, WorldResultKind.COLLISION)
        self.assertEqual(sorted(p.name for p in outside.iterdir()), [],
                         "symlink target must not be mutated")


class TestLegacyLayoutDetection(unittest.TestCase):
    """ONB-4.2 — read-only uppercase ``Lore``/``Personajes`` detection.

    Detection is strictly read-only (no rename/move/delete/write); migration is
    a separate, explicitly-approved step (ONB-4.3) and never automatic.
    """

    def _mundos(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "mundos"

    def test_detects_uppercase_legacy_folders(self) -> None:
        mundos = self._mundos()
        legacy = mundos / "legacy-x"
        (legacy / "Lore").mkdir(parents=True)
        (legacy / "Personajes").mkdir()
        findings = detect_legacy_layout(mundos)
        if _same_physical_dir(legacy / "Lore", legacy / "lore"):
            # case-insensitive FS: `Lore` IS the canonical `lore` — not legacy
            # (R-CIM-05). The runtime operates on the canonical tree already.
            self.assertEqual(findings, [])
        else:
            # case-sensitive FS: uppercase folders reported as legacy.
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["world"], "legacy-x")
            self.assertEqual(set(findings[0]["folders"]), {"Lore", "Personajes"})

    def test_canonical_lowercase_worlds_are_not_reported(self) -> None:
        mundos = self._mundos()
        result = create_world(mundos, "canonico")
        self.assertEqual(result.kind, WorldResultKind.CREATED)
        self.assertEqual(detect_legacy_layout(mundos), [])

    def test_detection_is_strictly_read_only(self) -> None:
        mundos = self._mundos()
        legacy = mundos / "legacy-y"
        (legacy / "Lore").mkdir(parents=True)
        (legacy / "Lore" / "reglas.md").write_text("# R\n", encoding="utf-8")
        before = sorted(p.name for p in legacy.iterdir())
        detect_legacy_layout(mundos)
        self.assertEqual(sorted(p.name for p in legacy.iterdir()), before,
                         "detection must never rename/move/delete folders")
        self.assertTrue((legacy / "Lore").is_dir())
        self.assertTrue((legacy / "Lore" / "reglas.md").exists())

    def test_missing_mundos_dir_returns_empty(self) -> None:
        self.assertEqual(detect_legacy_layout(self._mundos()), [])

    def test_case_insensitive_fs_does_not_report_legacy(self) -> None:
        """R-CIM-05 — on a case-insensitive FS, `Lore` matches the canonical
        `lore` case-insensitively (same physical directory), so it is NOT
        reported as legacy: the runtime already operates on the canonical tree
        through legacy-cased paths."""
        mundos = self._mundos()
        legacy = mundos / "legacy-x"
        (legacy / "Lore").mkdir(parents=True)
        (legacy / "Personajes").mkdir()
        if not _same_physical_dir(legacy / "Lore", legacy / "lore"):
            self.skipTest("case-sensitive FS: not applicable")
        findings = detect_legacy_layout(mundos)
        self.assertEqual(findings, [],
                         "case-insensitive FS: legacy-cased dirs are canonical")

    def test_case_sensitive_fs_still_reports_legacy(self) -> None:
        """R-CIM-05/R-CIM-06 — on a case-sensitive FS the existing detection
        is preserved: `Lore`/`Personajes` ARE reported as legacy (no
        regression on Linux)."""
        mundos = self._mundos()
        legacy = mundos / "legacy-x"
        (legacy / "Lore").mkdir(parents=True)
        (legacy / "Personajes").mkdir()
        if _same_physical_dir(legacy / "Lore", legacy / "lore"):
            self.skipTest("case-insensitive FS: legacy aliases are canonical")
        findings = detect_legacy_layout(mundos)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["world"], "legacy-x")
        self.assertEqual(set(findings[0]["folders"]), {"Lore", "Personajes"})


class TestCanonicalIdentity(unittest.TestCase):
    """IM — canonical ``id`` (``::``-qualified) recognition and safe slugs."""

    def test_canonical_id_with_segments_is_recognized(self) -> None:
        from wiki.okf_contract import is_canonical_id
        self.assertTrue(is_canonical_id(
            "Ayagares::Descripción Física::Forma Base"))
        self.assertTrue(is_canonical_id("Ayagares"))
        self.assertTrue(is_canonical_id("Ayagares::Descripción Física#2"))

    def test_non_canonical_ids_are_rejected(self) -> None:
        from wiki.okf_contract import is_canonical_id
        for bad in ("", "  ", "A::", "::A", "A:: B", "A  B",
                    "e\u0301"):  # decomposed accent -> not NFC
            self.assertFalse(is_canonical_id(bad), bad)

    def test_safe_slug_from_id(self) -> None:
        from wiki.okf_contract import safe_slug_from_id
        # Project-wide ASCII slug alphabet: accented characters drop out and
        # any run of non-alphanumerics collapses to a single ``-``.
        self.assertEqual(
            safe_slug_from_id("Ayagares::Descripción Física#2"),
            "ayagares-descripci-n-f-sica-2")
        self.assertEqual(safe_slug_from_id("Ayagares"), "ayagares")
        self.assertEqual(safe_slug_from_id("A::B::C"), "a-b-c")
        self.assertEqual(safe_slug_from_id("Vibrantes::Río Secreto"),
                         "vibrantes-r-o-secreto")

    def test_id_field_satisfies_identity_minimum(self) -> None:
        content = (
            "---\ntype: Personaje\n"
            "id: Ayagares::Descripción Física\n"
            "desire: completar algo\n---\nCuerpo.\n"
        )
        validation = validate(content)
        self.assertTrue(validation.ok, validation.issues)


if __name__ == "__main__":
    unittest.main()
