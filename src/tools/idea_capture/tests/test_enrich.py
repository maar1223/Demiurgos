"""Enrich provider tests: mandatory type classification, fail-open (R-CG-02).

The provider must NEVER block or crash the capture: any timeout, exception, or
unknown classification falls back to ``sin_clasificar`` while the raw content
is preserved. Every provider produces a STRUCTURED body (``## Descripción`` +
``## Detalles`` + optional ``## Notas``) — from the classifier's own markdown
when provided, else via the local ``_structure_body`` fallback — so ideas in
the bank are always scannable.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from idea_capture.enrich import (  # noqa: E402
    DEFAULT_TYPE,
    TYPE_TAXONOMY,
    EnrichResult,
    HermesEnrichProvider,
    _derive_bullets,
    _structure_body,
)


class EnrichProviderTests(unittest.TestCase):
    def test_success_path_returns_structured_body_and_classified_type(self):
        provider = HermesEnrichProvider(hermes=lambda raw: "trama")
        result = provider("  una trama genial  ")
        self.assertIsInstance(result, EnrichResult)
        self.assertEqual(result.type, "trama")
        # A legacy string-returning classifier yields an empty title AND a
        # locally structured body (fail-open compatibility).
        self.assertEqual(result.title, "")
        self.assertTrue(result.body.startswith("## Descripción"))
        self.assertIn("una trama genial", result.body)
        # The result is still a 3-tuple, so the processor seam unpacks it.
        self.assertEqual(tuple(result)[0], result.body)
        self.assertEqual(len(tuple(result)), 3)

    def test_tuple_classifier_yields_label_and_title(self):
        provider = HermesEnrichProvider(hermes=lambda raw: ("trama", "La conspiración"))
        result = provider("una trama genial")
        self.assertEqual(result.type, "trama")
        self.assertEqual(result.title, "La conspiración")
        self.assertTrue(result.body.startswith("## Descripción"))
        self.assertIn("una trama genial", result.body)

    def test_classifier_structured_body_is_used_verbatim(self):
        structured = "## Descripción\n\nuna trama genial\n\n## Detalles\n\n- giro final"
        provider = HermesEnrichProvider(
            hermes=lambda raw: ("trama", "La conspiración", structured, ["giro final"]))
        result = provider("una trama genial")
        self.assertEqual(result.body, structured)
        self.assertEqual(result.type, "trama")
        self.assertEqual(result.title, "La conspiración")

    def test_details_list_structures_body_when_no_body_field(self):
        provider = HermesEnrichProvider(
            hermes=lambda raw: ("concepto", "Mapa", "", ["un mapa", "tesoros"]))
        result = provider("un mapa con tesoros")
        self.assertTrue(result.body.startswith("## Descripción"))
        self.assertIn("## Detalles", result.body)
        self.assertIn("- un mapa", result.body)
        self.assertIn("- tesoros", result.body)

    def test_exception_fails_open_to_sin_clasificar_and_empty_title(self):
        def exploding(_raw):
            raise RuntimeError("hermes down")

        provider = HermesEnrichProvider(hermes=exploding)
        result = provider("idea con clasificador caido")
        self.assertTrue(result.body.startswith("## Descripción"))
        self.assertIn("idea con clasificador caido", result.body)
        self.assertEqual(result.type, DEFAULT_TYPE)
        self.assertEqual(result.title, "")

    def test_timeout_fails_open_to_sin_clasificar_and_empty_title(self):
        def slow(_raw):
            time.sleep(0.5)
            return ("personaje", "El personaje")

        provider = HermesEnrichProvider(hermes=slow, timeout_seconds=0.1)
        start = time.monotonic()
        result = provider("idea lenta")
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.0, "timeout must bound the call")
        self.assertTrue(result.body.startswith("## Descripción"))
        self.assertIn("idea lenta", result.body)
        self.assertEqual(result.type, DEFAULT_TYPE)
        self.assertEqual(result.title, "")

    def test_missing_hermes_fails_open(self):
        provider = HermesEnrichProvider()
        result = provider("sin proveedor")
        self.assertEqual(result.type, DEFAULT_TYPE)
        self.assertEqual(result.title, "")
        self.assertIn("sin proveedor", result.body)

    def test_unknown_classification_fails_open(self):
        provider = HermesEnrichProvider(hermes=lambda raw: "not-a-type")
        result = provider("clasificacion rara")
        self.assertEqual(result.type, DEFAULT_TYPE)
        self.assertEqual(result.title, "")

    def test_every_taxonomy_value_is_accepted(self):
        for expected in TYPE_TAXONOMY:
            provider = HermesEnrichProvider(hermes=lambda raw, t=expected: t)
            self.assertEqual(provider("x").type, expected)

    def test_bytes_input_has_no_body_and_never_raises(self):
        provider = HermesEnrichProvider()
        result = provider(b"\x89PNG raw-bytes")
        self.assertEqual(result.body, "")
        self.assertEqual(result.type, DEFAULT_TYPE)

    def test_empty_body_preserves_fail_open_semantics(self):
        provider = HermesEnrichProvider(hermes=lambda raw: "")
        result = provider("   ")
        self.assertEqual(result.body, "")
        self.assertEqual(result.type, DEFAULT_TYPE)
        self.assertEqual(result.title, "")


class StructureBodyTests(unittest.TestCase):
    def test_scheme_with_description_details_and_notes(self):
        body = _structure_body("una idea", bullets=["clave 1", "clave 2"],
                               notes="a desarrollar")
        self.assertIn("## Descripción\n\nuna idea", body)
        self.assertIn("## Detalles\n\n- clave 1\n- clave 2", body)
        self.assertIn("## Notas\n\na desarrollar", body)

    def test_details_and_notes_are_optional(self):
        body = _structure_body("solo texto")
        self.assertEqual(body, "## Descripción\n\nsolo texto")
        self.assertNotIn("## Detalles", body)
        self.assertNotIn("## Notas", body)

    def test_empty_text_returns_empty(self):
        self.assertEqual(_structure_body(""), "")
        self.assertEqual(_structure_body("   "), "")
        self.assertEqual(_structure_body("", bullets=["x"]), "## Detalles\n\n- x")

    def test_bullet_newlines_are_collapsed(self):
        body = _structure_body("idea", bullets=["clave\ncon salto"])
        self.assertIn("- clave con salto", body)
        self.assertNotIn("\n- clave\ncon salto", body)

    def test_derive_bullets_splits_sentences(self):
        bullets = _derive_bullets("Primera frase. Segunda frase. Tercera. Cuarta.")
        self.assertEqual(bullets, ["Primera frase.", "Segunda frase.", "Tercera."])
        self.assertEqual(_derive_bullets(""), [])
        self.assertEqual(_derive_bullets("solo una"), ["solo una"])


if __name__ == "__main__":
    unittest.main()