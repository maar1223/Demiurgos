"""Server-owned semantic decision contract and strict validator.

Hermes is the conversational voice and semantic interpreter. Demiurgos owns the
decision boundary: it accepts only strictly validated decision envelopes, never
trusts provider output directly, and derives every policy-safe field server-side
(action, fail-closed blocked result, bounded attempts). The contract is
deliberately disk-, graph-, and credential-free; no canon, proposal, or write can
originate here.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from assistant_activity import (
    HermesActivityRequest,
    HermesRunsActivityAdapter,
    RunSubmissionError,
)
from demiurgos_language import normalize_language, resolve_domain_language

SemanticState = Literal[
    "allow",
    "clarify",
    "require_confirmation",
    "proposal_ready",
    "blocked",
]

ContinuationOutcome = Literal["question", "delta"]

# Bounded explicitness of a guided intent. ``imperative`` is a direct command to
# create/start a character; ``musing`` (the conservative default) is everything
# else. Only ``imperative`` may auto-open the guided surface; ``musing``/absent
# yields a consent suggestion and creates nothing.
GuidedExplicitness = Literal["imperative", "musing"]

MAX_SEMANTIC_ATTEMPTS = 3

# Bounded circuit breaker: after this many consecutive fail-closed turns the
# provider is not called for a short cool-down and the last reason/copy is
# served instead. An account-wide refusal (authentication or quota) opens it
# immediately: no retry and no cool-down wait can fix it.
BREAKER_FAILURE_THRESHOLD = 3
BREAKER_COOLDOWN_SECONDS = 60.0
_OPEN_IMMEDIATELY_REASONS: frozenset[str] = frozenset({
    "provider_auth",
    "provider_quota",
})
MAX_RESPONSE_CHARS = 4096
MAX_CONTINUATION_QUESTION_CHARS = 2_000
MAX_CONTINUATION_DELTA_KEYS = 50
MAX_CONTINUATION_VALUE_CHARS = 2_000
MAX_CONTINUATION_NESTING_DEPTH = 4

# States the semantic seam can deliver as a self-contained server envelope
# without a server-owned guided session or diskless proposal behind it.
SELF_CONTAINED_SEMANTIC_STATES: frozenset[str] = frozenset(
    {"allow", "clarify", "blocked"}
)

# States that are real ONLY when backed by the existing guarded session /
# diskless proposal machinery. The single-run contract carries that backing as
# a typed ``continuation`` inside the SAME Hermes envelope: require_confirmation
# carries a confirmation question, proposal_ready carries a bounded candidate
# delta. The router never emits these states hollow: when the continuation is
# absent or invalid (or the guarded machinery rejects the request), it fails
# closed to ``blocked`` with zero writes.
CONTINUATION_STATES: frozenset[str] = frozenset(
    {"require_confirmation", "proposal_ready"}
)

# Provider-supplied authority claims are never trusted. Any of these keys
# anywhere inside a continuation delta fails the whole envelope closed.
_AUTHORITATIVE_CONTINUATION_KEYS: frozenset[str] = frozenset({
    "target", "digest", "revision", "authority", "reference",
    "acceptance", "accepted_canon", "authorization",
})

INVALID_ENVELOPE_REASON = "semantic_envelope_invalid"
PROVIDER_UNAVAILABLE_REASON = "semantic_provider_unavailable"

# Bounded, user-facing failure reasons carried by a fail-closed envelope. They
# let the client distinguish a dead session from an exhausted provider, a
# rejected request, or unvalidatable model output, instead of rendering one
# opaque copy for every cause. Codes are machine values; the UI renders only
# the localized copy.
INVALID_OUTPUT_REASON = "invalid_output"
PROVIDER_AUTH_REASON = "provider_auth"
PROVIDER_QUOTA_REASON = "provider_quota"
PROVIDER_REJECTED_REASON = "provider_rejected"
PROVIDER_UNREACHABLE_REASON = "provider_unreachable"

# Upstream statuses that a retry cannot fix (authentication, quota, unsupported
# or malformed request, missing route). Anything else is treated as transient.
_NON_RETRYABLE_STATUS_REASONS: Mapping[int, str] = {
    400: PROVIDER_REJECTED_REASON,
    401: PROVIDER_AUTH_REASON,
    402: PROVIDER_QUOTA_REASON,
    403: PROVIDER_AUTH_REASON,
    404: PROVIDER_REJECTED_REASON,
}

# Localized safe fail-closed copy. User-visible unavailable text MUST NOT expose
# Hermes/provider/internal terminology (no gateway, HTTP, timeout, quota,
# credits, credentials, or model terms). Copy is selected from
# ``DEMIURGOS_LANGUAGE`` and defaults to Spanish.
UNAVAILABLE_COPY_BY_LANGUAGE: Mapping[str, str] = {
    "es": (
        "El Asistente IA no pudo completar la solicitud en este momento. "
        "No se realizó ninguna acción ni escritura."
    ),
    "en": (
        "The AI Assistant could not complete the request right now. "
        "No action or write was made."
    ),
}

# Reason-specific copy. Every entry keeps the no-action guarantee explicit and
# stays free of provider/internal terms.
UNAVAILABLE_COPY_BY_REASON: Mapping[str, Mapping[str, str]] = {
    PROVIDER_AUTH_REASON: {
        "es": (
            "El asistente necesita que revises su configuración en Perfil antes de "
            "continuar. No se realizó ninguna acción ni escritura."
        ),
        "en": (
            "The assistant needs its configuration reviewed in Profile before it can "
            "continue. No action or write was made."
        ),
    },
    PROVIDER_QUOTA_REASON: {
        "es": (
            "El servicio de IA del asistente alcanzó su límite de uso. Revisa la cuenta "
            "del servicio o inténtalo más tarde. No se realizó ninguna acción ni escritura."
        ),
        "en": (
            "The assistant's AI service reached its usage limit. Check the service "
            "account or try again later. No action or write was made."
        ),
    },
    PROVIDER_REJECTED_REASON: {
        "es": (
            "El asistente no pudo procesar el mensaje tal como está. Inténtalo de nuevo "
            "o acorta el mensaje. No se realizó ninguna acción ni escritura."
        ),
        "en": (
            "The assistant could not process the message as written. Try again or "
            "shorten the message. No action or write was made."
        ),
    },
    PROVIDER_UNREACHABLE_REASON: {
        "es": (
            "El servicio de IA del asistente no respondió. Inténtalo de nuevo en un "
            "momento. No se realizó ninguna acción ni escritura."
        ),
        "en": (
            "The assistant's AI service did not respond. Try again in a moment. "
            "No action or write was made."
        ),
    },
    INVALID_OUTPUT_REASON: {
        "es": (
            "El asistente devolvió una respuesta que no se pudo validar. Inténtalo de "
            "nuevo o reformula el mensaje. No se realizó ninguna acción ni escritura."
        ),
        "en": (
            "The assistant returned a response that could not be validated. Try again "
            "or rephrase the message. No action or write was made."
        ),
    },
}


def unavailable_copy(language: str | None = None, reason: str | None = None) -> str:
    """Localized safe fail-closed copy; never exposes provider/internal terms."""
    normalized = (
        normalize_language(language)
        if language is not None
        else resolve_domain_language("conversation")
    )
    by_reason = UNAVAILABLE_COPY_BY_REASON.get(reason or "")
    if by_reason is not None:
        return by_reason[normalized]
    return UNAVAILABLE_COPY_BY_LANGUAGE[normalized]


# Only these keys may ever reach the Hermes prompt as authorized context.
# Anything else (credentials, filesystem, graph-write, canon-write, provider
# authority) is structurally dropped before prompt construction.
_CONTEXT_KEYS: tuple[str, ...] = ("mundo", "ficha", "reference", "graph")


@dataclass(frozen=True)
class SemanticContext:
    """Bounded server-authorized context for one Hermes interpretation.

    Only ``mundo``, ``ficha``, ``reference``, and ``graph`` are admitted;
    any other key supplied by a caller is dropped by :func:`normalize_context`.
    The DTO never carries credentials, filesystem, graph-write, canon-write, or
    provider authority.
    """

    mundo: str | None = None
    ficha: str | None = None
    reference: str | None = None
    graph: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mundo": self.mundo,
            "ficha": self.ficha,
            "reference": self.reference,
            "graph": self.graph,
        }


def normalize_context(
    context: "SemanticContext | Mapping[str, Any] | None",
) -> SemanticContext:
    """Return the bounded context, dropping any key outside the allowed set.

    Accepts a :class:`SemanticContext`, a mapping, or ``None``. Values that are
    not strings (or ``None``) are dropped too, so credentials and authority
    claims can never reach the provider prompt.
    """
    if context is None or isinstance(context, SemanticContext):
        return context or SemanticContext()
    if not isinstance(context, Mapping):
        return SemanticContext()
    return SemanticContext(
        **{
            key: context[key]
            for key in _CONTEXT_KEYS
            if key in context and (context[key] is None or isinstance(context[key], str))
        }
    )

_STATE_ACTIONS: Mapping[SemanticState, str] = {
    "allow": "answer",
    "clarify": "ask_question",
    "require_confirmation": "request_confirmation",
    "proposal_ready": "show_proposal",
    "blocked": "blocked_explanation",
}


def action_for_state(state: SemanticState) -> str:
    """Derive the deterministic server-side action for a decision state."""
    return _STATE_ACTIONS[state]


@dataclass(frozen=True)
class SemanticContinuation:
    """Typed single-run guided continuation carried inside the decision.

    ``question``: one concise confirmation/clarification question (outcome
    ``question``, used by require_confirmation).
    ``delta``: bounded candidate character fields (outcome ``delta``, used by
    proposal_ready). These are proposed data, never authority: the server
    re-derives the target slug, digest, revision, and acceptance through the
    existing guarded guided machinery.
    """

    outcome: ContinuationOutcome
    question: str | None = None
    delta: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class SemanticDecision:
    """Immutable validated Hermes decision. ``reference`` is server-issued only."""

    state: SemanticState
    response: str
    request_id: str
    session_id: str | None = None
    reference: str | None = None
    guided: bool = False
    continuation: SemanticContinuation | None = None
    guided_explicitness: GuidedExplicitness = "musing"


@dataclass(frozen=True)
class SemanticValidation:
    admitted: bool
    reason: str
    decision: SemanticDecision | None = None


def _continuation_value_safe(value: Any, *, depth: int = 0) -> bool:
    """Reject non-JSON-safe or over-bounded continuation values (fail closed)."""
    if depth > MAX_CONTINUATION_NESTING_DEPTH:
        return False
    if isinstance(value, str):
        return len(value) <= MAX_CONTINUATION_VALUE_CHARS
    if value is None or isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str) and key
            and _continuation_value_safe(item, depth=depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return len(value) <= MAX_CONTINUATION_DELTA_KEYS and all(
            _continuation_value_safe(item, depth=depth + 1) for item in value
        )
    return False


def _continuation_has_authoritative_key(value: Any, *, depth: int = 0) -> bool:
    """Detect provider authority claims at any depth inside a continuation."""
    if depth > MAX_CONTINUATION_NESTING_DEPTH:
        return True
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _AUTHORITATIVE_CONTINUATION_KEYS:
                return True
            if _continuation_has_authoritative_key(item, depth=depth + 1):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_continuation_has_authoritative_key(item, depth=depth + 1) for item in value)
    return False


def _validate_continuation(state: str, guided: bool, value: Any):
    """Return a SemanticContinuation, None when absent, or False when invalid.

    A continuation is only meaningful for require_confirmation/proposal_ready
    on a guided decision. Any malformed, unbounded, or authority-claiming
    continuation fails the entire envelope closed.
    """
    if value is None:
        return None
    if state not in CONTINUATION_STATES or guided is not True:
        return False
    if not isinstance(value, Mapping) or set(value) - {"outcome", "question", "delta"}:
        return False
    outcome = value.get("outcome")
    if outcome not in ("question", "delta"):
        return False
    question = value.get("question")
    delta = value.get("delta")
    if outcome == "question":
        if delta is not None or not isinstance(question, str) or not question.strip():
            return False
        if len(question) > MAX_CONTINUATION_QUESTION_CHARS:
            return False
        return SemanticContinuation("question", question=question.strip())
    if question is not None:
        return False
    if not isinstance(delta, Mapping) or not delta:
        return False
    if len(delta) > MAX_CONTINUATION_DELTA_KEYS:
        return False
    if any(not isinstance(key, str) or not key for key in delta):
        return False
    if _continuation_has_authoritative_key(delta):
        return False
    if any(not _continuation_value_safe(item) for item in delta.values()):
        return False
    return SemanticContinuation("delta", delta=dict(delta))


def validate_semantic_decision(value: Any) -> SemanticValidation:
    """Strictly validate a provider envelope before any routing decision.

    Rejects malformed output, unknown states, missing required fields, unsafe
    values, over-length responses, and any provider-supplied ``reference``
    (evidence identifiers are server-issued and never client authority).
    """
    if not isinstance(value, Mapping):
        return SemanticValidation(False, INVALID_ENVELOPE_REASON)

    state = value.get("state")
    if state not in _STATE_ACTIONS:
        return SemanticValidation(False, INVALID_ENVELOPE_REASON)

    response = value.get("response")
    if not isinstance(response, str) or not response.strip():
        return SemanticValidation(False, INVALID_ENVELOPE_REASON)
    if len(response) > MAX_RESPONSE_CHARS:
        return SemanticValidation(False, INVALID_ENVELOPE_REASON)

    request_id = value.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        return SemanticValidation(False, INVALID_ENVELOPE_REASON)

    session_id = value.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        return SemanticValidation(False, INVALID_ENVELOPE_REASON)

    guided = value.get("guided", False)
    if not isinstance(guided, bool):
        return SemanticValidation(False, INVALID_ENVELOPE_REASON)

    # Bounded explicitness degrades to the conservative default instead of
    # failing the envelope: an absent or out-of-enum value resolves to
    # ``musing`` (suggest, never auto-open) and never blocks admission.
    raw_explicitness = value.get("guided_explicitness", "musing")
    guided_explicitness: GuidedExplicitness = (
        raw_explicitness
        if raw_explicitness in ("imperative", "musing")
        else "musing"
    )

    reference = value.get("reference")
    if reference is not None:
        return SemanticValidation(False, INVALID_ENVELOPE_REASON)

    continuation = _validate_continuation(state, guided, value.get("continuation"))
    if continuation is False:
        return SemanticValidation(False, INVALID_ENVELOPE_REASON)

    return SemanticValidation(
        True,
        "",
        SemanticDecision(
            state=state,
            response=response.strip(),
            request_id=request_id.strip(),
            session_id=session_id,
            guided=guided,
            continuation=continuation,
            guided_explicitness=guided_explicitness,
        ),
    )


@dataclass(frozen=True)
class SemanticResult:
    """Server-side outcome envelope: valid decision or fail-closed blocked result.

    ``unavailable`` is True only when no validated Hermes decision was obtained
    (invalid, malformed, exhausted, or provider-unavailable attempts). A valid
    ``blocked`` decision from Hermes is NOT unavailable: it is a decision.
    """

    decision: SemanticDecision | None
    attempts: int
    request_id: str
    session_id: str | None = None
    unavailable: bool = False
    reason: str | None = None

    @property
    def state(self) -> SemanticState:
        if self.decision is not None:
            return self.decision.state
        return "blocked"

    @property
    def response(self) -> str:
        if self.decision is not None:
            return self.decision.response
        return unavailable_copy(reason=self.reason)

    @property
    def action(self) -> str:
        return action_for_state(self.state)

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": self.state,
            "response": self.response,
            "action": self.action,
            "request_id": self.request_id,
            "attempts": self.attempts,
            "unavailable": self.unavailable,
        }
        if self.decision is None and self.reason is not None:
            result["reason"] = self.reason
        if self.decision is not None:
            result["guided"] = self.decision.guided
            if self.decision.session_id is not None:
                result["session_id"] = self.decision.session_id
            if self.decision.reference is not None:
                result["reference"] = self.decision.reference
            if self.decision.guided and self.state in CONTINUATION_STATES:
                # Explicitness is only meaningful for a guided continuation.
                result["guided_explicitness"] = self.decision.guided_explicitness
        return result


_SEMANTIC_REASONING_OPTIONS: dict[str, str] = {"reasoning_effort": "low"}
"""Per-run gateway reasoning override for the semantic gate."""


class SemanticIntentProvider:
    """Bounded semantic decision runner over one Hermes runs adapter.

    Each attempt is one Hermes run; at most ``max_attempts`` runs happen. Invalid,
    malformed, or unavailable attempts are retried only up to the bound and then
    fail closed as ``blocked`` with ``unavailable: True`` and localized safe copy.
    There is NO lexical/plain-chat fallback: ``fallback_enabled`` does not exist
    and cannot be enabled.
    """

    def __init__(
        self,
        runs: HermesRunsActivityAdapter,
        *,
        max_attempts: int = MAX_SEMANTIC_ATTEMPTS,
        breaker_threshold: int = BREAKER_FAILURE_THRESHOLD,
        breaker_cooldown: float = BREAKER_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._runs = runs
        self._max_attempts = min(MAX_SEMANTIC_ATTEMPTS, max(1, max_attempts))
        self._breaker_threshold = max(1, breaker_threshold)
        self._breaker_cooldown = max(0.0, breaker_cooldown)
        self._clock = clock
        self._failures = 0
        self._open_until: float | None = None
        self._open_reason: str | None = None

    def _breaker_open(self) -> str | None:
        """Return the open breaker's reason, or None when calls are allowed.

        A cooled-down breaker closes and restarts its failure count, so one
        probe call decides whether the provider recovered.
        """
        if self._open_until is None:
            return None
        if self._clock() < self._open_until:
            return self._open_reason
        self._open_until = None
        self._open_reason = None
        self._failures = 0
        return None

    def _record_failure(self, reason: str | None) -> None:
        self._failures += 1
        immediate = reason in _OPEN_IMMEDIATELY_REASONS
        if immediate or self._failures >= self._breaker_threshold:
            self._open_until = self._clock() + self._breaker_cooldown
            self._open_reason = reason

    def _record_success(self) -> None:
        self._failures = 0
        self._open_until = None
        self._open_reason = None

    def _render_context(self, context: SemanticContext) -> str:
        data = {
            key: value for key, value in context.as_dict().items() if value is not None
        }
        if not data:
            return ""
        return (
            " Authorized context (server-verified, read-only reference): "
            + json.dumps(data, ensure_ascii=False)
            + "."
        )

    def _build_prompt(
        self,
        author_input: str,
        request_id: str,
        session_id: str | None,
        context: SemanticContext | Mapping[str, Any] | None = None,
        distilled_state: str | None = None,
        recent_turns: str | None = None,
        memory_context: str | None = None,
    ) -> str:
        session_instruction = (
            f" and session_id {json.dumps(session_id)}" if session_id else ""
        )
        context_block = self._render_context(normalize_context(context))
        distilled_block = (
            f" [Conversation context (summarized): {distilled_state}]"
            if distilled_state else ""
        )
        recent_block = (
            f" [Recent exchange (verbatim, last turns): {recent_turns}]"
            if recent_turns else ""
        )
        memory_block = (
            f" [Relevant memory from earlier sessions: {memory_context}]"
            if memory_context else ""
        )
        return (
            "Act as the Hermes semantic intent interpreter. Return ONLY one JSON "
            "object — no markdown fences, no code blocks — with exactly: state "
            "(one of allow, clarify, require_confirmation, proposal_ready, "
            "blocked), response (the author-facing reply: one short, direct "
            "sentence under 400 characters, in the same language as the "
            "author's input. Answer the message itself; never describe the "
            "author's intent or the classification — no 'the author wants', "
            "'the user asks' or 'the assistant should'. Use a safe refusal "
            "only for blocked), echoed ids (see the last line), guided (boolean), and "
            "guided_explicitness (one of imperative or musing: use imperative only "
            "when the author directly commands creating or starting a guided entity "
            "— a character or a world system — for example \"crea un personaje\" or "
            "\"crea un sistema\"; otherwise use musing). "
            "When state is require_confirmation include continuation "
            "{\"outcome\": \"question\", \"question\": \"<one concise confirmation "
            "question>\"}. When state is proposal_ready include continuation "
            "{\"outcome\": \"delta\", \"delta\": {<bounded candidate guided-entity "
            "fields, at most 50 keys>}}. continuation is allowed only for "
            "require_confirmation and proposal_ready and must not contain target, "
            "digest, revision, authority, reference, acceptance, or accepted_canon "
            "keys. You have no filesystem, graph, credential, or write access. "
            "Do not explain your reasoning or analysis; classify and emit only "
            "the JSON object."
            + context_block
            + distilled_block
            + recent_block
            + memory_block
            + " Never include reference, proposal, target, digest, revision, or "
            "authority fields; those are server-owned. Never write or claim "
            "approval. Author input: " + author_input
            # Volatile ids go LAST so the whole instruction block above stays a
            # stable prefix (prompt cache); they used to break it ~500 chars in.
            + " Echo request_id " + json.dumps(request_id)
            + session_instruction + " in the JSON object."
        )

    async def _collect_output(self, run_id: str) -> object:
        output: object = None
        deltas: list[str] = []
        async for event in self._runs.events(run_id):
            if not isinstance(event, Mapping) or event.get("run_id") != run_id:
                continue
            if event.get("event") == "message.delta" and isinstance(event.get("delta"), str):
                deltas.append(event["delta"])
            elif event.get("event") == "run.completed":
                output = event.get("output")
        if deltas:
            output = "".join(deltas)
        if output is None and hasattr(self._runs, "status"):
            try:
                status = await self._runs.status(run_id)
            except Exception:
                status = None
            if isinstance(status, Mapping) and status.get("status") == "completed":
                output = status.get("output")
        return output

    def _normalize_output(self, output: object) -> object:
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
                # A clean-EOF truncation drops only the closing braces; repair
                # them structurally and still parse strictly.
                from guided_character_provider import repair_truncated_json
                repaired = repair_truncated_json(text)
                if repaired is None:
                    return None
                try:
                    output = json.loads(repaired)
                except (TypeError, ValueError):
                    return None
        return output

    async def decide(
        self,
        author_input: str,
        *,
        request_id: str,
        session_id: str | None = None,
        context: SemanticContext | Mapping[str, Any] | None = None,
        distilled_state: str | None = None,
        recent_turns: str | None = None,
        memory_context: str | None = None,
    ) -> SemanticResult:
        open_reason = self._breaker_open()
        if open_reason is not None:
            # Serve the specific fail-closed copy without touching the provider.
            return SemanticResult(
                decision=None,
                attempts=0,
                request_id=request_id,
                session_id=session_id,
                unavailable=True,
                reason=open_reason,
            )
        reason: str | None = None
        attempts = 0
        for attempt in range(1, self._max_attempts + 1):
            attempts = attempt
            try:
                run_id = await self._runs.start(
                    HermesActivityRequest(
                        request_id=request_id,
                        prompt=self._build_prompt(
                            author_input, request_id, session_id, context,
                            distilled_state, recent_turns, memory_context,
                        ),
                        session_id=session_id or "",
                        # Classification plus one short sentence: the model does
                        # not need to reason at length, and reasoning tokens are
                        # most of this call's wall clock.
                        model_options=_SEMANTIC_REASONING_OPTIONS,
                    )
                )
                raw_output = await self._collect_output(run_id)
                output = self._normalize_output(raw_output)
                validation = validate_semantic_decision(output)
            except RunSubmissionError as exc:
                # A refusal that a retry cannot fix stops at one attempt; the
                # reason drives the specific fail-closed copy.
                non_retryable = _NON_RETRYABLE_STATUS_REASONS.get(exc.status_code or 0)
                if non_retryable is not None:
                    reason = non_retryable
                    break
                reason = PROVIDER_UNREACHABLE_REASON
                validation = SemanticValidation(False, PROVIDER_UNAVAILABLE_REASON)
            except Exception:
                reason = PROVIDER_UNREACHABLE_REASON
                validation = SemanticValidation(False, PROVIDER_UNAVAILABLE_REASON)
            if validation.admitted and validation.decision is not None:
                self._record_success()
                return SemanticResult(
                    decision=validation.decision,
                    attempts=attempt,
                    request_id=request_id,
                    session_id=session_id,
                )
            if reason is None:
                reason = INVALID_OUTPUT_REASON
        self._record_failure(reason)
        return SemanticResult(
            decision=None,
            attempts=attempts,
            request_id=request_id,
            session_id=session_id,
            unavailable=True,
            reason=reason,
        )
