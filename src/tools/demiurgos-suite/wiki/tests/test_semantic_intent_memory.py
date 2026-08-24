"""Tests: distilled_state is injected into the semantic gate prompt."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from pathlib import Path as _Path

_WIKI = _Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from semantic_intent import SemanticIntentProvider  # noqa: E402

DISTILLED = "The author wants a stoic knight named Rhyz who values loyalty."


class _Runs:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def start(self, request: object) -> str:
        self.prompts.append(request.prompt)  # type: ignore[attr-defined]
        return "run-1"

    async def events(self, run_id: str):
        yield {"event": "run.completed", "run_id": run_id, "output": None}


def _test_prompt(distilled_state: str | None) -> str:
    provider = SemanticIntentProvider(_Runs())
    return provider._build_prompt(
        "What should the knight want?",
        "request-1",
        "session-1",
        distilled_state=distilled_state,
    )


def test_distilled_state_is_injected_into_gate_prompt() -> None:
    prompt = _test_prompt(DISTILLED)
    assert "[Conversation context (summarized):" in prompt
    assert DISTILLED in prompt


def test_no_distilled_state_leaves_prompt_unchanged() -> None:
    prompt_with = _test_prompt(DISTILLED)
    prompt_without = _test_prompt(None)
    assert "[Conversation context (summarized):" not in prompt_without
    assert DISTILLED not in prompt_without
    # The distilled block must be the only difference.
    stripped_with = prompt_with.replace(
        f" [Conversation context (summarized): {DISTILLED}]", ""
    )
    assert stripped_with == prompt_without


def test_distilled_state_reaches_prompt_through_decide() -> None:
    async def scenario() -> None:
        runs = _Runs()
        provider = SemanticIntentProvider(runs)
        await provider.decide(
            "What should the knight want?",
            request_id="request-1",
            session_id="session-1",
            distilled_state=DISTILLED,
        )
        assert runs.prompts
        assert DISTILLED in runs.prompts[0]

    asyncio.run(scenario())


def test_decide_default_distilled_state_is_none() -> None:
    async def scenario() -> None:
        runs = _Runs()
        provider = SemanticIntentProvider(runs)
        await provider.decide(
            "What should the knight want?",
            request_id="request-1",
            session_id="session-1",
        )
        assert runs.prompts
        assert "[Conversation context (summarized):" not in runs.prompts[0]

    asyncio.run(scenario())
