"""Tests: the guided provider injects the compiled contract Markdown."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from guided_character_protocol import (  # noqa: E402
    CancellationToken,
    GuidedRequest,
    PROTOCOL_VERSION,
)
from guided_character_provider import HermesGuidedProvider  # noqa: E402

CONTRACT_MD = (
    "## Methodology: Knight Code (v1.0)\n"
    "**Identity**: A stoic knight creation methodology.\n"
    "**Phases**: concept → desire → name\n"
)


class _Runs:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def start(self, request: object) -> str:
        self.prompts.append(request.prompt)  # type: ignore[attr-defined]
        return "run-1"

    async def events(self, run_id: str):
        yield {"event": "run.completed", "run_id": run_id, "output": {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": "request-1",
            "session_id": "session-1",
            "outcome": "question",
            "question": "What drives them?",
        }}


def _request() -> GuidedRequest:
    return GuidedRequest(
        PROTOCOL_VERSION, "request-1", "session-1", "vibrantes", 0, "author-1",
        "Create a knight", deadline_ms=8_000, reference_context="A stoic ficha.",
    )


def test_contract_markdown_is_injected_into_prompt() -> None:
    async def scenario() -> None:
        runs = _Runs()
        provider = HermesGuidedProvider(runs)
        await provider.invoke(
            _request(),
            CancellationToken(),
            compiled_contract_markdown=CONTRACT_MD,
        )
        prompt = runs.prompts[0]
        assert "[Active methodology contract (server-pinned, read-only):" in prompt
        assert CONTRACT_MD in prompt

    asyncio.run(scenario())


def test_without_contract_uses_version_string_when_present() -> None:
    async def scenario() -> None:
        runs = _Runs()
        provider = HermesGuidedProvider(runs)
        from dataclasses import replace
        request = replace(_request(), methodology="knight-code@1.0")
        await provider.invoke(request, CancellationToken())
        prompt = runs.prompts[0]
        assert "Active methodology snapshot" in prompt
        assert "knight-code@1.0" in prompt

    asyncio.run(scenario())


def test_without_contract_or_version_has_no_methodology_block() -> None:
    async def scenario() -> None:
        runs = _Runs()
        provider = HermesGuidedProvider(runs)
        await provider.invoke(_request(), CancellationToken())
        prompt = runs.prompts[0]
        assert "Active methodology" not in prompt

    asyncio.run(scenario())
