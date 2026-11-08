"""Hermes gateway adapter for the guided-character provider contract."""

from __future__ import annotations

import asyncio
import json
import logging
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
from demiurgos_language import resolve_domain_language

logger = logging.getLogger(__name__)

_MAX_QUESTION_OPTIONS = 3


def first_pending_question(text: str) -> str:
    """Surface at most one pending question (REQ-GN-3 server enforcement).

    A pending question is a ``?``-terminated sentence. When the text contains
    more than one such sentence, only the first is kept and the remainder is
    dropped; a single question (or none) leaves the text unchanged. The
    question end is a ``?`` followed by end-of-string, whitespace, a closing
    quote/bracket, or sentence punctuation, so markers like ``?!"`` stay
    inside the first question.
    """
    if not text:
        return text
    ends = [
        index + 1
        for index, char in enumerate(text)
        if char == "?"
        and (
            index + 1 == len(text)
            or text[index + 1].isspace()
            or text[index + 1] in "!.\"'”’)]}"
        )
    ]
    if len(ends) <= 1:
        return text
    return text[: ends[0]].rstrip()


def _normalize_question(value: object) -> str | None:
    if isinstance(value, str):
        return first_pending_question(value)
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

    # One-question-per-turn server enforcement (REQ-GN-3): even when the
    # provider returns a structured question with several ``?``-terminated
    # sentences, only the first pending question is surfaced; options are
    # appended after the collapsed question text.
    text = first_pending_question(text.strip())
    parts = [text]
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


def repair_truncated_json(text: str) -> str | None:
    """Append the closers a clean-EOF truncation dropped.

    The provider sometimes ends the stream after the last field but before the
    closing brace (measured 2026-11-08: three ``{`` against two ``}``). Only
    STRUCTURAL closers are added — a value cut mid-string, an unbalanced closer
    or an escaping state returns ``None`` — and the caller still parses the
    result strictly, so a truncated value can never be "repaired" into
    something valid.
    """
    in_string = False
    escaped = False
    closers: list[str] = []
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            closers.append("}")
        elif char == "[":
            closers.append("]")
        elif char in "}]":
            if closers and closers[-1] == char:
                closers.pop()
            else:
                return None
    if in_string or escaped or not closers:
        return None
    return text + "".join(reversed(closers))


