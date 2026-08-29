"""World importer — in-process analysis facade (Phase 2).

Read-only analysis that preserves source order and context. Pure logic: given
a file's text it splits markdown into heading-delimited chunks, captures the
hierarchical heading path, the sequence, nearby text/anchor context, and the
image references found near each chunk. It never writes canon and never
guesses placement — every image association is surfaced for review.

This is the server-owned replacement for the legacy ``sync_lore`` extraction
path during import: it keeps the same heading/source-order semantics while
returning an ``AnalysisReport`` the import service can review and merge.

Slice 1 adds ``resolve_target``: a pure function that normalizes a
candidate's source path to its canonical OKF target (IM-1.2). Legacy
uppercase sections and supported subfolder aliases are mapped; unknown or
ambiguous candidates are returned with a ``review``/``rejected`` status
and a diagnostic — never a guessed target.

importador-auto-frontmatter (Phase 1) adds the deterministic H1-H5 tree
splitter: ``detect_heading_structure`` (Step 0, with a Hermes structure-
inference fallback seam) and ``split_heading_tree`` (Step 1), which produce
complete-ficha candidates with parent-qualified canonical identities,
empty-scaffold preservation, childless prose folding, and reference-image
diagnostics. This is additive — the legacy chunk flow stays untouched.
"""

from __future__ import annotations

import itertools
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterator

from import_intake import UnsafePathError, reject_unsafe_path
from import_models import (
    ImagePlacement,
    MediaDiagnostic,
    Provenance,
    TargetResolution,
    canonical_identity_from_segments,
    normalize_identity_segment,
)
from okf_contract import CANONICAL_ID_SEPARATOR, is_canonical_id
from wiki.world_authority import is_importer_scope_permitted

if TYPE_CHECKING:
    from sync_lore.schemas import ImageEntry

logger = logging.getLogger(__name__)

_RE_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
_RE_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_RE_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")

# ---------------------------------------------------------------------------
# Markdown noise cleaning (converted .docx/.pdf sources).
#
# markitdown-style conversions wrap Word formatting as markdown markers, so
# the splitter output can carry ``**bold**`` in headings/titles and even a
# heading that is only an inline image. Cleaning is applied to derived
# metadata (title, canonical identity) and to the ficha BODY for a clean
# review/OKF output — only the formatting MARKERS are removed, the
# underlying text and real images are preserved.
# ---------------------------------------------------------------------------

_RE_BODY_REF_IMAGE = re.compile(r"!\[([^\]]*)\]\[([^\]]*)\]")
_RE_BODY_INLINE_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")
_RE_BODY_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_RE_BODY_BOLD_UNDER = re.compile(r"__(.+?)__", re.S)
_RE_BODY_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_RE_BODY_ITALIC_UNDER = re.compile(r"(?<!_)_([^_\n]+?)_(?!_)")
_RE_BODY_CODE = re.compile(r"`([^`\n]+?)`")


def clean_markdown_body(text: str) -> str:
    """Remove emphasis/code markers from a ficha body, preserving images.

    ``**bold**``/``__bold__``/``*italic*``/``_italic_``/`` `code` `` are
    unwrapped to their inner text. Inline and reference images are KEPT
    (they are real content the gallery renders); only the formatting
    markers disappear, so the review and the written OKF body read clean.
    """
    if not text:
        return ""
    text = _RE_BODY_BOLD.sub(r"\1", text)
    text = _RE_BODY_BOLD_UNDER.sub(r"\1", text)
    text = _RE_BODY_ITALIC.sub(r"\1", text)
    text = _RE_BODY_ITALIC_UNDER.sub(r"\1", text)
    text = _RE_BODY_CODE.sub(r"\1", text)
    return text


# markitdown cannot inline very large embedded docx images and emits a broken
# truncated placeholder instead of real bytes: ``![alt](data:image/png;base64...)``
# (literal ``...``). It is not a valid image and would render as "Imagen no
# disponible"; the real images are referenced by the injected ``media/`` refs.
_RE_BROKEN_DATA_URI = re.compile(
    r"!\[[^\]]*\]\(\s*data:image/[a-zA-Z0-9+.-]+;base64(?:,)?\.\.\.\s*\)"
)


def strip_broken_data_uris(text: str) -> str:
    """Remove markitdown's truncated data-URI image placeholders.

    These carry no real image bytes (``base64...``) so they must never land in
    a ficha body; the extracted images are referenced via ``media/`` refs that
    the docx parser injects at the correct heading position.
    """
    if not text:
        return text
    return _RE_BROKEN_DATA_URI.sub("", text)


def clean_markdown_title(text: str) -> str:
    """Clean a heading-derived title: images → alt, emphasis unwrapped.

    Unlike the body cleaner, inline images are REMOVED from a title because
    an identity cannot contain an image payload; the alt text (when
    present) is kept, otherwise the segment is empty.
    """
    if not text:
        return ""
    text = _RE_BODY_REF_IMAGE.sub(lambda m: m.group(1).strip(), text)
    text = _RE_BODY_INLINE_IMAGE.sub(lambda m: m.group(1).strip(), text)
    # An image-only heading leaves orphaned wrapping markers (``**``) with no
    # inner text; drop the marker characters outright in the title context.
    text = text.replace("**", "").replace("__", "")
    return clean_markdown_body(text).strip()


@dataclass
class AnalyzedChunk:
    """One heading-delimited chunk with its preserved source context."""

    source_sequence: int
    heading_path: str
    nearby_text_anchor: str
    content: str
    images: list[ImagePlacement] = field(default_factory=list)


