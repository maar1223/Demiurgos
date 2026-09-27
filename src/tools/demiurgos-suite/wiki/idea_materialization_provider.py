"""Hermes chat-completions adapter for the idea-materialization provider contract.

The provider is pure transport plus prompt assembly: it builds a bounded,
JSON-only prompt from the idea/target/candidates, sends exactly one
non-streaming ``/v1/chat/completions`` request with ``tool_choice: "none"``
(so the gateway ships no unused tool schemas), strips markdown fences, parses
JSON, and stamps the response identity (``provider_run_id``/``provenance``).

The transport is injected (``chat_url`` + ``client_provider``) so this module
never imports ``api_server`` (circular import) and tests can drive it with an
``httpx.MockTransport``. The shared client already carries gateway auth.

It performs NO writes and NO validation. Strict envelope validation lives
server-side in ``MaterializationResponse.from_provider`` (fail closed,
R-IM-09): malformed or non-envelope output is passed through unchanged so
that validator rejects it — the provider never decides what is valid.

Mirrors ``_run_hermes_sync`` (api_server.py:7601-7667; same payload shape and
``tool_choice: "none"`` precedent) and the fence-strip precedent in
``HermesGuidedProvider`` (guided_character_provider.py:159-165).
"""

from __future__ import annotations

import asyncio
import json
from typing import Callable, Mapping

import httpx

from assistant_activity import (
    CapabilityAssessment,
    HermesRunsActivityAdapter,
)
from demiurgos_language import resolve_domain_language
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
    language = "Spanish" if resolve_domain_language("content") == "es" else "English"
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
    """Adapt one chat-completions response into a structured materialization envelope.

    The provider is the only external read-only call in the materialization
    path: it posts one bounded prompt and reads the text output, performing no
    writes and no validation (the server-side ``from_provider`` owns
    fail-closed validation). ``probe()`` still delegates to the injected
    activity adapter so the capability contract is unchanged.
    """

    def __init__(
        self,
        activity_adapter: HermesRunsActivityAdapter,
        *,
        chat_url: str,
        client_provider: Callable[[], httpx.AsyncClient],
    ) -> None:
        self._runs = activity_adapter
        self._chat_url = chat_url
        self._client_provider = client_provider

    async def probe(self) -> CapabilityAssessment:
        return await self._runs.probe()

    async def invoke(
        self,
        request: MaterializationRequest,
        cancellation: CancellationToken,
    ) -> object:
        """Send one non-streaming chat-completions request and parse its text.

        A non-2xx status or a transport/decode failure RAISES: the handler then
        maps it to PROVIDER_UNAVAILABLE (retryable), whereas fabricated
        fallback text would instead map to MALFORMED_OUTPUT (different retry
        semantics). There is no run to stop, so the cancellation token is
        honoured only by refusing to start remote work — the caller's
        ``asyncio.wait_for`` owns the overall deadline.
        """
        if cancellation.cancelled:
            raise asyncio.CancelledError
        prompt = _build_prompt(request)
        payload = {
            # One bounded text->JSON task. The gateway honors "tool_choice":
            # "none" for THIS request only, which yields an empty toolset and
            # omits the ~6.3k tokens of unused tool schemas. Do not pass a
            # browser-controlled model override; "hermes-agent" resolves the
            # active profile's model.default server-side.
            "model": "hermes-agent",
            "tool_choice": "none",
            "messages": [{"role": "user", "content": prompt}],
        }
        client = self._client_provider()
        try:
            response = await client.post(self._chat_url, json=payload)
        except Exception as exc:
            raise RuntimeError("Hermes chat-completions request failed") from exc
        if response.status_code != 200:
            raise RuntimeError(
                f"Hermes chat-completions returned HTTP {response.status_code}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Hermes chat-completions returned invalid JSON") from exc
        content = ""
        if isinstance(data, Mapping):
            choices = data.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
                message = choices[0].get("message")
                if isinstance(message, Mapping) and isinstance(message.get("content"), str):
                    content = message["content"]
        # Chat-completions ids (``chatcmpl-...``) are the only correlation
        # handle now; fall back to the request id when the gateway omits one.
        response_id = data.get("id") if isinstance(data, Mapping) else None
        has_response_id = isinstance(response_id, str) and bool(response_id.strip())
        run_id = response_id if has_response_id else request.request_id
        output = _parse_output(content)
        if isinstance(output, Mapping):
            result = dict(output)
            result.setdefault("provider_run_id", run_id)
            if has_response_id:
                result.setdefault("provenance", [f"hermes:chatcmpl:{response_id}"])
            return result
        return output