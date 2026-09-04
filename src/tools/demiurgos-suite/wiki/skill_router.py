"""Skill router: map a user intent to a skill_id.

The router is LLM-first (a single bounded Hermes classification run) with a
deterministic keyword fallback and a final fail-open to the generic assistant.
It deliberately never raises on routing: every path returns a
``SkillRouteResult``, so the conversational surface stays available even when
the provider is absent or the model is uncertain.

All seams (``methodology_library``, ``provider``) are injectable and optional.
With no provider, the LLM step is skipped and routing degrades to keyword or
fallback (fail-open). The router is a pure decision layer: it performs no
state mutation and persists nothing.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from assistant_activity import HermesActivityRequest
from guided_character_domain import route_new_character_intent
from methodology_library import SKILL_MADRE_ID

TRANSVERSAL_SKILLS: frozenset[str] = frozenset({
    SKILL_MADRE_ID,
    "narrative-world-spec",
    "narrative-idea",
    "narrative-outline",
    "narrative-draft",
    "narrative-revise",
    "narrative-explore",
})

CONFIDENCE_THRESHOLD = 0.7

# Deterministic keyword fallback: map simple terms to the transversal skills.
# ``narrative-character-creation`` is handled by the domain classifier
# (route_new_character_intent) which understands character intent precisely;
# the rest use lightweight substring maps.
_KEYWORD_SKILLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("narrative-world-spec", ("world", "mundo", "setting", "escenario", "realm", "reino")),
    ("narrative-idea", ("idea", "concept", "concepto", "premise", "premisa", "inspiration", "inspiración")),
    ("narrative-outline", ("outline", "esquema", "structure", "estructura", "plot", "argumento")),
    ("narrative-draft", ("draft", "borrador", "write", "escribir", "prose", "escena")),
    ("narrative-revise", ("revise", "revisar", "rewrite", "reescribir", "edit", "editar")),
    ("narrative-explore", ("explore", "explorar", "brainstorm", "lluvia de ideas", "develop", "desarrollar")),
)

_KEYWORD_CONFIDENCE = 0.5


@dataclass(frozen=True)
class SkillRouteResult:
    """Outcome of one routing decision.

    ``skill_id`` is None for a non-guided generic response. ``routed`` is True
    exactly when ``skill_id`` is not None. ``source`` records how the decision
    was reached: ``"llm"``, ``"keyword"`` or ``"fallback"``.
    """

    skill_id: str | None
    confidence: float
    source: str
    routed: bool


class SkillRouter:
    """Route an author prompt to a skill using LLM-first + keyword fallback.

    ``methodology_library`` supplies the world's activated skill (via
    ``active_for``); ``provider`` is the Hermes runs adapter used for the LLM
    classification step. ``semantic_provider`` is retained as an injectable
    seam for symmetry with the design; the LLM step itself uses ``provider``.
    Both may be None (fail-open to keyword/fallback).
    """

    def __init__(
        self,
        methodology_library: Any = None,
        semantic_provider: Any = None,
        provider: Any = None,
    ) -> None:
        self._library = methodology_library
        self._semantic_provider = semantic_provider
        self._provider = provider

    def _available_skills(self, mundo: str) -> list[str]:
        """Transversal skills unioned with the world's activated skill."""
        skills = set(TRANSVERSAL_SKILLS)
        if self._library is not None:
            try:
                activation = self._library.active_for(mundo)
            except Exception:
                activation = None
            if activation is not None and getattr(activation, "skill_id", None):
                skills.add(activation.skill_id)
        return sorted(skills)

    def _route_keyword(self, prompt: str) -> SkillRouteResult:
        """Deterministic keyword fallback. Never raises; never returns None."""
        # Character creation is classified by the domain's intent classifier,
        # which understands new-character vs edit-character precisely.
        try:
            turn = route_new_character_intent(prompt)
        except Exception:
            turn = None
        if turn is not None and getattr(turn, "is_new_character", False):
            return SkillRouteResult(
                SKILL_MADRE_ID, _KEYWORD_CONFIDENCE, "keyword", True,
            )
        lowered = prompt.casefold()
        for skill_id, keywords in _KEYWORD_SKILLS:
            if any(keyword in lowered for keyword in keywords):
                return SkillRouteResult(
                    skill_id, _KEYWORD_CONFIDENCE, "keyword", True,
                )
        return SkillRouteResult(None, 0.0, "fallback", False)

    async def _collect_output(self, run_id: str) -> object:
        output: object = None
        deltas: list[str] = []
        try:
            async for event in self._provider.events(run_id):
                if not isinstance(event, Mapping) or event.get("run_id") != run_id:
                    continue
                if event.get("event") == "message.delta" and isinstance(event.get("delta"), str):
                    deltas.append(event["delta"])
                elif event.get("event") == "run.completed":
                    output = event.get("output")
            if deltas:
                output = "".join(deltas)
        except Exception:
            output = None
        if output is None:
            try:
                status = await self._provider.status(run_id)
            except Exception:
                status = None
            if isinstance(status, Mapping) and status.get("status") == "completed":
                output = status.get("output")
        return output

    def _parse_classification(self, output: object) -> dict[str, Any] | None:
        if isinstance(output, str):
            text = output.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                if lines and lines[0].strip().startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
            try:
                output = json.loads(text)
            except (TypeError, ValueError):
                return None
        if not isinstance(output, Mapping):
            return None
        skill_id = output.get("skill_id")
        if skill_id is not None and not isinstance(skill_id, str):
            return None
        return {"skill_id": skill_id, "confidence": output.get("confidence", 0.0)}

    def _build_classification_prompt(self, prompt: str, candidates: list[str]) -> str:
        candidate_list = ", ".join(candidates)
        return (
            f"Classify the user intent into exactly one skill from this list: "
            f"[{candidate_list}]. "
            'Return ONLY a JSON object: {"skill_id": "<id or null>", '
            '"confidence": <0.0-1.0>}. '
            'If no skill matches, return {"skill_id": null, "confidence": 0.0}. '
            f"User intent: {prompt}"
        )

    async def _classify_llm(self, prompt: str, candidates: list[str]) -> dict[str, Any] | None:
        """Single bounded Hermes classification run; None on any failure."""
        if self._provider is None:
            return None
        request_id = uuid.uuid4().hex
        try:
            run_id = await self._provider.start(HermesActivityRequest(
                request_id=request_id,
                prompt=self._build_classification_prompt(prompt, candidates),
                session_id="",
            ))
            output = await self._collect_output(run_id)
        except Exception:
            return None
        return self._parse_classification(output)

    async def route(
        self,
        prompt: str,
        mundo: str,
        *,
        distilled_state: str | None = None,
    ) -> SkillRouteResult:
        """Route ``prompt`` for world ``mundo`` to a skill.

        Order: LLM classification → threshold check → keyword fallback →
        fail-open to generic. ``distilled_state`` is accepted for interface
        symmetry with the memory layer but is not required for routing.
        """
        candidates = self._available_skills(mundo)
        if not candidates:
            return SkillRouteResult(None, 0.0, "fallback", False)

        classification = await self._classify_llm(prompt, candidates)
        if classification is not None:
            skill_id = classification.get("skill_id")
            try:
                confidence = float(classification.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            if skill_id in candidates and confidence >= CONFIDENCE_THRESHOLD:
                return SkillRouteResult(skill_id, confidence, "llm", True)
            # Low confidence or an invalid skill: fall through to keyword.
            return self._route_keyword(prompt)

        # Provider absent or failed: deterministic fallback (fail-open).
        return self._route_keyword(prompt)
