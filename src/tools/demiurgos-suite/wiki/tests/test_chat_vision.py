# -*- coding: utf-8 -*-
"""Chat image attachments — vision description seam (S12/S13).

The provider HTTP call is always mocked: no network, no live model.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
_TOOLS = _HERE.parents[2]
for _p in (str(_WIKI), str(_SUITE), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import chat_vision  # noqa: E402
from chat_attachments import ChatAttachmentError  # noqa: E402
from import_vision import VisionConfig  # noqa: E402

_IMAGE = b"\x89PNG\r\n\x1a\noriginal-image-bytes"


def _thumbnail(_image: bytes, width: int) -> bytes:
    assert width == 300
    return b"THUMB"


class _FakeProvider:
    instances: list["_FakeProvider"] = []

    def __init__(self, description="Una torre de cristal al atardecer."):
        self.description = description
        self.calls: list[tuple[bytes, str]] = []
        _FakeProvider.instances.append(self)

    async def describe_image(self, image: bytes, context: str = ""):
        self.calls.append((image, context))
        return self.description


def _config() -> VisionConfig:
    return VisionConfig(
        provider="compatible",
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        api_key_env="OPENCODE_API_KEY",
    )


class TestDescribeChatImage:
    def test_returns_the_provider_description_for_the_thumbnail(self, monkeypatch):
        provider = _FakeProvider()
        monkeypatch.setattr(chat_vision, "_read_vision_config", lambda **_: _config())
        monkeypatch.setattr(chat_vision, "_build_provider", lambda _config: provider)

        description = asyncio.run(chat_vision.describe_chat_image(
            _IMAGE, generate_thumbnail=_thumbnail,
        ))

        assert description == "Una torre de cristal al atardecer."
        assert provider.calls[0][0] == b"THUMB"
        assert _IMAGE not in provider.calls[0][0]

    def test_unproven_capability_is_rejected_as_unavailable(self, monkeypatch):
        monkeypatch.setattr(chat_vision, "_read_vision_config", lambda **_: None)
        with pytest.raises(ChatAttachmentError) as info:
            asyncio.run(chat_vision.describe_chat_image(_IMAGE, generate_thumbnail=_thumbnail))
        assert info.value.code == "attachment.vision_unavailable"
        assert info.value.status == 422

    def test_undecodable_image_is_rejected_as_unreadable(self, monkeypatch):
        def _explode(_image, _width):
            raise OSError("cannot decode")

        monkeypatch.setattr(chat_vision, "_read_vision_config", lambda **_: _config())
        with pytest.raises(ChatAttachmentError) as info:
            asyncio.run(chat_vision.describe_chat_image(_IMAGE, generate_thumbnail=_explode))
        assert info.value.code == "attachment.unsupported_type"

    def test_provider_failure_is_reported_as_vision_failed(self, monkeypatch):
        class _Broken(_FakeProvider):
            async def describe_image(self, image, context=""):
                raise RuntimeError("provider down")

        monkeypatch.setattr(chat_vision, "_read_vision_config", lambda **_: _config())
        monkeypatch.setattr(chat_vision, "_build_provider", lambda _config: _Broken())
        with pytest.raises(ChatAttachmentError) as info:
            asyncio.run(chat_vision.describe_chat_image(_IMAGE, generate_thumbnail=_thumbnail))
        assert info.value.code == "attachment.vision_failed"
        assert info.value.status == 502

    def test_empty_description_is_reported_as_vision_failed(self, monkeypatch):
        monkeypatch.setattr(chat_vision, "_read_vision_config", lambda **_: _config())
        monkeypatch.setattr(
            chat_vision, "_build_provider", lambda _config: _FakeProvider(description="  ")
        )
        with pytest.raises(ChatAttachmentError) as info:
            asyncio.run(chat_vision.describe_chat_image(_IMAGE, generate_thumbnail=_thumbnail))
        assert info.value.code == "attachment.vision_failed"

    def test_provider_construction_failure_is_vision_failed(self, monkeypatch):
        def _explode(_config):
            raise RuntimeError("bad config")

        monkeypatch.setattr(chat_vision, "_read_vision_config", lambda **_: _config())
        monkeypatch.setattr(chat_vision, "_build_provider", _explode)
        with pytest.raises(ChatAttachmentError) as info:
            asyncio.run(chat_vision.describe_chat_image(_IMAGE, generate_thumbnail=_thumbnail))
        assert info.value.code == "attachment.vision_failed"


class TestProviderDescribeImage:
    def test_builds_a_vision_payload_and_returns_the_description(self, monkeypatch):
        from sync_lore.providers.llm import LlmProvider
        from sync_lore.schemas import ProviderConfig, VisionConfig as SyncVisionConfig

        config = ProviderConfig(
            provider="compatible",
            endpoint="https://api.deepseek.com",
            model="deepseek-flash",
            api_key_env="OPENCODE_API_KEY",
            vision=SyncVisionConfig(
                provider="compatible",
                endpoint="https://api.deepseek.com",
                model="deepseek-flash",
                api_key_env="OPENCODE_API_KEY",
            ),
        )
        provider = LlmProvider(config)
        monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
        # Rebuild so the key is picked up.
        provider = LlmProvider(config)
        captured: dict = {}

        async def fake_post(payload, cfg, key):
            captured["payload"] = payload
            captured["model"] = cfg.model
            return {"descripcion": "  Un mapa antiguo con tres reinos.  "}

        monkeypatch.setattr(provider, "_post", fake_post)
        description = asyncio.run(provider.describe_image(b"THUMB", "contexto"))

        assert description == "Un mapa antiguo con tres reinos."
        assert captured["model"] == "deepseek-flash"
        messages = captured["payload"]["messages"]
        assert messages[0]["role"] == "system"
        assert "transcribe" in messages[0]["content"].lower()
        assert messages[1]["content"][0]["type"] == "image_url"
        assert messages[1]["content"][0]["image_url"].startswith("data:image/")

    def test_missing_vision_config_returns_none(self):
        from sync_lore.providers.llm import LlmProvider
        from sync_lore.schemas import ProviderConfig

        provider = LlmProvider(ProviderConfig(
            provider="compatible",
            endpoint="https://api.deepseek.com",
            model="deepseek-flash",
            api_key_env="OPENCODE_API_KEY",
        ))
        assert asyncio.run(provider.describe_image(b"THUMB", "")) is None

    def test_missing_description_returns_none(self, monkeypatch):
        from sync_lore.providers.llm import LlmProvider
        from sync_lore.schemas import ProviderConfig, VisionConfig as SyncVisionConfig

        monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
        provider = LlmProvider(ProviderConfig(
            provider="compatible",
            endpoint="https://api.deepseek.com",
            model="deepseek-flash",
            api_key_env="OPENCODE_API_KEY",
            vision=SyncVisionConfig(
                provider="compatible",
                endpoint="https://api.deepseek.com",
                model="deepseek-flash",
                api_key_env="OPENCODE_API_KEY",
            ),
        ))

        async def fake_post(payload, cfg, key):
            return {"otro": "campo"}

        monkeypatch.setattr(provider, "_post", fake_post)
        assert asyncio.run(provider.describe_image(b"THUMB", "")) is None
