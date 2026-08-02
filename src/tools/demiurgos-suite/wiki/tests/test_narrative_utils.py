"""
tests/test_narrative_utils.py — Unit tests for narrative_utils.py helpers.

Covers: constants, Engram subprocess (mocked), claim extraction,
conflict detection, entity/theme extraction, idea scanning/BM25,
and lore formatting. Uses unittest (not pytest) for discovery via
``python -m unittest discover``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the wiki package is importable
_SRC_DIR = Path(__file__).resolve().parent.parent.parent  # demiurgos-suite/
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from wiki.narrative_utils import (  # noqa: E402
    CLAIM_PATTERNS,
    CONFLICT_TYPES,
    THEME_MAP,
    compare_claims,
    engram_get_observation,
    engram_search,
    extract_claims,
    extract_entities,
    extract_themes,
    format_lore,
    parse_frontmatter,
    sanitize_shell_arg,
    scan_ideas_dir,
    search_ideas_bm25,
)


# =============================================================================
# Constants
# =============================================================================

GOLDEN_MD = """---
title: "Rhyz El Resonante"
type: Ficha
description: "El resonante guardián del Ashen Valley"
estado: "muerto"
año_nacimiento: 1400
año_muerte: 1450
nombre_real: "Rhyzan Korr"
tags: ["importante", "guardián"]
---

# Rhyz El Resonante

