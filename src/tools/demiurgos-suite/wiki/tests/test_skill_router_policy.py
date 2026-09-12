"""Routing-policy tests for the skill router (PR ②, WU-B).

Self-contained companion-world policy scenarios: companion near-tie fail-open
(SR3), the classifier top-2 output contract (prompt request + tolerant parse),
the vacuous-margin rule, and degraded-mode zero injection. Mirrors the PR①
pattern (test_per_flow_activation.py): local sys.path bootstrap, per-test
stubs, no shared fixtures — the on-disk library is never read.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from skill_router import (  # noqa: E402
    NEAR_TIE_MARGIN,
    SkillRouteResult,
    SkillRouter,
)


class _Runs:
    """Configurable Hermes runs seam: returns a fixed JSON classification."""

    def __init__(self, classification: Any) -> None:
        self._classification = classification
        self.prompts: list[str] = []

    async def start(self, request: object) -> str:
        self.prompts.append(request.prompt)  # type: ignore[attr-defined]
        return "run-1"

    async def events(self, run_id: str):
        yield {"event": "run.completed", "run_id": run_id, "output": self._classification}

    async def status(self, run_id: str) -> dict:
        return {"status": "completed", "output": self._classification}


class _FailingRuns:
    """Hermes seam that raises on start (provider unavailable)."""

    async def start(self, request: object) -> str:
        raise RuntimeError("provider down")


@dataclass(frozen=True)
class _Activation:
    skill_id: str
    version: str


@dataclass(frozen=True)
class _Published:
    description: str
    name: str = ""


class _CompanionLibrary:
    """Minimal MethodologyLibrary stub: published companions, no slot activation."""

    def __init__(self, companions: list[_Activation]) -> None:
        self._companions = list(companions)

    def active_for(self, mundo: str, flow_type: str | None = None):
        return None

    def list_companions(self, mundo: str):
        return list(self._companions)

    def get_published(self, skill_id: str, version: str):
        return _Published(description=f"{skill_id} methodology")


def _result(router: SkillRouter, prompt: str, mundo: str = "vibrantes") -> SkillRouteResult:
    return asyncio.run(router.route(prompt, mundo))


# --------------------------------------------------------------------------- #
# Companion near-tie fail-open (SR3): both top-2 are companions and their
# confidence gap is below NEAR_TIE_MARGIN → fail open, source="ambiguous".
# --------------------------------------------------------------------------- #

def test_near_tie_margin_constant_is_015() -> None:
    """The near-tie margin is the normative 0.15 constant."""
    assert NEAR_TIE_MARGIN == 0.15


def test_near_tie_both_companions_fails_open_ambiguous() -> None:
    """Winner 0.80, companion runner-up 0.70 → diff 0.10 < 0.15 → fail open."""
    library = _CompanionLibrary([
        _Activation(skill_id="alpha", version="1.0"),
        _Activation(skill_id="omega", version="2.0"),
    ])
    runs = _Runs({
        "skill_id": "alpha",
        "confidence": 0.80,
        "runner_up_skill_id": "omega",
        "runner_up_confidence": 0.70,
    })
    router = SkillRouter(methodology_library=library, provider=runs)
    result = _result(router, "do the alpha thing")
    assert result.skill_id is None
    assert result.routed is False
    assert result.source == "ambiguous"


def test_clear_winner_above_margin_routes() -> None:
    """Winner 0.85, companion runner-up 0.60 → diff 0.25 ≥ 0.15 → routed."""
    library = _CompanionLibrary([
        _Activation(skill_id="alpha", version="1.0"),
        _Activation(skill_id="omega", version="2.0"),
    ])
    runs = _Runs({
        "skill_id": "alpha",
        "confidence": 0.85,
        "runner_up_skill_id": "omega",
        "runner_up_confidence": 0.60,
    })
    router = SkillRouter(methodology_library=library, provider=runs)
    result = _result(router, "do the alpha thing")
    assert result.skill_id == "alpha"
    assert result.routed is True
    assert result.source == "llm"


def test_vacuous_margin_with_non_companion_runner_up() -> None:
    """Runner-up is foundational (not a companion): a diff below the margin is
    vacuous and the threshold alone applies → the companion is routed."""
    library = _CompanionLibrary([
        _Activation(skill_id="alpha", version="1.0"),
        _Activation(skill_id="omega", version="2.0"),
    ])
    runs = _Runs({
        "skill_id": "alpha",
        "confidence": 0.80,
        "runner_up_skill_id": "narrative-character-creation",
        "runner_up_confidence": 0.72,
    })
    router = SkillRouter(methodology_library=library, provider=runs)
    result = _result(router, "do the alpha thing")
    assert result.skill_id == "alpha"
    assert result.routed is True
    assert result.source == "llm"


def test_runner_up_absent_is_tolerated() -> None:
    """LLM omits the runner-up: winner/confidence still parse, runner-up is
    None, and routing proceeds on the threshold rule alone."""
    library = _CompanionLibrary([
        _Activation(skill_id="alpha", version="1.0"),
        _Activation(skill_id="omega", version="2.0"),
    ])
    runs = _Runs({"skill_id": "alpha", "confidence": 0.85})
    router = SkillRouter(methodology_library=library, provider=runs)
    result = _result(router, "do the alpha thing")
    assert result.skill_id == "alpha"
    assert result.routed is True
    assert result.source == "llm"


def test_malformed_runner_up_is_tolerated() -> None:
    """Malformed runner-up fields parse to None → margin rule vacuous, never
    an error."""
    library = _CompanionLibrary([
        _Activation(skill_id="alpha", version="1.0"),
        _Activation(skill_id="omega", version="2.0"),
    ])
    runs = _Runs({
        "skill_id": "alpha",
        "confidence": 0.80,
        "runner_up_skill_id": 123,          # non-string id
        "runner_up_confidence": "high",     # non-numeric confidence
    })
    router = SkillRouter(methodology_library=library, provider=runs)
    result = _result(router, "do the alpha thing")
    assert result.skill_id == "alpha"
    assert result.routed is True
    assert result.source == "llm"


# --------------------------------------------------------------------------- #
# Classifier top-2 output contract: the companion-world prompt requests the
# runner-up alongside the winner.
# --------------------------------------------------------------------------- #

def test_companion_prompt_requests_runner_up() -> None:
    """The with-descriptions prompt asks for runner_up_skill_id and
    runner_up_confidence."""
    library = _CompanionLibrary([
        _Activation(skill_id="alpha", version="1.0"),
        _Activation(skill_id="omega", version="2.0"),
    ])
    runs = _Runs({"skill_id": "alpha", "confidence": 0.9})
    router = SkillRouter(methodology_library=library, provider=runs)
    _result(router, "do the alpha thing")
    prompt = runs.prompts[0]
    assert '"runner_up_skill_id"' in prompt
    assert '"runner_up_confidence"' in prompt


# --------------------------------------------------------------------------- #
# Degraded mode is pure fail-open: a companion is never routed when the
# classifier is unreachable (zero skill injection).
# --------------------------------------------------------------------------- #

def test_degraded_mode_injects_nothing() -> None:
    library = _CompanionLibrary([
        _Activation(skill_id="alpha", version="1.0"),
        _Activation(skill_id="omega", version="2.0"),
    ])
    router = SkillRouter(methodology_library=library, provider=_FailingRuns())
    result = _result(router, "do the alpha thing")
    assert result.skill_id is None
    assert result.routed is False
    assert result.source == "fallback"