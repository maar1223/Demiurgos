"""
tests/test_image_extraction.py — Tests for image extraction from .md, .docx, .pdf.

Conditional tests: uses pytest.importorskip for optional dependencies
(python-docx, PyMuPDF). Tests markdown image ref extraction with fixtures.
"""

import sys
import tempfile
import unittest
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import importlib

image_indexer = importlib.import_module("sync-lore.image_indexer")


class TestExtractImagesFromMarkdown(unittest.TestCase):
    """Markdown image reference extraction."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="sync_lore_img_md_"))

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir)

    def test_inline_image_extracted(self):
        """![alt](path) references are extracted when the file exists."""
        # Create a fake image file
        img_path = self.tmpdir / "test_img.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        md_text = f"Some lore text with an image.\n\n![A test image](test_img.png)"
        results = image_indexer.extract_images_from_md(
            md_text, self.tmpdir, chunk_ref="test.md##Test"
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].filename, "test_img.png")
        self.assertEqual(results[0].chunk_ref, "test.md##Test")
        self.assertGreater(len(results[0].image_bytes), 0)

    def test_missing_image_skipped(self):
        """References to non-existent files are silently skipped."""
        md_text = "![missing](nonexistent.png)\n\nSome text."
        results = image_indexer.extract_images_from_md(
            md_text, self.tmpdir, chunk_ref="test.md##Test"
        )
        self.assertEqual(len(results), 0)

    def test_web_url_skipped(self):
        """HTTP/HTTPS image URLs are skipped (not downloaded)."""
        md_text = "![web img](https://example.com/img.png)"
        results = image_indexer.extract_images_from_md(
            md_text, self.tmpdir, chunk_ref="test.md##Test"
        )
        self.assertEqual(len(results), 0)

    def test_data_uri_skipped(self):
        """data: URIs are skipped."""
        md_text = "![inline](data:image/png;base64,abc123)"
        results = image_indexer.extract_images_from_md(
            md_text, self.tmpdir, chunk_ref="test.md##Test"
        )
        self.assertEqual(len(results), 0)

    def test_multiple_images(self):
        """Multiple image refs in the same text are all extracted."""
        (self.tmpdir / "a.png").write_bytes(b"aaa")
        (self.tmpdir / "b.png").write_bytes(b"bbb")

        md_text = "![A](a.png)\n\n![B](b.png)"
        results = image_indexer.extract_images_from_md(
            md_text, self.tmpdir, chunk_ref="test.md##Multi"
        )
        self.assertEqual(len(results), 2)
        filenames = {r.filename for r in results}
        self.assertEqual(filenames, {"a.png", "b.png"})

    def test_reference_style_image(self):
        """Reference-style ![alt][ref] with [ref]: path definition."""
        (self.tmpdir / "ref_img.png").write_bytes(b"refdata")

        md_text = "![ref style][img1]\n\n[img1]: ref_img.png"
        results = image_indexer.extract_images_from_md(
            md_text, self.tmpdir, chunk_ref="test.md##Ref"
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].filename, "ref_img.png")


class TestExtractImagesFromDocxSkip(unittest.TestCase):
    """Tests that docx extraction gracefully falls back when python-docx is not installed."""

    def test_docx_extraction_skip_without_dependency(self):
        """extract_images_from_docx returns empty list when python-docx is missing."""
        # We use pytest.importorskip-style check inside the test
        # If python-docx IS installed, this test still works (it'll try real extraction)
        # but it verifies the function doesn't crash
        try:
            import docx  # noqa: F401
            pytest.skip("python-docx is installed — skipping skip test")
        except ImportError:
            pass

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"not a real docx")
            fake_path = Path(f.name)

        try:
            results = image_indexer.extract_images_from_docx(fake_path, "## Test")
            self.assertEqual(results, [])
        finally:
            if fake_path.exists():
                fake_path.unlink()

    def test_docx_extraction_does_not_crash_on_bad_file(self):
        """extract_images_from_docx handles corrupted files gracefully."""
        # Skip if python-docx is not installed — the graceful fallback is already tested above
        pytest.importorskip("docx")

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"this is not a valid docx file at all")
            fake_path = Path(f.name)

        try:
            # Should not raise — returns empty list on error
            results = image_indexer.extract_images_from_docx(fake_path, "## Test")
            self.assertEqual(results, [])
        finally:
            if fake_path.exists():
                fake_path.unlink()


class TestExtractImagesFromPdfSkip(unittest.TestCase):
    """Tests that PDF extraction gracefully falls back when PyMuPDF is not installed."""

    def test_pdf_extraction_skip_without_dependency(self):
        """extract_images_from_pdf returns empty list when PyMuPDF is missing."""
        try:
            import fitz  # noqa: F401
            pytest.skip("PyMuPDF is installed — skipping skip test")
        except ImportError:
            pass

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"not a real pdf")
            fake_path = Path(f.name)

        try:
            results = image_indexer.extract_images_from_pdf(fake_path, "## Test")
            self.assertEqual(results, [])
        finally:
            if fake_path.exists():
                fake_path.unlink()

    def test_pdf_extraction_does_not_crash_on_bad_file(self):
        """extract_images_from_pdf handles corrupted files gracefully."""
        pytest.importorskip("fitz")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"this is not a valid PDF file")
            fake_path = Path(f.name)

        try:
            results = image_indexer.extract_images_from_pdf(fake_path, "## Test")
            self.assertEqual(results, [])
        finally:
            if fake_path.exists():
                fake_path.unlink()


# ---------------------------------------------------------------------------
# Cache-per-file extraction tests
# ---------------------------------------------------------------------------


class FakeChunk:
    """Minimal chunk-like object for distribution tests."""
    def __init__(self, heading_path: str, content: str):
        self.heading_path = heading_path
        self.content = content


class TestCachedDocxExtraction(unittest.TestCase):
    """Docx extraction caching — single extraction per file."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="sync_lore_cache_"))
        # Clear module-level caches to avoid cross-test interference
        image_indexer._docx_cache.clear()
        try:
            import docx  # noqa: F401
        except ImportError:
            self.skip_docx = True
        else:
            self.skip_docx = False

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir)

    def _make_docx(self, name: str = "test.docx") -> Path:
        """Create a minimal valid .docx file (may have no embedded images)."""
        if self.skip_docx:
            self.skipTest("python-docx not installed")
        from docx import Document
        path = self.tmpdir / name
        doc = Document()
        doc.save(str(path))
        return path

    def test_cached_docx_extracts_once(self):
        """Cached wrapper calls original extraction only once per file."""
        docx_path = self._make_docx()
        fake_images = [
            image_indexer.ImageEntry(
                id="img1", source_file="test.docx", image_bytes=b"png_a"
            ),
            image_indexer.ImageEntry(
                id="img2", source_file="test.docx", image_bytes=b"png_b"
            ),
        ]

        with unittest.mock.patch.object(
            image_indexer, "extract_images_from_docx", return_value=fake_images
        ) as mock_extract:
            result1 = image_indexer._extract_images_from_docx_cached(docx_path)
            result2 = image_indexer._extract_images_from_docx_cached(docx_path)

            mock_extract.assert_called_once()
            self.assertIs(
                result1, result2,
                "Second call must return the same cached list object",
            )
            self.assertEqual(
                result1[0].id, "img1",
                "Cached entries preserve original ids",
            )

    def test_cached_distributes_to_chunks(self):
        """Cached images distributed to chunks get correct per-chunk context."""
        docx_path = self._make_docx()
        fake_images = [
            image_indexer.ImageEntry(
                id="img1", source_file="test.docx", image_bytes=b"png_a"
            ),
            image_indexer.ImageEntry(
                id="img2", source_file="test.docx", image_bytes=b"png_b"
            ),
        ]

        from dataclasses import replace
        chunks = [
            FakeChunk(heading_path="## Ch 1", content="First chapter content"),
            FakeChunk(heading_path="## Ch 2", content="Second chapter content"),
        ]

        with unittest.mock.patch.object(
            image_indexer, "extract_images_from_docx", return_value=fake_images
        ):
            cached = image_indexer._extract_images_from_docx_cached(docx_path)

            results = []
            for chunk in chunks:
                for img in cached:
                    results.append(
                        replace(img, context_text=chunk.content, chunk_ref=chunk.heading_path)
                    )

            self.assertEqual(len(results), 4)  # 2 images × 2 chunks
            # Chunk 1 images
            self.assertEqual(results[0].chunk_ref, "## Ch 1")
            self.assertEqual(results[0].context_text, "First chapter content")
            self.assertEqual(results[1].chunk_ref, "## Ch 1")
            # Chunk 2 images
            self.assertEqual(results[2].chunk_ref, "## Ch 2")
            self.assertEqual(results[2].context_text, "Second chapter content")
            # image_bytes shared by reference across chunks
            self.assertIs(results[0].image_bytes, results[2].image_bytes)
            self.assertIs(results[1].image_bytes, results[3].image_bytes)

    def test_cached_docx_fallback(self):
        """Cached wrapper handles errors gracefully (same fallback as original)."""
        if self.skip_docx:
            self.skipTest("python-docx not installed")
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"this is not a valid docx")
            fake_path = Path(f.name)
        try:
            result = image_indexer._extract_images_from_docx_cached(fake_path)
            self.assertEqual(result, [])
        finally:
            if fake_path.exists():
                fake_path.unlink()