Rhyz nació en 1400 y murió en 1450. Fue un guardián legendario.
Era mentor de [[Vael La Silenciadora]] y enemigo de [[Ekkor]].
"""


# =============================================================================
# Constants / taxonomy tests
# =============================================================================

class TestConstants(unittest.TestCase):
    """Verify constants exist and have correct structure."""

    def test_theme_map_has_30_themes(self) -> None:
        """THEME_MAP contains exactly 30 curated themes."""
        self.assertEqual(len(THEME_MAP), 30)
        for theme, keywords in THEME_MAP.items():
            self.assertIsInstance(theme, str)
            self.assertIsInstance(keywords, list)
            self.assertGreater(len(keywords), 0, f"Theme '{theme}' has no keywords")

    def test_conflict_types_taxonomy(self) -> None:
        """CONFLICT_TYPES contains expected taxonomy entries."""
        expected = {"date_contradiction", "status_contradiction",
                     "name_mismatch", "relationship_conflict", "unknown"}
        self.assertEqual(CONFLICT_TYPES, expected)

    def test_claim_patterns_structure(self) -> None:
        """CLAIM_PATTERNS is a list of (name, compiled_regex) tuples."""
        self.assertIsInstance(CLAIM_PATTERNS, list)
        self.assertGreater(len(CLAIM_PATTERNS), 0)
        for name, pattern in CLAIM_PATTERNS:
            self.assertIsInstance(name, str)
            self.assertTrue(hasattr(pattern, "search"),
                            f"Pattern '{name}' is not a compiled regex")


# =============================================================================
# sanitize_shell_arg
# =============================================================================

class TestSanitizeShellArg(unittest.TestCase):
    """Shell argument sanitization tests."""

    def test_normal_string_passes_through(self) -> None:
        """Normal strings are quoted but preserved."""
        result = sanitize_shell_arg("hello")
        self.assertIsInstance(result, str)
        self.assertIn("hello", result)

    def test_special_chars_quoted(self) -> None:
        """Special characters are properly quoted."""
        result = sanitize_shell_arg("hello; rm -rf /")
        self.assertIsInstance(result, str)
        # shlex.quote wraps in single quotes and escapes interior quotes
        self.assertTrue(result.startswith("'") or result.startswith('"'))

    def test_empty_string(self) -> None:
        """Empty string produces valid quoted empty string."""
        result = sanitize_shell_arg("")
        self.assertIsInstance(result, str)

    def test_spaces_preserved(self) -> None:
        """Strings with spaces are properly quoted."""
        result = sanitize_shell_arg("Rhyz El Resonante")
        self.assertIsInstance(result, str)
        self.assertNotEqual(result, "Rhyz El Resonante")  # should be quoted


# =============================================================================
# engram_search — subprocess (mocked)
# =============================================================================

class TestEngramSearch(unittest.TestCase):
    """Engram search via subprocess — all subprocess calls mocked."""

    def test_engram_search_returns_parsed_results(self) -> None:
        """Happy path: subprocess returns valid JSON from Engram."""
        mock_stdout = json.dumps({
            "result": [
                {"id": 123, "title": "Test Memory", "content": "preview text here"},
                {"id": 456, "title": "Another", "content": "more content"},
            ]
        })
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = mock_stdout

        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            results = engram_search("test query", "test-project")

        mock_run.assert_called_once()
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], 123)
        self.assertEqual(results[0]["title"], "Test Memory")
        self.assertEqual(results[0]["preview"], "preview text here")

    def test_engram_search_empty_result_list(self) -> None:
        """Engram returns empty result list — graceful."""
        mock_stdout = json.dumps({"result": []})
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = mock_stdout

        with patch("subprocess.run", return_value=mock_proc):
            results = engram_search("no-match", "test-project")

        self.assertEqual(results, [])

    def test_engram_search_nonzero_return_code(self) -> None:
        """Subprocess returns non-zero exit code — graceful fallback to []."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""

        with patch("subprocess.run", return_value=mock_proc):
            results = engram_search("query", "test-project")

        self.assertEqual(results, [])

    def test_engram_search_file_not_found(self) -> None:
        """Engram CLI not installed — graceful fallback to []."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            results = engram_search("query", "test-project")

        self.assertEqual(results, [])

    def test_engram_search_timeout(self) -> None:
        """Subprocess timeout — graceful fallback to []."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 15)):
            results = engram_search("query", "test-project")

        self.assertEqual(results, [])

    def test_engram_search_invalid_json(self) -> None:
        """Subprocess returns invalid JSON — graceful fallback to []."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "not valid json {{{"

        with patch("subprocess.run", return_value=mock_proc):
            results = engram_search("query", "test-project")

        self.assertEqual(results, [])

    def test_engram_search_result_not_list(self) -> None:
        """Result key is not a list — graceful fallback to []."""
        mock_stdout = json.dumps({"result": "not a list"})
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = mock_stdout

        with patch("subprocess.run", return_value=mock_proc):
            results = engram_search("query", "test-project")

        self.assertEqual(results, [])

    def test_engram_search_with_custom_cmd(self) -> None:
        """Custom engram command path is passed to subprocess."""
        mock_stdout = json.dumps({"result": []})
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = mock_stdout

        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            engram_search("query", "test-project", engram_cmd="/custom/engram")

        args, _ = mock_run.call_args
        self.assertEqual(args[0][0], "/custom/engram")


# =============================================================================
# engram_get_observation — subprocess (mocked)
# =============================================================================

class TestEngramGetObservation(unittest.TestCase):
    """Engram get-observation via subprocess — mocked."""

    def test_get_observation_returns_content(self) -> None:
        """Happy path: returns content string."""
        mock_stdout = json.dumps({"content": "Full observation text"})
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = mock_stdout

        with patch("subprocess.run", return_value=mock_proc):
            result = engram_get_observation(123)

        self.assertEqual(result, "Full observation text")

    def test_get_observation_nonzero_code(self) -> None:
        """Non-zero exit code → empty string."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""

        with patch("subprocess.run", return_value=mock_proc):
            result = engram_get_observation(999)

        self.assertEqual(result, "")

    def test_get_observation_missing_binary(self) -> None:
        """Engram CLI not found → empty string."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = engram_get_observation(123)

        self.assertEqual(result, "")

    def test_get_observation_timeout(self) -> None:
        """Timeout → empty string."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 15)):
            result = engram_get_observation(123)

        self.assertEqual(result, "")


# =============================================================================
# parse_frontmatter
# =============================================================================

class TestParseFrontmatter(unittest.TestCase):
    """YAML frontmatter parsing."""

    def test_parse_valid_frontmatter(self) -> None:
        """Parses standard YAML frontmatter block."""
        result = parse_frontmatter(GOLDEN_MD)
        self.assertEqual(result["title"], "Rhyz El Resonante")
        self.assertEqual(result["type"], "Ficha")
        self.assertEqual(result["estado"], "muerto")
        self.assertEqual(result["tags"], ["importante", "guardián"])

    def test_parse_no_frontmatter(self) -> None:
        """No frontmatter → empty dict."""
        result = parse_frontmatter("# Just a heading\n\nSome content.")
        self.assertEqual(result, {})

    def test_parse_invalid_yaml(self) -> None:
        """Invalid YAML in frontmatter → empty dict (graceful)."""
        result = parse_frontmatter("---\n{{ invalid yaml [[[ \n---\nbody")
        self.assertEqual(result, {})

    def test_parse_empty_file(self) -> None:
        """Empty string → empty dict."""
        result = parse_frontmatter("")
        self.assertEqual(result, {})


