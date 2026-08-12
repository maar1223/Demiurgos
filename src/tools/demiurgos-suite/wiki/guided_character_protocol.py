"""Backend-owned contracts and state boundary for guided character creation.

This module deliberately stops before routing, graph access, or persistence.  Hermes
is treated as an untrusted, bounded proposal provider; the in-memory store is the
authoritative seam that can later be replaced by the existing session persistence.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable, Mapping, Protocol


PROTOCOL_VERSION = "guided-character-v1"
DEFAULT_DEADLINE_MS = 8_000
MAX_DEADLINE_MS = 30_000


class ErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MALFORMED_OUTPUT = "malformed_output"
    UNAUTHORIZED = "unauthorized"
    REVISION_CONFLICT = "revision_conflict"
    INTERNAL = "internal"


@dataclass(frozen=True)
class StructuredError:
    code: ErrorCode
    message: str
    retryable: bool

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code.value, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True)
class Capabilities:
    protocol_version: str
    guided_character_v1: bool
    cancellation: bool
    structured_output: bool
    max_deadline_ms: int

    @classmethod
    def from_payload(cls, payload: object) -> "Capabilities | None":
        if not isinstance(payload, Mapping):
            return None
        values = {"protocol_version", "guided_character_v1", "cancellation", "structured_output", "max_deadline_ms"}
        if set(payload) & values != values:
            return None
        deadline = payload["max_deadline_ms"]
        if not isinstance(deadline, int) or isinstance(deadline, bool) or deadline <= 0:
            return None
        return cls(
            protocol_version=payload["protocol_version"], guided_character_v1=payload["guided_character_v1"],
            cancellation=payload["cancellation"], structured_output=payload["structured_output"],
            max_deadline_ms=deadline,
        ) if isinstance(payload["protocol_version"], str) and all(
            isinstance(payload[name], bool) for name in ("guided_character_v1", "cancellation", "structured_output")
        ) else None

    def admitted(self) -> bool:
        return (
            self.protocol_version == PROTOCOL_VERSION and self.guided_character_v1
            and self.cancellation and self.structured_output and self.max_deadline_ms > 0
        )


@dataclass(frozen=True)
class GuidedRequest:
    protocol_version: str
    request_id: str
    session_id: str
    world: str
    base_revision: int
    authorization_binding: str
    author_input: str
    context_budget: int = 4_000
    deadline_ms: int = DEFAULT_DEADLINE_MS

    def validate(self) -> StructuredError | None:
        if self.protocol_version != PROTOCOL_VERSION or not all(
            isinstance(value, str) and value.strip() for value in
            (self.request_id, self.session_id, self.world, self.authorization_binding, self.author_input)
        ) or self.base_revision < 0 or self.context_budget <= 0:
            return StructuredError(ErrorCode.INVALID_INPUT, "The guided request is invalid.", False)
        if not 1 <= self.deadline_ms <= MAX_DEADLINE_MS:
            return StructuredError(ErrorCode.INVALID_INPUT, "The deadline is outside the allowed bounds.", False)
        return None


class Outcome(StrEnum):
    QUESTION = "question"
    DELTA = "delta"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class GuidedResponse:
    protocol_version: str
    request_id: str
    session_id: str
    base_revision: int
    outcome: Outcome
    provenance: tuple[str, ...] = ()
    question: str | None = None
    delta: Mapping[str, Any] | None = None
    provider_run_id: str | None = None
    retryable: bool = False
    error: StructuredError | None = None

    @classmethod
    def from_provider(cls, value: object, request: GuidedRequest) -> "GuidedResponse | None":
        if not isinstance(value, Mapping) or value.get("protocol_version") != PROTOCOL_VERSION:
            return None
        if value.get("request_id") != request.request_id or value.get("session_id") != request.session_id:
            return None
        try:
            outcome = Outcome(value["outcome"])
        except (KeyError, ValueError):
            return None
        question = value.get("question")
        delta = value.get("delta")
        if outcome is Outcome.QUESTION and (not isinstance(question, str) or not question.strip()):
            return None
        if outcome is Outcome.DELTA and not isinstance(delta, Mapping):
            return None
        provenance = value.get("provenance", ())
        if not isinstance(provenance, (list, tuple)) or not all(isinstance(item, str) for item in provenance):
            return None
        return cls(PROTOCOL_VERSION, request.request_id, request.session_id, request.base_revision, outcome,
                   tuple(provenance), question if isinstance(question, str) else None,
                   dict(delta) if isinstance(delta, Mapping) else None,
                   value.get("provider_run_id") if isinstance(value.get("provider_run_id"), str) else None,
                   value.get("retryable") is True)


class MessageType(StrEnum):
    AUTHOR_INPUT = "author_input"
    ASSISTANT_RESPONSE = "assistant_response"
    PROPOSAL = "proposal"
    ACCEPTANCE = "acceptance"
    REJECTION = "rejection"
    ERROR = "error"
    RECOVERY = "recovery"


@dataclass(frozen=True)
class TypedMessage:
    message_type: MessageType
    content: Mapping[str, Any]
    revision: int


@dataclass
class CandidateState:
    accepted_canon: dict[str, Any] = field(default_factory=dict)
    proposals: dict[str, Any] = field(default_factory=dict)
    unknowns: list[Any] = field(default_factory=list)
    rumors: list[Any] = field(default_factory=list)
    conflicts: list[Any] = field(default_factory=list)
    unresolved_references: list[Any] = field(default_factory=list)
    provenance: list[str] = field(default_factory=list)


@dataclass
class SessionState:
    session_id: str
    world: str
    phase: str
    revision: int
    authorization_binding: str
    messages: list[TypedMessage] = field(default_factory=list)
    pending_question: str | None = None
    candidate: CandidateState = field(default_factory=CandidateState)


class Provider(Protocol):
    async def invoke(self, request: GuidedRequest, cancellation: "CancellationToken") -> object: ...


class CancellationToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class GuidedSessionStore:
    """Revision and authorization checks are performed before every mutation."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def create(self, session_id: str, world: str, authorization_binding: str) -> SessionState:
        if session_id in self._sessions:
            raise ValueError("session already exists")
        state = SessionState(session_id, world, "conversation", 0, authorization_binding)
        self._sessions[session_id] = state
        return deepcopy(state)

    def recover(self, session_id: str, authorization_binding: str) -> SessionState | None:
        state = self._sessions.get(session_id)
        return deepcopy(state) if state and state.authorization_binding == authorization_binding else None

    def commit(self, request: GuidedRequest, response: GuidedResponse) -> SessionState | None:
        state = self._sessions.get(request.session_id)
        if not state or state.authorization_binding != request.authorization_binding or state.revision != request.base_revision:
            return None
        next_state = deepcopy(state)
        next_state.revision += 1
        next_state.messages.append(TypedMessage(
            MessageType.ASSISTANT_RESPONSE if response.outcome is Outcome.QUESTION else MessageType.PROPOSAL,
            {"question": response.question} if response.question else dict(response.delta or {}), next_state.revision,
        ))
        next_state.pending_question = response.question
        if response.outcome is Outcome.DELTA and response.delta:
            # Keep provider deltas outside canon and attach their provenance.
            from guided_character_domain import apply_delta
            apply_delta(next_state.candidate, response.delta, response.provenance)
        elif response.provenance:
            next_state.candidate.provenance.extend(response.provenance)
        self._sessions[request.session_id] = next_state
        return deepcopy(next_state)

    def accept_proposal(self, session_id: str, authorization_binding: str,
                        base_revision: int, key: str) -> SessionState | None:
        """Accept exactly one proposal after revision and authorization checks."""
        state = self._sessions.get(session_id)
        if not state or state.authorization_binding != authorization_binding or state.revision != base_revision:
            return None
        from guided_character_domain import accept_proposal
        next_state = deepcopy(state)
        accept_proposal(next_state.candidate, key)
        next_state.revision += 1
        next_state.messages.append(TypedMessage(MessageType.ACCEPTANCE, {"key": key}, next_state.revision))
        self._sessions[session_id] = next_state
        return deepcopy(next_state)

    def reject_proposal(self, session_id: str, authorization_binding: str,
                        base_revision: int, key: str) -> SessionState | None:
        """Reject exactly one proposal without promoting it to canon."""
        state = self._sessions.get(session_id)
        if not state or state.authorization_binding != authorization_binding or state.revision != base_revision:
            return None
        from guided_character_domain import reject_proposal
        next_state = deepcopy(state)
        reject_proposal(next_state.candidate, key)
        next_state.revision += 1
        next_state.messages.append(TypedMessage(MessageType.REJECTION, {"key": key}, next_state.revision))
        self._sessions[session_id] = next_state
        return deepcopy(next_state)


