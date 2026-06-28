"""
Provider package for sync-lore.

Exports load_provider() factory and ProviderAdapter ABC.
"""

from .base import ProviderAdapter
from ..schemas import ChunkResult, ImageAnalysis, ProviderConfig


def load_provider(config: ProviderConfig) -> ProviderAdapter:
    """
    Factory: instantiate the correct ProviderAdapter for the given config.

    Args:
        config: ProviderConfig with provider name and settings.

    Returns:
        A concrete ProviderAdapter instance.

    Raises:
        ValueError: if provider name is unknown.
    """
    # LlmProvider handles any HTTP Chat Completion API endpoint.
    # Works with: OpenCode Go, OpenAI, Google, Groq, Together,
    # DeepSeek, xAI, Ollama, etc.
    from .llm import LlmProvider
    return LlmProvider(config)


__all__ = ["ProviderAdapter", "load_provider", "ChunkResult", "ImageAnalysis"]
