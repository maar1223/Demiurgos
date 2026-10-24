# -*- coding: utf-8 -*-
"""Chat image attachments — describe one image for the Assistant (S12/S13).

The image never reaches Hermes: this seam turns the bytes into the description
text the run prompt carries. It reuses the product's validated vision provider
(the same assistant settings the importer's vision gate reads) and fails with
the stable ``attachment.*`` contract instead of crashing the upload request.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from chat_attachments import ChatAttachmentError

logger = logging.getLogger(__name__)

#: Matches the importer's thumbnail width: originals never cross the boundary.
THUMBNAIL_WIDTH = 300


def _vision_unavailable() -> ChatAttachmentError:
    return ChatAttachmentError(
        "attachment.vision_unavailable",
        422,
        "Vision is unavailable for the active assistant model.",
    )


def _vision_failed() -> ChatAttachmentError:
    return ChatAttachmentError(
        "attachment.vision_failed",
        502,
        "The image could not be described.",
    )


def _read_vision_config(
    *,
    settings_path: Path | None = None,
    accepted_capability: str | None = None,
):
    """Resolve the vision config through the importer's read-only gate."""
    from import_vision import read_vision_config

    return read_vision_config(
        settings_path, accepted_capability=accepted_capability
    )


def _build_provider(config: Any):
    """Build the async provider from the resolved vision config.

    Mirrors ``import_vision.build_vision_callable``: the vision sub-config is
    required, otherwise ``LlmProvider`` treats image analysis as unconfigured.
    """
    from sync_lore.providers.llm import LlmProvider
    from sync_lore.schemas import ProviderConfig, VisionConfig as SyncVisionConfig

    vision = SyncVisionConfig(
        provider=config.provider,
        endpoint=config.base_url,
        model=config.model,
        api_key_env=config.api_key_env,
        timeout=config.timeout,
    )
    return LlmProvider(ProviderConfig(
        provider=config.provider,
        endpoint=config.base_url,
        model=config.model,
        api_key_env=config.api_key_env,
        timeout=config.timeout,
        vision=vision,
    ))


async def describe_chat_image(
    image_bytes: bytes,
    *,
    settings_path: Path | None = None,
    accepted_capability: str | None = None,
    generate_thumbnail: Callable[[bytes, int], bytes] | None = None,
) -> str:
    """Return a detailed description of one attached image.

    Raises :class:`ChatAttachmentError` with ``attachment.vision_unavailable``
    when the model is not proven multimodal, ``attachment.unsupported_type``
    when the bytes are not a decodable image, and ``attachment.vision_failed``
    when the provider cannot produce a description. Never raises anything else
    from this boundary.
    """
    config = _read_vision_config(
        settings_path=settings_path,
        accepted_capability=accepted_capability,
    )
    if config is None or generate_thumbnail is None:
        raise _vision_unavailable()

    try:
        thumbnail = generate_thumbnail(image_bytes, THUMBNAIL_WIDTH)
    except Exception as exc:  # noqa: BLE001 — undecodable input is a rejection
        raise ChatAttachmentError(
            "attachment.unsupported_type",
            422,
            "The image could not be read.",
        ) from exc

    try:
        provider = _build_provider(config)
    except Exception as exc:  # noqa: BLE001 — misconfiguration degrades safely
        logger.warning("Chat vision provider construction failed: %s", exc)
        raise _vision_failed() from exc

    try:
        description = await provider.describe_image(thumbnail, "")
    except Exception as exc:  # noqa: BLE001 — provider failure is a rejection
        logger.warning("Chat vision analysis failed: %s", exc)
        raise _vision_failed() from exc

    if not isinstance(description, str) or not description.strip():
        raise _vision_failed()
    return description.strip()