@dataclass
class AnalyzedFile:
    """A single source file analyzed read-only."""

    source_path: str
    source_hash: str
    size_bytes: int
    chunks: list[AnalyzedChunk] = field(default_factory=list)
    # PR1 (sync-lore-in-importer): extracted media persisted to the job
    # spool, attached for downstream review/execution (advisory metadata —
    # never changes candidate identity or digest).
    media: list[ExtractedMedia] = field(default_factory=list)
    # PR1: fail-open conversion/extraction diagnostic tokens
    # (e.g. "conversion_unavailable", "conversion_failed",
    # "media_extraction_failed"). Empty when no conversion was attempted.
    diagnostics: list[str] = field(default_factory=list)
    # PR2 (docx-image-extraction): file-level strategy warnings (unsupported
    # headers/SmartArt). In-memory advisory metadata — never persisted.
    warnings: list[str] = field(default_factory=list)

    def content_preview(self) -> str:
        """Flatten ordered chunks into a candidate body (source order kept)."""
        return "\n\n".join(c.content for c in self.chunks)


@dataclass
class ExtractedMedia:
    """An extracted image persisted to the job spool (PR1 media bundle).

    Carries the sync_lore ``ImageEntry`` (original bytes, filename, page,
    chunk reference, source context) plus the spool-relative path where the
    bytes were stored, so downstream execution can feed ``plan_placements``
    the original bytes without re-opening the source archive.

    PR2 (docx-image-extraction): the DOCX position contract is mirrored as
    flat additive fields (populated from the ``ImageEntry``) so spool
    persistence and placement planning keep the structural position without
    depending on the source archive.
    """

    image: ImageEntry
    spool_relative_path: str
    document_order: int = 0          # 1-based global order of extracted images
    paragraph_index: int = 0         # 0-based index of the containing w:p
    anchor_type: str = ""            # "inline" | "anchor" ("" when unknown)
    structural_path: str = ""        # e.g. body/p[3]/r[1]/inline[0]
    heading_path: str = ""           # heading hierarchy at extraction time
    context_text: str = ""           # paragraph/heading text around the image
    warnings: list[str] = field(default_factory=list)  # per-image notes


@dataclass
class AnalysisReport:
    """Ordered analysis of every intake file (source order preserved)."""

    files: list[AnalyzedFile] = field(default_factory=list)

    def ordered_files(self) -> list[AnalyzedFile]:
        return list(self.files)


def _split_chunks(text: str) -> list[tuple[str, str, str]]:
    """Split markdown into (heading_path, anchor, content) preserving order.

    ``##`` starts a new heading path; ``###`` nests under the last ``##``.
    The anchor is the first sentence/line of each chunk so the placement can
    point at nearby text without guessing.
    """
    lines = text.split("\n")
    sections: list[tuple[str, str, list[str]]] = []
    parent: str | None = None
    current: tuple[str, list[str]] | None = None

    for line in lines:
        m = _RE_HEADING.match(line.strip())
        if m:
            level, heading = len(m.group(1)), m.group(2).strip()
            if level == 1:
                parent = None
                path = heading
            elif level == 2:
                parent = heading
                path = heading
            else:  # level 3
                path = f"{parent} > {heading}" if parent else heading
            current = (path, [line])
            sections.append((path, "", current[1]))
            continue
        if current is not None:
            current[1].append(line)

    if not sections:
        content = text.strip()
        if content:
            sections.append(("", "", [content]))

    out: list[tuple[str, str, str]] = []
    for path, _anchor, body in sections:
        content = "\n".join(body).strip()
        if not content:
            continue
        anchor = _first_anchor(content)
        out.append((path, anchor, content))
    return out


def _first_anchor(content: str) -> str:
    """First meaningful body line (up to 120 chars) as a nearby-text anchor.

    Heading lines and image lines are skipped so the anchor points at nearby
    prose, never the section title or an image markdown.
    """
    for line in content.split("\n"):
        stripped = line.strip().lstrip("#").strip()
        if not stripped or stripped.startswith("!"):
            continue
        if line.strip().startswith("#"):
            continue
        return stripped[:120]
    return content[:120]


def _extract_images(content: str, source_path: str, sequence: int,
                    heading_path: str, anchor: str) -> list[ImagePlacement]:
    """Extract contextual image anchors for one chunk, never guessing."""
    placements: list[ImagePlacement] = []
    for m in _RE_IMAGE.finditer(content):
        alt, ref = m.group(1).strip(), m.group(2).strip()
        if ref.startswith(("http://", "https://", "data:")):
            continue
        placements.append(ImagePlacement(
            gallery_asset_id="",
            relative_media_path=ref,
            alt_text=alt,
            target_ficha=heading_path,
            confidence=1.0,
            placement_status="proposed",
        ))
    return placements


def analyze_markdown(text: str, source_path: str, source_hash: str,
                     size_bytes: int) -> AnalyzedFile:
    """Analyze one markdown file read-only, preserving source order."""
    chunks: list[AnalyzedChunk] = []
    for sequence, (path, anchor, content) in enumerate(_split_chunks(text)):
        images = _extract_images(content, source_path, sequence, path, anchor)
        chunks.append(AnalyzedChunk(
            source_sequence=sequence,
            heading_path=path,
            nearby_text_anchor=anchor,
            content=content,
            images=images,
        ))
    return AnalyzedFile(
        source_path=source_path,
        source_hash=source_hash,
        size_bytes=size_bytes,
        chunks=chunks,
    )


