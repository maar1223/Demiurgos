# -*- coding: utf-8 -*-
"""Unit tests for the streaming DOCX image extraction strategy (PR 1).

Covers tasks 1.3-1.8: strategy protocol and registry, relationship
resolution with traversal safety, streaming position tracking (paragraph /
run / drawing / char offset), heading context, inline vs anchor detection,
unsupported containers (headers, SmartArt), Markdown reference injection,
duplicate references, and a large streaming fixture proving bounded parsing.

Fixtures are minimal DOCX ZIP packages built in memory — no python-docx,
no markitdown, no external files required.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parents[1]  # src/tools — makes the sync_lore package importable
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from sync_lore.import_docx_parser import (  # noqa: E402
    DocxImageExtractionStrategy,
    extract_by_extension,
    inject_image_refs,
    registered_extensions,
    strategy_for,
)
from sync_lore.schemas import ImageEntry  # noqa: E402

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
T_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"

STRATEGY = DocxImageExtractionStrategy()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _rels(*pairs: tuple[str, str]) -> bytes:
    """document.xml.rels XML mapping rIds to targets."""
    body = "".join(
        f'<Relationship Id="{rid}" Type="{T_IMAGE}" Target="{tgt}"/>'
        for rid, tgt in pairs
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{PKG_REL_NS}">{body}</Relationships>'
    ).encode("utf-8")


def _drawing(rid: str, *, anchor: bool = False, name: str = "image.png") -> str:
    """A wp:inline / wp:anchor drawing embedding a blip with r:embed."""
    wrap = "anchor" if anchor else "inline"
    return (
        f"<w:drawing><wp:{wrap}><wp:docPr id=\"1\" name=\"{name}\"/>"
        f"<a:graphic><a:graphicData><a:blip r:embed=\"{rid}\"/></a:graphicData>"
        f"</a:graphic></wp:{wrap}></w:drawing>"
    )


def _para(*children: str) -> str:
    return f"<w:p>{''.join(children)}</w:p>"


def _heading_para(text: str, style: str = "Heading1") -> str:
    return (
        f"<w:p><w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>"
        f"<w:r><w:t>{text}</w:t></w:r></w:p>"
    )


def _text_para(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _image_para(
    rid: str, *, anchor: bool = False, prefix: str = "", name: str = "image.png"
) -> str:
    """Paragraph with optional text before an inline/anchor image."""
    before = f"<w:r><w:t>{prefix}</w:t></w:r>" if prefix else ""
    return f"<w:p>{before}<w:r>{_drawing(rid, anchor=anchor, name=name)}</w:r></w:p>"


def _docx_bytes(
    *paragraphs: str,
    rels: bytes | None = None,
    media: dict[str, bytes] | None = None,
    extra_members: dict[str, bytes] | None = None,
) -> bytes:
    """Build an in-memory DOCX ZIP from paragraph XML fragments."""
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document xmlns:w="{W_NS}" xmlns:wp="{WP_NS}" xmlns:a="{A_NS}" '
        f'xmlns:r="{R_NS}"><w:body>{"".join(paragraphs)}<w:sectPr/></w:body>'
        f"</w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", document)
        zf.writestr(
            "word/_rels/document.xml.rels",
            rels if rels is not None else _rels(("rId5", "media/image1.png")),
        )
        for name, data in (media or {}).items():
            zf.writestr(f"word/media/{name}", data)
        for name, data in (extra_members or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def _write_docx(tmp_path: Path, data: bytes, name: str = "sample.docx") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


DEFAULT_MEDIA = {
    "image1.png": b"PNG-DATA-1",
    "image2.png": b"PNG-DATA-2",
    "image3.png": b"PNG-DATA-3",
}


# ---------------------------------------------------------------------------
# Position contract (task 1.2)
# ---------------------------------------------------------------------------


class TestImageEntryPositionContract:
    def test_additive_fields_default(self):
        entry = ImageEntry(id="x", source_file="doc.docx")
        assert entry.document_order == 0
        assert entry.paragraph_index == 0
        assert entry.run_index == 0
        assert entry.run_offset == 0
        assert entry.drawing_index == 0
        assert entry.anchor_type == ""
        assert entry.structural_path == ""
        assert entry.heading_path == ""
        assert entry.section_context == ""
        assert entry.warnings == []

    def test_existing_construction_unaffected(self):
        entry = ImageEntry(
            id="x", source_file="doc.docx", page=1, chunk_ref="## A",
            context_text="ctx", filename="img.png", image_bytes=b"data",
        )
        assert entry.filename == "img.png"
        assert entry.document_order == 0  # additive default preserved


# ---------------------------------------------------------------------------
# Registry and dispatch (task 1.3)
# ---------------------------------------------------------------------------


class TestStrategyRegistry:
    def test_docx_registered(self):
        assert isinstance(strategy_for(".docx"), DocxImageExtractionStrategy)

    def test_dispatch_is_case_insensitive(self):
        assert isinstance(strategy_for(".DOCX"), DocxImageExtractionStrategy)

    def test_unsupported_extension_returns_none(self):
        assert strategy_for(".pdf") is None
        assert strategy_for(".epub") is None
        assert strategy_for("") is None

    def test_registered_extensions_contains_docx(self):
        assert ".docx" in registered_extensions()

    def test_unsupported_dispatch_typed_result(self):
        result = extract_by_extension(Path("file.pdf"))
        assert result.images == []
        assert result.markdown == ""
        assert result.diagnostics == ["no image extraction strategy for '.pdf'"]
        assert result.warnings == []

    def test_extensions_is_frozenset_of_docx(self):
        assert STRATEGY.extensions == frozenset({".docx"})


# ---------------------------------------------------------------------------
# Streaming extraction: order, positions, context (tasks 1.4-1.5)
# ---------------------------------------------------------------------------


class TestStreamingExtraction:
    def test_inline_and_anchor_ordering(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _heading_para("Chapter One"),
                _image_para("rId5", prefix="See ", name="image1.png"),
                _text_para("Plain paragraph."),
                _image_para("rId6", anchor=True, name="image2.png"),
                _image_para("rId7", name="image3.png"),
                rels=_rels(
                    ("rId5", "media/image1.png"),
                    ("rId6", "media/image2.png"),
                    ("rId7", "media/image3.png"),
                ),
                media=DEFAULT_MEDIA,
            ),
        )
        result = STRATEGY.extract(doc)

        assert result.diagnostics == []
        assert result.warnings == []
        assert [img.filename for img in result.images] == [
            "Chapter-One.png", "Chapter-One-2.png", "Chapter-One-3.png",
        ]
        assert [img.document_order for img in result.images] == [1, 2, 3]
        assert [img.anchor_type for img in result.images] == [
            "inline", "anchor", "inline",
        ]
        # paragraphs: 0 heading, 1 image, 2 text, 3 anchor image, 4 inline image
        assert [img.paragraph_index for img in result.images] == [1, 3, 4]
        assert [img.image_bytes for img in result.images] == [
            b"PNG-DATA-1", b"PNG-DATA-2", b"PNG-DATA-3",
        ]
        assert all(img.source_file == "sample.docx" for img in result.images)

    def test_heading_context_and_path(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _heading_para("Chapter One", style="Heading1"),
                _heading_para("The Forest", style="Heading2"),
                _image_para("rId5", prefix="See "),
                media=DEFAULT_MEDIA,
            ),
        )
        result = STRATEGY.extract(doc)
        img = result.images[0]
        assert img.heading_path == "Chapter One > The Forest"
        assert img.section_context == "See"  # paragraph text before the image

    def test_heading_stack_trimming_by_level(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _heading_para("Part I", style="Heading1"),
                _heading_para("Chapter A", style="Heading2"),
                _image_para("rId5", prefix="in A"),
                _heading_para("Chapter B", style="Heading2"),
                _image_para("rId6", prefix="in B"),
                rels=_rels(
                    ("rId5", "media/image1.png"),
                    ("rId6", "media/image2.png"),
                ),
                media=DEFAULT_MEDIA,
            ),
        )
        result = STRATEGY.extract(doc)
        assert result.images[0].heading_path == "Part I > Chapter A"
        assert result.images[1].heading_path == "Part I > Chapter B"

    def test_run_offsets_and_structural_path(self, tmp_path):
        # prefix text lives in its own run → the drawing run has offset 0
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _heading_para("H"),
                _image_para("rId5", prefix="See the "),
                _image_para("rId6", prefix=""),
                rels=_rels(
                    ("rId5", "media/image1.png"),
                    ("rId6", "media/image2.png"),
                ),
                media=DEFAULT_MEDIA,
            ),
        )
        result = STRATEGY.extract(doc)
        assert result.images[0].run_index == 1  # text run came first
        assert result.images[0].run_offset == 0
        assert result.images[0].drawing_index == 0
        assert result.images[0].structural_path == "body/p[1]/r[1]/inline[0]"
        assert result.images[1].run_offset == 0
        assert result.images[1].structural_path == "body/p[2]/r[0]/inline[0]"

    def test_run_offset_within_drawing_run(self, tmp_path):
        # text and drawing inside the same run → non-zero char offset
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _para("<w:r><w:t>See the </w:t>" + _drawing("rId5") + "</w:r>"),
                media=DEFAULT_MEDIA,
            ),
        )
        result = STRATEGY.extract(doc)
        img = result.images[0]
        assert img.run_offset == len("See the ")
        assert img.run_index == 0
        assert img.section_context == "See the"

    def test_two_drawings_in_one_paragraph(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _para(
                    "<w:r>" + _drawing("rId5", name="image1.png") + "</w:r>"
                    + "<w:r><w:t>middle</w:t></w:r>"
                    + "<w:r>" + _drawing("rId6", anchor=True, name="image2.png") + "</w:r>"
                ),
                rels=_rels(
                    ("rId5", "media/image1.png"),
                    ("rId6", "media/image2.png"),
                ),
                media=DEFAULT_MEDIA,
            ),
        )
        result = STRATEGY.extract(doc)
        assert len(result.images) == 2
        assert [img.drawing_index for img in result.images] == [0, 1]
        assert [img.paragraph_index for img in result.images] == [0, 0]
        assert [img.run_index for img in result.images] == [0, 2]
        # each drawing sits in its own run → offset within the run is 0;
        # the paragraph context before the second drawing is "middle"
        assert result.images[1].run_offset == 0
        assert result.images[1].section_context == "middle"

    def test_duplicate_reference_emits_two_entries(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _image_para("rId5"),
                _text_para("interlude"),
                _image_para("rId5"),
                media=DEFAULT_MEDIA,
            ),
        )
        result = STRATEGY.extract(doc)
        assert len(result.images) == 2
        assert result.images[0].document_order == 1
        assert result.images[1].document_order == 2
        # No heading context: names fall back to the media part name, and the
        # duplicate is disambiguated so every gallery file stays unique.
        assert result.images[0].filename == "image1.png"
        assert result.images[1].filename == "image1-2.png"

    def test_large_streaming_fixture_is_bounded(self, tmp_path):
        """Thousands of paragraphs parse with correct positions (bounded memory)."""
        paragraphs = [_heading_para("Chapter One")]
        paragraphs += [_text_para(f"filler paragraph {i}") for i in range(5000)]
        paragraphs.append(_image_para("rId5", prefix="target", name="image1.png"))
        doc = _write_docx(tmp_path, _docx_bytes(*paragraphs, media=DEFAULT_MEDIA))
        result = STRATEGY.extract(doc)
        assert len(result.images) == 1
        assert result.images[0].paragraph_index == 5001
        assert result.images[0].document_order == 1
        assert result.images[0].run_index == 1  # prefix text in its own run
        assert result.images[0].run_offset == 0
        assert result.images[0].section_context == "target"


# ---------------------------------------------------------------------------
# Relationship resolution and safety (task 1.4)
# ---------------------------------------------------------------------------


class TestRelationshipResolution:
    def test_relationship_resolution_and_bytes(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _image_para("rId5"),
                rels=_rels(("rId5", "media/sub/image1.png")),
                media={"sub/image1.png": b"PNG-NESTED"},
            ),
        )
        result = STRATEGY.extract(doc)
        assert len(result.images) == 1
        assert result.images[0].filename == "image1.png"
        assert result.images[0].image_bytes == b"PNG-NESTED"

    def test_missing_relationship_warns_and_omits(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _image_para("rId99"),
                rels=_rels(("rId5", "media/image1.png")),
                media=DEFAULT_MEDIA,
            ),
        )
        result = STRATEGY.extract(doc)
        assert result.images == []
        assert any("rId99" in w and "not found" in w for w in result.warnings)

    def test_missing_media_part_warns_and_omits(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _image_para("rId5"),
                rels=_rels(("rId5", "media/image9.png")),
                media=DEFAULT_MEDIA,  # image9.png absent
            ),
        )
        result = STRATEGY.extract(doc)
        assert result.images == []
        assert any("missing from package" in w for w in result.warnings)

    def test_traversal_target_rejected(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _image_para("rId5"),
                rels=_rels(("rId5", "../evil.png")),
                media={"evil.png": b"EVIL"},
            ),
        )
        result = STRATEGY.extract(doc)
        assert result.images == []
        assert any("outside" in w or "escapes" in w for w in result.warnings)

    def test_escape_outside_package_rejected(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _image_para("rId5"),
                rels=_rels(("rId5", "../../../evil.png")),
            ),
        )
        result = STRATEGY.extract(doc)
        assert result.images == []
        assert any("escapes the package" in w for w in result.warnings)

    def test_external_target_skipped(self, tmp_path):
        external = (
            f'<Relationships xmlns="{PKG_REL_NS}">'
            f'<Relationship Id="rId5" Type="{T_IMAGE}" Target="https://x/y.png" '
            f'TargetMode="External"/></Relationships>'
        ).encode("utf-8")
        doc = _write_docx(
            tmp_path, _docx_bytes(_image_para("rId5"), rels=external)
        )
        result = STRATEGY.extract(doc)
        assert result.images == []
        assert any("not found" in w for w in result.warnings)

    def test_missing_rels_part_warns(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "word/document.xml",
                f'<w:document xmlns:w="{W_NS}" xmlns:wp="{WP_NS}" xmlns:a="{A_NS}" '
                f'xmlns:r="{R_NS}"><w:body><w:p/></w:body></w:document>',
            )
        doc = _write_docx(tmp_path, buf.getvalue())
        result = STRATEGY.extract(doc)
        assert result.images == []
        assert any("missing word/_rels/document.xml.rels" in w for w in result.warnings)

    def test_malformed_rels_part_warns(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(_image_para("rId5"), rels=b"<Relationships><unclosed>"),
        )
        result = STRATEGY.extract(doc)
        assert result.images == []
        assert any("malformed" in w for w in result.warnings)

    def test_malformed_document_xml_fails_open(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/_rels/document.xml.rels", _rels(("rId5", "media/image1.png")))
            zf.writestr("word/document.xml", "<w:document><unclosed>")
        doc = _write_docx(tmp_path, buf.getvalue())
        result = STRATEGY.extract(doc)
        assert result.images == []
        assert any("malformed word/document.xml" in w for w in result.warnings)

    def test_not_a_zip_fails_open(self, tmp_path):
        doc = tmp_path / "broken.docx"
        doc.write_bytes(b"this is not a zip archive at all")
        result = STRATEGY.extract(doc)
        assert result.images == []
        assert result.diagnostics and "cannot open DOCX" in result.diagnostics[0]

    def test_missing_source_fails_open(self, tmp_path):
        result = STRATEGY.extract(tmp_path / "ghost.docx")
        assert result.images == []
        assert "source not found" in result.diagnostics[0]


# ---------------------------------------------------------------------------
# Unsupported containers (task 1.7)
# ---------------------------------------------------------------------------


class TestUnsupportedContainers:
    def test_header_images_warned_never_extracted(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _image_para("rId5"),
                media=DEFAULT_MEDIA,
                extra_members={
                    "word/header1.xml": b"<w:hdr/>",
                    "word/_rels/header1.xml.rels": _rels(("rH1", "media/header_logo.png")),
                    "word/media/header_logo.png": b"PNG-LOGO",
                },
            ),
        )
        result = STRATEGY.extract(doc)
        # body image still extracted
        assert len(result.images) == 1
        assert result.images[0].filename == "image1.png"
        assert any("header" in w and "not supported" in w for w in result.warnings)
        assert not any(img.filename == "header_logo.png" for img in result.images)

    def test_smartart_warned_never_extracted(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _image_para("rId5"),
                media=DEFAULT_MEDIA,
                extra_members={"word/diagrams/data1.xml": b"<dgm:data/>"},
            ),
        )
        result = STRATEGY.extract(doc)
        assert len(result.images) == 1
        assert any("SmartArt" in w and "not supported" in w for w in result.warnings)

    def test_plain_header_without_images_no_warning(self, tmp_path):
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _text_para("body"),
                extra_members={
                    "word/header1.xml": b"<w:hdr/>",
                    "word/_rels/header1.xml.rels": b'<Relationships xmlns="x"/>',
                },
            ),
        )
        result = STRATEGY.extract(doc)
        assert result.images == []
        assert not any("header" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Markdown reference injection (task 1.6)
# ---------------------------------------------------------------------------


def _positioned_image(
    filename: str = "image1.png",
    *,
    heading_path: str = "Chapter One",
    document_order: int = 1,
) -> ImageEntry:
    return ImageEntry(
        id=f"img-{document_order}",
        source_file="sample.docx",
        filename=filename,
        image_bytes=b"data",
        document_order=document_order,
        paragraph_index=1,
        run_index=0,
        run_offset=0,
        drawing_index=0,
        anchor_type="inline",
        heading_path=heading_path,
        section_context="See ",
    )


class TestMarkdownInjection:
    def test_no_images_returns_markdown_unchanged(self):
        md, diags = inject_image_refs("# Chapter One\n\nText.\n", [])
        assert md == "# Chapter One\n\nText.\n"
        assert diags == []

    def test_injects_after_paragraph_in_matching_section(self):
        markdown = "# Chapter One\n\nIntro text here.\n\n# Next\n\nMore.\n"
        images = [_positioned_image("image1.png", heading_path="Chapter One")]
        md, diags = inject_image_refs(markdown, images)
        assert diags == []
        assert "![image1](media/image1.png)" in md
        lines = md.split("\n")
        ref_idx = lines.index("![image1](media/image1.png)")
        assert lines[ref_idx - 1] == "Intro text here."  # after the paragraph

    def test_section_document_order_kept(self):
        markdown = "# Chapter One\n\nP1.\n\nP2.\n\n# Next\n\nMore.\n"
        images = [
            _positioned_image("image1.png", document_order=1),
            _positioned_image("image2.png", document_order=2),
        ]
        md, diags = inject_image_refs(markdown, images)
        assert diags == []
        lines = md.split("\n")
        assert lines.index("![image1](media/image1.png)") < lines.index(
            "![image2](media/image2.png)"
        )

    def test_matches_bold_wrapped_heading(self):
        """markitdown wraps docx headings in ``**bold**`` (``## **Sold (Nivel 1)**``);
        the heading must still match the docx ``heading_path`` (``Sold (Nivel 1)``)
        instead of being reported unmatched and dumped at the document end."""
        markdown = "# Chapter One\n\nIntro text.\n\n## **Sold (Sólido | Nivel 1)**\n\nBody.\n"
        images = [_positioned_image("image1.png", heading_path="Chapter One > Sold (Sólido | Nivel 1)")]
        md, diags = inject_image_refs(markdown, images)
        assert diags == []
        lines = md.split("\n")
        ref_idx = lines.index("![image1](media/image1.png)")
        assert lines[ref_idx - 1] == "Body."  # injected inside the matching section

    def test_matches_full_heading_path_not_first_deepest_match(self):
        """BUG 2b — an image under a repeated child heading (``Forma Base``
        under every Stal) must land in ITS OWN section: matching uses the
        FULL heading path (``Stal N > Forma Base``), never just the deepest
        component, so the FIRST ``Forma Base`` section cannot capture the
        other Stals' images."""
        markdown = (
            "# Sistema Stal\n\n"
            "## Áyagar del 1er Stal\n\n"
            "### Forma Base\n\n"
            "Cuerpo del 1er Stal.\n\n"
            "## Áyagar del 2do Stal\n\n"
            "### Forma Base\n\n"
            "Cuerpo del 2do Stal.\n"
        )
        images = [
            _positioned_image(
                "forma-base-1.png", document_order=1,
                heading_path="Sistema Stal > Áyagar del 1er Stal > Forma Base"),
            _positioned_image(
                "forma-base-2.png", document_order=2,
                heading_path="Sistema Stal > Áyagar del 2do Stal > Forma Base"),
        ]
        md, diags = inject_image_refs(markdown, images)
        assert diags == []
        lines = md.split("\n")
        body1 = lines.index("Cuerpo del 1er Stal.")
        body2 = lines.index("Cuerpo del 2do Stal.")
        idx1 = lines.index("![forma-base-1](media/forma-base-1.png)")
        idx2 = lines.index("![forma-base-2](media/forma-base-2.png)")
        # Each image is injected inside ITS OWN Stal's section, in order.
        assert body1 < idx1 < body2 < idx2

    def test_deepest_component_fallback_when_ancestry_differs(self):
        """Unique leaf headings still match when the converted markdown
        ancestry differs from the DOCX path (e.g. markitdown drops an
        intermediate heading): the deepest-component fallback resolves them
        exactly as the legacy matching did."""
        markdown = "# Capítulo\n\n## Dvex del Stal 1\n\nCuerpo.\n"
        images = [_positioned_image(
            "dvex.png",
            heading_path="Capítulo > Intermedio Descartado > Dvex del Stal 1")]
        md, diags = inject_image_refs(markdown, images)
        assert diags == []
        lines = md.split("\n")
        assert lines.index("![dvex](media/dvex.png)") > lines.index("Cuerpo.")

    def test_overflow_refs_appended_at_section_end_with_diagnostic(self):
        markdown = "# Chapter One\n\nP1.\n\n# Next\n\nMore.\n"
        images = [
            _positioned_image(f"image{i}.png", document_order=i) for i in (1, 2)
        ]
        md, diags = inject_image_refs(markdown, images)
        assert any("no exact paragraph position" in d for d in diags)
        lines = md.split("\n")
        # both refs present; second one lands at the section end
        assert "![image2](media/image2.png)" in lines

    def test_unmatched_heading_appended_with_diagnostic(self):
        markdown = "# Chapter One\n\nText.\n"
        images = [_positioned_image("image1.png", heading_path="Ghost Heading")]
        md, diags = inject_image_refs(markdown, images)
        assert any("no markdown heading match" in d for d in diags)
        assert md.strip().endswith("![image1](media/image1.png)")

    def test_empty_markdown_returns_only_refs(self):
        md, diags = inject_image_refs("", [_positioned_image()])
        assert md == "![image1](media/image1.png)"
        assert diags == []

    def test_extract_injects_into_converted_markdown(self, tmp_path):
        markdown = "# Chapter One\n\nIntro text.\n"
        doc = _write_docx(
            tmp_path,
            _docx_bytes(
                _heading_para("Chapter One"),
                _image_para("rId5", prefix="See "),
                media=DEFAULT_MEDIA,
            ),
        )
        result = STRATEGY.extract(doc, converted_markdown=markdown)
        lines = result.markdown.split("\n")
        ref_idx = lines.index("![Chapter-One](media/Chapter-One.png)")
        assert lines[ref_idx - 1] == "Intro text."  # after the paragraph line


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))