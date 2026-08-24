"""
import_docx_parser.py — Streaming DOCX image extraction with precise positioning.

Strategy seam for the world importer: reads the DOCX package directly with
``zipfile`` + ``lxml.etree.iterparse`` (bounded memory for large documents),
resolves ``r:embed`` relationships to ``word/media/*`` parts, and returns
ordered ``ImageEntry`` records carrying deterministic structural position
(heading context, paragraph/run/drawing counters, run char offset) plus
inline/anchor metadata. The converted Markdown is enriched with generated
image references at the matching heading/paragraph position, with a
deterministic document-order fallback and a diagnostic when no exact
converted location exists.

Design contract:
- ``anchor_type`` is the closed value ``inline | anchor``.
- Unsupported or unresolved records are never emitted as imported media;
  they produce actionable warnings and body analysis continues (fail-open).
- Header parts and SmartArt are detected as unsupported containers, warned
  about, and omitted from body extraction.
- ``.pdf`` stays on the legacy extractor path; the registry only knows the
  formats that implement the strategy seam (``.docx`` now, ``.epub``/``.odt``
  in Phase 2).
"""

from __future__ import annotations

import posixpath
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol

from lxml import etree

from .schemas import ImageEntry

# ---------------------------------------------------------------------------
# OOXML namespaces
# ---------------------------------------------------------------------------

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_W = f"{{{_W_NS}}}"
_WP = f"{{{_WP_NS}}}"
_A = f"{{{_A_NS}}}"
_R = f"{{{_R_NS}}}"

DOCUMENT_XML = "word/document.xml"
DOCUMENT_RELS = "word/_rels/document.xml.rels"
MEDIA_PREFIX = "word/media/"

_HEADER_RELS_RE = re.compile(r"^word/_rels/header\d*\.xml\.rels$")
_IMAGE_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".bmp",
    ".tif", ".tiff", ".webp", ".svg", ".emf", ".wmf",
)

# Tags the streaming parse listens for. lxml discards every other element as
# it is parsed, so memory stays bounded without clearing the whole tree.
_ITERPARSE_TAGS = (
    _W + "p",
    _W + "r",
    _W + "t",
    _W + "pStyle",
    _WP + "inline",
    _WP + "anchor",
    _A + "blip",
)

# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class ImageExtractionStrategy(Protocol):
    """Format strategy seam: extract positioned images from a source file.

    Implementations declare the extensions they own and return a typed
    ``ExtractionResult``; failures are reported through ``diagnostics`` and
    ``warnings`` so callers can keep body analysis fail-open.
    """

    extensions: frozenset[str]

    def extract(self, source: Path, converted_markdown: str = "") -> ExtractionResult: ...


@dataclass
class ExtractionResult:
    """Typed outcome of a format strategy run."""

    images: list[ImageEntry] = field(default_factory=list)
    markdown: str = ""
    diagnostics: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extension-keyed strategy registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, ImageExtractionStrategy] = {}


def register_strategy(strategy: ImageExtractionStrategy) -> None:
    """Register a strategy under its (lowercased) extensions."""
    for ext in strategy.extensions:
        _REGISTRY[ext.lower()] = strategy


def strategy_for(extension: str) -> ImageExtractionStrategy | None:
    """Return the strategy owning ``extension`` (e.g. ``".docx"``), or None."""
    return _REGISTRY.get(extension.lower())


def registered_extensions() -> frozenset[str]:
    """All extensions currently registered in the strategy registry."""
    return frozenset(_REGISTRY)


def extract_by_extension(source: Path, converted_markdown: str = "") -> ExtractionResult:
    """Dispatch a source file to its strategy by extension.

    Unsupported extensions (including ``.pdf``, which stays on the legacy
    extractor path) yield a typed unsupported result instead of entering the
    DOCX parser.
    """
    strategy = strategy_for(source.suffix)
    if strategy is None:
        return ExtractionResult(
            markdown=converted_markdown,
            diagnostics=[f"no image extraction strategy for '{source.suffix}'"],
        )
    return strategy.extract(source, converted_markdown)