class HermesGuidedProvider:
    """Adapt one Hermes run into a strictly structured guided response."""

    def __init__(self, runs: HermesRunsActivityAdapter) -> None:
        self._runs = runs

    async def probe(self) -> CapabilityAssessment:
        return await self._runs.probe()

    async def invoke(
        self,
        request: GuidedRequest,
        cancellation: CancellationToken,
        *,
        compiled_contract_markdown: str | None = None,
        convergence_specimen_markdown: str | None = None,
    ) -> object:
        reference = request.reference_context or "(No active ficha reference was provided.)"
        world_lore = request.world_context or "(No matching world lore was found for this turn.)"
        known_state = request.known_state or "(Nothing collected yet.)"
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
        language = "Spanish" if resolve_domain_language("conversation") == "es" else "English"
        # Decision B: the narrative level of a character must be explicit, never
        # a silent 1º fallback. The server asks the provider to settle it early.
        level_instruction = (
            "Narrative level: if 'nivel' or 'rol_narrativo' is not in Known so far, "
            "settle it before asking for deeper details — ask whether this character "
            "is 1º principal, 2º secundario or 3º relleno, and record the answer under "
            "'nivel'. The level decides how much detail the sheet needs; never assume "
            "it silently. "
            if request.flow_entity_type == "personaje" else ""
        )
        if compiled_contract_markdown:
            methodology_context = (
                "[Active methodology contract (server-pinned, read-only):\n"
                f"{compiled_contract_markdown}]\n"
                "Follow this methodology for the entire session. "
            )
        else:
            methodology_context = (
                f"Active methodology snapshot (server-pinned, read-only): {request.methodology}. "
                "Follow this methodology and version for the entire session. "
                if request.methodology else ""
            )
        if convergence_specimen_markdown:
            # The convergence specimen block (D7) is appended AFTER the contract
            # block, outside the ≤1000-token projection (R12/R13): the block is
            # already fully built and bounded by the serving seam.
            methodology_context = f"{methodology_context}{convergence_specimen_markdown}"
        prompt = (
            "Act as the guided co-creation provider. Return ONLY one JSON object "
            f"matching the {PROTOCOL_VERSION} response envelope — do not wrap the "
            "JSON in markdown fences or code blocks. "
            "The outcome must be question or delta; never claim author acceptance. "
            "For a question, return the fields question, synthesis, observations, options "
            "and allow_custom. "
            "A delta envelope carries EXACTLY request_id, session_id, outcome, synthesis, "
            "observations and delta; it never carries question, options or allow_custom. "
            "'delta' is a flat object of candidate fields (for example nombre, deseo, "
            "oficio) — never a rendered document, never the finished ficha, and never "
            "markdown blocks: the server renders the sheet from your fields. "
            "Always close every JSON object and array you open. "
            "This is a conversation, not an interrogation. Before asking, write the "
            "'synthesis' field: at most 3 short sentences (~60 words, under 350 "
            "characters) that reflect what you have already understood, including any "
            "correction the author just made; never one long paragraph. Then ask exactly "
            "ONE open, focused question. The 'question' field is ONLY the question: one "
            "sentence ending with '?'; never repeat the synthesis inside the question. "
            "The JSON object itself must not be wrapped in markdown, but the synthesis "
            "and question values MAY contain GitHub-flavored Markdown (**bold** for names "
            "and key terms, - bullets only for an inventory); the chat renders it. "
            "When it genuinely helps, include your own reading or proposal inside the "
            "synthesis, explicitly labeled as a proposal (never as canon). "
            "Options are optional and a LAST RESORT: include at most "
            f"{_MAX_QUESTION_OPTIONS}, and only when the author says they do not know, asks "
            "for help, or the choice is genuinely discrete. Never make options the only "
            "way to answer; always leave room for free text. "
            "Put the non-canon facts you extracted from this turn in 'observations' "
            "(an object of concise keys and values) so the session keeps what was "
            "collected instead of asking again. "
            "Never re-ask something already present in 'Known so far'; if the author "
            "corrected a value, use the corrected value from now on. "
            "You have no filesystem, graph, or credential access. Use only the bounded "
            "reference, world lore and known state below; do not expose internal paths "
            "or provenance. Treat the world lore as verified canon: never ask the author "
            "to explain it and never invent details beyond it; if something is not "
            "present, say so. "
            f"Answer all questions and provide all deltas in the same language as the author's input ({language}). "
            "Keep the response JSON-only, concise, bounded to the supplied context, and never write or claim approval. "
            f"Turn mode: {request.turn_mode}. World: {request.world}. "
            f"Guided mode: {request.guided_mode}; question depth: {request.question_depth}. "
            f"{fast_guidance}"
            f"{level_instruction}"
            f"{methodology_context}"
            f"Known so far (never ask these again):\n{known_state}\n"
            f"World lore (verified, read-only):\n{world_lore}\n"
            f"Verified active ficha reference:\n{reference}\n"
            f"{goal_instruction}"
            f"Author input: {request.author_input}\n"
            # Volatile ids go LAST so the whole instruction block stays a stable
            # prefix (prompt cache); they used to sit in the second sentence.
            "Echo request_id "
            f"{json.dumps(request.request_id)} and session_id "
            f"{json.dumps(request.session_id)} in the JSON object."
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
                    repaired = repair_truncated_json(text)
                    if repaired is not None:
                        try:
                            output = json.loads(repaired)
                        except (TypeError, ValueError):
                            output = None
                    if output is None:
                        # Bounded diagnostics: what came back and how it broke.
                        logger.warning(
                            "guided provider returned unparseable output "
                            "(len=%d head=%r tail=%r)",
                            len(text), text[:200], text[-200:],
                        )
            if isinstance(output, Mapping):
                result = dict(output)
                if "question" in result and result["question"] is not None:
                    # Server-side one-question-per-turn enforcement (REQ-GN-3):
                    # plain-string AND structured questions are normalized here
                    # so at most one pending question ever surfaces in a turn.
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
