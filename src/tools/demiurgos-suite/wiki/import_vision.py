# -*- coding: utf-8 -*-
"""World importer — vision analysis module (PR2, sync-lore-in-importer).

Provides :class:`VisionResult` for the persistent content cache and
:func:`build_vision_callable` as the seam that wires the multimodal
provider into the import pipeline.

The seam fails CLOSED at configuration time (missing settings file, invalid
YAML, missing provider/base_url/model, or a text-only assistant capability
all yield ``None`` → vision disabled) and fails OPEN at analysis time (a
broken thumbnailer, cache, or provider never blocks the batch).

Each image is analysed through a 300px thumbnail — the original bytes never
cross the provider boundary — and the SHA-256 of the ORIGINAL bytes is both
the cache key and the result identity. The returned callable is synchronous:
it runs the async ``LlmProvider.analyze_image`` inside its own event loop,
degrading gracefully when called from a running loop.

Only stdlib is imported at module level (``sync_lore`` and the assistant
settings chain are imported lazily inside the callables) so this module
stays importable wherever the store or the router load it.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import yaml

if TYPE_CHECKING:
    from sync_lore.schemas import ImageEntry, ProviderConfig

# Closed verdict vocabulary for the importer (the sync_lore provider enum
# plus the reviewer-facing alias). Anything else degrades to ``no_aplica``.
_ALLOWED_VERDICTS = frozenset({"confirma", "rechaza", "no_aplica", "contradice"})

# Fallback capability catalog (mirrors ``assistant_settings.ASSISTANT_MODEL_CATALOG``)
# so the multimodal gate stays decidable even when that module is not
# importable in the current runtime.
_MODEL_CAPABILITIES: dict[str, str] = {
    "gpt-5.6-luna": "multimodal",
    "qwen3.6-plus": "multimodal",
    "deepseek-v4-flash": "text-only",
    "deepseek-v4-pro": "text-only",
    "deepseek-v4-lite": "text-only",
}

_THUMBNAIL_WIDTH = 300


@dataclass
class VisionResult:
    """Persisted outcome of a multimodal image analysis."""

    image_hash: str
    description: str = ""
    verdict: str = "no_aplica"
    analysis: str = ""
    tags: list[str] = field(default_factory=list)

    # -- serialisation --------------------------------------------------

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "image_hash": self.image_hash,
            "description": self.description,
            "verdict": self.verdict,
            "analysis": self.analysis,
            "tags": list(self.tags),
        }

    @classmethod
    def from_json_dict(cls, data: Any, image_hash: str) -> "VisionResult":
        """Rebuild a result from a cached payload.

        Strict by design: the caller (the store lookup) validates the payload
        and treats a non-dict value as a corrupt cache row, degrading to
        ``None`` — this constructor must raise on non-dict data so that
        fail-open path works. Any verdict outside the closed vocabulary
        degrades to ``no_aplica``.
        """
        return cls(
            image_hash=data.get("image_hash", image_hash) or image_hash,
            description=data.get("description", "") or "",
            verdict=_normalize_verdict(data.get("verdict", "no_aplica")),
            analysis=data.get("analysis", "") or "",
            tags=list(data.get("tags", []) or []),
        )


def _normalize_verdict(value: Any) -> str:
    """Map a provider verdict onto the closed vocabulary, failing closed."""
    verdict = str(value or "no_aplica")
    return verdict if verdict in _ALLOWED_VERDICTS else "no_aplica"


def _model_capability(model_id: str) -> str:
    """Resolve a model's capability from the server catalog, if importable."""
    try:
        from assistant_settings import ASSISTANT_MODEL_CATALOG  # noqa: PLC0415

        for item in ASSISTANT_MODEL_CATALOG:
            if item.get("id") == model_id:
                return str(item.get("capability") or "unknown")
    except Exception:  # noqa: BLE001 — the catalog is advisory, never fatal
        pass
    return _MODEL_CAPABILITIES.get(model_id, "unknown")


def _is_multimodal(model_id: str, stored_capability: Any) -> bool:
    """Multimodal gate: a stored ``capability`` wins, else the model catalog.

    Mirrors ``assistant_settings``: only ``multimodal`` passes. An absent
    stored capability falls back to the catalog; unknown models fail closed.
    """
    if stored_capability is not None:
        return str(stored_capability) == "multimodal"
    return _model_capability(model_id) == "multimodal"


