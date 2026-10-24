"""
providers/llm.py — General LLM provider (OpenAI-compatible).

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

#: Chat attachments: a standalone, question-agnostic description that an
#: assistant can later answer from. Unlike ``_IMAGE_SYSTEM_PROMPT`` it never
#: compares against surrounding lore text and always transcribes visible text.
_CHAT_IMAGE_SYSTEM_PROMPT = (
    "Describe esta imagen en detalle para que un asistente de worldbuilding "
    "pueda responder preguntas sobre ella mas tarde. Incluye que se ve, "
    "personas, objetos, lugares, colores, composicion, estilo, atmosfera y "
    "transcribe TODO el texto visible. No evalues si coincide con un texto: "
    "describe la imagen. Responde en espanol, estrictamente en este formato "
    'JSON: {"descripcion": "..."}'
)


# ---------------------------------------------------------------------------
# LlmProvider
# ---------------------------------------------------------------------------

class LlmProvider(ProviderAdapter):
    """
    LlmProvider — HTTP Chat Completion API (any OpenAI, Google, Groq, etc.)

    Uses httpx.AsyncClient for async HTTP. 3 retries with exponential
    backoff on connection/timeout errors.
    """

    def __init__(
        self,
        config: "ProviderConfig",
        *,
        api_key: str | None = None,
        vision_api_key: str | None = None,
    ) -> None:
        self._text_config = config
        self._vision_config = config.vision

        # Text API key — explicit key first, then the environment fallback chain.
        self._text_api_key = (
            api_key
            if api_key is not None
            else (
                os.environ.get(config.api_key_env)
                or os.environ.get("OPENCODE_API_KEY")
                or os.environ.get("OPENCODE_GO_API_KEY")
                or ""
            )
        )

        # Vision API key — explicit key, then the vision env var, else the text key.
        if self._vision_config is not None:
            if vision_api_key is not None:
                self._vision_api_key = vision_api_key
            else:
                self._vision_api_key = (
                    os.environ.get(self._vision_config.api_key_env)
                    or self._text_api_key  # fallback to text key
                    or ""
                )
        else:
            self._vision_api_key = ""

    @property
    def config(self) -> "ProviderConfig":
        """The provider adapter contract (``ProviderAdapter.config``)."""
        return self._text_config

    def _cfg(self, text_or_vision: str = "text") -> tuple[Any, str, str]:
        """Return (config, api_key, label) for the given mode."""
        if text_or_vision == "vision" and self._vision_config is not None:
            return self._vision_config, self._vision_api_key, "vision"
        return self._text_config, self._text_api_key, "text"

    # ------------------------------------------------------------------
    # Text analysis
    # ------------------------------------------------------------------

    async def analyze_text(self, chunk: "Chunk") -> ChunkResult:
        """
        Extract entities, terms, and contradictions from a chunk.

        Returns empty ChunkResult if API key is not set or call fails.
        """
        cfg, key, label = self._cfg("text")
        if not key:
            print(
                f"  \u26a0 {cfg.provider} ({label}) API key not set "
                f"({cfg.api_key_env}, OPENCODE_API_KEY, or OPENCODE_GO_API_KEY)",
                file=sys.stderr,
            )
            return ChunkResult()

        return await self._call_json(
            chunk.full_context(),
            _TEXT_SYSTEM_PROMPT,
            ChunkResult,
            cfg,
            key,
        )

    # ------------------------------------------------------------------
    # Image analysis
    # ------------------------------------------------------------------

    async def analyze_image(
        self, image: bytes, context: str
    ) -> ImageAnalysis | None:
        """
        Analyze an image with vision LLM.

        Returns None if vision config is not set or API key is missing.
        """
        cfg, key, label = self._cfg("vision")
        if self._vision_config is None:
            print(
                "  \u26a0 No vision provider configured — skipping image analysis. "
                "Add a 'vision' section to your sync-lore config.",
                file=sys.stderr,
            )
            return None
        if not key:
            print(
                f"  \u26a0 {cfg.provider} ({label}) API key not set "
                f"({cfg.api_key_env}, OPENCODE_API_KEY, or OPENCODE_GO_API_KEY)",
                file=sys.stderr,
            )
            return None

        b64 = base64.b64encode(image).decode("utf-8")
        mime = _detect_mime(image)
        ctx = context or "[Image — standalone, no surrounding text]"

        payload: dict = {
            "model": cfg.model,
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

        result = await self._post(payload, cfg, key)
        if result is None:
            return None

        return ImageAnalysis(
            descripcion=result.get("descripcion", ""),
            veredicto=result.get("veredicto", "no_aplica"),
            analisis=result.get("analisis", ""),
            tags=result.get("tags", []),
        )

    async def describe_image(
        self, image: bytes, context: str = ""
    ) -> str | None:
        """Describe one standalone image for the Assistant chat (S12).

        Returns the ``descripcion`` string, or ``None`` when vision is not
        configured, the key is missing, or the provider answers without a
        usable description. Failures never raise: the caller decides how to
        degrade.
        """
        cfg, key, label = self._cfg("vision")
        if self._vision_config is None or not key:
            return None

        b64 = base64.b64encode(image).decode("utf-8")
        mime = _detect_mime(image)
        payload: dict = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": _CHAT_IMAGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": f"data:{mime};base64,{b64}",
                        },
                        {
                            "type": "text",
                            "text": context or "[Imagen adjunta a la conversación]",
                        },
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
        }
        result = await self._post(payload, cfg, key)
        if not isinstance(result, dict):
            return None
        description = result.get("descripcion")
        if not isinstance(description, str) or not description.strip():
            return None
        return description.strip()

    # ------------------------------------------------------------------
    # Core HTTP + retry logic
    # ------------------------------------------------------------------

    async def _call_json(
        self,
        user_text: str,
        system_prompt: str,
        fallback_cls: type,
        cfg: Any,
        api_key: str,
    ) -> "ChunkResult | ImageAnalysis":
        """Call LLM with JSON response_format, return typed result or empty."""
        payload: dict = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "response_format": {"type": "json_object"},
        }
        result = await self._post(payload, cfg, api_key)
        if result is None:
            return fallback_cls()
        try:
            return fallback_cls(**result)
        except TypeError:
            return fallback_cls()

    async def _post(self, payload: dict, cfg: Any, api_key: str) -> dict | None:
        """
        Core HTTP async call with 3 retries and exponential backoff.

        Uses httpx.AsyncClient (async-native, unlike requests).

        Returns:
            Parsed JSON dict from the LLM response, or None on failure.
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            for attempt in range(3):
                try:
                    resp = await client.post(
                        f"{cfg.endpoint}/chat/completions",
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
