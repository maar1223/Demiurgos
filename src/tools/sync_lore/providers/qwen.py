"""
providers/qwen.py — QwenProvider implementation.

Replicates the LLM call pattern from sync-ideas.py, adapted for async
via httpx.AsyncClient with 3 retries and exponential backoff.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from typing import TYPE_CHECKING

import httpx

from .base import ChunkResult, ImageAnalysis, ProviderAdapter

if TYPE_CHECKING:
    from ..schemas import Chunk, ProviderConfig


# ---------------------------------------------------------------------------
# MIME detection (magic bytes)
# ---------------------------------------------------------------------------

_SIGNATURES: dict[bytes, str] = {
    b"\xff\xd8\xff": ".jpg",
    b"\x89PNG\r\n\x1a\n": ".png",
    b"GIF87a": ".gif",
    b"GIF89a": ".gif",
    b"RIFF": ".webp",
    b"BM": ".bmp",
}

_MIME_MAP: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _detect_mime(image_bytes: bytes) -> str:
    """Detect MIME type from magic bytes. Falls back to image/jpeg."""
    for sig, ext in _SIGNATURES.items():
        if image_bytes[: len(sig)] == sig:
            return _MIME_MAP.get(ext, "image/jpeg")
    return "image/jpeg"


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_TEXT_SYSTEM_PROMPT = (
    "Extrae entidades narrativas del siguiente texto de lore. "
    "Responde en español. Devuelve JSON EXACTO:\n"
    '{"entities": [{"name": "...", "type": "personaje|lugar|concepto|evento|objeto|organizacion|especie|criatura", '
    '"description": "...", "relations": [{"target": "...", "type": "...", "strength": 1.0}], '
    '"quotes": ["..."]}], '
    '"terms": [{"term": "...", "definition": "...", "context_snippet": "..."}], '
    '"contradictions": [{"entity": "...", "claim": "...", "reason": "..."}]}'
)

_IMAGE_SYSTEM_PROMPT = (
    "Analiza esta imagen. Describe colores, composicion, texturas, estilo, "
    "y atmosfera. Luego, evalua si esta imagen coincide con el texto adjunto. "
    "Responde en espanol, estrictamente en este formato JSON:\n\n"
    '{\n'
    '  "descripcion": "...",\n'
    '  "veredicto": "confirma|contradice|no_aplica",\n'
    '  "analisis": "...",\n'
    '  "tags": ["..."]\n'
    '}'
)


# ---------------------------------------------------------------------------
# QwenProvider
# ---------------------------------------------------------------------------

class QwenProvider(ProviderAdapter):
    """
    Qwen LLM provider via OpenCode Go OpenAI-compatible endpoint.

    Uses httpx.AsyncClient for async HTTP. 3 retries with exponential
    backoff on connection/timeout errors.
    """

    def __init__(self, config: "ProviderConfig") -> None:
        self._config = config
        self._api_key = (
            os.environ.get(config.api_key_env)
            or os.environ.get("OPENCODE_API_KEY")
            or ""
        )

    @property
    def config(self) -> "ProviderConfig":
        return self._config

    # ------------------------------------------------------------------
    # Text analysis
    # ------------------------------------------------------------------

    async def analyze_text(self, chunk: "Chunk") -> ChunkResult:
        """
        Extract entities, terms, and contradictions from a chunk.

        Returns empty ChunkResult if API key is not set or call fails.
        """
        if not self._api_key:
            print(
                f"  \u26a0 {self._config.provider} API key not set "
                f"({self._config.api_key_env} or OPENCODE_API_KEY)",
                file=sys.stderr,
            )
            return ChunkResult()

        return await self._call_json(
            chunk.full_context(),
            _TEXT_SYSTEM_PROMPT,
            ChunkResult,
        )

    # ------------------------------------------------------------------
    # Image analysis
    # ------------------------------------------------------------------

    async def analyze_image(
        self, image: bytes, context: str
    ) -> ImageAnalysis | None:
        """
        Analyze an image with vision LLM.

        Returns None if API key is not set or call fails.
        """
        if not self._api_key:
            print(
                f"  \u26a0 {self._config.provider} API key not set "
                f"({self._config.api_key_env} or OPENCODE_API_KEY)",
                file=sys.stderr,
            )
            return None

        b64 = base64.b64encode(image).decode("utf-8")
        mime = _detect_mime(image)
        ctx = context or "[Image — standalone, no surrounding text]"

        payload: dict = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": _IMAGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": f"data:{mime};base64,{b64}",
                        },
                        {"type": "text", "text": ctx},
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
        }

        result = await self._post(payload)
        if result is None:
            return None

        return ImageAnalysis(
            descripcion=result.get("descripcion", ""),
            veredicto=result.get("veredicto", "no_aplica"),
            analisis=result.get("analisis", ""),
            tags=result.get("tags", []),
        )

    # ------------------------------------------------------------------
    # Core HTTP + retry logic
    # ------------------------------------------------------------------

    async def _call_json(
        self,
        user_text: str,
        system_prompt: str,
        fallback_cls: type,
    ) -> "ChunkResult | ImageAnalysis":
        """Call LLM with JSON response_format, return typed result or empty."""
        payload: dict = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "response_format": {"type": "json_object"},
        }
        result = await self._post(payload)
        if result is None:
            return fallback_cls()
        try:
            return fallback_cls(**result)
        except TypeError:
            return fallback_cls()

    async def _post(self, payload: dict) -> dict | None:
        """
        Core HTTP async call with 3 retries and exponential backoff.

        Uses httpx.AsyncClient (async-native, unlike requests).

        Returns:
            Parsed JSON dict from the LLM response, or None on failure.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._config.timeout) as client:
            for attempt in range(3):
                try:
                    resp = await client.post(
                        f"{self._config.endpoint}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    raw = data["choices"][0]["message"]["content"]
                    return json.loads(raw)

                except (httpx.ConnectError, httpx.TimeoutException):
                    if attempt < 2:
                        await asyncio.sleep(2**attempt)
                    continue

                except (
                    httpx.HTTPStatusError,
                    json.JSONDecodeError,
                    KeyError,
                    TypeError,
                ) as exc:
                    print(
                        f"  \u26a0 LLM call failed (attempt {attempt+1}/3): {exc}",
                        file=sys.stderr,
                    )
                    if attempt < 2:
                        continue
                    return None

        return None