def analyze_source(
    files: list[dict],
    read_file: Callable[[str], str],
    file_path: Callable[[str], Path] | None = None,
    spool_root: Path | None = None,
) -> AnalysisReport:
    """Analyze all intake files in source order, preserving every anchor.

    ``files``: list of ``{"relative": str, "sha256": str, "size": int}`` in
    source order. ``read_file`` returns text for a relative path. The service
    maps each analyzed file to a candidate; analysis stays pure.

    PR1 (sync-lore-in-importer): when ``file_path`` is provided — a resolver
    from a relative path to the on-disk file — ``.docx``/``.pdf`` sources are
    dispatched through ``safe_convert_to_markdown`` (never letting
    ``SystemExit`` kill the server) and their extracted media is persisted to
    the job spool with metadata. Converted candidates use the ``.md``
    identity path so ``resolve_target`` maps them to the correct OKF section.
    Markdown sources keep their identity and chunk flow unchanged; media
    extraction for disk image references is additive metadata only.
    ``spool_root`` is the job spool root under which media is stored as
    ``media/<source-stem>/<filename>``; it defaults to each source file's
    parent directory when omitted. When ``file_path`` is omitted (legacy
    callers), binary sources yield an empty candidate exactly as before and
    the markdown flow is untouched.
    """
    report = AnalysisReport()
    for entry in files:
        relative = entry["relative"]
        digest = entry.get("sha256") or ""
        size = entry.get("size") or 0
        suffix = Path(relative).suffix.lower()
        if suffix in _CONVERTIBLE_SUFFIXES and file_path is not None:
            source = Path(file_path(relative))
            media_root = spool_root if spool_root is not None else source.parent
            text, images, diagnostics, warnings = _convert_source(source)
            if text is None:
                text = ""
            analyzed = analyze_markdown(
                text, normalized_identity_path(relative), digest, size)
            analyzed.media = store_media_in_spool(images, relative, media_root)
            analyzed.diagnostics = diagnostics
            analyzed.warnings = warnings
            _enrich_placements(analyzed)
            report.files.append(analyzed)
        elif suffix == ".md" and file_path is not None:
            source = Path(file_path(relative))
            media_root = spool_root if spool_root is not None else source.parent
            text = read_file(relative) or ""
            analyzed = analyze_markdown(text, relative, digest, size)
            try:
                images = extract_images_from_file(source)
            except Exception as exc:  # noqa: BLE001 — media is optional, never fatal
                analyzed.diagnostics.append("media_extraction_failed")
                logger.warning(
                    "Image extraction failed for %s: %s", source, exc)
                images = []
            analyzed.media = store_media_in_spool(images, relative, media_root)
            _enrich_placements(analyzed)
            report.files.append(analyzed)
        else:
            text = read_file(relative) or ""
            analyzed = analyze_markdown(text, relative, digest, size)
            report.files.append(analyzed)
    return report


# ---------------------------------------------------------------------------
# PR1 — safe format conversion + media extraction (sync-lore-in-importer)
# ---------------------------------------------------------------------------

_CONVERTIBLE_SUFFIXES = frozenset({".docx", ".pdf"})
_EXTRACTABLE_SUFFIXES = frozenset({".md", ".docx", ".pdf"})


def normalized_identity_path(relative: str) -> str:
    """Map a source path to its markdown identity path (PR1 identity rule).

    Converted ``.docx``/``.pdf`` candidates must resolve as markdown so
    ``resolve_target`` maps them to the correct OKF section; ``.md`` and any
    other source keep their path unchanged.
    """
    path = Path(relative)
    if path.suffix.lower() in _CONVERTIBLE_SUFFIXES:
        return str(path.with_suffix(".md")).replace("\\", "/")
    return relative


def safe_convert_to_markdown(file_path: Path) -> tuple[str | None, list[ImageEntry]]:
    """Convert ``.docx``/``.pdf`` to markdown, never letting the server die.

    ``sync_lore.convert_to_markdown`` raises ``SystemExit(1)`` when markitdown
    is not installed — that would terminate the import server. This wrapper
    catches it (plus any conversion error) and returns ``(None, [])`` so the
    caller records a diagnostic and produces an empty, reviewable candidate
    instead of failing the job. Images are extracted from the original file
    alongside the conversion.
    """
    text, images, _diagnostics, _warnings = _convert_source(file_path)
    return text, images


def _convert_source(file_path: Path) -> tuple[str | None, list[ImageEntry], list[str], list[str]]:
    """Convert + extract with granular diagnostics (internal seam).

    Returns ``(markdown, images, diagnostics, warnings)``. Conversion and
    media are optional and fail-open: any failure yields an empty result plus
    a diagnostic token, never an exception or process exit. ``.docx`` sources
    dispatch through the format strategy seam with the converted markdown so
    the positioned ``ImageEntry`` records are enriched with Markdown image
    references at their structural location (PR2); ``.pdf`` keeps the legacy
    extractor (no position contract).
    """
    diagnostics: list[str] = []
    warnings: list[str] = []
    try:
        from sync_lore.utils.converter import convert_to_markdown
        result = convert_to_markdown(file_path)
        if result is None:
            diagnostics.append("conversion_failed")
            logger.warning(
                "Conversion returned None for %s (markitdown failed)",
                file_path)
            return None, [], diagnostics, warnings
        try:
            if file_path.suffix.lower() == ".docx":
                from sync_lore.import_docx_parser import extract_by_extension
                extraction = extract_by_extension(
                    file_path, converted_markdown=result)
                text = extraction.markdown or result
                images = extraction.images
                diagnostics.extend(extraction.diagnostics)
                warnings.extend(extraction.warnings)
            else:
                text = result
                images = extract_images_from_file(file_path)
        except Exception as exc:  # noqa: BLE001 — media is optional, never fatal
            diagnostics.append("media_extraction_failed")
            logger.warning(
                "Image extraction failed for %s: %s", file_path, exc)
            text = result
            images = []
        # markitdown emits invalid truncated ``data:image/...;base64...``
        # placeholders for embedded docx images it cannot inline; they are not
        # real images and would break the ficha render. Drop them — the real
        # images are referenced by the ``media/`` refs the parser injects.
        if text:
            text = strip_broken_data_uris(text)
        return text, images, diagnostics, warnings
    except SystemExit:
        logger.warning("Conversion unavailable: markitdown not installed")
        diagnostics.append("conversion_unavailable")
        return None, [], diagnostics, warnings
    except Exception as exc:  # noqa: BLE001 — fail-open never breaks analysis
        logger.warning("Conversion failed for %s: %s", file_path, exc)
        diagnostics.append("conversion_failed")
        return None, [], diagnostics, warnings


