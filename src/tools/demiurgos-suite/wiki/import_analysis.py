"""World importer — in-process analysis facade (Phase 2).

Read-only analysis that preserves source order and context. Pure logic: given
a file's text it splits markdown into heading-delimited chunks, captures the
hierarchical heading path, the sequence, nearby text/anchor context, and the
image references found near each chunk. It never writes canon and never
guesses placement — every image association is surfaced for review.

This is the server-owned replacement for the legacy ``sync_lore`` extraction
path during import: it keeps the same heading/source-order semantics while
returning an ``AnalysisReport`` the import service can review and merge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from import_models import ImagePlacement

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

    def content_preview(self) -> str:
        """Flatten ordered chunks into a candidate body (source order kept)."""
        return "\n\n".join(c.content for c in self.chunks)


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
) -> AnalysisReport:
    """Analyze all intake files in source order, preserving every anchor.

    ``files``: list of ``{"relative": str, "sha256": str, "size": int}`` in
    source order. ``read_file`` returns text for a relative path. The service
    maps each analyzed file to a candidate; analysis stays pure.
    """
    report = AnalysisReport()
    for entry in files:
        relative = entry["relative"]
        digest = entry.get("sha256") or ""
        size = entry.get("size") or 0
        text = read_file(relative) or ""
        analyzed = analyze_markdown(text, relative, digest, size)
        report.files.append(analyzed)
    return report
