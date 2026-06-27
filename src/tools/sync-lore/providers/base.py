"""
providers/base.py — ProviderAdapter abstract base class.

Defines the contract for all LLM providers. Any concrete provider
only needs to implement analyze_text() and analyze_image().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..schemas import ChunkResult, ImageAnalysis

if TYPE_CHECKING:
    from ..schemas import Chunk, ProviderConfig


class ProviderAdapter(ABC):
    """
    Abstract base for LLM provider adapters.

    Subclasses must implement:
    - analyze_text(chunk) -> ChunkResult   (async)
    - analyze_image(image, context) -> ImageAnalysis | None  (async)

    The config property exposes the provider's settings.
    """

    @property
    @abstractmethod
    def config(self) -> "ProviderConfig":
        """Return the provider's configuration."""
        ...

    @abstractmethod
    async def analyze_text(self, chunk: "Chunk") -> ChunkResult:
        """
        Extract entities, terms, and contradictions from a text chunk.

        Returns ChunkResult with empty lists if unable to process.
        ASYNC — executed in the worker pool.
        """
        ...

    @abstractmethod
    async def analyze_image(
        self, image: bytes, context: str
    ) -> ImageAnalysis | None:
        """
        Analyze an image with surrounding text context.

        Returns None on failure.
        ASYNC — executed in the worker pool.
        """
        ...