def extract_images_from_file(file_path: Path) -> list[ImageEntry]:
    """Extract images from ``.md``/``.docx``/``.pdf`` reusing sync_lore.

    Markdown sources yield images referenced on disk; ``.docx`` dispatches
    through the format strategy registry (positioned extraction, PR2);
    ``.pdf`` yields embedded blobs via the legacy adapter. Any failure is
    logged and returns no images so analysis never blocks on media.
    """
    suffix = file_path.suffix.lower()
    if suffix not in _EXTRACTABLE_SUFFIXES:
        return []
    try:
        if suffix == ".md":
            from sync_lore.image_indexer import extract_images_from_md
            return extract_images_from_md(
                file_path.read_text(encoding="utf-8"),
                file_path.parent, chunk_ref="")
        elif suffix == ".docx":
            from sync_lore.import_docx_parser import extract_by_extension
            return extract_by_extension(file_path).images
        elif suffix == ".pdf":
            from sync_lore.image_indexer import extract_images_from_pdf
            return extract_images_from_pdf(file_path)
    except Exception as exc:  # noqa: BLE001 — media is optional, never fatal
        logger.warning("Image extraction failed for %s: %s", file_path, exc)
    return []


def _position_lookup(media: list[ExtractedMedia]) -> dict[str, ExtractedMedia]:
    """Map media filename → ExtractedMedia for position enrichment.

    First occurrence wins so document order is preserved for duplicate
    filenames. Keys by BOTH the spool basename (the on-disk name, possibly
    renamed on collision) and the original ``ImageEntry.filename``, so an
    injected markdown ref (``media/pic.png``) still resolves when the spool
    renamed the file (``pic-1.png``) because the target already existed
    (BUG 2 — spool collision rename vs injected ref attribution).
    """
    lookup: dict[str, ExtractedMedia] = {}
    for entry in media:
        name = Path(entry.spool_relative_path).name
        lookup.setdefault(name, entry)
        original = Path(entry.image.filename or "").name
        if original and original != name:
            lookup.setdefault(original, entry)
    return lookup


def _enrich_placements(analyzed: AnalyzedFile) -> None:
    """Merge DOCX position fields from spooled media onto chunk placements.

    Placements derived from Markdown references carry only the media path;
    the position contract lives on the extracted ``ImageEntry``. Matching by
    media filename lets injected refs (``media/pic.png``) and spool paths
    (``media/<stem>/pic.png``) resolve to the same entry. Additive only —
    identity/digest inputs are untouched.
    """
    lookup = _position_lookup(analyzed.media)
    for chunk in analyzed.chunks:
        for placement in chunk.images:
            media = lookup.get(Path(placement.relative_media_path).name)
            if media is None:
                continue
            placement.document_order = media.document_order
            placement.paragraph_index = media.paragraph_index
            placement.anchor_type = media.anchor_type
            placement.structural_path = media.structural_path
            placement.heading_path = media.heading_path
            placement.context_text = media.context_text
            if media.warnings:
                placement.warnings = list(media.warnings)


def store_media_in_spool(images: list[ImageEntry], source_rel: str,
                         spool_dir: Path) -> list[ExtractedMedia]:
    """Persist extracted image bytes under the job spool with metadata.

    Bytes land in ``<spool_dir>/media/<source-stem>/<filename>`` so review
    and execution can feed the original bytes to ``plan_placements`` without
    re-opening the source archive. Collisions are avoided by suffixing a
    counter when the target already exists. The DOCX position contract is
    mirrored onto each ``ExtractedMedia`` from its ``ImageEntry`` (PR2).
    """
    stored: list[ExtractedMedia] = []
    base = spool_dir / "media" / Path(source_rel).stem
    base.mkdir(parents=True, exist_ok=True)
    for image in images:
        name = image.filename or f"{image.id}.img"
        target = base / name
        counter = 1
        while target.exists():
            target = base / f"{Path(name).stem}-{counter}{Path(name).suffix}"
            counter += 1
        try:
            target.write_bytes(image.image_bytes)
        except OSError as exc:
            logger.warning("Failed to store media %s: %s", target, exc)
            continue
        stored.append(ExtractedMedia(
            image=image,
            spool_relative_path=str(
                target.relative_to(spool_dir)).replace("\\", "/"),
            document_order=image.document_order,
            paragraph_index=image.paragraph_index,
            anchor_type=image.anchor_type,
            structural_path=image.structural_path,
            heading_path=image.heading_path,
            context_text=image.context_text,
            warnings=list(image.warnings),
        ))
    return stored


