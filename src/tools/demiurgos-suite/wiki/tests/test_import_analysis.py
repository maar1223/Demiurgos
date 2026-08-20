# -*- coding: utf-8 -*-
"""World importer — PR1 (sync-lore-in-importer) tests for the safe
conversion seam and image extraction integration.

Covers tasks 1.1-1.6 (Phase 1: safe conversion + .md identity
normalization) and 2.1-2.5 (Phase 2: reuse of sync_lore extraction
adapters, spool persistence, and fail-open behavior). All conversion and
extraction seams are mocked — no markitdown/python-docx/PyMuPDF required.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_TOOLS = _HERE.parents[2]
for _p in (str(_WIKI), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_analysis import (  # noqa: E402
    analyze_markdown,
    analyze_source,
    extract_images_from_file,
    normalized_identity_path,
    safe_convert_to_markdown,
    store_media_in_spool,
)
from import_models import (  # noqa: E402
    Candidate,
    Provenance,
)
from sync_lore.schemas import ImageEntry  # noqa: E402


def _entry(filename: str = "pic.png", page: int | None = 1,
           data: bytes = b"\x89PNG\r\n\x1a\nfake",
           source_file: str = "Lore/Enciclopedia.docx") -> ImageEntry:
    """Build a minimal sync_lore ImageEntry for tests."""
    return ImageEntry(
        id=str(uuid.uuid4()),
        source_file=source_file,
        page=page,
        chunk_ref="",
        context_text="",
        filename=filename,
        image_bytes=data,
    )


def _read_file(root: Path):
    """Mirror the router's read_file closure (binaries yield '')."""
    def read(relative: str) -> str:
        try:
            return (root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""
    return read


def _path_for(root: Path):
    return lambda relative: root / relative


# ---------------------------------------------------------------------------
# Phase 1 — safe conversion seam
# ---------------------------------------------------------------------------


class TestSafeConversion:
    def test_systemexit_from_missing_markitdown_is_caught(self, monkeypatch):
        """Task 1.1/1.5 — SystemExit(1) never propagates out of the seam."""
        def _die(_path):
            raise SystemExit(1)
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", _die)
        text, images = safe_convert_to_markdown(Path("Lore/Enciclopedia.docx"))
        assert text is None
        assert images == []

    def test_systemexit_yields_empty_reviewable_analysis(
            self, monkeypatch, tmp_path):
        """Task 1.5 — server stays alive; diagnostics recorded."""
        def _die(_path):
            raise SystemExit(1)
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", _die)
        (tmp_path / "Lore").mkdir(parents=True)
        (tmp_path / "Lore" / "Enciclopedia.docx").write_bytes(b"PK..fake")
        files = [{"relative": "Lore/Enciclopedia.docx",
                  "sha256": "abc", "size": 8}]
        report = analyze_source(files, _read_file(tmp_path),
                                file_path=_path_for(tmp_path))
        analyzed = report.ordered_files()[0]
        assert analyzed.content_preview() == ""
        assert analyzed.diagnostics == ["conversion_unavailable"]
        assert analyzed.source_path == "Lore/Enciclopedia.md"

    def test_converter_exception_fail_open(self, monkeypatch, tmp_path):
        """Task 1.5 — a converter error yields an empty candidate, not a job
        failure and not an exception."""
        def _boom(_path):
            raise RuntimeError("markitdown exploded")
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", _boom)
        (tmp_path / "Lore").mkdir(parents=True)
        (tmp_path / "Lore" / "Enciclopedia.docx").write_bytes(b"PK..fake")
        files = [{"relative": "Lore/Enciclopedia.docx",
                  "sha256": "abc", "size": 8}]
        report = analyze_source(files, _read_file(tmp_path),
                                file_path=_path_for(tmp_path))
        analyzed = report.ordered_files()[0]
        assert analyzed.content_preview() == ""
        assert "conversion_failed" in analyzed.diagnostics

    def test_docx_converts_to_md_identity(self, monkeypatch, tmp_path):
        """Tasks 1.3/1.4/1.6 — .docx is dispatched to the converter and the
        candidate identity uses the .md extension."""
        called_with: list[Path] = []

        def _convert(path):
            called_with.append(Path(path))
            return "# Enciclopedia\n\nBody text here"
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", _convert)
        monkeypatch.setattr(
            "import_analysis.extract_images_from_file",
            lambda _p: [])
        (tmp_path / "Lore").mkdir(parents=True)
        (tmp_path / "Lore" / "Enciclopedia.docx").write_bytes(b"PK..fake")
        files = [{"relative": "Lore/Enciclopedia.docx",
                  "sha256": "abc", "size": 8}]
        report = analyze_source(files, _read_file(tmp_path),
                                file_path=_path_for(tmp_path))
        analyzed = report.ordered_files()[0]
        assert called_with == [tmp_path / "Lore" / "Enciclopedia.docx"]
        assert analyzed.source_path == "Lore/Enciclopedia.md"
        assert "Body text here" in analyzed.content_preview()
        assert analyzed.diagnostics == []

    def test_md_bypasses_conversion_unchanged(self, monkeypatch, tmp_path):
        """Task 1.6 — .md sources never reach the converter and keep their
        identity and chunk flow."""
        def _must_not_convert(_path):
            raise AssertionError("converter must not run for .md")
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", _must_not_convert)
        (tmp_path / "lore").mkdir(parents=True)
        (tmp_path / "lore" / "City.md").write_text(
            "# City\n\nThe capital.", encoding="utf-8")
        files = [{"relative": "lore/City.md", "sha256": "abc", "size": 15}]
        report = analyze_source(files, _read_file(tmp_path),
                                file_path=_path_for(tmp_path))
        analyzed = report.ordered_files()[0]
        assert analyzed.source_path == "lore/City.md"
        assert analyzed.diagnostics == []
        assert "The capital." in analyzed.content_preview()

    def test_analyze_source_legacy_two_arg_flow(self, tmp_path):
        """Preserve existing functionality — without a file_path resolver the
        legacy flow is untouched (binaries yield empty candidates, markdown
        is analyzed from read_file text)."""
        (tmp_path / "lore").mkdir(parents=True)
        (tmp_path / "lore" / "City.md").write_text(
            "# City\n\nThe capital.", encoding="utf-8")
        # Real .docx bytes are invalid UTF-8 so read_text raises, mirroring
        # the router's read_file closure (binary -> "").
        (tmp_path / "Lore" / "Enciclopedia.docx").parent.mkdir(parents=True)
        (tmp_path / "Lore" / "Enciclopedia.docx").write_bytes(
            b"\xff\xfe\x00binary-docx")
        files = [
            {"relative": "lore/City.md", "sha256": "abc", "size": 15},
            {"relative": "Lore/Enciclopedia.docx", "sha256": "def", "size": 8},
        ]
        report = analyze_source(files, _read_file(tmp_path))
        md, docx = report.ordered_files()
        assert md.source_path == "lore/City.md"
        assert "The capital." in md.content_preview()
        assert md.media == [] and md.diagnostics == []
        # Binary without the seam: empty candidate, no conversion, no media.
        assert docx.source_path == "Lore/Enciclopedia.docx"
        assert docx.content_preview() == ""
        assert docx.media == [] and docx.diagnostics == []

    def test_normalized_identity_path(self):
        """Task 1.4 — .docx/.pdf normalize to .md; everything else is kept."""
        assert normalized_identity_path("Lore/Enciclopedia.docx") == \
            "Lore/Enciclopedia.md"
        assert normalized_identity_path("Lore/Map.pdf") == "Lore/Map.md"
        assert normalized_identity_path("lore/City.md") == "lore/City.md"
        assert normalized_identity_path("notes.txt") == "notes.txt"

    def test_resolve_target_uses_normalized_identity(self):
        """Task 1.4 contract — resolve_target needs the .md identity; a raw
        .docx provenance would land in review as non-markdown."""
        def candidate_with(source_path: str) -> Candidate:
            return Candidate(
                candidate_id="c1", job_id="j1", world="w1",
                normalized_identity="Enciclopedia",
                source_hash="sha256:abc",
                provenance=Provenance(
                    source_path=source_path, source_kind="loose",
                    source_hash="sha256:abc"),
                content_preview="x",
            )
        from import_analysis import resolve_target
        resolved = resolve_target("w1", candidate_with("Lore/Enciclopedia.md"))
        assert resolved.status == "resolved"
        assert resolved.canonical_path == "lore/Enciclopedia.md"
        rejected = resolve_target("w1", candidate_with("Lore/Enciclopedia.docx"))
        assert rejected.status == "review"
        assert "non-markdown" in rejected.diagnostic


# ---------------------------------------------------------------------------
# Phase 2 — image extraction integration
# ---------------------------------------------------------------------------


class TestImageExtraction:
    def test_extract_images_from_md_file(self, tmp_path):
        """Task 2.1/2.2 — markdown disk references yield ImageEntry bytes."""
        (tmp_path / "img.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        md_file = tmp_path / "note.md"
        md_file.write_text("![portrait](img.png)\n\nSome lore.",
                           encoding="utf-8")
        images = extract_images_from_file(md_file)
        assert len(images) == 1
        assert images[0].filename == "img.png"
        assert images[0].image_bytes == b"\x89PNG\r\n\x1a\nfake"

    def test_extract_images_from_docx_dispatch(self, monkeypatch):
        """Task 2.2 — .docx dispatches to the sync_lore docx adapter."""
        expected = [_entry(filename="inline.png", page=None)]
        monkeypatch.setattr(
            "sync_lore.image_indexer.extract_images_from_docx",
            lambda _p: expected)
        images = extract_images_from_file(Path("Lore/Enciclopedia.docx"))
        assert images == expected
        assert images[0].filename == "inline.png"

    def test_extract_images_from_pdf_dispatch(self, monkeypatch):
        """Task 2.2 — .pdf dispatches to the sync_lore pdf adapter."""
        expected = [_entry(filename="page3.png", page=3)]
        monkeypatch.setattr(
            "sync_lore.image_indexer.extract_images_from_pdf",
            lambda _p: expected)
        images = extract_images_from_file(Path("Lore/Map.pdf"))
        assert images == expected
        assert images[0].page == 3

    def test_extract_images_from_unknown_suffix(self):
        """Unsupported formats yield no images (fail-open)."""
        assert extract_images_from_file(Path("notes.txt")) == []

    def test_media_stored_in_spool_with_metadata(
            self, monkeypatch, tmp_path):
        """Tasks 2.3/2.4 — extracted bytes land in the spool and metadata is
        attached to the AnalyzedFile for downstream consumption."""
        def _convert(_path):
            return "# Enciclopedia\n\nBody"
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", _convert)
        entries = [
            _entry(filename="portada.png", page=None,
                   data=b"PORTADA-BYTES"),
            _entry(filename="mapa.png", page=1, data=b"MAPA-BYTES"),
        ]
        monkeypatch.setattr(
            "import_analysis.extract_images_from_file", lambda _p: entries)
        spool = tmp_path / "spool"
        (spool / "Lore").mkdir(parents=True)
        (spool / "Lore" / "Enciclopedia.docx").write_bytes(b"PK..fake")
        files = [{"relative": "Lore/Enciclopedia.docx",
                  "sha256": "abc", "size": 8}]
        report = analyze_source(files, _read_file(spool),
                                file_path=_path_for(spool),
                                spool_root=spool)
        analyzed = report.ordered_files()[0]
        assert len(analyzed.media) == 2
        # Bytes persisted under <spool>/media/<stem>/<filename>.
        stored = spool / "media" / "Enciclopedia" / "portada.png"
        assert stored.read_bytes() == b"PORTADA-BYTES"
        assert (spool / "media" / "Enciclopedia" / "mapa.png").exists()
        first = analyzed.media[0]
        assert first.spool_relative_path == \
            "media/Enciclopedia/portada.png"
        assert first.image.filename == "portada.png"
        assert first.image.image_bytes == b"PORTADA-BYTES"
        # Metadata survives on the bundle: source, page, filename, bytes.
        second = analyzed.media[1]
        assert second.image.source_file == "Lore/Enciclopedia.docx"
        assert second.image.page == 1
        assert second.image.filename == "mapa.png"

    def test_spool_collision_avoids_overwrite(self, tmp_path):
        """Task 2.3 — duplicate filenames get a counter suffix, never
        overwrite an existing spool file."""
        spool = tmp_path / "spool"
        entries = [
            _entry(filename="pic.png", data=b"FIRST"),
            _entry(filename="pic.png", data=b"SECOND"),
        ]
        stored = store_media_in_spool(entries, "Lore/Enciclopedia.docx", spool)
        assert len(stored) == 2
        paths = [m.spool_relative_path for m in stored]
        assert "media/Enciclopedia/pic.png" in paths
        assert "media/Enciclopedia/pic-1.png" in paths
        assert (spool / "media" / "Enciclopedia" / "pic.png").read_bytes() \
            == b"FIRST"
        assert (spool / "media" / "Enciclopedia" / "pic-1.png").read_bytes() \
            == b"SECOND"

    def test_extraction_failure_does_not_block_analysis(
            self, monkeypatch, tmp_path):
        """Task 2.5 — an extraction failure leaves the converted candidate
        intact and records a diagnostic."""
        def _convert(_path):
            return "# Enciclopedia\n\nBody"
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", _convert)

        def _boom(_path):
            raise RuntimeError("docx adapter broke")
        monkeypatch.setattr(
            "import_analysis.extract_images_from_file", _boom)
        spool = tmp_path / "spool"
        (spool / "Lore").mkdir(parents=True)
        (spool / "Lore" / "Enciclopedia.docx").write_bytes(b"PK..fake")
        files = [{"relative": "Lore/Enciclopedia.docx",
                  "sha256": "abc", "size": 8}]
        report = analyze_source(files, _read_file(spool),
                                file_path=_path_for(spool))
        analyzed = report.ordered_files()[0]
        assert "Body" in analyzed.content_preview()
        assert analyzed.media == []
        assert "media_extraction_failed" in analyzed.diagnostics

    def test_md_extraction_failure_non_blocking(self, monkeypatch, tmp_path):
        """Task 2.5 — markdown disk-ref extraction failure is also non-fatal."""
        def _boom(_path):
            raise RuntimeError("md reader broke")
        monkeypatch.setattr(
            "import_analysis.extract_images_from_file", _boom)
        (tmp_path / "lore").mkdir(parents=True)
        (tmp_path / "lore" / "City.md").write_text(
            "# City\n\nThe capital.", encoding="utf-8")
        files = [{"relative": "lore/City.md", "sha256": "abc", "size": 15}]
        report = analyze_source(files, _read_file(tmp_path),
                                file_path=_path_for(tmp_path))
        analyzed = report.ordered_files()[0]
        assert "The capital." in analyzed.content_preview()
        assert analyzed.source_path == "lore/City.md"
        assert "media_extraction_failed" in analyzed.diagnostics


# ---------------------------------------------------------------------------
# Regression guard — analyze_markdown and chunking are untouched
# ---------------------------------------------------------------------------


class TestExistingFlowPreserved:
    def test_analyze_markdown_unchanged(self):
        """The core chunker keeps its contract: headings, order, anchors."""
        text = "# City\n\nThe capital.\n\n## Districts\n\nOld town."
        analyzed = analyze_markdown(text, "lore/City.md", "abc", 42)
        assert analyzed.source_path == "lore/City.md"
        assert len(analyzed.chunks) == 2
        assert analyzed.chunks[0].heading_path == "City"
        assert analyzed.chunks[0].nearby_text_anchor == "The capital."
        assert analyzed.media == [] and analyzed.diagnostics == []