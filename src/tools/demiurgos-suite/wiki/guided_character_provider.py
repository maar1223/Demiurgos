"""Hermes gateway adapter for the guided-character provider contract."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping

from assistant_activity import (
    CapabilityAssessment,
    HermesActivityRequest,
    HermesRunsActivityAdapter,
)
from guided_character_protocol import (
    Capabilities,
    CancellationToken,
    GuidedRequest,
    MAX_DEADLINE_MS,
    PROTOCOL_VERSION,
)
from demiurgos_language import resolve_ui_language

_MAX_QUESTION_OPTIONS = 5


def _normalize_question(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return None

    text = value.get("text")
    options = value.get("options")
    allow_custom = value.get("allow_custom")
    if not isinstance(text, str) or not text.strip():
        return None
    if options is not None and (
        not isinstance(options, list)
        or len(options) > _MAX_QUESTION_OPTIONS
        or not all(isinstance(option, str) and option.strip() for option in options)
    ):
        return None
    if allow_custom is not None and not isinstance(allow_custom, bool):
        return None

    parts = [text.strip()]
    if options:
        parts.append("Options:\n" + "\n".join(f"- {option.strip()}" for option in options))
    if allow_custom is True:
        parts.append("Custom answers are allowed.")
    return "\n\n".join(parts)


def guided_capabilities(assessment: CapabilityAssessment) -> Capabilities | None:
    """Translate the admitted gateway runs contract into guided capabilities."""
    if not assessment.admitted or assessment.capabilities is None:
        return None
    return Capabilities(PROTOCOL_VERSION, True, True, True, MAX_DEADLINE_MS)


class HermesGuidedProvider:
    """Adapt one Hermes run into a strictly structured guided response."""

    def __init__(self, runs: HermesRunsActivityAdapter) -> None:
        self._runs = runs

    async def probe(self) -> CapabilityAssessment:
        return await self._runs.probe()

    async def invoke(self, request: GuidedRequest, cancellation: CancellationToken) -> object:
        reference = request.reference_context or "(No active ficha reference was provided.)"
        goal_instruction = ""
        if request.relation_goal:
            goal_instruction = (
                f"STRICT TARGET: {request.relation_goal}. "
                "You are creating a brand-new character who stands in the stated "
                "relationship to the reference. Every question and every delta "
                "must be about THIS NEW character and its relationship to the "
                "reference. Never describe, summarize, expand, or develop the "
                "reference character itself; the reference exists ONLY as "
                "relational context for the new character. "
            )
        fast_guidance = (
            "Ask only fundamental questions and assemble a preliminary candidate from the author's input; "
            "mark assumptions clearly. "
            if request.guided_mode == "fast" else ""
        )
        language = "Spanish" if resolve_ui_language() == "es" else "English"
        methodology_context = (
            f"Active methodology snapshot (server-pinned, read-only): {request.methodology}. "
            "Follow this methodology and version for the entire session. "
            if request.methodology else ""
        )
        prompt = (
            "Act as the guided character provider. Return ONLY one JSON object — "
            f"no markdown fences, no code blocks — matching the "
            f"{PROTOCOL_VERSION} response envelope. Use request_id "
            f"{json.dumps(request.request_id)} and session_id {json.dumps(request.session_id)}. "
            "The outcome must be question or delta; never claim author acceptance. "
            "For a question, ask exactly one concise question at a time. Keep it to one or "
            f"two short sentences and provide no more than {_MAX_QUESTION_OPTIONS} useful options. "
            "Do not add long explanations or recite the ficha; use the reference silently. "
            "You have no filesystem, graph, or credential access. Use only the bounded "
            "reference material below; do not expose internal paths or provenance. "
            f"Answer all questions and provide all deltas in the same language as the author's input ({language}). "
            "Keep the response JSON-only, concise, bounded to the supplied context, and never write or claim approval. "
            f"Turn mode: {request.turn_mode}. World: {request.world}. "
            f"Guided mode: {request.guided_mode}; question depth: {request.question_depth}. "
            f"{fast_guidance}"
            f"{methodology_context}"
            f"Verified active ficha reference:\n{reference}\n"
            f"{goal_instruction}"
            f"Author input: {request.author_input}"
        )
        run_id = await self._runs.start(HermesActivityRequest(
            request_id=request.request_id,
            prompt=prompt,
            session_id=request.session_id,
        ))
        try:
            output: object = None
            deltas: list[str] = []
            async for event in self._runs.events(run_id):
                if cancellation.cancelled:
                    raise asyncio.CancelledError
                if not isinstance(event, Mapping) or event.get("run_id") != run_id:
                    continue
                if event.get("event") == "message.delta" and isinstance(event.get("delta"), str):
                    deltas.append(event["delta"])
                elif event.get("event") == "run.completed":
                    output = event.get("output")
            if deltas:
                output = "".join(deltas)
            if output is None:
                status = await self._runs.status(run_id)
                if status.get("status") == "completed":
                    output = status.get("output")
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
                    pass
            if isinstance(output, Mapping):
                result = dict(output)
                if "question" in result and isinstance(result["question"], Mapping):
                    normalized_question = _normalize_question(result["question"])
                    if normalized_question is not None:
                        result["question"] = normalized_question
                if "protocol_version" not in result and result.get("version") == PROTOCOL_VERSION:
                    result["protocol_version"] = result["version"]
                elif (
                    "protocol_version" not in result
                    and "version" not in result
                    and result.get("request_id") == request.request_id
                    and result.get("session_id") == request.session_id
                    and (
                        (
                            result.get("outcome") == "question"
                            and isinstance(result.get("question"), str)
                            and bool(result["question"].strip())
                        )
                        or (
                            result.get("outcome") == "delta"
                            and isinstance(result.get("delta"), Mapping)
                        )
                    )
                ):
                    result["protocol_version"] = PROTOCOL_VERSION
                result.setdefault("provider_run_id", run_id)
                result.setdefault("provenance", [f"hermes:run:{run_id}"])
                return result
            return output
        finally:
            if cancellation.cancelled:
                await self._runs.cancel(run_id)
