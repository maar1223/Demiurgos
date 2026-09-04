"""Hermes gateway adapter for the Skill Madre co-creation provider contract.

The Skill Madre is a kernel-owned protected provider: its prompt is a hardcoded
kernel artifact (installed with Demiurgos, release-only updates, never a
library package). Hermes proposes/redacts only inside the ``co-creation-v1``
envelope; this adapter enforces the Hermes boundary (REQ-CC-7) at the provider
layer by rejecting authority keys in its own output before returning, and the
protocol layer re-checks them on every parsed envelope.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping

from assistant_activity import (
    CapabilityAssessment,
    HermesActivityRequest,
    HermesRunsActivityAdapter,
)
from co_creation_protocol import (
    CancellationToken,
    Capabilities,
    CoCreationRequest,
    MAX_DEADLINE_MS,
    PROTOCOL_VERSION,
    reject_authority_keys,
)
from demiurgos_language import resolve_ui_language

_MAX_QUESTION_OPTIONS = 5

# Skill Madre method rules (REQ-CC-4), embedded in the kernel prompt.
_METHOD_RULES = (
    "Method rules for this session: purpose before name; clarify the Taller and "
    "scope early; ask whether the skill is mundo-specific or transversal at the "
    "Alcance milestone; establish the main flow before branches; a branch is a "
    "conditional path inside the skill, not a separate skill (rama vs skill-distinct)."
)
_MILESTONE_LIST = (
    "Milestone progress: proposito -> alcance -> flujo_principal -> ramas_reglas "
    "-> borrador_listo -> revision_publicacion."
)


def _normalize_question(value: object) -> str | None:
    """Flatten a structured question mapping into bounded question text."""
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


def co_creation_capabilities(assessment: CapabilityAssessment) -> Capabilities | None:
    """Translate the admitted gateway runs contract into co-creation capabilities."""
    if not assessment.admitted or assessment.capabilities is None:
        return None
    return Capabilities(PROTOCOL_VERSION, True, True, True, MAX_DEADLINE_MS)


class HermesCoCreationProvider:
    """Adapt one Hermes run into a strictly structured co-creation response."""

    def __init__(self, runs: HermesRunsActivityAdapter) -> None:
        self._runs = runs

    async def probe(self) -> CapabilityAssessment:
        return await self._runs.probe()

    async def invoke(
        self,
        request: CoCreationRequest,
        cancellation: CancellationToken,
    ) -> object:
        language = "Spanish" if resolve_ui_language() == "es" else "English"
        world_context = request.world or "(transversal — no world binding)"
        milestone_context = (
            f"Current milestone: {request.milestone}." if request.milestone else "Session start."
        )
        prompt = (
            "Act as the Skill Madre, the kernel-owned co-creation provider. Return ONLY one "
            f"JSON object — no markdown fences, no code blocks — matching the {PROTOCOL_VERSION} "
            f"response envelope. Use request_id {json.dumps(request.request_id)} and session_id "
            f"{json.dumps(request.session_id)}. The outcome must be question or milestone_delta; "
            "never claim author approval. You propose and redact only: you never write, grant "
            "permissions, skip gates, or emit authority keys (target, digest, revision, authority, "
            "reference, acceptance, accepted_canon, authorization) at any nesting level. "
            f"{_METHOD_RULES} {_MILESTONE_LIST} "
            "For a question, ask exactly one concise question at a time. Keep it to one or two "
            "short sentences and provide no more than 5 useful options. Report milestone progress "
            "in every envelope. "
            "You have no filesystem, graph, or credential access. Use only the bounded session "
            "context below; do not expose internal paths or provenance. Answer all questions in "
            f"the same language as the author's input ({language}). "
            "Keep the response JSON-only, concise, bounded to the supplied context, and never "
            "write or claim approval. "
            f"{milestone_context} World: {world_context}. "
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
                    structured = result["question"]
                    normalized_question = _normalize_question(structured)
                    if normalized_question is not None:
                        result["question"] = normalized_question
                        structured_options = structured.get("options")
                        if isinstance(structured_options, list) and structured_options:
                            result.setdefault("options", structured_options)
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
                            result.get("outcome") == "milestone_delta"
                            and isinstance(result.get("milestone"), str)
                            and bool(result["milestone"].strip())
                        )
                    )
                ):
                    result["protocol_version"] = PROTOCOL_VERSION
                result.setdefault("provider_run_id", run_id)
                result.setdefault("provenance", [f"hermes:run:{run_id}"])
                if reject_authority_keys(result):
                    # Fail closed at the provider layer: never return an envelope
                    # that claims authority. The protocol re-checks every parsed
                    # envelope, so this is a defensive second gate.
                    return {
                        "protocol_version": PROTOCOL_VERSION,
                        "request_id": request.request_id,
                        "session_id": request.session_id,
                        "outcome": "error",
                        "error": {
                            "code": "invalid_envelope",
                            "message": "Authority keys rejected in provider output.",
                            "retryable": True,
                        },
                    }
                return result
            return output
        finally:
            if cancellation.cancelled:
                await self._runs.cancel(run_id)