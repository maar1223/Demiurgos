"""A clean-EOF truncation must not turn a good delta into a failed turn.

Measured on the live Vibrantes session (2026-11-08): two consecutive turns
failed as ``malformed_output`` because the provider ended the stream after the
last field but before the closing brace — 3 ``{`` against 2 ``}``. The gateway
stamps a text-only clean EOF as ``stop``, so the app received a complete-looking
JSON with one missing brace and rejected the whole turn.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from guided_character_protocol import (  # noqa: E402
    PROTOCOL_VERSION,
    CancellationToken,
    GuidedRequest,
    GuidedResponse,
)
from guided_character_provider import HermesGuidedProvider  # noqa: E402


def request() -> GuidedRequest:
    return GuidedRequest(
        PROTOCOL_VERSION, "req-1", "session-1", "vibrantes", 2, "author-1", "sigue",
    )


class _Runs:
    def __init__(self, output: str) -> None:
        self.output = output
        self.requests: list[object] = []

    async def start(self, request: object) -> str:
        self.requests.append(request)
        return "run-1"

    def events(self, run_id: str):
        async def _gen():
            yield {"run_id": run_id, "event": "run.completed", "output": self.output}
        return _gen()

    async def status(self, _run_id: str) -> dict:
        return {"status": "completed", "output": self.output}


def _delta_payload() -> str:
    return json.dumps(
        {
            "request_id": "req-1",
            "session_id": "session-1",
            "outcome": "delta",
            "synthesis": "Ficha lista.",
            "observations": {"estado": "propuesta"},
            "delta": {"nombre": "Ganic", "oficio": "repara Dvins"},
        },
        ensure_ascii=False,
    )


def test_a_missing_closing_brace_is_repaired() -> None:
    complete = _delta_payload()
    assert complete.endswith("}}")
    truncated = complete[:-1]  # exactly the measured failure: one brace short

    provider = HermesGuidedProvider(_Runs(truncated))  # type: ignore[arg-type]
    raw = asyncio.run(provider.invoke(request(), CancellationToken()))

    parsed = GuidedResponse.from_provider(raw, request())
    assert parsed is not None
    assert parsed.outcome.value == "delta"
    assert parsed.delta == {"nombre": "Ganic", "oficio": "repara Dvins"}


def test_a_value_cut_mid_string_is_never_repaired() -> None:
    complete = _delta_payload()
    truncated = complete[: complete.index("Ganic") + 2]  # inside the value

    provider = HermesGuidedProvider(_Runs(truncated))  # type: ignore[arg-type]
    raw = asyncio.run(provider.invoke(request(), CancellationToken()))

    assert GuidedResponse.from_provider(raw, request()) is None


def test_a_wrong_request_id_is_still_rejected_after_repair() -> None:
    payload = _delta_payload().replace('"req-1"', '"other-id"')[:-1]
    provider = HermesGuidedProvider(_Runs(payload))  # type: ignore[arg-type]
    raw = asyncio.run(provider.invoke(request(), CancellationToken()))
    assert GuidedResponse.from_provider(raw, request()) is None


def test_the_prompt_defines_the_delta_envelope() -> None:
    runs = _Runs(_delta_payload())
    provider = HermesGuidedProvider(runs)  # type: ignore[arg-type]
    asyncio.run(provider.invoke(request(), CancellationToken()))
    prompt = runs.requests[0].prompt
    assert "flat" in prompt.casefold()
    assert "never a rendered document" in prompt.casefold()