# ---------------------------------------------------------------------------
# Relationship resolution and path safety
# ---------------------------------------------------------------------------


def _parse_relationships(rels_bytes: bytes) -> dict[str, str]:
    """Map relationship Id → target for a ``.rels`` part.

    External targets (``TargetMode="External"``) are skipped — they have no
    package member behind them.
    """
    root = etree.fromstring(rels_bytes)
    rels: dict[str, str] = {}
    for rel in root:
        if not isinstance(rel.tag, str):
            continue
        rid = rel.get("Id")
        target = rel.get("Target")
        if rid and target and rel.get("TargetMode") != "External":
            rels[rid] = target
    return rels


def _normalize_package_path(target: str) -> str | None:
    """Normalize an OPC relationship target into a safe package member path.

    OPC targets are relative to the part directory (``word/``); a leading
    ``/`` is package-relative. Returns ``None`` when the path escapes the
    package (``..`` traversal past the package root).
    """
    raw = target.replace("\\", "/").strip()
    if not raw:
        return None
    if raw.startswith("/"):
        candidate = PurePosixPath(raw.lstrip("/"))
    else:
        candidate = PurePosixPath("word") / raw
    depth = 0
    for part in candidate.parts:
        if part == "..":
            depth -= 1
            if depth < 0:
                return None
        elif part not in ("", "."):
            depth += 1
    if depth <= 0:
        return None
    return posixpath.normpath(candidate.as_posix())


# ---------------------------------------------------------------------------
# Heading helpers
# ---------------------------------------------------------------------------


def _is_heading_style(style: str) -> bool:
    """True when an OOXML ``w:pStyle`` value denotes a heading or title."""
    v = style.strip().lower()
    return v == "title" or "heading" in v


def _heading_level(style: str) -> int:
    """Heading level from a style value: ``Heading1`` → 1, ``Title`` → 1."""
    m = re.search(r"(\d+)\s*$", style)
    return int(m.group(1)) if m else 1


# ---------------------------------------------------------------------------
# DOCX strategy
# ---------------------------------------------------------------------------


