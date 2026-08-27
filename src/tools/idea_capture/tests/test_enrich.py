"""Enrich provider tests: mandatory type classification, fail-open (R-CG-02).

The provider must NEVER block or crash the capture: any timeout, exception, or
unknown classification falls back to ``sin_clasificar`` while the body is
preserved.
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
)


class EnrichProviderTests(unittest.TestCase):
    def test_success_path_returns_body_and_classified_type(self):
        provider = HermesEnrichProvider(hermes=lambda raw: "trama")
        result = provider("  una trama genial  ")
        self.assertIsInstance(result, EnrichResult)
        self.assertEqual(result.body, "una trama genial")
        self.assertEqual(result.type, "trama")
        # A legacy string-returning classifier yields an empty title.
        self.assertEqual(result.title, "")
        # The result is a 3-tuple, so the processor seam unpacks it.
        self.assertEqual(tuple(result), ("una trama genial", "trama", ""))

    def test_tuple_classifier_yields_label_and_title(self):
        provider = HermesEnrichProvider(hermes=lambda raw: ("trama", "La conspiración"))
        result = provider("una trama genial")
        self.assertEqual(result.type, "trama")
        self.assertEqual(result.title, "La conspiración")
        self.assertEqual(tuple(result), ("una trama genial", "trama", "La conspiración"))

    def test_exception_fails_open_to_sin_clasificar_and_empty_title(self):
        def exploding(_raw):
            raise RuntimeError("hermes down")

        provider = HermesEnrichProvider(hermes=exploding)
        result = provider("idea con clasificador caido")
        self.assertEqual(result.body, "idea con clasificador caido")
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
        self.assertEqual(result.body, "idea lenta")
        self.assertEqual(result.type, DEFAULT_TYPE)
        self.assertEqual(result.title, "")

    def test_missing_hermes_fails_open(self):
        provider = HermesEnrichProvider()
        result = provider("sin proveedor")
        self.assertEqual(result.type, DEFAULT_TYPE)
        self.assertEqual(result.title, "")

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


if __name__ == "__main__":
    unittest.main()