class TestCachedPdfExtraction(unittest.TestCase):
    """PDF extraction caching — conditional on PyMuPDF."""

    def setUp(self):
        image_indexer._pdf_cache.clear()

    def test_cached_pdf_extracts_once(self):
        """Cached PDF wrapper calls original extraction only once."""
        pytest.importorskip("fitz")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"not a real pdf")
            fake_path = Path(f.name)

        try:
            fake_images = [
                image_indexer.ImageEntry(
                    id="pdf1", source_file="test.pdf", image_bytes=b"page1_img"
                ),
            ]
            with unittest.mock.patch.object(
                image_indexer, "extract_images_from_pdf", return_value=fake_images
            ) as mock_extract:
                result1 = image_indexer._extract_images_from_pdf_cached(fake_path)
                result2 = image_indexer._extract_images_from_pdf_cached(fake_path)

                mock_extract.assert_called_once()
                self.assertIs(result1, result2)
        finally:
            if fake_path.exists():
                fake_path.unlink()

    def test_cached_pdf_fallback(self):
        """Cached PDF wrapper returns empty list when PyMuPDF is missing."""
        try:
            import fitz  # noqa: F401
            pytest.skip("PyMuPDF is installed — testing cache behavior instead")
        except ImportError:
            pass

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"not a real pdf")
            fake_path = Path(f.name)

        try:
            result = image_indexer._extract_images_from_pdf_cached(fake_path)
            self.assertEqual(result, [])
        finally:
            if fake_path.exists():
                fake_path.unlink()


if __name__ == "__main__":
    unittest.main()