def build_vision_callable(
    settings_path: Any = None,
    generate_thumbnail: Callable[[bytes, int], bytes] | None = None,
    vision_cache_lookup: Callable[[str], VisionResult | None] | None = None,
    vision_cache_store: Callable[[str, VisionResult], None] | None = None,
) -> Callable[..., list[VisionResult]] | None:
    """Compose the vision analysis callable, or ``None`` when unavailable.

    The settings gate fails CLOSED: a missing settings file, invalid YAML,
    missing provider/base_url/model, or a text-only model capability yields
    ``None`` (vision disabled). When the gate opens, the returned callable
    ``analyze(entries, batch_context) -> list[VisionResult]`` runs the async
    ``LlmProvider.analyze_image`` inside its own event loop per image, so it
    is synchronous from the caller's perspective.

    The seams are injected by position or keyword: ``generate_thumbnail``
    (300px gate), ``vision_cache_lookup``/``vision_cache_store`` (SHA-256
    content cache). Cache hits never touch the thumbnailer or the provider.
    """
    # -- settings gate (fail-closed) ------------------------------------
    path = Path(settings_path) if settings_path else None
    if path is None or not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None

    model_block = data.get("model")
    if not isinstance(model_block, dict):
        model_block = {}
    assistant = data.get("assistant_settings")
    if not isinstance(assistant, dict):
        assistant = {}

    model_id = str(assistant.get("model_id") or model_block.get("default") or "")
    provider = str(assistant.get("provider") or model_block.get("provider") or "")
    base_url = str(assistant.get("base_url") or model_block.get("base_url") or "")
    stored_capability = assistant.get("capability")

    if not model_id or not provider or not base_url:
        return None
    if not _is_multimodal(model_id, stored_capability):
        return None

    # -- analysis callable ----------------------------------------------
    def analyze(
        entries: list[ImageEntry],
        batch_context: str = "",
    ) -> list[VisionResult]:
        from sync_lore.providers.llm import LlmProvider  # noqa: PLC0415
        from sync_lore.schemas import ProviderConfig, VisionConfig  # noqa: PLC0415

        # No thumbnailer → nothing can be analysed (fail-open, empty batch).
        if generate_thumbnail is None:
            return []
        if not entries:
            return []

        # The ProviderConfig carries the settings model — both for text and
        # for the vision sub-config (never hardcoded).
        config = ProviderConfig(
            provider=provider,
            model=model_id,
            endpoint=base_url,
            vision=VisionConfig(
                provider=provider,
                model=model_id,
                endpoint=base_url,
            ),
        )
        # A fresh provider is built per analyze call (repeat imports with
        # identical bytes hit the cache instead of building new traffic).
        provider_instance = LlmProvider(config)

        results: list[VisionResult] = []
        for entry in entries:
            image_bytes = getattr(entry, "image_bytes", b"")
            image_hash = hashlib.sha256(image_bytes).hexdigest()

            # Cache first — a hit never touches the thumbnailer or provider.
            cached: VisionResult | None = None
            if vision_cache_lookup is not None:
                try:
                    cached = vision_cache_lookup(image_hash)
                except Exception:  # noqa: BLE001 — cache is advisory
                    cached = None
            if cached is not None:
                results.append(cached)
                continue

            # 300px thumbnail gate: the provider receives ONLY the thumbnail.
            try:
                thumbnail = generate_thumbnail(image_bytes, _THUMBNAIL_WIDTH)
            except Exception:  # noqa: BLE001 — thumbnailer failure skips image
                continue

            context = entry.context_text or batch_context
            try:
                analysis = asyncio.run(
                    provider_instance.analyze_image(thumbnail, context),
                )
            except Exception:  # noqa: BLE001 — provider failure skips image
                continue
            if analysis is None:
                continue

            result = VisionResult(
                image_hash=image_hash,
                description=analysis.descripcion or "",
                verdict=_normalize_verdict(analysis.veredicto),
                analysis=analysis.analisis or "",
                tags=list(analysis.tags or []),
            )
            # Only successful analyses reach the cache; store failures
            # degrade gracefully (the result is still returned).
            if vision_cache_store is not None:
                try:
                    vision_cache_store(image_hash, result)
                except Exception:  # noqa: BLE001 — cache is advisory
                    pass
            results.append(result)
        return results

    return analyze