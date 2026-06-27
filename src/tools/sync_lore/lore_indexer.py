"""
lore_indexer.py — Text pipeline orchestrator.

Orchestrates the text extraction pipeline:
  scan → convert → chunk → async LLM process → collect results

When mode is "images" or "both", also extracts images from files
and associates them with their parent chunks for vision analysis.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .providers.base import ChunkResult, ProviderAdapter
    from .schemas import Chunk, ImageEntry


# ---------------------------------------------------------------------------
# File scanner
# ---------------------------------------------------------------------------

_SUPPORTED_EXTENSIONS = frozenset({".md", ".docx", ".pdf"})


def _scan_files(input_path: Path) -> list[Path]:
    """
    Scan input_path for supported files.

    - If input_path is a file: return [file] if supported.
    - If input_path is a directory: recursively find all supported files.

    Excludes template files (_* prefix) and non-markdown files if
    markitdown is not available for .docx/.pdf.

    Returns:
        List of absolute Path objects.
    """
    from .utils.chunker import is_template

    if input_path.is_file():
        if input_path.suffix.lower() in _SUPPORTED_EXTENSIONS:
            return [input_path.resolve()]
        return []

    # Directory scan
    files: list[Path] = []
    for ext in _SUPPORTED_EXTENSIONS:
        for fpath in input_path.rglob(f"*{ext}"):
            if is_template(fpath.name):
                print(f"  \u23ed Omitiendo plantilla: {fpath.name}", file=sys.stderr)
                continue
            files.append(fpath.resolve())

    # Sort for deterministic processing
    files.sort()
    return files


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------

def process_lore(
    input_path: Path,
    provider: "ProviderAdapter",
    mode: str = "text",
    workers: int = 5,
) -> tuple[list[tuple["Chunk", "ChunkResult"]], list["ImageEntry"], int, int, int]:
    """
    Orchestrate the complete extraction pipeline (text + images).

    Phases:
    1. SCAN: find all supported files
    2. CONVERT: .docx/.pdf → markdown
    3. CHUNK: split into heading-delimited chunks
    4. EXTRACT IMAGES: from .md refs, .docx blobs, .pdf pages
    5. PROCESS: async LLM calls for text + images with worker pool
    6. COLLECT: return all results for index building

    Args:
        input_path: File or directory to process.
        provider: ProviderAdapter instance.
        mode: "text", "images", or "both".
        workers: Max concurrent LLM calls.

    Returns:
        (chunk_results, image_entries, files_processed, files_omitted, chunks_failed)
    """
    from .utils.chunker import chunk_markdown, estimate_tokens, is_skeleton
    from .utils.converter import convert_to_markdown
    from .utils.parallel import process_chunks_async, process_images_async
    from .image_indexer import (
        _extract_images_from_docx_cached,
        _extract_images_from_pdf_cached,
        extract_images_from_docx,
        extract_images_from_md,
        extract_images_from_pdf,
    )

    # === Phase 1: Scan ===
    files = _scan_files(input_path)
    if not files:
        print("  \u2139 No supported files found.", file=sys.stderr)
        return [], [], 0, 0, 0

    print(f"  \U0001f4c4 Found {len(files)} file(s)", file=sys.stderr)

    # === Phase 2 & 3: Convert + Chunk (synchronous) ===
    all_chunks: list["Chunk"] = []
    all_images: list["ImageEntry"] = []
    files_omitted = 0
    files_processed = 0

    do_images = mode in ("images", "both")
    do_text = mode in ("text", "both")

    for fpath in files:
        # Convert to markdown
        md_text = convert_to_markdown(fpath)
        if md_text is None:
            files_omitted += 1
            continue

        # Skip skeletons
        if is_skeleton(md_text):
            print(
                f"  \u26a0 Skipping skeleton file: {fpath.name}",
                file=sys.stderr,
            )
            files_omitted += 1
            continue

        rel_path = str(fpath.relative_to(Path.cwd())) if fpath.is_relative_to(Path.cwd()) else fpath.name

        # Chunk the markdown
        chunks = chunk_markdown(md_text, rel_path)

        # Extract images if mode requires it
        if do_images:
            suffix = fpath.suffix.lower()
            md_dir = fpath.parent
            if suffix == ".md":
                # Extract images from each chunk's content
                for chunk in chunks:
                    imgs = extract_images_from_md(
                        chunk.content, md_dir, chunk.heading_path
                    )
                    # Fill context_text from chunk content
                    for img in imgs:
                        img.context_text = chunk.content
                        img.source_file = rel_path
                    all_images.extend(imgs)
            elif suffix == ".docx":
                cached_imgs = _extract_images_from_docx_cached(fpath)
                for chunk in chunks:
                    for img in cached_imgs:
                        all_images.append(
                            replace(img, context_text=chunk.content, chunk_ref=chunk.heading_path)
                        )
            elif suffix == ".pdf":
                cached_imgs = _extract_images_from_pdf_cached(fpath)
                for chunk in chunks:
                    for img in cached_imgs:
                        all_images.append(
                            replace(img, chunk_ref=chunk.heading_path)
                        )

        all_chunks.extend(chunks)
        files_processed += 1

    # === Phase 4: Async LLM processing ===
    chunks_failed = 0

    # Text processing
    chunk_results: list[tuple["Chunk", "ChunkResult"]] = []
    if do_text and all_chunks:
        total_tokens = sum(c.token_count for c in all_chunks)
        print(
            f"  \u2702 Chunked into {len(all_chunks)} chunk(s) "
            f"({total_tokens} tokens est.)",
            file=sys.stderr,
        )
        chunk_results = asyncio.run(
            process_chunks_async(all_chunks, provider, workers)
        )
        chunks_failed = sum(
            1 for _, cr in chunk_results
            if not cr.entities and not cr.terms and cr.raw_response is None
        )

    # Image processing
    if do_images and all_images:
        print(
            f"  \U0001f5bc Found {len(all_images)} image(s)",
            file=sys.stderr,
        )
        all_images = asyncio.run(
            process_images_async(all_images, provider, workers)
        )

    return chunk_results, all_images, files_processed, files_omitted, chunks_failed
