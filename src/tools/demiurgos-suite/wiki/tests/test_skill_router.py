"""Unit tests for the skill router (LLM-first + fail-open)."""

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
    """Minimal MethodologyLibrary stub exposing active_for, list_companions,
    and get_published (the subset the skill router reads)."""

    def __init__(
        self, activation: Any = None, companions: list[Any] | None = None,
        published: dict[tuple[str, str], Any] | None = None,
    ) -> None:
        self._activation = activation
        self._companions = list(companions or [])
        self._published = dict(published or {})
        self.calls: list[str] = []

    def active_for(self, mundo: str, flow_type: str | None = None):
        self.calls.append(mundo)
        return self._activation

    def list_companions(self, mundo: str):
        self.calls.append(f"list:{mundo}")
        return list(self._companions)

    def get_published(self, skill_id: str, version: str):
        self.calls.append(f"get:{skill_id}:{version}")
        return self._published.get((skill_id, version))


@dataclass(frozen=True)
class _Activation:
    skill_id: str
    version: str


@dataclass(frozen=True)
class _Published:
    description: str
    name: str = ""
    trigger: str | None = None


def _result(router: SkillRouter, prompt: str, mundo: str = "vibrantes") -> SkillRouteResult:
    return asyncio.run(router.route(prompt, mundo))


# --------------------------------------------------------------------------- #
# LLM routing
# --------------------------------------------------------------------------- #

def test_llm_routing_returns_skill_when_above_threshold() -> None:
    runs = _Runs({"skill_id": "narrative-character-creation", "confidence": 0.9})
    router = SkillRouter(methodology_library=None, provider=runs)
    result = _result(router, "Describe the kingdom of Rhyz")
    assert result.skill_id == "narrative-character-creation"
    assert result.confidence == 0.9
    assert result.source == "llm"
    assert result.routed is True
    # Candidates must be listed in the classification prompt.
    assert "narrative-character-creation" in runs.prompts[0]


def test_llm_prompt_lists_only_candidates_and_asks_for_strict_json() -> None:
    runs = _Runs({"skill_id": "narrative-character-creation", "confidence": 0.95})
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
    runs = _Runs({"skill_id": "narrative-character-creation", "confidence": CONFIDENCE_THRESHOLD})
    router = SkillRouter(methodology_library=None, provider=runs)
    result = _result(router, "I have an idea")
    assert result.source == "llm"
    assert result.routed is True
    assert result.skill_id == "narrative-character-creation"


def test_confidence_below_threshold_fails_open() -> None:
    runs = _Runs({"skill_id": "narrative-character-creation", "confidence": 0.3})
    router = SkillRouter(methodology_library=None, provider=runs)
    result = _result(router, "I have an idea for a plot")
    # Keyword layer retired: a below-threshold verdict fails open directly.
    assert result.source == "fallback"
    assert result.routed is False
    assert result.skill_id is None
    assert result.confidence == 0.0


def test_low_confidence_with_no_keyword_fails_open() -> None:
    runs = _Runs({"skill_id": "narrative-character-creation", "confidence": 0.2})
    router = SkillRouter(methodology_library=None, provider=runs)
    result = _result(router, "hello there random text")
    assert result.source == "fallback"
    assert result.routed is False
    assert result.skill_id is None
    assert result.confidence == 0.0


# --------------------------------------------------------------------------- #
# Fail-open (degraded mode is pure fail-open; keyword layer retired)
# --------------------------------------------------------------------------- #

def test_provider_absent_with_character_intent_fails_open() -> None:
    router = SkillRouter(methodology_library=None, provider=None)
    result = _result(router, "I want to create a new character")
    assert result.skill_id is None
    assert result.routed is False
    assert result.source == "fallback"


def test_provider_absent_with_other_transversal_intent_fails_open() -> None:
    router = SkillRouter(methodology_library=None, provider=None)
    result = _result(router, "give me an outline for my novel")
    assert result.skill_id is None
    assert result.routed is False
    assert result.source == "fallback"


def test_provider_absent_spanish_intent_fails_open() -> None:
    router = SkillRouter(methodology_library=None, provider=None)
    result = _result(router, "quiero un borrador de la escena")
    assert result.skill_id is None
    assert result.routed is False
    assert result.source == "fallback"


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


def test_transversal_pool_is_audit_derived() -> None:
    """The transversal pool is exactly the server-seeded foundational skills."""
    assert set(TRANSVERSAL_SKILLS) == {
        "narrative-character-creation",
        "narrative-system-creation",
    }


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


# --------------------------------------------------------------------------- #
# Companion worlds (WU3): description-aware classification over
# TRANSVERSAL ∪ list_companions with deterministic ordering (DD2).
# --------------------------------------------------------------------------- #

