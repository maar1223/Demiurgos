"""Unit tests for the skill router (LLM-first + keyword fallback + fail-open)."""

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
    CONFIDENCE_THRESHOLD,
    TRANSVERSAL_SKILLS,
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


class _Library:
    """Minimal MethodologyLibrary stub exposing only active_for."""

    def __init__(self, activation: Any = None) -> None:
        self._activation = activation
        self.calls: list[str] = []

    def active_for(self, mundo: str):
        self.calls.append(mundo)
        return self._activation


@dataclass(frozen=True)
class _Activation:
    skill_id: str
    version: str


def _result(router: SkillRouter, prompt: str, mundo: str = "vibrantes") -> SkillRouteResult:
    return asyncio.run(router.route(prompt, mundo))


# --------------------------------------------------------------------------- #
# LLM routing
# --------------------------------------------------------------------------- #

def test_llm_routing_returns_skill_when_above_threshold() -> None:
    runs = _Runs({"skill_id": "narrative-world-spec", "confidence": 0.9})
    router = SkillRouter(methodology_library=None, provider=runs)
    result = _result(router, "Describe the kingdom of Rhyz")
    assert result.skill_id == "narrative-world-spec"
    assert result.confidence == 0.9
    assert result.source == "llm"
    assert result.routed is True
    # Candidates must be listed in the classification prompt.
    assert "narrative-world-spec" in runs.prompts[0]


def test_llm_prompt_lists_only_candidates_and_asks_for_strict_json() -> None:
    runs = _Runs({"skill_id": "narrative-draft", "confidence": 0.95})
    router = SkillRouter(methodology_library=None, provider=runs)
    _result(router, "write a scene")
    prompt = runs.prompts[0]
    for skill in TRANSVERSAL_SKILLS:
        assert skill in prompt
    assert '"skill_id"' in prompt and '"confidence"' in prompt
    assert "User intent: write a scene" in prompt


# --------------------------------------------------------------------------- #
# Confidence threshold (0.7 boundary)
# --------------------------------------------------------------------------- #

def test_confidence_at_threshold_is_admitted() -> None:
    runs = _Runs({"skill_id": "narrative-idea", "confidence": CONFIDENCE_THRESHOLD})
    router = SkillRouter(methodology_library=None, provider=runs)
    result = _result(router, "I have an idea")
    assert result.source == "llm"
    assert result.routed is True
    assert result.skill_id == "narrative-idea"


def test_confidence_below_threshold_falls_back_to_keyword() -> None:
    runs = _Runs({"skill_id": "narrative-idea", "confidence": 0.3})
    router = SkillRouter(methodology_library=None, provider=runs)
    result = _result(router, "I have an idea for a plot")
    # Keyword fallback detects the "idea"/"plot" term.
    assert result.source == "keyword"
    assert result.routed is True
    assert result.skill_id == "narrative-idea"
    assert result.confidence == 0.5


def test_low_confidence_with_no_keyword_fails_open() -> None:
    runs = _Runs({"skill_id": "narrative-idea", "confidence": 0.2})
    router = SkillRouter(methodology_library=None, provider=runs)
    result = _result(router, "hello there random text")
    assert result.source == "fallback"
    assert result.routed is False
    assert result.skill_id is None
    assert result.confidence == 0.0


# --------------------------------------------------------------------------- #
# Keyword fallback
# --------------------------------------------------------------------------- #

def test_keyword_fallback_for_character_creation_uses_domain_classifier() -> None:
    router = SkillRouter(methodology_library=None, provider=None)
    result = _result(router, "I want to create a new character")
    assert result.skill_id == "narrative-character-creation"
    assert result.source == "keyword"
    assert result.confidence == 0.5
    assert result.routed is True


def test_keyword_fallback_for_other_transversal_skill() -> None:
    router = SkillRouter(methodology_library=None, provider=None)
    result = _result(router, "give me an outline for my novel")
    assert result.skill_id == "narrative-outline"
    assert result.source == "keyword"


def test_spanish_keyword_fallback() -> None:
    router = SkillRouter(methodology_library=None, provider=None)
    result = _result(router, "quiero un borrador de la escena")
    assert result.skill_id == "narrative-draft"
    assert result.source == "keyword"


# --------------------------------------------------------------------------- #
# Transversal skills discovery
# --------------------------------------------------------------------------- #

def test_available_skills_include_transversal_and_world_activation() -> None:
    library = _Library(_Activation(skill_id="custom-skill", version="1.0"))
    router = SkillRouter(methodology_library=library, provider=None)
    skills = router._available_skills("vibrantes")
    assert set(TRANSVERSAL_SKILLS).issubset(set(skills))
    assert "custom-skill" in skills
    assert library.calls == ["vibrantes"]


def test_available_skills_without_activation_are_just_transversal() -> None:
    router = SkillRouter(methodology_library=_Library(None), provider=None)
    skills = router._available_skills("vibrantes")
    assert set(skills) == set(TRANSVERSAL_SKILLS)


# --------------------------------------------------------------------------- #
# Fail-open
# --------------------------------------------------------------------------- #

def test_fail_open_with_no_provider_and_no_keyword() -> None:
    router = SkillRouter(methodology_library=None, provider=None)
    result = _result(router, "some random gibberish")
    assert result.source == "fallback"
    assert result.routed is False
    assert result.skill_id is None


def test_fail_open_when_provider_raises() -> None:
    router = SkillRouter(methodology_library=None, provider=_FailingRuns())
    result = _result(router, "some random gibberish")
    assert result.source == "fallback"
    assert result.routed is False
    assert result.skill_id is None


def test_fail_open_when_llm_returns_null() -> None:
    runs = _Runs({"skill_id": None, "confidence": 0.0})
    router = SkillRouter(methodology_library=None, provider=runs)
    result = _result(router, "some random gibberish")
    assert result.source == "fallback"
    assert result.routed is False
    assert result.skill_id is None


def test_llm_returning_unknown_skill_falls_back() -> None:
    runs = _Runs({"skill_id": "not-in-candidates", "confidence": 0.95})
    router = SkillRouter(methodology_library=None, provider=runs)
    result = _result(router, "hello there random text")
    assert result.source == "fallback"
    assert result.routed is False