class DocxImageExtractionStrategy:
    """Streaming DOCX image extraction with precise structural positioning."""

    extensions = frozenset({".docx"})

    def extract(self, source: Path, converted_markdown: str = "") -> ExtractionResult:
        """Open the DOCX package, extract positioned body images, enrich markdown."""
        if not source.exists():
            return ExtractionResult(
                markdown=converted_markdown,
                diagnostics=[f"source not found: {source}"],
            )
        try:
            zf = zipfile.ZipFile(str(source))
        except (zipfile.BadZipFile, OSError) as exc:
            return ExtractionResult(
                markdown=converted_markdown,
                diagnostics=[f"cannot open DOCX {source.name}: {exc}"],
            )

        with zf:
            warnings: list[str] = []
            diagnostics: list[str] = []
            members = set(zf.namelist())

            self._warn_unsupported_containers(zf, members, warnings)

            rels: dict[str, str] = {}
            if DOCUMENT_RELS not in members:
                warnings.append(
                    f"missing {DOCUMENT_RELS}: relationships cannot be resolved; "
                    "no images extracted from body"
                )
            else:
                try:
                    rels = _parse_relationships(zf.read(DOCUMENT_RELS))
                except etree.XMLSyntaxError as exc:
                    warnings.append(
                        f"malformed {DOCUMENT_RELS}: {exc}; no images extracted from body"
                    )

            images: list[ImageEntry] = []
            if DOCUMENT_XML not in members:
                warnings.append(f"missing {DOCUMENT_XML}: no body images extracted")
            else:
                try:
                    images = self._parse_document(
                        zf, members, rels, source.name, warnings
                    )
                except etree.XMLSyntaxError as exc:
                    warnings.append(
                        f"malformed {DOCUMENT_XML}: {exc}; no body images extracted"
                    )
                except zipfile.BadZipFile as exc:
                    warnings.append(f"unreadable DOCX package: {exc}")

            markdown, inject_diags = inject_image_refs(converted_markdown, images)
            diagnostics.extend(inject_diags)

            return ExtractionResult(
                images=images,
                markdown=markdown,
                diagnostics=diagnostics,
                warnings=warnings,
            )

    # -- streaming document.xml parse --------------------------------------

    def _parse_document(
        self,
        zf: zipfile.ZipFile,
        members: set[str],
        rels: dict[str, str],
        source_name: str,
        warnings: list[str],
    ) -> list[ImageEntry]:
        """Stream ``word/document.xml`` tracking paragraph/run/drawing state.

        Uses ``lxml.etree.iterparse`` with a tag filter: non-matching elements
        are discarded as they are parsed, and every matching element is
        cleared at its end event, keeping memory bounded for very large
        documents. ``r:embed`` references are captured at the ``a:blip``
        start event into a pending per-drawing list (the subtree is discarded
        before the drawing ends) and resolved when the ``wp:inline`` /
        ``wp:anchor`` end event fires.
        """
        images: list[ImageEntry] = []
        paragraph_index = -1
        run_index = -1
        drawing_index = 0
        run_char_count = 0
        paragraph_parts: list[str] = []
        paragraph_style: str | None = None
        heading_stack: list[str] = []
        pending_drawing: dict[str, object] | None = None

        with zf.open(DOCUMENT_XML) as xml_stream:
            context = etree.iterparse(
                xml_stream, events=("start", "end"), tag=_ITERPARSE_TAGS
            )
            for event, elem in context:
                tag = elem.tag
                if event == "start":
                    if tag == _W + "p":
                        paragraph_index += 1
                        run_index = -1
                        drawing_index = 0
                        run_char_count = 0
                        paragraph_parts = []
                        paragraph_style = None
                    elif tag == _W + "r":
                        run_index += 1
                        run_char_count = 0
                    elif tag == _W + "t":
                        text = elem.text or ""
                        paragraph_parts.append(text)
                        run_char_count += len(text)
                    elif tag == _W + "pStyle":
                        paragraph_style = elem.get(_W + "val")
                    elif tag in (_WP + "inline", _WP + "anchor"):
                        drawing_index += 1
                        pending_drawing = {
                            "anchor_type": "inline" if tag == _WP + "inline" else "anchor",
                            "r_ids": [],
                        }
                    elif tag == _A + "blip":
                        if pending_drawing is not None:
                            rid = elem.get(_R + "embed")
                            if rid is None:
                                rid = elem.get(_R + "link")
                            r_ids = pending_drawing["r_ids"]
                            assert isinstance(r_ids, list)
                            r_ids.append(rid)
                else:  # end
                    if tag == _W + "p":
                        text = "".join(paragraph_parts).strip()
                        if paragraph_style and _is_heading_style(paragraph_style):
                            level = max(1, _heading_level(paragraph_style))
                            heading_stack = heading_stack[: level - 1] + [text]
                    elif tag in (_WP + "inline", _WP + "anchor"):
                        if pending_drawing is not None:
                            self._resolve_drawing(
                                zf=zf,
                                anchor_type=str(pending_drawing["anchor_type"]),
                                r_ids=list(pending_drawing["r_ids"]),
                                paragraph_index=paragraph_index,
                                run_index=run_index,
                                run_offset=run_char_count,
                                drawing_index=drawing_index - 1,
                                heading_stack=heading_stack,
                                paragraph_parts=paragraph_parts,
                                source_name=source_name,
                                members=members,
                                rels=rels,
                                images=images,
                                warnings=warnings,
                            )
                        pending_drawing = None

                    # Bound memory: matching elements stay in the tree until
                    # their parent ends, so drop them and their already closed
                    # siblings once processed.
                    elem.clear()
                    while elem.getprevious() is not None:
                        parent = elem.getparent()
                        if parent is None:
                            break
                        del parent[0]

        return images

    # -- drawing resolution ------------------------------------------------

    def _resolve_drawing(
        self,
        *,
        zf: zipfile.ZipFile,
        anchor_type: str,
        r_ids: list[str | None],
        paragraph_index: int,
        run_index: int,
        run_offset: int,
        drawing_index: int,
        heading_stack: list[str],
        paragraph_parts: list[str],
        source_name: str,
        members: set[str],
        rels: dict[str, str],
        images: list[ImageEntry],
        warnings: list[str],
    ) -> None:
        """Resolve every captured ``r:embed`` reference into an ImageEntry."""
        if not r_ids:
            return  # chart/shape drawing without a raster — not an image

        section_context = "".join(paragraph_parts).strip()[:200]
        heading_path = " > ".join(h for h in heading_stack if h)
        if not section_context and heading_stack:
            section_context = heading_stack[-1]
        structural_path = (
            f"body/p[{paragraph_index}]/r[{run_index}]/{anchor_type}[{drawing_index}]"
        )

        successes = 0
        failures: list[str] = []
        for rid in r_ids:
            if rid is None:
                failures.append("linked (external) image is not embedded; skipped")
                continue

            target = rels.get(rid)
            if target is None:
                failures.append(f"relationship rId '{rid}' not found; skipped")
                continue

            member = _normalize_package_path(target)
            if member is None:
                failures.append(
                    f"relationship rId '{rid}' escapes the package ('{target}'); skipped"
                )
                continue
            if not member.startswith(MEDIA_PREFIX):
                failures.append(
                    f"relationship rId '{rid}' resolves outside {MEDIA_PREFIX} "
                    f"('{target}'); skipped"
                )
                continue
            if member not in members:
                failures.append(f"media part '{member}' missing from package; skipped")
                continue

            try:
                image_bytes = zf.read(member)
            except Exception as exc:
                failures.append(f"failed to read '{member}': {exc}; skipped")
                continue

            images.append(
                ImageEntry(
                    id=str(uuid.uuid4()),
                    source_file=source_name,
                    context_text=section_context,
                    filename=PurePosixPath(member).name,
                    image_bytes=image_bytes,
                    document_order=len(images) + 1,
                    paragraph_index=paragraph_index,
                    run_index=run_index,
                    run_offset=run_offset,
                    drawing_index=drawing_index,
                    anchor_type=anchor_type,
                    structural_path=structural_path,
                    heading_path=heading_path,
                    section_context=section_context,
                )
            )
            successes += 1

        if failures and successes:
            # Partial failure inside one drawing: attach the note to the
            # entries that did resolve so the failure stays actionable.
            for img in images[-successes:]:
                img.warnings.extend(failures)
        elif failures:
            warnings.extend(failures)

    # -- unsupported containers --------------------------------------------

    def _warn_unsupported_containers(
        self, zf: zipfile.ZipFile, members: set[str], warnings: list[str]
    ) -> None:
        """Emit actionable warnings for header images and SmartArt diagrams."""
        for part in sorted(m for m in members if _HEADER_RELS_RE.match(m)):
            try:
                rels = _parse_relationships(zf.read(part))
            except (etree.XMLSyntaxError, KeyError) as exc:
                warnings.append(f"header relationships '{part}' unreadable: {exc}")
                continue
            image_targets = sorted(
                t for t in rels.values() if t.lower().endswith(_IMAGE_SUFFIXES)
            )
            if image_targets:
                shown = ", ".join(image_targets[:3])
                more = "..." if len(image_targets) > 3 else ""
                warnings.append(
                    f"header part '{part}' embeds {len(image_targets)} image(s) "
                    f"({shown}{more}) — headers are not supported; skipped"
                )
        for part in sorted(m for m in members if m.startswith("word/diagrams/")):
            warnings.append(
                f"SmartArt diagram '{part}' is not supported; skipped"
            )