# =============================================================================
# extract_claims
# =============================================================================

class TestExtractClaims(unittest.TestCase):
    """Regex-based claim extraction from entity content."""

    def test_extract_date_claims(self) -> None:
        """Detects date patterns like 'nació en 1400', 'murió en 1450'."""
        claims = extract_claims(GOLDEN_MD, "personajes/rhyz.md")
        date_claims = [c for c in claims if c["field"] in ("año_nacimiento", "año_muerte")]

        years = {c["value"] for c in date_claims}
        self.assertIn("1400", years)
        self.assertIn("1450", years)

    def test_extract_status_claims(self) -> None:
        """Detects 'estado: muerto' from frontmatter."""
        claims = extract_claims(GOLDEN_MD, "personajes/rhyz.md")
        status_claims = [c for c in claims if c["pattern"] == "status"]

        self.assertTrue(any(c["value"] == "muerto" for c in status_claims))

    def test_extract_name_claims(self) -> None:
        """Detects 'nombre_real: Rhyzan Korr' from frontmatter."""
        claims = extract_claims(GOLDEN_MD, "personajes/rhyz.md")
        name_claims = [c for c in claims if c["field"] == "nombre_real"]

        self.assertTrue(any("Rhyzan Korr" in c["value"] for c in name_claims))

    def test_source_included(self) -> None:
        """All claims include the entity_path as source."""
        claims = extract_claims(GOLDEN_MD, "personajes/rhyz.md")
        for claim in claims:
            self.assertIn("source", claim)
            self.assertEqual(claim["source"], "personajes/rhyz.md")

    def test_empty_content(self) -> None:
        """Empty content returns minimal claims (still scans frontmatter)."""
        claims = extract_claims("", "empty.md")
        # May have zero or minimal claims — should not crash
        self.assertIsInstance(claims, list)


# =============================================================================
# compare_claims
# =============================================================================

class TestCompareClaims(unittest.TestCase):
    """Conflict detection between entity claims and Engram claims."""

    def test_date_contradiction_detected(self) -> None:
        """Different death years → date_contradiction."""
        entity = [{"field": "año_muerte", "value": "1450", "pattern": "date",
                    "source": "personajes/rhyz.md"}]
        engram = [{"field": "año_muerte", "value": "1452", "pattern": "date",
                    "source": "engram#1234", "id": 1234}]

        conflicts = compare_claims(entity, engram)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["conflict_type"], "date_contradiction")
        self.assertEqual(conflicts[0]["claim_a"], "1450")
        self.assertEqual(conflicts[0]["claim_b"], "1452")

    def test_status_contradiction(self) -> None:
        """'muerto' vs 'vivo' → status_contradiction."""
        entity = [{"field": "estado", "value": "muerto", "pattern": "status",
                    "source": "personajes/rhyz.md"}]
        engram = [{"field": "estado", "value": "vivo", "pattern": "status",
                    "source": "engram#5678", "id": 5678}]

        conflicts = compare_claims(entity, engram)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["conflict_type"], "status_contradiction")

    def test_no_conflict_when_values_match(self) -> None:
        """Same value → no conflict generated."""
        entity = [{"field": "año_muerte", "value": "1450", "pattern": "date",
                    "source": "personajes/rhyz.md"}]
        engram = [{"field": "año_muerte", "value": "1450", "pattern": "date",
                    "source": "engram#1234"}]

        conflicts = compare_claims(entity, engram)

        self.assertEqual(conflicts, [])

    def test_similar_values_no_conflict(self) -> None:
        """Similar values (case difference) → no strong conflict."""
        entity = [{"field": "title", "value": "Rhyz El Resonante", "pattern": "name",
                    "source": "personajes/rhyz.md"}]
        engram = [{"field": "title", "value": "rhyz el resonante", "pattern": "name",
                    "source": "engram#999"}]

        conflicts = compare_claims(entity, engram)

        # Case-insensitive match → no conflict
        self.assertEqual(conflicts, [])

    def test_empty_inputs(self) -> None:
        """Empty claim lists → no conflicts."""
        self.assertEqual(compare_claims([], []), [])
        self.assertEqual(compare_claims([{"field": "x", "value": "y"}], []), [])

    def test_unknown_pattern_maps_to_unknown(self) -> None:
        """Unrecognized pattern → conflict_type='unknown'."""
        entity = [{"field": "custom", "value": "A", "pattern": "weird_pattern",
                    "source": "test.md"}]
        engram = [{"field": "custom", "value": "B", "pattern": "weird_pattern",
                    "source": "engram#1"}]

        conflicts = compare_claims(entity, engram)
        if conflicts:
            self.assertEqual(conflicts[0]["conflict_type"], "unknown")

    def test_name_mismatch_type(self) -> None:
        """Different names → name_mismatch."""
        entity = [{"field": "nombre_real", "value": "Rhyzan Korr", "pattern": "name",
                    "source": "personajes/rhyz.md"}]
        engram = [{"field": "nombre_real", "value": "Rhyzan Karr", "pattern": "name",
                    "source": "engram#111"}]

        conflicts = compare_claims(entity, engram)

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["conflict_type"], "name_mismatch")