# ---------------------------------------------------------------------------
# Slice 1 — canonical OKF target resolution (IM-1.2)
# ---------------------------------------------------------------------------

# Legacy English subfolder names mapped to canonical OKF subfolder names
# (OC8 lore skeleton: reglas, lugares, culturas, criaturas, facciones,
# artefactos, historia). The mapping is case-insensitive on the subfolder
# key; the section (``Lore``/``Personajes``) is normalized separately via
# case-insensitive comparison to ``lore``/``personajes``.
LEGACY_SUBFOLDER_ALIASES: dict[str, str] = {
    "rules": "reglas",
    "places": "lugares",
    "cultures": "culturas",
    "creatures": "criaturas",
    "factions": "facciones",
    "artifacts": "artefactos",
    "history": "historia",
}

# Canonical OKF top-level sections (lowercase, case-sensitive). Membership is
# delegated to ``world_authority.is_importer_scope_permitted`` so the importer
# shares ONE section/path authority with world creation (OC7/W9/W10).

# Legacy uppercase sections normalized to their canonical lowercase form.
_LEGACY_SECTIONS = {
    "lore": "lore",
    "personajes": "personajes",
}

# ---------------------------------------------------------------------------
# identity-path-mapping (BLOQUE 1 piece 2) — canonical_id hierarchy slugs.
#
# ``slug_segment`` turns one ``::``-separated canonical_id segment into an
# ASCII-safe, human-readable path component. It is a DIFFERENT transform from
# ``okf_contract.safe_slug_from_id`` (whole-id flat slug); that helper stays
# untouched. Pure and deterministic: no I/O, no external state.
# ---------------------------------------------------------------------------

_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slug_segment(segment: str) -> str:
    """ASCII-safe slug from one canonical_id segment.

    NFD-decompose → drop combining marks (category Mn) → lowercase →
    collapse runs of non-[a-z0-9] to a single '-' → trim leading/trailing '-'.
    Pure and deterministic. Empty input or all-punctuation input returns "".
    """
    nfd = unicodedata.normalize("NFD", segment)
    stripped = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    lowered = stripped.lower()
    collapsed = _RE_NON_ALNUM.sub("-", lowered).strip("-")
    return collapsed


