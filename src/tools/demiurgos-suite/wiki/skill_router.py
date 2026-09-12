"""Skill router: map a user intent to a skill_id.

The router is LLM-first (a single bounded Hermes classification run) and fails
open to the generic assistant. It deliberately never raises on routing: every
path returns a ``SkillRouteResult``, so the conversational surface stays
available even when the provider is absent or the model is uncertain.

All seams (``methodology_library``, ``provider``) are injectable and optional.
With no provider, the LLM step is skipped and routing fails open directly
(degraded mode is pure fail-open; the keyword fallback layer is retired). The
router is a pure decision layer: it performs no state mutation and persists
nothing.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from assistant_activity import HermesActivityRequest
from methodology_library import FOUNDATIONAL_CHARACTER_SKILL_ID, GUIDED_CHARACTER_FLOW

# Audit-derived transversal pool (SR2): the methodology library publishes exactly
# one foundational transversal today — narrative-character-creation (1 recoverable
# of the 20 audited skills; 19 are legacy). The six legacy transversal slugs and
# the keyword fallback layer were retired in PR ② so every routing candidate
# traces to a foundational / companion / flow-slot class (pool traceability).
TRANSVERSAL_SKILLS: frozenset[str] = frozenset({
    FOUNDATIONAL_CHARACTER_SKILL_ID,
})

CONFIDENCE_THRESHOLD = 0.7

# Companion near-tie margin (contract §6, PR ②): when BOTH top-2 classifier
# choices are companions and winner − runner-up confidence is below this
# margin, routing fails open to ``skill_id=None`` (zero injection via
# ``_companion_contract_for``). The rule is vacuous with fewer than two
# companions or a non-companion runner-up.
NEAR_TIE_MARGIN = 0.15

# Companion-world classification cap: each per-line description is collapsed
# (newlines -> spaces) and clipped to this many characters at prompt build, so
# the total classification prompt stays within the bounded token budget (DD2).
_DESCRIPTION_MAX_CHARS = 160


@dataclass(frozen=True)
class SkillRouteResult:
    """Outcome of one routing decision.

    ``skill_id`` is None for a non-guided generic response. ``routed`` is True
    exactly when ``skill_id`` is not None. ``source`` records how the decision
    was reached: ``"llm"`` (above-threshold winner), ``"ambiguous"`` (companion
    near-tie fail-open), or ``"fallback"`` (degraded fail-open).
    """

    skill_id: str | None
    confidence: float
    source: str
    routed: bool


class SkillRouter:
    """Route an author prompt to a skill using LLM-first + fail-open.

    ``methodology_library`` supplies the world's activated skill (via
    ``active_for``); ``provider`` is the Hermes runs adapter used for the LLM
    classification step. ``semantic_provider`` is retained as an injectable
    seam for symmetry with the design; the LLM step itself uses ``provider``.
    Both may be None (fail-open directly to the generic assistant).
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
                activation = self._library.active_for(mundo, GUIDED_CHARACTER_FLOW)
            except Exception:
                activation = None
            if activation is not None and getattr(activation, "skill_id", None):
                skills.add(activation.skill_id)
        return sorted(skills)

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
        # Classifier top-2 output contract (PR ②): the runner-up is optional.
        # Absent or malformed runner-up fields parse to None so the near-tie
        # margin rule stays vacuous — never an error.
        runner_up_id = output.get("runner_up_skill_id")
        if runner_up_id is not None and not isinstance(runner_up_id, str):
            runner_up_id = None
        runner_up_confidence = output.get("runner_up_confidence")
        if runner_up_confidence is not None:
            try:
                runner_up_confidence = float(runner_up_confidence)
            except (TypeError, ValueError):
                runner_up_confidence = None
        return {
            "skill_id": skill_id,
            "confidence": output.get("confidence", 0.0),
            "runner_up_skill_id": runner_up_id,
            "runner_up_confidence": runner_up_confidence,
        }

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

    @staticmethod
    def _clip_description(description: str) -> str:
        """Collapse newlines/whitespace and clip a description to 160 chars."""
        collapsed = " ".join(description.split())
        return collapsed[:_DESCRIPTION_MAX_CHARS]

    def _description_for(self, skill_id: str, version: str | None) -> str | None:
        """Published description for a skill/version, clipped, or None."""
        if not version or self._library is None:
            return None
        try:
            published = self._library.get_published(skill_id, version)
        except Exception:
            return None
        description = getattr(published, "description", None)
        if not description:
            return None
        return self._clip_description(description)

    def _companion_candidates(
        self, mundo: str,
    ) -> tuple[list[tuple[str, str | None]], frozenset[str]] | None:
        """Ordered description-aware candidate set for a companion world.

        Returns ``None`` when the world has no companions, so callers keep the
        byte-identical legacy bare-id prompt path. Otherwise returns
        ``(ordered, companion_ids)``: ``ordered`` is the candidate list
        (companions sorted by ``skill_id`` -> the slot activation skill (if
        any) -> sorted transversals) and ``companion_ids`` is the set of the
        world's companion skill ids — the near-tie margin (SR3) applies only
        when BOTH top-2 classifier choices are in this set. Descriptions come
        from the published record and are clipped to 160 chars; transversals
        (versionless) stay bare ids.
        """
        if self._library is None:
            return None
        try:
            companions = self._library.list_companions(mundo)
        except Exception:
            return None
        if not companions:
            return None
        ordered: list[tuple[str, str | None]] = []
        companion_ids: set[str] = set()
        seen: set[str] = set()
        for comp in sorted(companions, key=lambda c: getattr(c, "skill_id", "") or ""):
            skill_id = getattr(comp, "skill_id", None)
            if not skill_id or skill_id in seen:
                continue
            seen.add(skill_id)
            companion_ids.add(skill_id)
            ordered.append(
                (skill_id, self._description_for(skill_id, getattr(comp, "version", None)))
            )
        try:
            activation = self._library.active_for(mundo, GUIDED_CHARACTER_FLOW)
        except Exception:
            activation = None
        if activation is not None:
            skill_id = getattr(activation, "skill_id", None)
            if skill_id and skill_id not in seen:
                seen.add(skill_id)
                ordered.append(
                    (skill_id, self._description_for(skill_id, getattr(activation, "version", None)))
                )
        for skill_id in sorted(TRANSVERSAL_SKILLS):
            if skill_id not in seen:
                seen.add(skill_id)
                ordered.append((skill_id, None))
        return ordered, frozenset(companion_ids)

    def _build_classification_prompt_with_descriptions(
        self, prompt: str, candidates: list[tuple[str, str | None]],
    ) -> str:
        lines = []
        for skill_id, description in candidates:
            if description:
                lines.append(f"- {skill_id}: {description}")
            else:
                lines.append(f"- {skill_id}")
        candidate_block = "\n".join(lines)
        return (
            f"Classify the user intent into exactly one skill from this list:\n"
            f"{candidate_block}\n"
            "If several skills could match, prefer the world-specific (non-transversal) "
            "skill listed first.\n"
            'Return ONLY a JSON object: {"skill_id": "<id or null>", '
            '"confidence": <0.0-1.0>, "runner_up_skill_id": "<id or null>", '
            '"runner_up_confidence": <0.0-1.0>}.\n'
            'If no skill matches, return {"skill_id": null, "confidence": 0.0, '
            '"runner_up_skill_id": null, "runner_up_confidence": 0.0}.\n'
            f"User intent: {prompt}"
        )

    async def _classify_llm(self, prompt: str, candidates: list[str]) -> dict[str, Any] | None:
        """Single bounded Hermes classification run; None on any failure.

        ``candidates`` is either a list of bare ids (legacy companion-free
        prompt) or a list of ``(skill_id, description)`` tuples (companion
        worlds) — the prompt builder dispatches on the shape.
        """
        if self._provider is None:
            return None
        request_id = uuid.uuid4().hex
        if candidates and isinstance(candidates[0], tuple):
            prompt_text = self._build_classification_prompt_with_descriptions(prompt, candidates)
        else:
            prompt_text = self._build_classification_prompt(prompt, candidates)
        try:
            run_id = await self._provider.start(HermesActivityRequest(
                request_id=request_id,
                prompt=prompt_text,
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

        Order: LLM classification → near-tie margin → threshold check →
        fail-open to generic. ``distilled_state`` is accepted for interface
        symmetry with the memory layer but is not required for routing.

        Companion worlds (≥1 companion) classify over the description-aware
        ordered candidate set (DD2); companion-free worlds keep the byte-identical
        legacy bare-id prompt. When both top-2 classifier choices are companions
        and their confidence gap is below ``NEAR_TIE_MARGIN``, routing fails open
        with ``source="ambiguous"`` (zero injection); below-threshold verdicts and
        degraded mode fail open with ``source="fallback"``.
        """
        companion_candidates = self._companion_candidates(mundo)
        if companion_candidates is not None:
            candidate_pool, companion_ids = companion_candidates
            candidate_ids = [skill_id for skill_id, _ in candidate_pool]
        else:
            candidate_ids = self._available_skills(mundo)
            candidate_pool = candidate_ids
            companion_ids = frozenset()
        if not candidate_ids:
            return SkillRouteResult(None, 0.0, "fallback", False)

        classification = await self._classify_llm(prompt, candidate_pool)
        if classification is not None:
            skill_id = classification.get("skill_id")
            try:
                confidence = float(classification.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            if skill_id in candidate_ids and confidence >= CONFIDENCE_THRESHOLD:
                # Companion near-tie (SR3): both top-2 choices are companions
                # and too close to call → fail open, zero injection. Vacuous
                # when the runner-up is absent/malformed (None) or not in the
                # companion set, or when the winner is not a companion.
                runner_up_id = classification.get("runner_up_skill_id")
                runner_up_conf = classification.get("runner_up_confidence")
                if (runner_up_id in companion_ids
                        and skill_id in companion_ids
                        and runner_up_conf is not None
                        and confidence - runner_up_conf < NEAR_TIE_MARGIN):
                    return SkillRouteResult(None, 0.0, "ambiguous", False)
                return SkillRouteResult(skill_id, confidence, "llm", True)
            # Low confidence or an invalid skill: fail open directly.
            return SkillRouteResult(None, 0.0, "fallback", False)

        # Provider absent or failed: fail open directly (degraded mode = pure
        # fail-open; the retired keyword layer would never inject here).
        return SkillRouteResult(None, 0.0, "fallback", False)