# =============================================================================
# extract_entities
# =============================================================================

class TestExtractEntities(unittest.TestCase):
    """Entity name matching from free text."""

    def test_extract_single_word_entities(self) -> None:
        """Finds single-word entity names."""
        known = {"Rhyz", "Vael", "Ekkor", "Ashen Valley"}
        result = extract_entities("Rhyz trained Vael in the valley", known)

        self.assertIn("Rhyz", result)
        self.assertIn("Vael", result)

    def test_extract_multi_word_entities(self) -> None:
        """Finds multi-word entity names when all words appear."""
        known = {"Ashen Valley", "Rhyz El Resonante"}
        result = extract_entities("The Ashen Valley was guarded by Rhyz El Resonante", known)

        self.assertIn("Ashen Valley", result)
        self.assertIn("Rhyz El Resonante", result)

    def test_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        known = {"Rhyz El Resonante"}
        result = extract_entities("rhyz el resonante was here", known)

        self.assertIn("Rhyz El Resonante", result)

    def test_no_matches(self) -> None:
        """Unrelated text → empty list."""
        known = {"Rhyz", "Vael"}
        result = extract_entities("The weather is nice today", known)

        self.assertEqual(result, [])

    def test_empty_text(self) -> None:
        """Empty text → empty list."""
        result = extract_entities("", {"Rhyz"})
        self.assertEqual(result, [])

    def test_empty_known_names(self) -> None:
        """Empty known names → empty list."""
        result = extract_entities("Rhyz was here", set())
        self.assertEqual(result, [])


# =============================================================================
# extract_themes
# =============================================================================

class TestExtractThemes(unittest.TestCase):
    """Keyword-based theme extraction."""

    def test_extract_battle_theme(self) -> None:
        """Text mentioning 'batalla' → ['batalla']."""
        result = extract_themes("La gran batalla comenzó al amanecer")
        self.assertIn("batalla", result)

    def test_extract_multiple_themes(self) -> None:
        """Text with multiple keywords → multiple themes."""
        result = extract_themes(
            "El entrenamiento terminó en batalla. Viajó al exilio."
        )
        self.assertIn("entrenamiento", result)
        self.assertIn("batalla", result)
        self.assertIn("viaje", result)
        self.assertIn("exilio", result)

    def test_no_themes(self) -> None:
        """Text with no matching keywords → empty list."""
        result = extract_themes("El día estaba soleado y tranquilo.")
        self.assertEqual(result, [])

    def test_empty_text(self) -> None:
        """Empty text → empty list."""
        result = extract_themes("")
        self.assertEqual(result, [])

    def test_custom_theme_map(self) -> None:
        """Custom theme map is used when provided."""
        custom = {"prueba": ["test", "probar"], "fallo": ["error", "bug"]}
        result = extract_themes("vamos a probar este test", theme_map=custom)
        self.assertIn("prueba", result)
        self.assertNotIn("fallo", result)

    def test_english_keywords(self) -> None:
        """English keywords in THEME_MAP also trigger matches."""
        result = extract_themes("The great battle began at dawn")
        self.assertIn("batalla", result)


# =============================================================================
# scan_ideas_dir and search_ideas_bm25
# =============================================================================

