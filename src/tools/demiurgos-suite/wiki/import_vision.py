# -*- coding: utf-8 -*-
"""Vision analysis for imported images — thumbnail-optimized, fail-open.

PR2 (sync-lore-in-importer, Phases 3-4): builds an optional vision callable
from the active Hermes assistant settings. Vision is gated on a
``multimodal`` catalog capability; when enabled, each extracted image is
thumbnailed to 300px (originals never cross the boundary), analyzed by
``LlmProvider.analyze_image`` with the surrounding text chunk, and the
result is persisted in the content cache keyed by the SHA-256 of the
original bytes.

Fail-open at every boundary: missing/invalid/text-only settings, thumbnail
failures, provider failures, and cache errors all degrade to empty results
— an import never blocks on vision. Models are never hardcoded here; the
provider configuration comes exclusively from ``assistant_settings``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from sync_lore.schemas import ImageEntry

logger = logging.getLogger(__name__)

_THUMBNAIL_WIDTH = 300
# Matches the sync_lore VisionConfig default; used as the total budget for
# the async bridge (mirrors api_server._sync_hermes_enricher).
_VISION_TIMEOUT = 120
_ALLOWED_VERDICTS = frozenset({"confirma", "rechaza", "no_aplica", "contradice"})


@dataclass
class VisionResult:
    """Analysis result for one image (persisted in the vision cache)."""

    image_hash: str
    description: str  # used as alt-text
    verdict: str      # "confirma" | "contradice" | "no_aplica"
    analysis: str
    tags: list[str]

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize to the persisted ``result_json`` contract."""
        return {
            "image_hash": self.image_hash,
            "description": self.description,
            "verdict": self.verdict,
            "analysis": self.analysis,
            "tags": list(self.tags),
        }

    @classmethod
    def from_json_dict(cls, data: Any, default_hash: str = "") -> "VisionResult | None":
        """Rebuild a result from a cached JSON dict; ``None`` when malformed."""
        if not isinstance(data, dict):
            return None
        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        return cls(
            image_hash=str(data.get("image_hash") or default_hash),
            description=str(data.get("description") or ""),
            verdict=_normalize_verdict(data.get("verdict")),
            analysis=str(data.get("analysis") or ""),
            tags=[t for t in tags if isinstance(t, str)],
        )


@dataclass(frozen=True)
class VisionConfig:
    """Vision provider configuration derived from assistant_settings."""

    provider: str
    base_url: str
    model: str
    api_key_env: str
    timeout: int = _VISION_TIMEOUT
    #: Resolved from the stored Hermes env file; never serialized.
    api_key: str = ""


def _normalize_verdict(value: Any) -> str:
    """Coerce a provider verdict to the closed vocabulary; else no_aplica."""
    if isinstance(value, str) and value in _ALLOWED_VERDICTS:
        return value
    return "no_aplica"


def _as_dict(value: Any) -> dict[str, Any]:
    """Normalize an ``ImageAnalysis`` (dataclass) or plain dict to a dict."""
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        try:
            return asdict(value)
        except Exception:  # noqa: BLE001 — advisory payload, never fatal
            pass
    return {}


def _run_vision(coro: Any, timeout: int) -> Any:
    """Bridge the async vision provider into the sync importer seam.

    Mirrors ``api_server._sync_hermes_enricher``: the coroutine runs with a
    total budget via ``asyncio.run``. A ``RuntimeError`` (caller already
    drives an event loop) propagates to the caller's fail-open handler.
    """
    return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


def _read_assistant_vision_config(
    settings_path: Path | None,
    *,
    accepted_capability: str | None = None,
) -> VisionConfig | None:
    """Read the active assistant settings; ``None`` unless multimodal.

    Reuses ``assistant_settings`` read-only so the vision gate sees the
    exact config Hermes uses: profile resolution honors ``HERMES_HOME``,
    ``provider``/``base_url``/``model_id`` come from the normalized
    ``assistant_settings`` block (falling back to the legacy top-level
    ``model`` block), and capability comes from the stored metadata or the
    ``ASSISTANT_MODEL_CATALOG``. Models are never hardcoded here.
    """
    try:
        from assistant_settings import (  # lazy: keep this module dependency-free
            ASSISTANT_MODEL_CATALOG,
            _provider_key_env,
            _read_config,
            _resolve_profile_paths,
            _stored_api_key,
        )
        if settings_path is None:
            settings_path = _resolve_profile_paths().config
        _, _, data = _read_config(settings_path)
    except Exception as exc:  # noqa: BLE001 — fail-open gate
        logger.info("Vision settings unavailable: %s", exc)
        return None

    normalized = (data.get("assistant_settings")
                  if isinstance(data.get("assistant_settings"), dict) else {})
    model_block = data.get("model") if isinstance(data.get("model"), dict) else {}
    provider = str(normalized.get("provider") or model_block.get("provider") or "").strip()
    base_url = str(normalized.get("base_url") or model_block.get("base_url") or "").strip()
    model_id = str(normalized.get("model_id") or model_block.get("default") or "").strip()
    if not provider or not base_url or not model_id:
        logger.info("Vision settings incomplete in %s", settings_path)
        return None

    capability = str(normalized.get("capability") or "")
    if capability not in {"multimodal", "text-only", "unknown"}:
        catalog = next(
            (item for item in ASSISTANT_MODEL_CATALOG if item["id"] == model_id),
            None,
        )
        capability = str((catalog or {}).get("capability") or "unknown")
    # A product-recorded causal vision acceptance for this config revision is
    # proof the model is multimodal even when the stored metadata predates the
    # catalog entry (S14). Callers pass it explicitly; the importer does not.
    if capability != "multimodal" and accepted_capability == "multimodal":
        capability = "multimodal"
    if capability != "multimodal":
        logger.info("Model %s is %s; vision skipped", model_id, capability)
        return None

    return VisionConfig(
        provider=provider,
        base_url=base_url,
        model=model_id,
        api_key_env=_provider_key_env(provider),
        # The server process may not export the Hermes env file into its own
        # environment, so resolve the stored key explicitly.
        api_key=_stored_api_key(provider),
    )