def resolve_target(world: str, candidate,
                   *, mundos_dir: Path | None = None) -> TargetResolution:
    """Map a candidate's source path to its canonical OKF target.

    Pure function: never mutates the candidate, never writes files, never
    guesses ambiguous mappings. The returned ``TargetResolution`` carries:

      - ``canonical_path`` — canonical OKF target as a relative POSIX path
        (``lore/lugares/City.md``). For ``review``/``rejected`` outcomes this
        is the best-effort path the caller may surface for human approval.
      - ``normalized_source`` — the source path rewritten with the legacy
        section mapped to its canonical lowercase form.
      - ``status`` — ``"resolved"`` (canonical target determined),
        ``"review"`` (unknown section / subfolder — never guessed), or
        ``"rejected"`` (empty / unsafe source path).
      - ``diagnostic`` — reason for ``review``/``rejected``; safe to surface.
      - ``alias_used`` — which legacy alias produced the canonical target
        (e.g., ``"Lore/Places"``); empty when no alias was applied.

    When ``candidate.section`` is non-empty (BLOQUE 1 piece 1 classifier),
    the author-chosen section roots the target. BLOQUE 1 piece 2 extends that
    branch with the ``canonical_id`` hierarchy: when ``canonical_id`` is
    non-empty AND a valid canonical id (``okf_contract.is_canonical_id``),
    each ``::``-separated segment is slugged via ``slug_segment`` and becomes
    a path component — all but the last are subfolders, the last is the
    filename stem (``{section}/{slug0}/.../{slugN}.md``). Empty or invalid
    ``canonical_id``, or one whose segments all collapse to empty slugs,
    falls back to the piece-1 mapping ``{section}/{identity}.md`` where
    ``identity`` is the source filename stem. Empty ``section`` falls
    through to the legacy source-path branch below, unchanged.

    The ``world`` parameter is accepted to mirror the design contract; it is
    not currently needed for resolution (the canonical path is world-agnostic)
    but is kept so future per-world policy (custom aliases, blocked targets)
    can extend the function without a signature change.
    """
    del world, mundos_dir  # resolution is world-agnostic today; reserved for future policy
    source = (getattr(getattr(candidate, "provenance", None),
                     "source_path", None) or "").replace("\\", "/")

    if not source.strip():
        return TargetResolution(
            canonical_path="", normalized_source="",
            status="rejected", diagnostic="empty source path",
        )

    # Reject traversal / absolute / hidden / system paths up front. The
    # candidate must never reach canon if the source path is unsafe.
    try:
        reject_unsafe_path(source)
    except UnsafePathError as exc:
        return TargetResolution(
            canonical_path="", normalized_source=source,
            status="rejected", diagnostic=str(exc),
        )

    parts = [p for p in source.split("/") if p]
    if not parts:
        return TargetResolution(
            canonical_path="", normalized_source=source,
            status="rejected", diagnostic="empty source path",
        )

    # The last path component is always the filename (must end with .md).
    filename = parts[-1]
    if not filename.endswith(".md"):
        return TargetResolution(
            canonical_path=source, normalized_source=source,
            status="review",
            diagnostic=f"non-markdown source path: {filename!r}",
        )
    identity = Path(filename).stem

    # Classifier (BLOQUE 1 piece 1): the author-chosen section wins over the
    # legacy source-path derivation. Empty section (legacy jobs / files with
    # no map entry) falls through to the legacy branch unchanged.
    #
    # identity-path-mapping (BLOQUE 1 piece 2): when the section is set AND
    # the candidate carries a valid hierarchical canonical_id, each ``::``
    # segment becomes a slugged path component — all but the last are
    # subfolders, the last is the filename stem. Empty or invalid
    # canonical_id (or one whose segments all collapse to empty slugs) falls
    # back to the piece-1 ``{section}/{identity}.md`` mapping (byte-identical).
    section_choice = getattr(candidate, "section", "") or ""
    if section_choice:
        canonical_id = getattr(candidate, "canonical_id", "") or ""
        if canonical_id and is_canonical_id(canonical_id):
            raw_segments = canonical_id.split(CANONICAL_ID_SEPARATOR)
            slugs = [s for s in (slug_segment(seg) for seg in raw_segments) if s]
            if slugs:
                folders = "/".join(slugs[:-1])
                stem = slugs[-1]
                canonical = (
                    f"{section_choice}/{folders}/{stem}.md"
                    if folders else f"{section_choice}/{stem}.md"
                )
                return TargetResolution(
                    canonical_path=canonical, normalized_source=canonical,
                    status="resolved", alias_used="",
                )
        # Fallback: empty/invalid canonical_id or all-segments-collapsed.
        canonical = f"{section_choice}/{identity}.md"
        return TargetResolution(
            canonical_path=canonical, normalized_source=canonical,
            status="resolved", alias_used="",
        )

    # Normalize the top-level section (case-insensitive Lore/Personajes).
    head = parts[0]
    head_lower = head.lower()
    if head_lower in _LEGACY_SECTIONS:
        section = _LEGACY_SECTIONS[head_lower]
    else:
        section = head_lower

    # Everything between the section and the filename is the subfolder chain.
    rest = parts[1:-1]

    # Legacy alias: ``lore/<legacy subfolder>/...`` -> ``lore/<okf subfolder>/...``
    if section == "lore" and rest:
        first_sub_lower = rest[0].lower()
        if first_sub_lower in LEGACY_SUBFOLDER_ALIASES:
            okf_sub = LEGACY_SUBFOLDER_ALIASES[first_sub_lower]
            alias_key = f"Lore/{rest[0]}"
            # Preserve additional nested subfolders after the alias.
            tail = rest[1:]
            tail_str = ("/" + "/".join(tail)) if tail else ""
            canonical = f"lore/{okf_sub}{tail_str}/{identity}.md"
            return TargetResolution(
                canonical_path=canonical, normalized_source=canonical,
                status="resolved", alias_used=alias_key,
            )

    # No alias applied. If there are subfolders under a canonical section
    # they are unknown -> review (never guessed). The diagnostic carries
    # the original subfolder name for the reviewer's reference.
    if rest:
        if is_importer_scope_permitted(section):
            normalized_path = f"{section}/{'/'.join(rest)}/{identity}.md"
            return TargetResolution(
                canonical_path=normalized_path,
                normalized_source=normalized_path,
                status="review",
                diagnostic=f"unknown subfolder under {section!r}: {rest[0]!r}",
            )
        # Unknown top-level section with subfolders -> review with section
        # diagnostic (the canonical_path keeps the original structure so a
        # reviewer can override or relabel).
        return TargetResolution(
            canonical_path=source, normalized_source=source,
            status="review",
            diagnostic=f"unknown section: {parts[0]!r}",
        )

    # No subfolders. The top-level section itself must be a canonical OKF
    # section (authority-validated); anything else is reported for review
    # (never guessed).
    if not is_importer_scope_permitted(section):
        return TargetResolution(
            canonical_path=source, normalized_source=source,
            status="review",
            diagnostic=f"unknown section: {parts[0]!r}",
        )

    # Top-level file under a canonical section (resolved). Section case
    # normalization (``Lore`` -> ``lore``) is NOT recorded as an alias —
    # ``alias_used`` is reserved for the subfolder alias table.
    canonical = f"{section}/{identity}.md"
    return TargetResolution(
        canonical_path=canonical, normalized_source=canonical,
        status="resolved", alias_used="",
    )


# ---------------------------------------------------------------------------
# Phase 1 — deterministic H1-H5 tree splitter (importador-auto-frontmatter)
#
# Step 0 detects a usable H1-H5 heading tree; Step 1 splits the source into
# complete-ficha candidates. Every H1 is a valid root/index ficha (including
# empty scaffolds); siblings with children become fichas; childless prose
# folds verbatim into the parent ficha; a source without usable headings
# yields a single implicit ficha (legacy single-candidate path). Canonical
# identities are parent-qualified ``::``-joined, NFC-normalized,
# whitespace-collapsed heading segments with ``#N`` ordinals for duplicate
# same-title siblings.
# ---------------------------------------------------------------------------

_RE_HEADING_TREE = re.compile(r"^(#{1,5})\s+(.+)$")
_RE_REF_IMAGE = re.compile(r"!\[([^\]]*)\]\[([^\]]+)\]")
_RE_REF_DEFINITION = re.compile(r"^\[([^\]]+)\]:\s*(\S+)(?:\s+.*)?$")


@dataclass
class HeadingSpan:
    """One detected H1-H5 heading (Step 0)."""

    level: int
    title: str
    source_text: str
    line_index: int


@dataclass
class HeadingStructure:
    """Step 0 detection result for a source text."""

    spans: list[HeadingSpan] = field(default_factory=list)
    usable: bool = True
    diagnostic: str = ""
    inferred: bool = False    # True when spans came from the inference seam


