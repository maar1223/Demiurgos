# -*- coding: utf-8 -*-
"""Every direct provider call carries the OpenCode Go session header.

The relay rejects a chat completion without ``x-opencode-session`` with HTTP 400
``MissingSessionID``. Only the capability probe knew that; the provider used by
text analysis, enrichment and image description did not, so chat image
attachments failed with 502 ("The image could not be described") while the
assistant answered text normally through the gateway.

These tests pin the shared header builder AND that ``LlmProvider._post`` uses
it, so a future call site cannot quietly skip the header.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sync_lore.providers import llm  # noqa: E402
from sync_lore.providers.llm import chat_headers  # noqa: E402


class _Config:
    def __init__(self, endpoint: str, timeout: int = 5) -> None:
        self.endpoint = endpoint
        self.timeout = timeout


def test_opencode_endpoint_gets_the_session_header():
    headers = chat_headers(_Config("https://opencode.ai/zen/go/v1"), "key")
    assert headers["Authorization"] == "Bearer key"
    session = headers["x-opencode-session"]
    assert session.startswith("demiurgos-")
    # Stable for the process: routing affinity and prompt cache depend on it.
    assert session == chat_headers(_Config("https://opencode.ai/zen/go/v1"), "key")[
        "x-opencode-session"
    ]


def test_subdomain_is_treated_as_opencode():
    headers = chat_headers(_Config("https://console.opencode.ai/v1"), "key")
    assert "x-opencode-session" in headers


def test_other_providers_get_no_session_header():
    headers = chat_headers(_Config("https://api.openai.com/v1"), "key")
    assert "x-opencode-session" not in headers


def test_explicit_session_id_wins():
    headers = chat_headers(
        _Config("https://opencode.ai/zen/go/v1"), "key", session_id="conversation-42"
    )
    assert headers["x-opencode-session"] == "conversation-42"


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:  # noqa: D401 - httpx contract
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    seen: list[tuple[str, dict]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url: str, json: dict, headers: dict) -> _FakeResponse:
        _FakeClient.seen.append((url, headers))
        return _FakeResponse(
            {"choices": [{"message": {"content": '{"descripcion": "una imagen"}'}}]}
        )


def test_post_sends_the_session_header(monkeypatch):
    _FakeClient.seen = []
    monkeypatch.setattr(llm.httpx, "AsyncClient", _FakeClient)

    from sync_lore.providers.llm import LlmProvider
    from sync_lore.schemas import ProviderConfig

    provider = LlmProvider(ProviderConfig(), api_key="key", vision_api_key="key")
    payload = {"model": "m", "messages": []}
    result = asyncio.run(
        provider._post(payload, _Config("https://opencode.ai/zen/go/v1"), "key")
    )

    assert result == {"descripcion": "una imagen"}
    assert len(_FakeClient.seen) == 1
    url, headers = _FakeClient.seen[0]
    assert url.endswith("/chat/completions")
    assert headers["x-opencode-session"].startswith("demiurgos-")