class TestIdeaFunctions(unittest.TestCase):
    """Idea Bank scanning and BM25 search."""

    def setUp(self) -> None:
        """Create a temporary mundo with Ideas/ directory for testing."""
        # Use tempfile for cross-platform temp directory creation
        self._tmpdir_obj = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmpdir_obj.name)
        self.mundo_dir = self.tmpdir / "test_mundo"
        self.ideas_dir = self.mundo_dir / "Ideas"
        self.ideas_dir.mkdir(parents=True)

        # Write a couple of idea files
        idea_1 = """---
slug: "2026-07-30-sistema-educativo-meritocratico"
type: "idea_loose"
tags: ["educación", "mundo"]
---

# Sistema educativo meritocrático

Tengo una idea de un sistema educativo meritocrático donde los
estudiantes compiten por recursos limitados. Similar a un examen imperial.
"""
        (self.ideas_dir / "2026-07-30-sistema-educativo-meritocratico.md").write_text(
            idea_1, encoding="utf-8"
        )

        idea_2 = """---
slug: "2026-07-31-combate-elemental-facciones"
type: "idea_loose"
tags: ["combate", "magia"]
---

# Combate entre facciones elementales

Idea para un sistema de combate basado en elementos donde cada
facción controla un tipo de magia diferente.
"""
        (self.ideas_dir / "2026-07-31-combate-elemental-facciones.md").write_text(
            idea_2, encoding="utf-8"
        )

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        self._tmpdir_obj.cleanup()

    def test_scan_ideas_dir_parses_files(self) -> None:
        """Scans Ideas/ directory and parses frontmatter + body."""
        ideas = scan_ideas_dir("test_mundo", str(self.tmpdir))

        self.assertEqual(len(ideas), 2)
        slugs = {i["slug"] for i in ideas}
        self.assertIn("2026-07-30-sistema-educativo-meritocratico", slugs)
        self.assertIn("2026-07-31-combate-elemental-facciones", slugs)

        # Check first idea structure
        edu = next(i for i in ideas if "educativo" in i["slug"])
        self.assertIn("body", edu)
        self.assertIn("frontmatter", edu)
        self.assertIn("path", edu)
        self.assertEqual(edu["frontmatter"]["type"], "idea_loose")

    def test_scan_ideas_dir_missing_directory(self) -> None:
        """Missing Ideas/ directory → empty list."""
        ideas = scan_ideas_dir("nonexistent_world", str(self.tmpdir))
        self.assertEqual(ideas, [])

    def test_search_ideas_bm25_relevant_match(self) -> None:
        """Query containing overlapping terms matches the educational idea above threshold."""
        ideas = scan_ideas_dir("test_mundo", str(self.tmpdir))

        # Inject mock rank_bm25 into sys.modules so the in-function import succeeds
        mock_bm25_module = MagicMock()
        mock_bm25_instance = MagicMock()
        mock_bm25_instance.get_scores.return_value = [0.85, 0.12]
        mock_bm25_module.BM25Okapi.return_value = mock_bm25_instance

        with patch.dict("sys.modules", {"rank_bm25": mock_bm25_module}):
            results = search_ideas_bm25("sistema educativo meritocrático", ideas)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["slug"], "2026-07-30-sistema-educativo-meritocratico")
        self.assertAlmostEqual(results[0]["score"], 0.85, places=2)
        self.assertIn("preview_80chars", results[0])
        self.assertLessEqual(len(results[0]["preview_80chars"]), 83)  # 80 + "…"

    def test_search_ideas_bm25_no_match(self) -> None:
        """Unrelated query → results below threshold, returned empty."""
        ideas = scan_ideas_dir("test_mundo", str(self.tmpdir))
        results = search_ideas_bm25("zzz unprecedentedly xtreme karaoke marathon", ideas)

        self.assertEqual(results, [])

    def test_search_ideas_bm25_sorted_by_score(self) -> None:
        """Results are sorted by score descending."""
        ideas = scan_ideas_dir("test_mundo", str(self.tmpdir))
        results = search_ideas_bm25("combate magia", ideas)

        if len(results) >= 2:
            self.assertGreaterEqual(results[0]["score"], results[1]["score"])

    def test_search_ideas_bm25_empty_ideas(self) -> None:
        """Empty ideas list → empty results."""
        results = search_ideas_bm25("query", [])
        self.assertEqual(results, [])

    def test_search_ideas_bm25_empty_content(self) -> None:
        """Empty query → empty results."""
        ideas = scan_ideas_dir("test_mundo", str(self.tmpdir))
        results = search_ideas_bm25("", ideas)
        self.assertEqual(results, [])

    def test_search_ideas_bm25_threshold_filter(self) -> None:
        """Higher threshold filters out low-scoring results."""
        ideas = scan_ideas_dir("test_mundo", str(self.tmpdir))
        # Normal threshold
        normal = search_ideas_bm25("escuela", ideas, threshold=0.3)
        # High threshold
        strict = search_ideas_bm25("escuela", ideas, threshold=0.99)
        self.assertGreaterEqual(len(normal), len(strict))

    def test_scan_ideas_skips_hidden_files(self) -> None:
        """Files starting with _ or . are skipped."""
        (self.ideas_dir / "_indice.md").write_text("---\n---\nskip me", encoding="utf-8")
        (self.ideas_dir / ".hidden.md").write_text("---\n---\nhidden", encoding="utf-8")

        ideas = scan_ideas_dir("test_mundo", str(self.tmpdir))
        slugs = {i["slug"] for i in ideas}
        self.assertNotIn("_indice", slugs)
        self.assertNotIn(".hidden", slugs)