@dataclass
class StructureNode:
    """One complete-ficha node of the deterministic H1-H5 split (Step 1).

    ``canonical_id`` is the parent-qualified identity (``::``-joined
    normalized heading segments, ``#N`` ordinals for duplicate same-title
    siblings). ``body`` is the ficha's own prose plus every childless
    descendant folded in verbatim (heading line included); ``children`` are
    the ficha children in source order. ``media_diagnostics`` carries the
    reference-image placements found in the ficha body.
    """

    level: int
    title: str                  # raw heading title (display)
    heading_text: str           # verbatim heading line
    source_line: int            # 0-based line index of the heading
    canonical_segment: str = ""
    canonical_id: str = ""
    body: str = ""
    children: list["StructureNode"] = field(default_factory=list)
    is_ficha: bool = False
    is_implicit: bool = False   # document-level fallback root (no headings)
    source_order: int = -1      # document order among fichas
    media_diagnostics: list[MediaDiagnostic] = field(default_factory=list)


@dataclass
class HeadingTree:
    """Step 1 result — the complete-ficha tree of a source document.

    ``fichas`` are in source order; ``usable_structure``/``diagnostic``
    mirror the Step 0 detection outcome so callers can decide whether the
    Hermes inference seam should be consulted.
    """

    fichas: list[StructureNode] = field(default_factory=list)
    usable_structure: bool = True
    diagnostic: str = ""


@dataclass
class _RawNode:
    """Internal tree node used while building the H1-H5 tree."""

    level: int
    title: str
    heading_text: str
    source_line: int
    body_lines: list[str] = field(default_factory=list)
    children: list["_RawNode"] = field(default_factory=list)
    canonical_segment: str = ""
    is_ficha: bool = False


def detect_heading_structure(
    text: str,
    *,
    structure_inference: Callable[[str], list[HeadingSpan]] | None = None,
) -> HeadingStructure:
    """Step 0 — detect a usable H1-H5 heading tree.

    Deterministic scan first (``#{1,5}`` headings). When no heading is found
    and ``structure_inference`` is provided (Phase 2 wires the Hermes
    structure-inference prompt here), the callback supplies the spans.
    Without a callback the structure is reported unusable so the splitter
    falls back to a single implicit ficha (legacy single-candidate path).
    """
    spans = _scan_headings(text)
    if spans:
        return HeadingStructure(spans=spans, usable=True, diagnostic="")
    if structure_inference is not None:
        try:
            inferred = list(structure_inference(text))
        except Exception as exc:  # noqa: BLE001 — inference is optional, fail-open
            logger.warning("Structure inference failed: %s", exc)
            inferred = []
        if inferred:
            return HeadingStructure(
                spans=inferred, usable=True,
                diagnostic="structure_inferred", inferred=True,
            )
    return HeadingStructure(
        spans=[], usable=False, diagnostic="no_heading_structure",
    )


def _scan_headings(text: str) -> list[HeadingSpan]:
    """Deterministic H1-H5 heading scan (line order preserved)."""
    spans: list[HeadingSpan] = []
    for idx, line in enumerate(text.split("\n")):
        m = _RE_HEADING_TREE.match(line.strip())
        if m:
            spans.append(HeadingSpan(
                level=len(m.group(1)),
                title=m.group(2).strip(),
                source_text=line.strip(),
                line_index=idx,
            ))
    return spans


def split_heading_tree(
    text: str,
    *,
    structure: HeadingStructure | None = None,
    structure_inference: Callable[[str], list[HeadingSpan]] | None = None,
) -> HeadingTree:
    """Step 1 — deterministic H1-H5 split into complete-ficha candidates.

    Rules (design, Step 1): every H1 is a valid root/index ficha — including
    an empty scaffold, which is review-visible and never dropped; a sibling
    with children becomes a ficha; childless prose folds verbatim into the
    parent ficha (its heading line included, so nothing is lost); a source
    with no usable headings yields one implicit ficha holding the whole text
    (legacy single-candidate path). Each ficha carries the parent-qualified
    canonical identity, source order, and reference-image diagnostics.

    ``structure`` short-circuits Step 0 (callers that already detected can
    pass the result); otherwise detection runs with the
    ``structure_inference`` fallback seam.
    """
    if structure is None:
        structure = detect_heading_structure(
            text, structure_inference=structure_inference)
    fichas = _split_into_fichas(text, structure.spans)
    return HeadingTree(
        fichas=fichas,
        usable_structure=structure.usable,
        diagnostic=structure.diagnostic,
    )


def _split_into_fichas(text: str, spans: list[HeadingSpan]) -> list[StructureNode]:
    """Build the ficha list from heading spans (pure, deterministic)."""
    if not spans:
        body = text.strip()
        implicit = StructureNode(
            level=0, title="", heading_text="", source_line=-1,
            body=body, is_ficha=True, is_implicit=True, source_order=0,
        )
        implicit.media_diagnostics = reference_image_diagnostics(
            body, implicit.canonical_id)
        return [implicit]

    roots, preamble = _build_raw_tree(text, spans)
    counts: dict[str, int] = {}
    for root in roots:
        segment = normalize_identity_segment(root.title)
        counts[segment] = counts.get(segment, 0) + 1
        root.canonical_segment = (
            segment if counts[segment] == 1 else f"{segment}#{counts[segment]}")
        # Every root is a scope: an H1 always, or the first heading of a
        # document that lacks H1s (no parent exists to fold into).
        root.is_ficha = True
        _assign_tree(root)
    if preamble:
        # Preamble lines precede the first heading in the source; splice the
        # heading line between preamble and body so source order is preserved
        # when ``_ficha_from`` opens the body with the heading.
        roots[0].body_lines = [
            *preamble, roots[0].heading_text, *roots[0].body_lines,
        ]
        roots[0].heading_text = ""  # consumed; ``_ficha_from`` must not re-add

    fichas: list[StructureNode] = []
    order: Iterator[int] = itertools.count()
    for root in roots:
        _ficha_from(root, [], order, fichas)
    return fichas


