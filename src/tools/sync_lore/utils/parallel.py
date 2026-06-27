"""
utils/parallel.py — Async parallel processing with semaphore-controlled pools.

Provides concurrent chunk and image processing with configurable
worker limits. Each worker is error-isolated: one failure does not
interrupt the batch.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..providers.base import ChunkResult, ImageAnalysis, ProviderAdapter
    from ..schemas import Chunk, ImageEntry


async def process_chunks_async(
    chunks: list["Chunk"],
    provider: "ProviderAdapter",
    max_workers: int = 5,
) -> list[tuple["Chunk", "ChunkResult"]]:
    """
    Process text chunks in parallel with a bounded worker pool.

    Each chunk is analyzed independently via provider.analyze_text().
    Failed chunks return empty ChunkResult — never interrupt the batch.

    Args:
        chunks: List of Chunk objects to process.
        provider: ProviderAdapter instance for LLM calls.
        max_workers: Maximum concurrent LLM calls (semaphore limit).

    Returns:
        List of (Chunk, ChunkResult) tuples, one per input chunk.
    """
    sem = asyncio.Semaphore(max_workers)

    async def process_one(chunk: "Chunk") -> tuple["Chunk", "ChunkResult"]:
        async with sem:
            try:
                result = await provider.analyze_text(chunk)
                return (chunk, result)
            except Exception as exc:
                print(
                    f"  \u26a0 Chunk {chunk.id[:8]}... failed: {exc}",
                    file=sys.stderr,
                )
                # Return empty result — don't interrupt batch
                from ..providers.base import ChunkResult
                return (chunk, ChunkResult())

    tasks = [process_one(chunk) for chunk in chunks]
    return await asyncio.gather(*tasks)


async def process_images_async(
    images: list["ImageEntry"],
    provider: "ProviderAdapter",
    max_workers: int = 5,
) -> list["ImageEntry"]:
    """
    Process image entries in parallel with a bounded worker pool.

    Each image is analyzed via provider.analyze_image().
    Failed images get analysis=None — never interrupt the batch.

    Args:
        images: List of ImageEntry objects with image_bytes and context_text.
        provider: ProviderAdapter instance for vision calls.
        max_workers: Maximum concurrent LLM calls (semaphore limit).

    Returns:
        List of ImageEntry objects with analysis populated (or None on failure).
    """
    sem = asyncio.Semaphore(max_workers)

    async def process_one(img: "ImageEntry") -> "ImageEntry":
        async with sem:
            try:
                analysis = await provider.analyze_image(
                    img.image_bytes, img.context_text
                )
                img.analysis = analysis
            except Exception as exc:
                print(
                    f"  \u26a0 Image {img.id[:8]}... failed: {exc}",
                    file=sys.stderr,
                )
                img.analysis = None
            return img

    tasks = [process_one(img) for img in images]
    return await asyncio.gather(*tasks)
