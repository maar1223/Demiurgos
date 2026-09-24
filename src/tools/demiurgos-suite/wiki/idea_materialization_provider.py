"""Hermes gateway adapter for the idea-materialization provider contract.

The provider is pure transport plus prompt assembly: it builds a bounded,
JSON-only prompt from the idea/target/candidates, starts exactly one Hermes
run, streams ``message.delta`` events, strips markdown fences, parses JSON,
and stamps the run identity (``provider_run_id``/``provenance``).

It performs NO writes and NO validation. Strict envelope validation lives
server-side in ``MaterializationResponse.from_provider`` (fail closed,
R-IM-09): malformed or non-envelope output is passed through unchanged so
that validator rejects it — the provider never decides what is valid.

Mirrors ``HermesGuidedProvider`` (guided_character_provider.py:61-202;
fence-strip precedent :159-165).
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
from demiurgos_language import resolve_ui_language
from idea_materialization_protocol import (
    CancellationToken,
    MAX_IDEA_BODY_CHARS,
    MAX_TITLE_CHARS,
    MaterializationRequest,
    PROTOCOL_VERSION,
)


def _bounded(value: str, limit: int) -> str:
    """Deterministic truncation for prompt inputs (AD1 bounds).

    The idea body is a seed, not the product: it is truncated to
    ``MAX_IDEA_BODY_CHARS`` before prompting; the title is bounded by
    ``MAX_TITLE_CHARS`` the same way.
    """
    if len(value) <= limit:
        return value
    return value[:limit].rstrip()


def _strip_fences(text: str) -> str:
    """Remove a leading ``` fence and its closing marker, if present.

    Mirrors the fence-strip precedent in ``HermesGuidedProvider``
    (guided_character_provider.py:159-165): only a fence that actually opens
    the output is stripped.
    """
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_output(text: str) -> object:
    """Fence-strip then ``json.loads`` the provider text.

    When parsing fails the ORIGINAL text is returned unchanged so the
    server-side validator fails it closed (R-IM-09 malformed scenario) — the
    provider never fabricates an envelope.
    """
    stripped = _strip_fences(text.strip())
    try:
        return json.loads(stripped)
    except (TypeError, ValueError):
        return text


def _build_prompt(request: MaterializationRequest) -> str:
    """Assemble the bounded, JSON-only provider prompt.

    Includes the idea (``{slug,title,type,tags,body}`` with the body truncated
    to ``MAX_IDEA_BODY_CHARS``), the target (``{world,section,folder,
    title_hint}``), the already-bounded candidate entity list, the required
    response envelope, and the UI language.
    """
    language = "Spanish" if resolve_ui_language() == "es" else "English"
    idea_body = _bounded(request.idea_body, MAX_IDEA_BODY_CHARS)
    title = _bounded(request.title, MAX_TITLE_CHARS)
    tags = ", ".join(request.tags) if request.tags else "(none)"
    idea = (
        f"- slug: {request.slug}\n"
        f"- title: {title}\n"
        f"- type: {request.idea_type}\n"
        f"- tags: {tags}\n"
        f"- body: {idea_body}"
    )
    target = (
        f"- world: {request.world}\n"
        f"- section: {request.section}\n"
        f"- folder: {request.folder or '(section root)'}\n"
        f"- title hint: {request.title_hint or '(none)'}"
    )
    candidates = json.dumps(list(request.candidates), ensure_ascii=False)
    envelope = (
        "{\n"
        f'  "protocol_version": "{PROTOCOL_VERSION}",\n'
        '  "request_id": "<must match the request>",\n'
        '  "session_id": "<must match the request>",\n'
        '  "outcome": "delta",\n'
        '  "delta": {\n'
        '    "body": "<markdown narrative text, no frontmatter>",\n'
        '    "relations": [ { "target_id": "<existing canonical id>", "rel_type": "<relation type>" } ]\n'
        "  }\n"
        "}"
    )
    return (
        "Act as the world-materialization provider. Return ONLY one JSON object — "
        "no markdown fences, no code blocks — matching the "
        f"{PROTOCOL_VERSION} response envelope. Use request_id "
        f"{json.dumps(request.request_id)} and session_id {json.dumps(request.session_id)}. "
        "The outcome must be delta; never claim author acceptance. "
        "You are turning a captured idea into a world ficha: write the ficha body "
        "in markdown and propose relations to EXISTING entities only. "
        "You have no filesystem, graph, or credential access. Use only the bounded "
        "material below; do not expose internal paths or provenance. "
        "Never write frontmatter, paths, or new entity names; the server owns the "
        "frontmatter and the ficha id. "
        f"Write the body in the same language as the author's input ({language}). "
        "Keep the response JSON-only, concise, bounded to the supplied context, and "
        "never write or claim approval.\n"
        "Target:\n"
        f"{target}\n"
        "Idea to materialize:\n"
        f"{idea}\n"
        "Existing candidate entities (target_id MUST be reused verbatim from this "
        "list; use [] when no candidate fits):\n"
        f"{candidates}\n"
        "Required response envelope (exactly this shape, no extra fields):\n"
        f"{envelope}"
    )


class HermesMaterializationProvider:
    """Adapt one Hermes run into a strictly structured materialization envelope.

    The provider is the only external read-only call in the materialization
    path: it starts a run and reads its events, performing no writes and no
    validation (the server-side ``from_provider`` owns fail-closed validation).
    """

    def __init__(self, activity_adapter: HermesRunsActivityAdapter) -> None:
        self._runs = activity_adapter

    async def probe(self) -> CapabilityAssessment:
        return await self._runs.probe()

    async def invoke(
        self,
        request: MaterializationRequest,
        cancellation: CancellationToken,
    ) -> object:
        prompt = _build_prompt(request)
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
                output = _parse_output(output)
            if isinstance(output, Mapping):
                result = dict(output)
                result.setdefault("provider_run_id", run_id)
                result.setdefault("provenance", [f"hermes:run:{run_id}"])
                return result
            return output
        finally:
            if cancellation.cancelled:
                await self._runs.cancel(run_id)