def _build_raw_tree(
    text: str, spans: list[HeadingSpan],
) -> tuple[list[_RawNode], list[str]]:
    """Build the raw H1-H5 tree; return ``(roots, preamble_lines)``.

    A heading attaches under the nearest ancestor with a strictly smaller
    level. Lines before the first heading are the preamble and fold into the
    first root ficha (preservation-first; the legacy flow dropped them).
    """
    spans_by_line = {span.line_index: span for span in spans}
    roots: list[_RawNode] = []
    stack: list[_RawNode] = []
    preamble: list[str] = []
    for idx, line in enumerate(text.split("\n")):
        span = spans_by_line.get(idx)
        if span is None:
            if stack:
                stack[-1].body_lines.append(line)
            else:
                preamble.append(line)
            continue
        node = _RawNode(
            level=span.level,
            title=clean_markdown_title(span.title) or "Sección",
            heading_text=span.source_text, source_line=idx,
        )
        while stack and stack[-1].level >= node.level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots, preamble


def _assign_tree(raw: _RawNode) -> None:
    """Assign canonical segments (+``#N`` ordinals) and ficha flags.

    Duplicate same-title siblings receive ``#2``, ``#3`` ordinals in source
    order (design identity decision); the first occurrence keeps the plain
    segment. A child is a ficha when it is an H1 or has children of its own;
    childless prose folds into the parent ficha.
    """
    counts: dict[str, int] = {}
    for child in raw.children:
        segment = normalize_identity_segment(child.title)
        counts[segment] = counts.get(segment, 0) + 1
        child.canonical_segment = (
            segment if counts[segment] == 1 else f"{segment}#{counts[segment]}")
        child.is_ficha = child.level == 1 or bool(child.children)
        _assign_tree(child)


def _ficha_from(
    raw: _RawNode,
    parent_segments: list[str],
    order: Iterator[int],
    fichas: list[StructureNode],
) -> StructureNode:
    """Emit the ficha node for ``raw`` (must already be flagged a ficha).

    The node is appended to ``fichas`` (pre-order = source order); childless
    descendants fold into this ficha's body verbatim (heading line included);
    ficha children recurse and are attached in source order.
    """
    segments = [*parent_segments, raw.canonical_segment]
    node = StructureNode(
        level=raw.level,
        title=raw.title,
        heading_text=raw.heading_text,
        source_line=raw.source_line,
        canonical_segment=raw.canonical_segment,
        canonical_id=canonical_identity_from_segments(segments),
        is_ficha=True,
        source_order=next(order),
    )
    fichas.append(node)
    body_lines = list(raw.body_lines)
    # The ficha's own heading line opens its body so the ficha is
    # self-descriptive when opened (the heading previously lived only in
    # metadata). Verbatim markdown — a ``|``-containing title stays a real
    # heading. ``_split_into_fichas`` already consumed the heading into
    # ``body_lines`` for the preamble case, so it is never duplicated.
    if raw.heading_text:
        body_lines.insert(0, raw.heading_text)
    for child in raw.children:
        if child.is_ficha:
            node.children.append(_ficha_from(
                child, segments, order, fichas))
        else:
            body_lines.append(child.heading_text)
            body_lines.extend(child.body_lines)
    # Body stays VERBATIM markdown: emphasis markers are the document's real
    # formatting (bold/italic/code from the original Word source) and the
    # viewer renders them. Only derived metadata (title/identity) is cleaned.
    node.body = "\n".join(body_lines).strip()
    node.media_diagnostics = reference_image_diagnostics(
        node.body, node.canonical_id)
    return node


def reference_image_diagnostics(
    content: str, target_ficha: str,
) -> list[MediaDiagnostic]:
    """Scan ``content`` for reference-style image spans (``![..][key]``).

    Reference spans are preserved verbatim in the diagnostic. A matching
    ``[key]: target`` definition line in the same ficha resolves the
    placement; otherwise the placement is marked unresolved — excluded from
    gallery registration, surfaced as a review warning, and never blocking
    the ficha or the job (design: reference-image diagnostics).
    """
    definitions: dict[str, str] = {}
    for line in content.split("\n"):
        m = _RE_REF_DEFINITION.match(line.strip())
        if m:
            definitions.setdefault(m.group(1), m.group(2))
    diagnostics: list[MediaDiagnostic] = []
    for m in _RE_REF_IMAGE.finditer(content):
        alt, key = m.group(1).strip(), m.group(2).strip()
        target = definitions.get(key)
        if target is not None:
            diagnostics.append(MediaDiagnostic(
                reference=m.group(0), image_key=key, alt_text=alt,
                status="resolved", target_path=target,
                target_ficha=target_ficha,
                message="reference image placement resolved",
            ))
        else:
            diagnostics.append(MediaDiagnostic(
                reference=m.group(0), image_key=key, alt_text=alt,
                status="unresolved", target_ficha=target_ficha,
                message=(
                    "reference image placement unresolved: "
                    f"no definition for [{key}]"
                ),
            ))
    return diagnostics