#: Public alias for callers outside this module (the chat image seam).
read_vision_config = _read_assistant_vision_config


def _safe_cache_lookup(
    lookup: Callable[[str], VisionResult | None] | None,
    image_hash: str,
) -> VisionResult | None:
    """Cache lookup that never raises; failures degrade to a miss."""
    if lookup is None:
        return None
    try:
        return lookup(image_hash)
    except Exception as exc:  # noqa: BLE001 — cache is advisory
        logger.warning("Vision cache lookup failed: %s", exc)
        return None


def _safe_cache_store(
    store: Callable[[str, VisionResult], None] | None,
    image_hash: str,
    result: VisionResult,
) -> None:
    """Cache store that never raises; failures degrade to a no-op."""
    if store is None:
        return
    try:
        store(image_hash, result)
    except Exception as exc:  # noqa: BLE001 — cache is advisory
        logger.warning("Vision cache store failed: %s", exc)


def build_vision_callable(
    settings_path: Path | None = None,
    generate_thumbnail: Callable[[bytes, int], bytes] | None = None,
    vision_cache_lookup: Callable[[str], VisionResult | None] | None = None,
    vision_cache_store: Callable[[str, VisionResult], None] | None = None,
    accepted_capability: str | None = None,
) -> Callable[[list[ImageEntry], str], list[VisionResult]] | None:
    """Build the vision callable from assistant settings; ``None`` when disabled.

    Returns ``None`` when the assistant is not configured, the model
    capability is text-only, or the settings are invalid. The returned
    callable analyzes ``ImageEntry`` values cache-first (keyed by the
    SHA-256 of the original bytes), thumbnails to 300px before the provider
    call, and fails open at every boundary.
    """
    config = _read_assistant_vision_config(
        settings_path, accepted_capability=accepted_capability)
    if config is None:
        return None

    def analyze_images(
        images: list[ImageEntry], context: str,
    ) -> list[VisionResult]:
        """Analyze each image: cache-first, thumbnail-gated, fail-open."""
        results: list[VisionResult] = []
        if generate_thumbnail is None:
            logger.warning("No thumbnail generator injected; vision skipped")
            return results
        try:
            from sync_lore.providers.llm import LlmProvider
            from sync_lore.schemas import (
                ProviderConfig,
                VisionConfig as SyncLoreVisionConfig,
            )

            # The vision sub-config is REQUIRED: without it LlmProvider
            # treats image analysis as unconfigured and returns None. Both
            # come from assistant_settings — nothing is hardcoded.
            provider = LlmProvider(ProviderConfig(
                provider=config.provider,
                endpoint=config.base_url,
                model=config.model,
                api_key_env=config.api_key_env,
                timeout=config.timeout,
                vision=SyncLoreVisionConfig(
                    provider=config.provider,
                    endpoint=config.base_url,
                    model=config.model,
                    api_key_env=config.api_key_env,
                    timeout=config.timeout,
                ),
            ), api_key=config.api_key or None, vision_api_key=config.api_key or None)
        except Exception as exc:  # noqa: BLE001 — fail-open: never block import
            logger.warning("Vision provider construction failed: %s", exc)
            return results

        for img in images:
            img_hash = hashlib.sha256(img.image_bytes).hexdigest()

            cached = _safe_cache_lookup(vision_cache_lookup, img_hash)
            if cached is not None:
                results.append(cached)
                continue

            # Thumbnail first: originals never cross the vision boundary.
            try:
                thumbnail = generate_thumbnail(img.image_bytes, _THUMBNAIL_WIDTH)
            except Exception as exc:  # noqa: BLE001 — fail-open per image
                logger.warning("Thumbnail generation failed: %s", exc)
                continue

            try:
                ctx = img.context_text or context or ""
                analysis = _run_vision(
                    provider.analyze_image(thumbnail, ctx),
                    timeout=config.timeout,
                )
                if analysis is None:
                    continue
                payload = _as_dict(analysis)
                result = VisionResult(
                    image_hash=img_hash,
                    description=str(payload.get("descripcion") or ""),
                    verdict=_normalize_verdict(payload.get("veredicto")),
                    analysis=str(payload.get("analisis") or ""),
                    tags=[t for t in payload.get("tags", []) if isinstance(t, str)],
                )
                # Store only successful analyses; the next import of the
                # same bytes skips the provider entirely.
                _safe_cache_store(vision_cache_store, img_hash, result)
                results.append(result)
            except Exception as exc:  # noqa: BLE001 — fail-open per image
                logger.warning(
                    "Vision analysis failed for %s: %s",
                    img.filename or img_hash, exc,
                )

        return results

    return analyze_images