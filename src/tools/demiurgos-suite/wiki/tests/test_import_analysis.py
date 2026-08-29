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
    resolve_target,
    safe_convert_to_markdown,
    slug_segment,
    store_media_in_spool,
    strip_broken_data_uris,
)
from import_models import (  # noqa: E402
    Candidate,
    ImagePlacement,
    Provenance,
)
from sync_lore.import_docx_parser import ExtractionResult  # noqa: E402
from sync_lore.schemas import ImageEntry  # noqa: E402


def _entry(filename: str = "pic.png", page: int | None = 1,
           data: bytes = b"\x89PNG\r\n\x1a\nfake",
           source_file: str = "Lore/Enciclopedia.docx",
           document_order: int = 0, paragraph_index: int = 0,
           anchor_type: str = "", structural_path: str = "",
           heading_path: str = "", context_text: str = "",
           warnings: list[str] | None = None) -> ImageEntry:
    """Build a minimal sync_lore ImageEntry for tests."""
    return ImageEntry(
        id=str(uuid.uuid4()),
        source_file=source_file,
        page=page,
        chunk_ref="",
        context_text=context_text,
        filename=filename,
        image_bytes=data,
        document_order=document_order,
        paragraph_index=paragraph_index,
        anchor_type=anchor_type,
        structural_path=structural_path,
        heading_path=heading_path,
        section_context=context_text,
        warnings=list(warnings or []),
    )


