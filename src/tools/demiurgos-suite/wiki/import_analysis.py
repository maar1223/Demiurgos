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

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from import_intake import UnsafePathError, reject_unsafe_path
from import_models import (
    ImagePlacement,
    Provenance,
    TargetResolution,
)

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