async def invoke_bounded(provider: Provider | Callable[..., Awaitable[object]], request: GuidedRequest,
                         capabilities: Capabilities | None, cancellation: CancellationToken | None = None) -> GuidedResponse:
    """Invoke only an admitted provider; no parsed output is committed here."""
    invalid = request.validate()
    if invalid:
        return GuidedResponse(PROTOCOL_VERSION, request.request_id, request.session_id, request.base_revision,
                              Outcome.ERROR, error=invalid)
    if capabilities is None or not capabilities.admitted() or request.deadline_ms > capabilities.max_deadline_ms:
        return GuidedResponse(PROTOCOL_VERSION, request.request_id, request.session_id, request.base_revision,
                              Outcome.UNAVAILABLE, error=StructuredError(ErrorCode.CAPABILITY_UNAVAILABLE,
                              "The guided provider is unavailable.", True), retryable=True)
    token = cancellation or CancellationToken()
    if token.cancelled:
        error = StructuredError(ErrorCode.CANCELLED, "The guided request was cancelled.", True)
        return GuidedResponse(PROTOCOL_VERSION, request.request_id, request.session_id, request.base_revision, Outcome.ERROR, error=error, retryable=True)
    try:
        call = provider.invoke(request, token) if hasattr(provider, "invoke") else provider(request, token)
        raw = await asyncio.wait_for(call, request.deadline_ms / 1000)
    except asyncio.TimeoutError:
        token.cancel()
        error = StructuredError(ErrorCode.TIMEOUT, "The guided provider timed out.", True)
        return GuidedResponse(PROTOCOL_VERSION, request.request_id, request.session_id, request.base_revision, Outcome.ERROR, error=error, retryable=True)
    except asyncio.CancelledError:
        token.cancel()
        error = StructuredError(ErrorCode.CANCELLED, "The guided request was cancelled.", True)
        return GuidedResponse(PROTOCOL_VERSION, request.request_id, request.session_id, request.base_revision, Outcome.ERROR, error=error, retryable=True)
    except (ConnectionError, OSError):
        error = StructuredError(ErrorCode.PROVIDER_UNAVAILABLE, "The guided provider is unavailable.", True)
        return GuidedResponse(PROTOCOL_VERSION, request.request_id, request.session_id, request.base_revision, Outcome.UNAVAILABLE, error=error, retryable=True)
    except Exception:
        error = StructuredError(ErrorCode.INTERNAL, "The guided request failed safely.", False)
        return GuidedResponse(PROTOCOL_VERSION, request.request_id, request.session_id, request.base_revision, Outcome.ERROR, error=error)
    parsed = GuidedResponse.from_provider(raw, request)
    if parsed is None:
        error = StructuredError(ErrorCode.MALFORMED_OUTPUT, "The provider returned an invalid response.", True)
        return GuidedResponse(PROTOCOL_VERSION, request.request_id, request.session_id, request.base_revision, Outcome.ERROR, error=error, retryable=True)
    return parsed


async def continue_session(store: GuidedSessionStore, provider: Provider | Callable[..., Awaitable[object]],
                           request: GuidedRequest, capabilities: Capabilities | None,
                           cancellation: CancellationToken | None = None) -> tuple[GuidedResponse, SessionState | None]:
    state = store.recover(request.session_id, request.authorization_binding)
    if state is None:
        error = StructuredError(ErrorCode.UNAUTHORIZED, "The session is unavailable.", False)
        return GuidedResponse(PROTOCOL_VERSION, request.request_id, request.session_id, request.base_revision, Outcome.ERROR, error=error), None
    if state.revision != request.base_revision:
        error = StructuredError(ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True)
        return GuidedResponse(PROTOCOL_VERSION, request.request_id, request.session_id, request.base_revision, Outcome.ERROR, error=error, retryable=True), None
    response = await invoke_bounded(provider, request, capabilities, cancellation)
    if response.outcome in {Outcome.ERROR, Outcome.UNAVAILABLE}:
        return response, None
    return response, store.commit(request, response)