# ---------------------------------------------------------------------------
# Markdown reference injection
# ---------------------------------------------------------------------------


def _normalize_heading(text: str) -> str:
    """Normalized heading text for matching: lowercased, collapsed spaces."""
    return " ".join(text.strip().lower().split())


def _is_heading_line(line: str) -> bool:
    """True when a Markdown line is an ATX heading."""
    return bool(re.match(r"^\s{0,3}#{1,6}\s", line))


def _markdown_heading_spans(lines: list[str]) -> list[tuple[int, int, str, int]]:
    """Return ``(line_index, level, normalized_text, span_end)`` per heading.

    ``span_end`` is the first line that starts a heading of the same or a
    higher level (or the end of the document).
    """
    heads: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", line)
        if m:
            heads.append((i, len(m.group(1)), _normalize_heading(m.group(2))))
    spans: list[tuple[int, int, str, int]] = []
    for idx, (i, lvl, text) in enumerate(heads):
        end = len(lines)
        for j in range(idx + 1, len(heads)):
            if heads[j][1] <= lvl:
                end = heads[j][0]
                break
        spans.append((i, lvl, text, end))
    return spans


def _deepest_heading(heading_path: str) -> str:
    """Last component of a ``a > b > c`` heading path."""
    if " > " in heading_path:
        return heading_path.rsplit(" > ", 1)[-1]
    return heading_path


