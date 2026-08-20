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
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from import_intake import UnsafePathError, reject_unsafe_path
from import_models import (
    ImagePlacement,
    Provenance,
    TargetResolution,
)

if TYPE_CHECKING:
    from sync_lore.schemas import ImageEntry

logger = logging.getLogger(__name__)

_RE_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
_RE_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_RE_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


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
    """

    image: ImageEntry
    spool_relative_path: str


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
            text, images, diagnostics = _convert_source(source)
            if text is None:
                text = ""
            analyzed = analyze_markdown(
                text, normalized_identity_path(relative), digest, size)
            analyzed.media = store_media_in_spool(images, relative, media_root)
            analyzed.diagnostics = diagnostics
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
    text, images, _ = _convert_source(file_path)
    return text, images


def _convert_source(file_path: Path) -> tuple[str | None, list[ImageEntry], list[str]]:
    """Convert + extract with granular diagnostics (internal seam).

    Returns ``(markdown, images, diagnostics)``. Conversion and media are
    optional and fail-open: any failure yields an empty result plus a
    diagnostic token, never an exception or process exit.
    """
    diagnostics: list[str] = []
    try:
        from sync_lore.utils.converter import convert_to_markdown
        result = convert_to_markdown(file_path)
        if result is None:
            diagnostics.append("conversion_failed")
            logger.warning(
                "Conversion returned None for %s (markitdown failed)",
                file_path)
            return None, [], diagnostics
        try:
            images = extract_images_from_file(file_path)
        except Exception as exc:  # noqa: BLE001 — media is optional, never fatal
            diagnostics.append("media_extraction_failed")
            logger.warning(
                "Image extraction failed for %s: %s", file_path, exc)
            images = []
        return result, images, diagnostics
    except SystemExit:
        logger.warning("Conversion unavailable: markitdown not installed")
        diagnostics.append("conversion_unavailable")
        return None, [], diagnostics
    except Exception as exc:  # noqa: BLE001 — fail-open never breaks analysis
        logger.warning("Conversion failed for %s: %s", file_path, exc)
        diagnostics.append("conversion_failed")
        return None, [], diagnostics


def extract_images_from_file(file_path: Path) -> list[ImageEntry]:
    """Extract images from ``.md``/``.docx``/``.pdf`` reusing sync_lore.

    Markdown sources yield images referenced on disk; ``.docx``/``.pdf``
    yield embedded blobs. Any failure is logged and returns no images so
    analysis never blocks on media.
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
            from sync_lore.image_indexer import extract_images_from_docx
            return extract_images_from_docx(file_path)
        elif suffix == ".pdf":
            from sync_lore.image_indexer import extract_images_from_pdf
            return extract_images_from_pdf(file_path)
    except Exception as exc:  # noqa: BLE001 — media is optional, never fatal
        logger.warning("Image extraction failed for %s: %s", file_path, exc)
    return []


def store_media_in_spool(images: list[ImageEntry], source_rel: str,
                         spool_dir: Path) -> list[ExtractedMedia]:
    """Persist extracted image bytes under the job spool with metadata.

    Bytes land in ``<spool_dir>/media/<source-stem>/<filename>`` so review
    and execution can feed the original bytes to ``plan_placements`` without
    re-opening the source archive. Collisions are avoided by suffixing a
    counter when the target already exists.
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

# Canonical OKF top-level sections (lowercase, case-sensitive).
_CANONICAL_SECTIONS = frozenset({"lore", "personajes", "sagas", "referencias"})

# Legacy uppercase sections normalized to their canonical lowercase form.
_LEGACY_SECTIONS = {
    "lore": "lore",
    "personajes": "personajes",
}


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
        if section in _CANONICAL_SECTIONS:
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

    # No subfolders. The top-level section itself must be a known canonical
    # OKF section; anything else is reported for review (never guessed).
    if section not in _CANONICAL_SECTIONS:
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