def _strategy_result(entries: list[ImageEntry], markdown: str = "",
                     diagnostics: list[str] | None = None,
                     warnings: list[str] | None = None) -> ExtractionResult:
    """Build the typed outcome the DOCX strategy returns (PR2 seam)."""
    return ExtractionResult(
        images=entries,
        markdown=markdown,
        diagnostics=list(diagnostics or []),
        warnings=list(warnings or []),
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


class TestStripBrokenDataUris:
    """markitdown emits truncated ``data:image/...;base64...`` placeholders for
    large embedded docx images; they must be stripped from the ficha body so
    they never render as "Imagen no disponible"."""

    def test_strips_truncated_data_uri_from_prose(self):
        text = ("**Nombre:** *Armonizador Stalico*"
                "![](data:image/png;base64...)")
        assert strip_broken_data_uris(text) == \
            "**Nombre:** *Armonizador Stalico*"

    def test_strips_alt_and_jpeg_placeholder(self):
        assert strip_broken_data_uris("![alt](data:image/jpeg;base64...)") == ""

    def test_keeps_media_ref_and_real_data_uri(self):
        text = ("![real](wiki/media/image1.png)  and  "
                "![ok](data:image/png;base64,iVBORw0KGgo=)")
        assert strip_broken_data_uris(text) == text

    def test_empty_and_plain_passthrough(self):
        assert strip_broken_data_uris("") == ""
        assert strip_broken_data_uris("no images here") == "no images here"


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
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": _strategy_result(
                [], markdown=converted_markdown))
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
        is analyzed from read_file text). Uses a non-case-colliding sibling
        dir (portable fixture, R-CIM-07): `Lore`/`lore` are the same physical
        directory on case-insensitive filesystems."""
        (tmp_path / "lore").mkdir(parents=True)
        (tmp_path / "lore" / "City.md").write_text(
            "# City\n\nThe capital.", encoding="utf-8")
        # Real .docx bytes are invalid UTF-8 so read_text raises, mirroring
        # the router's read_file closure (binary -> "").
        (tmp_path / "fuentes").mkdir(parents=True)
        (tmp_path / "fuentes" / "Enciclopedia.docx").write_bytes(
            b"\xff\xfe\x00binary-docx")
        files = [
            {"relative": "lore/City.md", "sha256": "abc", "size": 15},
            {"relative": "fuentes/Enciclopedia.docx", "sha256": "def", "size": 8},
        ]
        report = analyze_source(files, _read_file(tmp_path))
        md, docx = report.ordered_files()
        assert md.source_path == "lore/City.md"
        assert "The capital." in md.content_preview()
        assert md.media == [] and md.diagnostics == []
        # Binary without the seam: empty candidate, no conversion, no media.
        assert docx.source_path == "fuentes/Enciclopedia.docx"
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

    def test_resolve_target_section_priority_branch(self):
        """BLOQUE 1 piece 1 — a non-empty ``candidate.section`` roots the
        target under that section (before the legacy source-path branch);
        an empty section falls through to the legacy branch unchanged."""
        def candidate_with(source_path: str, section: str = "") -> Candidate:
            return Candidate(
                candidate_id="c1", job_id="j1", world="w1",
                normalized_identity="Enciclopedia",
                source_hash="sha256:abc",
                provenance=Provenance(
                    source_path=source_path, source_kind="loose",
                    source_hash="sha256:abc"),
                content_preview="x",
                section=section,
            )
        from import_analysis import resolve_target
        # Non-empty section → root = section.
        chosen = resolve_target(
            "w1", candidate_with("Enciclopedia.md", section="personajes"))
        assert chosen.status == "resolved"
        assert chosen.canonical_path == "personajes/Enciclopedia.md"
        # Section wins even over a conflicting legacy alias path.
        wins = resolve_target(
            "w1", candidate_with("Lore/Places/City.md", section="referencias"))
        assert wins.status == "resolved"
        assert wins.canonical_path == "referencias/City.md"
        # Empty section → legacy branch (uppercase normalization) unchanged.
        legacy = resolve_target("w1", candidate_with("Lore/Dottua.md"))
        assert legacy.status == "resolved"
        assert legacy.canonical_path == "lore/Dottua.md"


# ---------------------------------------------------------------------------
# BLOQUE 1 piece 2 — slug_segment helper (identity-path-mapping)
# ---------------------------------------------------------------------------


class TestSlugSegment:
    """``slug_segment`` — NFD decompose, drop combining marks (Mn),
    lowercase, collapse runs of non-[a-z0-9] to ``-``, trim. Pure and
    deterministic; empty/all-punctuation input returns ""."""

    def test_accent_stripped(self):
        assert slug_segment("Política") == "politica"

    def test_leading_accent(self):
        assert slug_segment("Áyagars") == "ayagars"

    def test_ordinal_preserved(self):
        assert slug_segment("1er Stal#2") == "1er-stal-2"

    def test_spaces_collapsed(self):
        assert slug_segment("Distribución Y Territorios") == \
            "distribucion-y-territorios"

    def test_pipe_collapsed(self):
        assert slug_segment("Política | Distribución") == \
            "politica-distribucion"

    def test_empty_returns_empty(self):
        assert slug_segment("") == ""

    def test_all_punctuation_returns_empty(self):
        assert slug_segment("---") == ""
        assert slug_segment("!!!") == ""

    def test_already_slug_passthrough(self):
        assert slug_segment("sistema-stal") == "sistema-stal"


# ---------------------------------------------------------------------------
# BLOQUE 1 piece 2 — resolve_target canonical_id hierarchy (identity-path-mapping)
# ---------------------------------------------------------------------------


class TestResolveTargetHierarchy:
    """``resolve_target`` section branch — each ``::`` segment of a valid
    canonical_id becomes a slugged path component (all but last are
    subfolders, last is the filename stem); empty/invalid canonical_id or
    all-empty slugs fall back to the piece-1 ``{section}/{identity}.md``
    mapping; empty section falls through to the legacy branch."""

    def _candidate(self, source_path: str, section: str = "",
                   canonical_id: str = "") -> Candidate:
        return Candidate(
            candidate_id="c1", job_id="j1", world="w1",
            normalized_identity="Enciclopedia",
            source_hash="sha256:abc",
            provenance=Provenance(
                source_path=source_path, source_kind="loose",
                source_hash="sha256:abc"),
            content_preview="x",
            section=section,
            canonical_id=canonical_id,
        )

    def test_multi_segment_canonical_id(self):
        """3-segment canonical_id → subfolder chain under the section."""
        cand = self._candidate(
            "Enciclopedia de los Vibrantes.md", section="lore",
            canonical_id="Áyagars::Impacto Social::Áyagar del 9no Stal")
        r = resolve_target("w1", cand)
        assert r.status == "resolved"
        assert r.canonical_path == \
            "lore/ayagars/impacto-social/ayagar-del-9no-stal.md"
        assert r.alias_used == ""

    def test_single_segment_canonical_id(self):
        """Single-segment canonical_id → file directly under the section."""
        cand = self._candidate("Enciclopedia de los Vibrantes.md",
                               section="lore", canonical_id="Dottua")
        r = resolve_target("w1", cand)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/dottua.md"

    def test_ordinal_suffix(self):
        """Ordinal ``#N`` participates as a ``-N`` suffix in the slug."""
        cand = self._candidate("Enciclopedia de los Vibrantes.md",
                               section="lore",
                               canonical_id="Sistema Stal::1er Stal#2")
        r = resolve_target("w1", cand)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/sistema-stal/1er-stal-2.md"

    def test_deep_hierarchy(self):
        """5 segments → 4 subfolders + filename stem."""
        cand = self._candidate("Enciclopedia de los Vibrantes.md",
                               section="lore",
                               canonical_id="A::B::C::D::E")
        r = resolve_target("w1", cand)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/a/b/c/d/e.md"

    def test_empty_canonical_id_fallback(self):
        """Empty canonical_id → piece-1 ``{section}/{identity}.md``."""
        cand = self._candidate("Enciclopedia de los Vibrantes.md",
                               section="lore", canonical_id="")
        r = resolve_target("w1", cand)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/Enciclopedia de los Vibrantes.md"

    def test_invalid_canonical_id_fallback(self):
        """``:::broken`` has empty segments → is_canonical_id False →
        piece-1 fallback."""
        cand = self._candidate("Enciclopedia de los Vibrantes.md",
                               section="lore", canonical_id=":::broken")
        r = resolve_target("w1", cand)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/Enciclopedia de los Vibrantes.md"

    def test_all_segments_collapse_fallback(self):
        """``:::`` fails is_canonical_id (all segments empty) → piece-1."""
        cand = self._candidate("Enciclopedia de los Vibrantes.md",
                               section="lore", canonical_id=":::")
        r = resolve_target("w1", cand)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/Enciclopedia de los Vibrantes.md"

    def test_all_segments_slug_empty_fallback(self):
        """Defensive branch: ``---`` IS a canonical id (is_canonical_id True)
        but every segment slugs to "" → piece-1 fallback, never
        ``{section}/.md``."""
        cand = self._candidate("Enciclopedia de los Vibrantes.md",
                               section="lore", canonical_id="---")
        r = resolve_target("w1", cand)
        assert r.status == "resolved"
        assert r.canonical_path == "lore/Enciclopedia de los Vibrantes.md"

    def test_empty_section_ignores_canonical_id(self):
        """Empty section → legacy source-path branch; canonical_id unused."""
        cand = self._candidate("lore/old/x.md", section="",
                               canonical_id="Áyagars::Impacto Social")
        r = resolve_target("w1", cand)
        assert r.status == "review"
        assert r.canonical_path == "lore/old/x.md"
        assert "ayagars" not in r.canonical_path

    def test_52_ficha_distinctness(self):
        """Enciclopedia 52-ficha: two distinct canonical ids under the same
        section root map to two distinct paths (injective over the last
        segment)."""
        first = resolve_target(
            "w1", self._candidate(
                "Enciclopedia de los Vibrantes.md", section="lore",
                canonical_id="Política | Distribución Y Territorios::Dottua"))
        second = resolve_target(
            "w1", self._candidate(
                "Enciclopedia de los Vibrantes.md", section="lore",
                canonical_id="Política | Distribución Y Territorios::Vex"))
        assert first.status == "resolved"
        assert second.status == "resolved"
        assert first.canonical_path == \
            "lore/politica-distribucion-y-territorios/dottua.md"
        assert second.canonical_path == \
            "lore/politica-distribucion-y-territorios/vex.md"
        assert first.canonical_path != second.canonical_path
        assert first.canonical_path.startswith(
            "lore/politica-distribucion-y-territorios/")
        assert second.canonical_path.startswith(
            "lore/politica-distribucion-y-territorios/")


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
        """Task 2.2 + PR2 — .docx dispatches through the strategy registry."""
        expected = [_entry(filename="inline.png", page=None,
                           document_order=1, anchor_type="inline",
                           structural_path="body/p[0]/r[0]/inline[0]")]
        monkeypatch.setattr(
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": _strategy_result(expected))
        images = extract_images_from_file(Path("Lore/Enciclopedia.docx"))
        assert images == expected
        assert images[0].filename == "inline.png"
        assert images[0].anchor_type == "inline"
        assert images[0].structural_path == "body/p[0]/r[0]/inline[0]"

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
        """Tasks 2.3/2.4 + PR2 — extracted bytes land in the spool and
        metadata (including the DOCX position contract) is attached to the
        AnalyzedFile for downstream consumption."""
        def _convert(_path):
            return "# Enciclopedia\n\nBody"
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", _convert)
        entries = [
            _entry(filename="portada.png", page=None,
                   data=b"PORTADA-BYTES",
                   document_order=1, paragraph_index=2, anchor_type="inline",
                   structural_path="body/p[2]/r[0]/inline[0]",
                   heading_path="Enciclopedia > Portada",
                   context_text="Retrato de la fundadora"),
            _entry(filename="mapa.png", page=1, data=b"MAPA-BYTES",
                   document_order=2, anchor_type="anchor",
                   structural_path="body/p[5]/r[1]/anchor[0]"),
        ]
        monkeypatch.setattr(
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": _strategy_result(entries))
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
        # PR2 — the DOCX position contract is mirrored on ExtractedMedia.
        assert first.document_order == 1
        assert first.paragraph_index == 2
        assert first.anchor_type == "inline"
        assert first.structural_path == "body/p[2]/r[0]/inline[0]"
        assert first.heading_path == "Enciclopedia > Portada"
        assert first.context_text == "Retrato de la fundadora"
        assert second.anchor_type == "anchor"
        assert second.structural_path == "body/p[5]/r[1]/anchor[0]"

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
        """Task 2.5 + PR2 — an extraction failure leaves the converted
        candidate intact and records a diagnostic (fail-open)."""
        def _convert(_path):
            return "# Enciclopedia\n\nBody"
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", _convert)

        def _boom(_path, converted_markdown=""):
            raise RuntimeError("docx strategy broke")
        monkeypatch.setattr(
            "sync_lore.import_docx_parser.extract_by_extension", _boom)
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


# ---------------------------------------------------------------------------
# PR2 — DOCX strategy integration (tasks 2.1/2.2/2.3 + scenario R3-S1/R4-S1)
# ---------------------------------------------------------------------------


class TestDocxStrategyIntegration:
    """Positioned media propagation through ``analyze_source`` (PR2 seam).

    The strategy mock emulates the real ``DocxImageExtractionStrategy``:
    it receives the converted markdown, enriches it with injected image
    references, and returns positioned ``ImageEntry`` records plus
    diagnostics/warnings — exactly what ``import_docx_parser`` produces.
    """

    def test_strategy_enriches_markdown_and_placements_carry_position(
            self, monkeypatch, tmp_path):
        """R3-S1 — the enriched markdown (with injected refs) becomes the
        candidate body, and the derived placements carry the DOCX position
        fields from the spooled media."""
        converted = "# Origen\n\nLa fundadora partió al exilio."
        enriched = (
            "# Origen\n\nLa fundadora partió al exilio.\n"
            "![portada](media/portada.png)"
        )
        entry = _entry(
            filename="portada.png", page=None, data=b"PORTADA-BYTES",
            document_order=1, paragraph_index=1, anchor_type="inline",
            structural_path="body/p[1]/r[0]/inline[0]",
            heading_path="Origen", context_text="La fundadora partió",
            warnings=["media part 'word/media/x.png' missing from package; skipped"],
        )
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown",
            lambda _p: converted)
        monkeypatch.setattr(
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": _strategy_result(
                [entry], markdown=enriched))
        spool = tmp_path / "spool"
        (spool / "Lore").mkdir(parents=True)
        (spool / "Lore" / "Enciclopedia.docx").write_bytes(b"PK..fake")
        files = [{"relative": "Lore/Enciclopedia.docx",
                  "sha256": "abc", "size": 8}]
        report = analyze_source(files, _read_file(spool),
                                file_path=_path_for(spool),
                                spool_root=spool)
        analyzed = report.ordered_files()[0]
        # Injected reference lands in the candidate body (converted text).
        assert "![portada](media/portada.png)" in analyzed.content_preview()
        # The chunk placement derived from the ref carries the position.
        placement = analyzed.chunks[0].images[0]
        assert placement.relative_media_path == "media/portada.png"
        assert placement.document_order == 1
        assert placement.paragraph_index == 1
        assert placement.anchor_type == "inline"
        assert placement.structural_path == "body/p[1]/r[0]/inline[0]"
        assert placement.heading_path == "Origen"
        assert placement.context_text == "La fundadora partió"
        assert placement.warnings == [
            "media part 'word/media/x.png' missing from package; skipped"]
        # Spooled media mirrors the same contract.
        assert analyzed.media[0].document_order == 1
        assert analyzed.media[0].anchor_type == "inline"

    def test_spool_collision_rename_preserves_position_enrichment(
            self, monkeypatch, tmp_path):
        """BUG 2 gap — spool collision rename vs injected ref attribution.

        When ``store_media_in_spool`` renames a file on disk because the
        target already exists (``pic.png`` -> ``pic-1.png`` — e.g. a
        same-stem sibling source like ``Lore/Enciclopedia.md`` already
        stored ``pic.png`` under ``media/Enciclopedia/`` in the same job),
        the markdown ref injected by the DOCX strategy still points at the
        ORIGINAL name (``media/pic.png``). ``_enrich_placements`` matches by
        basename, so the ref must still resolve to the renamed media —
        otherwise the DOCX position contract (``document_order`` /
        ``paragraph_index``) is lost and the placement is silently
        unenriched.
        """
        # Pre-existing spool file simulates a same-stem sibling source in
        # the same job that already stored ``pic.png`` under this stem dir.
        spool = tmp_path / "spool"
        media_dir = spool / "media" / "Enciclopedia"
        media_dir.mkdir(parents=True)
        (media_dir / "pic.png").write_bytes(b"STALE-SIBLING-BYTES")

        converted = "# Origen\n\nLa fundadora partió al exilio."
        enriched = (
            "# Origen\n\nLa fundadora partió al exilio.\n"
            "![pic](media/pic.png)"
        )
        entry = _entry(
            filename="pic.png", page=None, data=b"PIC-BYTES",
            document_order=1, paragraph_index=2, anchor_type="inline",
            structural_path="body/p[2]/r[0]/inline[0]",
            heading_path="Origen", context_text="La fundadora partió",
        )
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown",
            lambda _p: converted)
        monkeypatch.setattr(
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": _strategy_result(
                [entry], markdown=enriched))
        (spool / "Lore").mkdir(parents=True)
        (spool / "Lore" / "Enciclopedia.docx").write_bytes(b"PK..fake")
        files = [{"relative": "Lore/Enciclopedia.docx",
                  "sha256": "abc", "size": 8}]
        report = analyze_source(files, _read_file(spool),
                                file_path=_path_for(spool),
                                spool_root=spool)
        analyzed = report.ordered_files()[0]
        # The collision really fired: the extracted bytes were stored under a
        # renamed path and the stale file was not overwritten.
        assert [m.spool_relative_path for m in analyzed.media] == \
            ["media/Enciclopedia/pic-1.png"]
        assert (media_dir / "pic.png").read_bytes() == b"STALE-SIBLING-BYTES"
        assert (media_dir / "pic-1.png").read_bytes() == b"PIC-BYTES"
        # The injected ref keeps pointing at the ORIGINAL name, and the DOCX
        # position contract must survive the spool rename.
        placement = analyzed.chunks[0].images[0]
        assert placement.relative_media_path == "media/pic.png"
        assert placement.document_order == 1
        assert placement.paragraph_index == 2
        assert placement.anchor_type == "inline"
        assert placement.structural_path == "body/p[2]/r[0]/inline[0]"

    def test_strategy_warnings_flow_to_analyzed_file(
            self, monkeypatch, tmp_path):
        """R1-S2 — file-level strategy warnings (headers/SmartArt) surface on
        the AnalyzedFile as advisory metadata; body analysis continues."""
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown",
            lambda _p: "# Origen\n\nBody")
        monkeypatch.setattr(
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": _strategy_result(
                [], markdown=converted_markdown,
                warnings=[
                    "header part 'word/_rels/header1.xml.rels' embeds 2 "
                    "image(s) — headers are not supported; skipped",
                    "SmartArt diagram 'word/diagrams/data1.xml' is not "
                    "supported; skipped",
                ]))
        spool = tmp_path / "spool"
        (spool / "Lore").mkdir(parents=True)
        (spool / "Lore" / "Enciclopedia.docx").write_bytes(b"PK..fake")
        files = [{"relative": "Lore/Enciclopedia.docx",
                  "sha256": "abc", "size": 8}]
        report = analyze_source(files, _read_file(spool),
                                file_path=_path_for(spool),
                                spool_root=spool)
        analyzed = report.ordered_files()[0]
        assert "Body" in analyzed.content_preview()
        assert len(analyzed.warnings) == 2
        assert any("headers are not supported" in w for w in analyzed.warnings)
        assert analyzed.media == []

    def test_one_candidate_per_docx(self, monkeypatch, tmp_path):
        """R4-S1 — one source file yields exactly one analyzed file."""
        def _convert(_path):
            return "# Origen\n\nBody"
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", _convert)
        monkeypatch.setattr(
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": _strategy_result(
                [_entry(filename="a.png", document_order=1),
                 _entry(filename="b.png", document_order=2)],
                markdown=converted_markdown))
        spool = tmp_path / "spool"
        (spool / "Lore").mkdir(parents=True)
        (spool / "Lore" / "Enciclopedia.docx").write_bytes(b"PK..fake")
        files = [{"relative": "Lore/Enciclopedia.docx",
                  "sha256": "abc", "size": 8}]
        report = analyze_source(files, _read_file(spool),
                                file_path=_path_for(spool),
                                spool_root=spool)
        assert len(report.files) == 1
        assert len(report.ordered_files()[0].media) == 2

    def test_media_store_failure_fail_open_for_other_images(
            self, monkeypatch, tmp_path):
        """R4-S1 — one media write failing never blocks body analysis nor the
        other images; the failed media is simply absent from the bundle."""
        def _convert(_path):
            return "# Origen\n\nBody"
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", _convert)
        entries = [
            _entry(filename="good.png", data=b"GOOD-BYTES",
                   document_order=1),
            _entry(filename="bad.png", data=b"BAD-BYTES",
                   document_order=2),
        ]
        monkeypatch.setattr(
            "sync_lore.import_docx_parser.extract_by_extension",
            lambda _p, converted_markdown="": _strategy_result(entries))
        real_write_bytes = Path.write_bytes

        def _flaky_write(self, data):
            if self.name == "bad.png":
                raise OSError("simulated disk full")
            return real_write_bytes(self, data)
        monkeypatch.setattr(Path, "write_bytes", _flaky_write)
        spool = tmp_path / "spool"
        (spool / "Lore").mkdir(parents=True)
        (spool / "Lore" / "Enciclopedia.docx").write_bytes(b"PK..fake")
        files = [{"relative": "Lore/Enciclopedia.docx",
                  "sha256": "abc", "size": 8}]
        report = analyze_source(files, _read_file(spool),
                                file_path=_path_for(spool),
                                spool_root=spool)
        analyzed = report.ordered_files()[0]
        assert "Body" in analyzed.content_preview()
        assert [m.image.filename for m in analyzed.media] == ["good.png"]
        assert (spool / "media" / "Enciclopedia" / "good.png").read_bytes() \
            == b"GOOD-BYTES"
        assert not (spool / "media" / "Enciclopedia" / "bad.png").exists()

    def test_pdf_keeps_legacy_adapter(self, monkeypatch, tmp_path):
        """R2-S1 — PDF stays on the legacy extractor (no strategy): the
        converted markdown is not enriched and images come from the adapter."""
        called_with: list[Path] = []

        def _convert(_path):
            return "# Manual\n\nBody"
        monkeypatch.setattr(
            "sync_lore.utils.converter.convert_to_markdown", _convert)
        monkeypatch.setattr(
            "sync_lore.image_indexer.extract_images_from_pdf",
            lambda path: called_with.append(Path(path)) or [
                _entry(filename="page1.png", page=1)])
        spool = tmp_path / "spool"
        (spool / "Lore").mkdir(parents=True)
        (spool / "Lore" / "Manual.pdf").write_bytes(b"%PDF-fake")
        files = [{"relative": "Lore/Manual.pdf", "sha256": "abc", "size": 8}]
        report = analyze_source(files, _read_file(spool),
                                file_path=_path_for(spool),
                                spool_root=spool)
        analyzed = report.ordered_files()[0]
        assert called_with == [spool / "Lore" / "Manual.pdf"]
        assert len(analyzed.media) == 1
        assert analyzed.media[0].image.page == 1
        assert analyzed.media[0].anchor_type == ""