def _image_ref(img: ImageEntry) -> str:
    """Markdown reference for a positioned image entry."""
    stem = PurePosixPath(img.filename or "image").stem
    return f"![{stem}](media/{img.filename})"


def inject_image_refs(
    markdown: str, images: list[ImageEntry]
) -> tuple[str, list[str]]:
    """Inject ``![alt](media/filename)`` references into converted Markdown.

    Deterministic, line-based strategy:
    1. Each image is matched to the first Markdown heading whose normalized
       text equals the deepest component of the image ``heading_path``.
    2. Within a section, refs are inserted after the section's paragraph lines
       in document order (one ref per paragraph). When the section runs out
       of paragraph lines, the remaining refs are appended at the section end
       with a diagnostic.
    3. Images without a heading match are appended at the end of the document
       in document order, with a diagnostic naming the missing heading.

    Returns ``(updated_markdown, diagnostics)``.
    """
    if not images:
        return markdown, []
    if not markdown.strip():
        return "\n".join(_image_ref(i) for i in images), []

    diagnostics: list[str] = []
    lines = markdown.split("\n")
    headings = _markdown_heading_spans(lines)

    sections: list[list[ImageEntry]] = [[] for _ in headings]
    unmatched: list[ImageEntry] = []
    for img in images:
        section_idx = next(
            (
                idx
                for idx, (_i, _lvl, text, _end) in enumerate(headings)
                if text == _normalize_heading(_deepest_heading(img.heading_path))
            ),
            None,
        )
        if section_idx is not None:
            sections[section_idx].append(img)
        else:
            unmatched.append(img)

    insertions: list[tuple[int, str]] = []  # (line index to insert AFTER, ref)
    for idx, section_images in enumerate(sections):
        if not section_images:
            continue
        h_idx, _lvl, text, span_end = headings[idx]
        para_lines = [
            i
            for i in range(h_idx + 1, span_end)
            if lines[i].strip() and not _is_heading_line(lines[i])
        ]
        for n, img in enumerate(section_images):
            ref = _image_ref(img)
            if n < len(para_lines):
                insertions.append((para_lines[n], ref))
            else:
                diagnostics.append(
                    f"image {img.document_order} ('{img.filename}'): no exact paragraph "
                    f"position in section '{text}'; appended at section end"
                )
                insertions.append((span_end - 1, ref))

    for img in unmatched:
        diagnostics.append(
            f"image {img.document_order} ('{img.filename}'): no markdown heading match "
            f"for '{img.heading_path or '(no heading)'}'; appended in document order"
        )
        insertions.append((len(lines) - 1, _image_ref(img)))

    # Insert from the end backwards so earlier line indices stay valid.
    for line_idx, ref in sorted(insertions, key=lambda x: x[0], reverse=True):
        lines.insert(line_idx + 1, ref)

    return "\n".join(lines), diagnostics


# Register the DOCX strategy at import time.
register_strategy(DocxImageExtractionStrategy())