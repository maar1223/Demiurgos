"""
utils/chunker.py — Heading-based Markdown chunking.

Splits lore documents into manageable chunks for LLM processing.
Each chunk is bounded by heading boundaries (## / ###) and preserves
hierarchical context (heading_path).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from ..schemas import Chunk, ImageRef


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """
    Estimate token count. Approximation for Spanish: ~4 chars/token.

    Returns at least 1, even for empty strings.
    """
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Heading-based chunking
# ---------------------------------------------------------------------------

def chunk_markdown(
    text: str,
    source_file: str,
    min_tokens: int = 500,
    max_tokens: int = 4000,
) -> list[Chunk]:
    """
    Split markdown text into heading-delimited chunks.

    Rules:
    - Each ## heading starts a new chunk with heading_path inheritance
    - ### sub-headings inherit their parent's heading
    - Files with no headings → single chunk with heading_path = filename
    - Chunks exceeding max_tokens are split by paragraph via split_oversized()

    Args:
        text: Raw markdown content.
        source_file: Relative path of the source file.
        min_tokens: Minimum tokens for a sub-chunk after splitting.
        max_tokens: Maximum tokens before a chunk is split.

    Returns:
        List of Chunk objects.
    """
    lines = text.split("\n")

    # Detect headings and their positions
    heading_positions: list[tuple[int, str, int]] = []  # (line_idx, text, level)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            level = 3 if stripped.startswith("### ") else 2
            heading_positions.append((i, stripped, level))

    # No headings → single chunk
    if not heading_positions:
        content = text.strip()
        if not content:
            return []
        chunk = _make_chunk(
            content=content,
            heading_path=source_file,
            source_file=source_file,
            images=[],
        )
        oversized = _check_oversized([chunk], max_tokens, min_tokens, source_file)
        return oversized

    # Build chunks from heading boundaries
    chunks: list[Chunk] = []
    heading_stack: list[str] = []  # hierarchical path

    # Pre-chunk: content before first heading
    if heading_positions[0][0] > 0:
        pre_content = "\n".join(lines[: heading_positions[0][0]]).strip()
        if pre_content:
            chunks.append(
                _make_chunk(
                    content=pre_content,
                    heading_path=source_file,
                    source_file=source_file,
                    images=[],
                )
            )

    for idx, (line_idx, heading_text, level) in enumerate(heading_positions):
        # Determine heading path
        heading_clean = heading_text.lstrip("#").strip()

        if level == 2:
            heading_stack = [heading_clean]
        elif level == 3:
            if len(heading_stack) >= 1:
                heading_stack = [heading_stack[0], heading_clean]
            else:
                heading_stack = [heading_clean]

        heading_path = " > ".join(heading_stack)
        heading_path_full = f"{source_file}##{heading_path}"

        # Determine chunk boundaries
        start = line_idx
        if idx + 1 < len(heading_positions):
            end = heading_positions[idx + 1][0]
        else:
            end = len(lines)

        # Extract content (heading line + body)
        chunk_lines = lines[start:end]
        content = "\n".join(chunk_lines).strip()

        if not content:
            continue

        # Extract image references from this chunk's content
        images = _extract_image_refs(content)

        chunks.append(
            _make_chunk(
                content=content,
                heading_path=heading_path_full,
                source_file=source_file,
                images=images,
            )
        )

    # Apply oversize splitting
    return _check_oversized(chunks, max_tokens, min_tokens, source_file)


def split_oversized(
    chunk: Chunk,
    max_tokens: int = 4000,
    min_tokens: int = 500,
) -> list[Chunk]:
    """
    Split a chunk that exceeds max_tokens by paragraph boundaries.

    Each sub-chunk must have at least min_tokens (unless it's the
    only remaining content). Paragraph boundaries are \n\n.

    Args:
        chunk: The oversized chunk.
        max_tokens: Maximum tokens allowed per sub-chunk.
        min_tokens: Minimum tokens for a sub-chunk.

    Returns:
        List of Chunk objects (may be the original if not oversized).
    """
    if chunk.token_count <= max_tokens:
        return [chunk]

    paragraphs = chunk.content.split("\n\n")
    sub_chunks: list[Chunk] = []
    current_lines: list[str] = []
    current_tokens = 0
    part = 1

    for para in paragraphs:
        para_tokens = estimate_tokens(para)

        if current_lines and current_tokens + para_tokens > max_tokens:
            # Flush current sub-chunk
            content = "\n\n".join(current_lines).strip()
            if content:
                sub_chunks.append(
                    _make_chunk(
                        content=content,
                        heading_path=f"{chunk.heading_path} (part {part})",
                        source_file=chunk.source_file,
                        images=[],
                    )
                )
                part += 1
            current_lines = []
            current_tokens = 0

        current_lines.append(para)
        current_tokens += para_tokens

    # Flush remaining
    if current_lines:
        content = "\n\n".join(current_lines).strip()
        if content:
            sub_chunks.append(
                _make_chunk(
                    content=content,
                    heading_path=(
                        f"{chunk.heading_path} (part {part})"
                        if part > 1
                        else chunk.heading_path
                    ),
                    source_file=chunk.source_file,
                    images=[],
                )
            )

    # Ensure minimum token count (merge tiny tail into previous if needed)
    if len(sub_chunks) > 1:
        last = sub_chunks[-1]
        if last.token_count < min_tokens and len(sub_chunks) > 1:
            prev = sub_chunks[-2]
            merged = _make_chunk(
                content=f"{prev.content}\n\n{last.content}",
                heading_path=prev.heading_path,
                source_file=chunk.source_file,
                images=[],
            )
            sub_chunks = sub_chunks[:-2] + [merged]

    return sub_chunks or [chunk]


# ---------------------------------------------------------------------------
# Template / skeleton detection
# ---------------------------------------------------------------------------

def is_template(filename: str) -> bool:
    """Check if a filename indicates a template (starts with _)."""
    return Path(filename).name.startswith("_")


def is_skeleton(text: str, min_lines: int = 20) -> bool:
    """
    Check if a file is a skeleton (too few significant lines).

    Significant lines: non-empty, non-heading-only.
    """
    lines = [l.strip() for l in text.split("\n")]
    significant = [l for l in lines if l and not l.startswith("#")]
    return len(significant) < min_lines


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_chunk(
    content: str,
    heading_path: str,
    source_file: str,
    images: list[ImageRef],
) -> Chunk:
    """Create a Chunk with computed token_count."""
    return Chunk(
        id=str(uuid.uuid4()),
        source_file=source_file,
        heading_path=heading_path,
        content=content,
        token_count=estimate_tokens(content),
        images=images,
    )


def _extract_image_refs(text: str) -> list[ImageRef]:
    """
    Extract markdown image references: ![alt](path) and ![alt][ref].

    Returns list of ImageRef with source_type="md_ref".
    """
    import re

    refs: list[ImageRef] = []
    # Inline: ![alt](path)
    for m in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", text):
        refs.append(
            ImageRef(
                ref=f"![{m.group(1)}]({m.group(2)})",
                alt_text=m.group(1),
                source_type="md_ref",
            )
        )
    # Reference-style: ![alt][ref]
    for m in re.finditer(r"!\[([^\]]*)\]\[([^\]]*)\]", text):
        refs.append(
            ImageRef(
                ref=f"![{m.group(1)}][{m.group(2)}]",
                alt_text=m.group(1),
                source_type="md_ref",
            )
        )
    return refs


def _check_oversized(
    chunks: list[Chunk],
    max_tokens: int,
    min_tokens: int,
    source_file: str,
) -> list[Chunk]:
    """Apply split_oversized to any chunks exceeding max_tokens."""
    result: list[Chunk] = []
    for chunk in chunks:
        if chunk.token_count > max_tokens:
            result.extend(split_oversized(chunk, max_tokens, min_tokens))
        else:
            result.append(chunk)
    return result