# =============================================================================
# format_lore
# =============================================================================

class TestFormatLore(unittest.TestCase):
    """Deterministic lore formatting with wikilinks."""

    def test_format_full_struct(self) -> None:
        """All three sections present → entity, engram, and conflicts sections."""
        data = {
            "entity": {
                "name": "Rhyz El Resonante",
                "type": "Ficha",
                "description": "El guardián resonante",
                "tags": ["importante"],
                "path": "personajes/rhyz.md",
                "content": "Rhyz nació en 1400 y fue mentor de Vael.",
            },
            "engram": [
                {"title": "Memory 1", "preview": "Observation about Rhyz"},
            ],
            "conflicts": [
                {"conflict_type": "date_contradiction",
                 "claim_a": "1450", "claim_b": "1452"},
            ],
        }

        result = format_lore(data)

        self.assertIn("## Entity: [[Rhyz El Resonante]]", result)
        self.assertIn("**Type**: Ficha", result)
        self.assertIn("## Engram Context", result)
        self.assertIn("Memory 1", result)
        self.assertIn("## Conflicts", result)
        self.assertIn("date_contradiction", result)

    def test_format_entity_only(self) -> None:
        """Only entity data → only entity section rendered."""
        data = {
            "entity": {"name": "Vael", "type": "Ficha", "description": "La silenciadora"},
        }

        result = format_lore(data)

        self.assertIn("## Entity: [[Vael]]", result)
        self.assertIn("**Type**: Ficha", result)
        self.assertNotIn("## Engram Context", result)
        self.assertNotIn("## Conflicts", result)

    def test_format_empty_struct(self) -> None:
        """Empty data → empty string."""
        result = format_lore({})
        self.assertEqual(result, "")

    def test_format_empty_entity(self) -> None:
        """Entity key present but no name → entity section omitted."""
        data = {"entity": {"type": "Ficha"}}
        result = format_lore(data)
        self.assertNotIn("## Entity:", result)

    def test_format_wikilinks_in_output(self) -> None:
        """Entity references use [[wikilinks]] syntax."""
        data = {
            "entity": {"name": "Rhyz El Resonante", "type": "Personaje"},
        }
        result = format_lore(data)
        self.assertIn("[[Rhyz El Resonante]]", result)

    def test_format_content_preview_truncation(self) -> None:
        """Long content is truncated with …."""
        long_content = "A" * 300
        data = {"entity": {"name": "Rhyz", "content": long_content}}
        result = format_lore(data)
        self.assertIn("…", result)
        self.assertLess(len(result), 300)


# =============================================================================
# Integration: full claim → compare pipeline
# =============================================================================

class TestClaimPipeline(unittest.TestCase):
    """End-to-end: extract_claims → compare_claims on golden data."""

    def test_full_claim_conflict_pipeline(self) -> None:
        """Extract from golden file, simulate contradictory Engram claims."""
        entity_claims = extract_claims(GOLDEN_MD, "personajes/rhyz_resonante.md")

        # Simulate Engram claiming different death year
        engram_claims = [
            {"field": "año_muerte", "value": "1452", "pattern": "date",
             "source": "engram#1001", "id": 1001},
            {"field": "estado", "value": "desaparecido", "pattern": "status",
             "source": "engram#1002", "id": 1002},
        ]

        conflicts = compare_claims(entity_claims, engram_claims)

        # Should have at least the date conflict
        date_conflicts = [c for c in conflicts if c["conflict_type"] == "date_contradiction"]
        self.assertGreater(len(date_conflicts), 0)


if __name__ == "__main__":
    unittest.main()