def test_companion_candidates_order_and_descriptions() -> None:
    library = _Library(
        companions=[
            _Activation(skill_id="alpha", version="1.0"),
            _Activation(skill_id="omega", version="2.0"),
        ],
        published={
            ("alpha", "1.0"): _Published(description="Alpha methodology"),
            ("omega", "2.0"): _Published(description="Omega methodology"),
        },
    )
    runs = _Runs({"skill_id": "alpha", "confidence": 0.9})
    router = SkillRouter(methodology_library=library, provider=runs)
    _result(router, "do the alpha thing")
    prompt = runs.prompts[0]
    # Deterministic order: companions sorted by skill_id first, then the slot
    # skill (none here), then sorted transversals.
    assert prompt.index("- alpha: Alpha methodology") < prompt.index("- omega: Omega methodology")
    # Descriptions present for companions; transversals stay bare ids.
    assert "- alpha: Alpha methodology" in prompt
    assert "- omega: Omega methodology" in prompt
    assert "- narrative-character-creation" in prompt
    # World-specific-over-transversal tie instruction is present.
    assert "prefer the world-specific (non-transversal) skill listed first" in prompt
    # The world's companions are read from the library.
    assert "list:vibrantes" in library.calls


def test_companion_free_world_prompt_byte_identical() -> None:
    """A world with a library but ZERO companions keeps the legacy bare-id
    comma-separated prompt byte-for-byte (spec R-CLASSIFY invariance)."""
    library = _Library(companions=[], published={})
    runs = _Runs({"skill_id": "narrative-character-creation", "confidence": 0.95})
    router = SkillRouter(methodology_library=library, provider=runs)
    _result(router, "write a scene")
    legacy = router._build_classification_prompt(
        "write a scene", router._available_skills("vibrantes")
    )
    assert runs.prompts[0] == legacy
    # The companion prompt format (bullets / tie sentence) is absent.
    assert "prefer the world-specific" not in runs.prompts[0]
    assert "- narrative-character-creation" not in runs.prompts[0]


def test_candidate_label_prefers_the_authored_trigger() -> None:
    """The classifier sees the same short label the skills index renders."""
    library = _Library(
        companions=[_Activation(skill_id="alpha", version="1.0")],
        published={
            ("alpha", "1.0"): _Published(
                description="Metodología fundacional para co-crear un sistema "
                            "nuevo, agnóstica al mundo.",
                trigger="Co-crea sistemas: origen, qué exige y límite.",
            ),
        },
    )
    runs = _Runs({"skill_id": "alpha", "confidence": 0.9})
    router = SkillRouter(methodology_library=library, provider=runs)
    _result(router, "quiero crear un sistema")
    prompt = runs.prompts[0]
    assert "- alpha: Co-crea sistemas: origen, qué exige y límite." in prompt
    assert "Metodología fundacional" not in prompt


def test_description_clipped_at_160() -> None:
    long = "x" * 500
    library = _Library(
        companions=[_Activation(skill_id="alpha", version="1.0")],
        published={("alpha", "1.0"): _Published(description=long)},
    )
    runs = _Runs({"skill_id": "alpha", "confidence": 0.9})
    router = SkillRouter(methodology_library=library, provider=runs)
    _result(router, "hello")
    prompt = runs.prompts[0]
    line = next(l for l in prompt.splitlines() if l.startswith("- alpha:"))
    desc = line[len("- alpha: "):]
    assert desc == "x" * 160


def test_gateway_down_companions_unreachable() -> None:
    """Degraded mode is pure fail-open: with the classification gateway down, a
    companion is NEVER routed and the turn receives zero skill injection."""
    library = _Library(
        companions=[_Activation(skill_id="alpha", version="1.0")],
        published={("alpha", "1.0"): _Published(description="Alpha methodology")},
    )
    router = SkillRouter(methodology_library=library, provider=_FailingRuns())
    result = _result(router, "give me an outline for my novel")
    assert result.skill_id is None
    assert result.routed is False
    assert result.skill_id != "alpha"


def test_tie_candidate_order_companions_first() -> None:
    library = _Library(
        companions=[_Activation(skill_id="alpha", version="1.0")],
        published={("alpha", "1.0"): _Published(description="Alpha methodology")},
    )
    runs = _Runs({"skill_id": "alpha", "confidence": 0.7})
    router = SkillRouter(methodology_library=library, provider=runs)
    result = _result(router, "alpha thing")
    prompt = runs.prompts[0]
    assert result.skill_id == "alpha"
    assert result.source == "llm"
    # The companion is listed before every transversal in the prompt.
    alpha_idx = prompt.index("- alpha: Alpha methodology")
    for skill in TRANSVERSAL_SKILLS:
        assert alpha_idx < prompt.index(f"- {skill}")
