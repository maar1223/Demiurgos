"""
tests/test_provider_mock.py — Integration tests with a mock ProviderAdapter.

Tests that the pipeline correctly handles provider responses without
making real LLM calls.
"""

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import importlib

schemas = importlib.import_module("sync-lore.schemas")
providers_base = importlib.import_module("sync-lore.providers.base")
parallel = importlib.import_module("sync-lore.utils.parallel")


class MockProvider(providers_base.ProviderAdapter):
    """Mock provider that returns predefined results."""

    def __init__(self, config=None):
        if config is None:
            config = schemas.ProviderConfig()
        self._config = config
        self._text_results: dict[str, providers_base.ChunkResult] = {}
        self._image_results: dict[str, providers_base.ImageAnalysis] = {}
        self.text_calls = 0
        self.image_calls = 0

    @property
    def config(self):
        return self._config

    async def analyze_text(self, chunk):
        self.text_calls += 1
        key = chunk.heading_path
        if key in self._text_results:
            return self._text_results[key]
        return providers_base.ChunkResult()

    async def analyze_image(self, image: bytes, context: str):
        self.image_calls += 1
        # Return a simple analysis
        return providers_base.ImageAnalysis(
            descripcion="Mocked image analysis",
            veredicto="no_aplica",
            tags=["mock"],
        )

    def set_text_result(self, heading_path: str, result: providers_base.ChunkResult):
        self._text_results[heading_path] = result


class TestMockProvider(unittest.TestCase):
    """Mock provider returns expected results."""

    def test_mock_creates_provider(self):
        provider = MockProvider()
        self.assertIsInstance(provider, providers_base.ProviderAdapter)

    def test_mock_analyze_text_empty(self):
        provider = MockProvider()
        chunk = schemas.Chunk(
            id="test-1",
            source_file="test.md",
            heading_path="## Test",
            content="Hello",
            token_count=1,
        )
        result = asyncio.run(provider.analyze_text(chunk))
        self.assertIsInstance(result, providers_base.ChunkResult)
        self.assertEqual(result.entities, [])

    def test_mock_analyze_text_with_data(self):
        provider = MockProvider()
        provider.set_text_result("## Kaelen", providers_base.ChunkResult(
            entities=[{"name": "Kaelen", "type": "personaje", "description": "A warrior"}],
            terms=[{"term": "Staler", "definition": "Immortal being"}],
        ))
        chunk = schemas.Chunk(
            id="test-2",
            source_file="test.md",
            heading_path="## Kaelen",
            content="Kaelen is a warrior.",
            token_count=4,
        )
        result = asyncio.run(provider.analyze_text(chunk))
        self.assertEqual(len(result.entities), 1)
        self.assertEqual(result.entities[0]["name"], "Kaelen")
        self.assertEqual(len(result.terms), 1)

    def test_mock_analyze_image(self):
        provider = MockProvider()
        result = asyncio.run(
            provider.analyze_image(b"fake_image_bytes", "context text")
        )
        self.assertIsInstance(result, providers_base.ImageAnalysis)
        self.assertEqual(result.descripcion, "Mocked image analysis")
        self.assertEqual(result.veredicto, "no_aplica")
        self.assertEqual(result.tags, ["mock"])

    def test_mock_call_counting(self):
        provider = MockProvider()
        self.assertEqual(provider.text_calls, 0)
        self.assertEqual(provider.image_calls, 0)
        chunk = schemas.Chunk(
            id="test-3",
            source_file="test.md",
            heading_path="## Test",
            content="Text",
            token_count=1,
        )
        asyncio.run(provider.analyze_text(chunk))
        asyncio.run(provider.analyze_image(b"img", "ctx"))
        self.assertEqual(provider.text_calls, 1)
        self.assertEqual(provider.image_calls, 1)


class TestProcessChunksAsync(unittest.TestCase):
    """Parallel processing with mock provider."""

    def test_empty_chunks(self):
        provider = MockProvider()
        results = asyncio.run(
            parallel.process_chunks_async([], provider, max_workers=2)
        )
        self.assertEqual(results, [])

    def test_single_chunk(self):
        provider = MockProvider()
        provider.set_text_result("## Test", providers_base.ChunkResult(
            entities=[{"name": "Test"}],
        ))
        chunks = [
            schemas.Chunk(
                id="c1",
                source_file="test.md",
                heading_path="## Test",
                content="Text",
                token_count=1,
            )
        ]
        results = asyncio.run(
            parallel.process_chunks_async(chunks, provider, max_workers=2)
        )
        self.assertEqual(len(results), 1)
        chunk, cr = results[0]
        self.assertEqual(len(cr.entities), 1)

    def test_multiple_chunks(self):
        provider = MockProvider()
        for i in range(5):
            provider.set_text_result(
                f"## Chunk{i}",
                providers_base.ChunkResult(
                    entities=[{"name": f"Entity{i}"}],
                ),
            )
        chunks = [
            schemas.Chunk(
                id=f"c{i}",
                source_file="test.md",
                heading_path=f"## Chunk{i}",
                content=f"Content {i}",
                token_count=1,
            )
            for i in range(5)
        ]
        results = asyncio.run(
            parallel.process_chunks_async(chunks, provider, max_workers=3)
        )
        self.assertEqual(len(results), 5)
        self.assertEqual(provider.text_calls, 5)


class TestProcessImagesAsync(unittest.TestCase):
    """Parallel image processing with mock provider."""

    def test_empty_images(self):
        provider = MockProvider()
        results = asyncio.run(
            parallel.process_images_async([], provider, max_workers=2)
        )
        self.assertEqual(results, [])

    def test_single_image(self):
        provider = MockProvider()
        images = [
            schemas.ImageEntry(
                id="img1",
                source_file="test.md",
                filename="test.png",
                image_bytes=b"fake",
                context_text="context",
            )
        ]
        results = asyncio.run(
            parallel.process_images_async(images, provider, max_workers=2)
        )
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].analysis)
        self.assertEqual(results[0].analysis.descripcion, "Mocked image analysis")


if __name__ == "__main__":
    unittest.main()
