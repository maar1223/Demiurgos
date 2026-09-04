"""Backend-owned contracts and state boundary for Skill Madre co-creation.

Mirrors the guided-character protocol seam: Hermes is treated as an untrusted,
bounded proposal provider; the durable store is the authoritative state
boundary. The Hermes boundary (REQ-CC-7) is enforced here at the envelope
layer: authority keys (flat or nested, up to depth 4) are rejected before any
parsed response can reach the store, and malformed/unavailable output fails
closed with zero mutations.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable, Literal, Mapping, Protocol


PROTOCOL_VERSION = "co-creation-v1"
DEFAULT_DEADLINE_MS = 30_000
MAX_DEADLINE_MS = 30_000
QUESTION_CEILING = 20
MAX_QUESTION_OPTIONS = 5

MILESTONES = (
    "proposito",
    "alcance",
    "flujo_principal",
    "ramas_reglas",
    "borrador_listo",
    "revision_publicacion",
)

# Authority keys Hermes must NEVER emit (flat or nested). Presence anywhere in
# the envelope (up to depth 4) fails closed as an invalid envelope.
AUTHORITY_KEYS = frozenset({
    "target",
    "digest",
    "revision",
    "authority",
    "reference",
    "acceptance",
    "accepted_canon",
    "authorization",
})

_MILESTONE_STATES = frozenset({"completado", "actual", "pendiente"})

# Canvas-sync envelope extension keys (REQ-CC-23). The canvas PUT request body
# adds exactly these two keys at the envelope level; both stay OUTSIDE the
# 8-key AUTHORITY_KEYS set so REQ-CC-7 envelope validation passes by
# construction. Never add an authority-key-adjacent name here.
CANVAS_SYNC_ENVELOPE_KEYS = frozenset({"base_revision", "payload"})

# The typed, Author-editable structured draft sections exposed by the canvas
# (REQ-CC-11). ``branches``/``rules``/``pending_questions`` are lists; the rest
# are plain strings. ``pending_questions`` is chat-owned (REQ-CC-14): the
# canvas may display it but never authors it.
CANVAS_PAYLOAD_KEYS = frozenset({
    "name",
    "description",
    "purpose",
    "scope",
    "main_flow",
    "branches",
    "rules",
    "pending_questions",
    "world",
})


class WarningState(StrEnum):
    """Three-state draft-review warning lifecycle (REQ-CC-13).

    Pending warnings NEVER auto-correct; only the Author transitions out of
    ``PENDIENTE`` (``RESUELTA`` or ``ACEPTADA_POR_AUTOR``).
    """

    PENDIENTE = "pendiente"
    RESUELTA = "resuelta"
    ACEPTADA_POR_AUTOR = "aceptada_por_autor"


class HistorySource(StrEnum):
    """Origin of an immutable draft-history snapshot (REQ-CC-15)."""

    AUTHOR = "author"
    CHAT = "chat"
    AUTOSAVE = "autosave"


def canvas_payload_issues(payload: Mapping[str, Any]) -> list[str]:
    """Validate a canvas payload against the typed editable-key contract.

    Returns a list of human-readable issue strings; an empty list means the
    payload is admissible. Authority keys (flat or nested, depth <= 4) are an
    envelope violation (REQ-CC-7 / REQ-CC-23); unknown keys and non-list
    ``branches``/``rules`` are shape violations (REQ-CC-11).
    ``pending_questions`` entries may be plain strings or ``{text, state}``
    objects (the chat-appended wire shape) — the canvas never authors them.
    """
    issues: list[str] = []
    if reject_authority_keys(payload):
        issues.append("authority keys are not allowed in a canvas payload")
    for key in payload:
        if key not in CANVAS_PAYLOAD_KEYS:
            issues.append(f"unknown canvas payload key {key!r}")
    for key in ("branches", "rules"):
        value = payload.get(key)
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            issues.append(f"{key} must be a list of strings")
    for key in CANVAS_PAYLOAD_KEYS - {"branches", "rules", "pending_questions"}:
        value = payload.get(key)
        if value is not None and not isinstance(value, str):
            issues.append(f"{key} must be a string")
    return issues


def reject_authority_keys(value: object, depth: int = 0) -> bool:
    """Return True when any authority key is found (flat or nested).

    Mirrors the ``semantic_intent.py`` / ``assistantActivity.ts`` precedent:
    keys are rejected at any nesting level up to depth 4; anything deeper is
    treated as found so the envelope fails closed rather than trusting an
    arbitrarily deep payload. Recurses through both mappings and sequences so
    keys nested inside arrays (e.g. ``progress[].target``) cannot slip past
    the boundary.
    """
    if depth > 4:
        return True
    if isinstance(value, Mapping):
        return any(
            key in AUTHORITY_KEYS or reject_authority_keys(item, depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(reject_authority_keys(item, depth + 1) for item in value)
    return False


class ErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MALFORMED_OUTPUT = "malformed_output"
    INVALID_ENVELOPE = "invalid_envelope"
    UNAUTHORIZED = "unauthorized"
    REVISION_CONFLICT = "revision_conflict"
    CEILING_REACHED = "ceiling_reached"
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
    co_creation_v1: bool
    cancellation: bool
    structured_output: bool
    max_deadline_ms: int

    @classmethod
    def from_payload(cls, payload: object) -> "Capabilities | None":
        if not isinstance(payload, Mapping):
            return None
        values = {
            "protocol_version", "co_creation_v1", "cancellation",
            "structured_output", "max_deadline_ms",
        }
        if set(payload) & values != values:
            return None
        deadline = payload["max_deadline_ms"]
        if not isinstance(deadline, int) or isinstance(deadline, bool) or deadline <= 0:
            return None
        if not isinstance(payload["protocol_version"], str):
            return None
        if not all(
            isinstance(payload[name], bool)
            for name in ("co_creation_v1", "cancellation", "structured_output")
        ):
            return None
        return cls(
            protocol_version=payload["protocol_version"],
            co_creation_v1=payload["co_creation_v1"],
            cancellation=payload["cancellation"],
            structured_output=payload["structured_output"],
            max_deadline_ms=deadline,
        )

    def admitted(self) -> bool:
        return (
            self.protocol_version == PROTOCOL_VERSION
            and self.co_creation_v1
            and self.cancellation
            and self.structured_output
            and self.max_deadline_ms > 0
        )


@dataclass(frozen=True)
class CoCreationRequest:
    protocol_version: str
    request_id: str
    session_id: str
    principal_id: str
    base_revision: int
    authorization_binding: str
    author_input: str
    world: str | None = None
    deadline_ms: int = DEFAULT_DEADLINE_MS
    context_budget: int = 4_000
    milestone: str | None = None

    def validate(self) -> StructuredError | None:
        if (
            self.protocol_version != PROTOCOL_VERSION
            or not all(
                isinstance(value, str) and value.strip()
                for value in (
                    self.request_id, self.session_id, self.principal_id,
                    self.authorization_binding, self.author_input,
                )
            )
            or self.base_revision < 0
            or self.context_budget <= 0
            or (self.world is not None and (not isinstance(self.world, str) or not self.world.strip()))
            or (self.milestone is not None and self.milestone not in MILESTONES)
        ):
            return StructuredError(ErrorCode.INVALID_INPUT, "The co-creation request is invalid.", False)
        if not 1 <= self.deadline_ms <= MAX_DEADLINE_MS:
            return StructuredError(ErrorCode.INVALID_INPUT, "The deadline is outside the allowed bounds.", False)
        return None


class CoCreationOutcome(StrEnum):
    QUESTION = "question"
    MILESTONE_DELTA = "milestone_delta"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class MilestoneState:
    name: str
    state: Literal["completado", "actual", "pendiente"]


def initial_milestone_states() -> tuple[MilestoneState, ...]:
    """Six milestones with only ``proposito`` active and the rest pending."""
    return tuple(
        MilestoneState(name, "actual" if index == 0 else "pendiente")
        for index, name in enumerate(MILESTONES)
    )


def states_for_milestone(milestone_name: str) -> tuple[MilestoneState, ...]:
    """Milestone states for a session currently at ``milestone_name``."""
    index = MILESTONES.index(milestone_name)
    return tuple(
        MilestoneState(
            name,
            "completado" if position < index
            else ("actual" if position == index else "pendiente"),
        )
        for position, name in enumerate(MILESTONES)
    )


def advance_milestone(states: tuple[MilestoneState, ...]) -> tuple[MilestoneState, ...]:
    """Mark the active milestone completed and activate the next one.

    The final milestone never advances past itself: ``revision_publicacion``
    stays active until the session is explicitly completed by the Author.
    """
    active = next(
        (index for index, item in enumerate(states) if item.state == "actual"),
        None,
    )
    if active is None or active >= len(MILESTONES) - 1:
        return states
    return tuple(
        MilestoneState(
            item.name,
            "completado" if position == active
            else ("actual" if position == active + 1 else item.state),
        )
        for position, item in enumerate(states)
    )


@dataclass(frozen=True)
class CoCreationResponse:
    protocol_version: str
    request_id: str
    session_id: str
    base_revision: int
    outcome: CoCreationOutcome
    question: str | None = None
    options: tuple[str, ...] = ()
    milestone: str | None = None
    progress: tuple[MilestoneState, ...] | None = None
    provenance: tuple[str, ...] = ()
    provider_run_id: str | None = None
    error: StructuredError | None = None

    @classmethod
    def from_provider(cls, value: object, request: CoCreationRequest) -> "CoCreationResponse | None":
        """Strictly parse a provider envelope; ``None`` means fail closed.

        Authority keys anywhere in the envelope (flat or nested) reject the
        envelope before any field is trusted. ``error`` payloads are parsed
        best-effort for display only; they never carry state authority.
        """
        if not isinstance(value, Mapping) or value.get("protocol_version") != PROTOCOL_VERSION:
            return None
        if value.get("request_id") != request.request_id or value.get("session_id") != request.session_id:
            return None
        if reject_authority_keys(value):
            return None
        try:
            outcome = CoCreationOutcome(value["outcome"])
        except (KeyError, ValueError):
            return None
        question = value.get("question")
        if outcome is CoCreationOutcome.QUESTION and (
            not isinstance(question, str) or not question.strip()
        ):
            return None
        milestone = value.get("milestone")
        if outcome is CoCreationOutcome.MILESTONE_DELTA and (
            not isinstance(milestone, str) or milestone not in MILESTONES
        ):
            return None
        options_raw = value.get("options", ())
        if options_raw is not None:
            if (
                not isinstance(options_raw, (list, tuple))
                or len(options_raw) > MAX_QUESTION_OPTIONS
                or not all(isinstance(item, str) and item.strip() for item in options_raw)
            ):
                return None
            options = tuple(options_raw)
        else:
            options = ()
        progress_raw = value.get("progress")
        progress: tuple[MilestoneState, ...] | None = None
        if progress_raw is not None:
            if not isinstance(progress_raw, (list, tuple)) or len(progress_raw) != len(MILESTONES):
                return None
            parsed: list[MilestoneState] = []
            for item in progress_raw:
                if (
                    not isinstance(item, Mapping)
                    or not isinstance(item.get("name"), str)
                    or item["name"] not in MILESTONES
                    or item.get("state") not in _MILESTONE_STATES
                ):
                    return None
                parsed.append(MilestoneState(item["name"], item["state"]))
            progress = tuple(parsed)
        provenance = value.get("provenance", ())
        if not isinstance(provenance, (list, tuple)) or not all(
            isinstance(item, str) for item in provenance
        ):
            return None
        run_id = value.get("provider_run_id")
        return cls(
            PROTOCOL_VERSION,
            request.request_id,
            request.session_id,
            request.base_revision,
            outcome,
            question=question if isinstance(question, str) else None,
            options=options,
            milestone=milestone if isinstance(milestone, str) else None,
            progress=progress,
            provenance=tuple(provenance),
            provider_run_id=run_id if isinstance(run_id, str) else None,
            error=_parse_error(value.get("error")),
        )


def _parse_error(value: object) -> StructuredError | None:
    if not isinstance(value, Mapping):
        return None
    code = value.get("code")
    message = value.get("message")
    if not isinstance(code, str) or not isinstance(message, str):
        return None
    try:
        return StructuredError(ErrorCode(code), message, value.get("retryable") is True)
    except ValueError:
        return None


@dataclass(frozen=True)
class CoCreationMessage:
    role: Literal["author", "assistant"]
    content: str
    revision: int


@dataclass(frozen=True)
class DerivedFrom:
    """Server-injected parent identity for a derived draft (TW14).

    Read from the PUBLISHED record by the server; the client never supplies
    it. Phase 2 populates it — Phase 1 stores and exposes the (None) field.
    """

    skill_id: str
    version: str


@dataclass
class DraftHistoryEntry:
    """One immutable autosave snapshot (REQ-CC-15).

    ``payload`` is the full draft payload AT the snapshot's revision; the list
    is append-only and capped (~50 per session, oldest evicted).
    """

    revision: int
    payload: dict[str, Any]
    source: Literal["author", "chat", "autosave"]
    ts: str  # ISO 8601


@dataclass
class DraftWarning:
    """A validation-panel warning with a 3-state lifecycle (REQ-CC-13)."""

    code: str
    message: str
    field: str | None
    state: Literal["pendiente", "resuelta", "aceptada_por_autor"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "state": self.state,
        }


@dataclass
class CoCreationSessionState:
    session_id: str
    principal_id: str
    world: str | None
    revision: int
    authorization_binding: str
    milestone: str
    milestone_states: tuple[MilestoneState, ...]
    question_count: int
    draft_payload: dict[str, Any] = field(default_factory=dict)
    messages: list[CoCreationMessage] = field(default_factory=list)
    pending_question: str | None = None
    pending_options: tuple[str, ...] = ()
    draft_id: str | None = None
    phase: str = "conversation"
    # TW12 canvas data layer (Phase 1): immutable autosave history, 3-state
    # warnings, and the (server-injected, Phase 2) provenance field.
    draft_history: list[DraftHistoryEntry] = field(default_factory=list)
    warnings: list[DraftWarning] = field(default_factory=list)
    derived_from: DerivedFrom | None = None


class Provider(Protocol):
    async def invoke(self, request: CoCreationRequest, cancellation: "CancellationToken") -> object: ...


class CancellationToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


async def invoke_bounded_co_creation(
    provider: Provider | Callable[..., Awaitable[object]],
    request: CoCreationRequest,
    capabilities: Capabilities | None,
    cancellation: CancellationToken | None = None,
) -> CoCreationResponse:
    """Invoke only an admitted provider; no parsed output is committed here."""
    invalid = request.validate()
    if invalid:
        return CoCreationResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id,
            request.base_revision, CoCreationOutcome.ERROR, error=invalid,
        )
    if capabilities is None or not capabilities.admitted() or request.deadline_ms > capabilities.max_deadline_ms:
        return CoCreationResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id,
            request.base_revision, CoCreationOutcome.UNAVAILABLE,
            error=StructuredError(
                ErrorCode.CAPABILITY_UNAVAILABLE,
                "The co-creation provider is unavailable.", True,
            ),
        )
    token = cancellation or CancellationToken()
    if token.cancelled:
        return CoCreationResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id,
            request.base_revision, CoCreationOutcome.ERROR,
            error=StructuredError(ErrorCode.CANCELLED, "The co-creation request was cancelled.", True),
        )
    try:
        call = provider.invoke(request, token) if hasattr(provider, "invoke") else provider(request, token)
        raw = await asyncio.wait_for(call, request.deadline_ms / 1000)
    except asyncio.TimeoutError:
        token.cancel()
        return CoCreationResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id,
            request.base_revision, CoCreationOutcome.ERROR,
            error=StructuredError(ErrorCode.TIMEOUT, "The co-creation provider timed out.", True),
        )
    except asyncio.CancelledError:
        token.cancel()
        return CoCreationResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id,
            request.base_revision, CoCreationOutcome.ERROR,
            error=StructuredError(ErrorCode.CANCELLED, "The co-creation request was cancelled.", True),
        )
    except (ConnectionError, OSError):
        return CoCreationResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id,
            request.base_revision, CoCreationOutcome.UNAVAILABLE,
            error=StructuredError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "The co-creation provider is unavailable.", True,
            ),
        )
    except Exception:
        return CoCreationResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id,
            request.base_revision, CoCreationOutcome.ERROR,
            error=StructuredError(ErrorCode.INTERNAL, "The co-creation request failed safely.", False),
        )
    parsed = CoCreationResponse.from_provider(raw, request)
    if parsed is None:
        return CoCreationResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id,
            request.base_revision, CoCreationOutcome.ERROR,
            error=StructuredError(
                ErrorCode.MALFORMED_OUTPUT,
                "The provider returned an invalid response.", True,
            ),
        )
    return parsed


async def continue_co_creation_session(
    store: Any,
    provider: Provider | Callable[..., Awaitable[object]],
    request: CoCreationRequest,
    capabilities: Capabilities | None,
    cancellation: CancellationToken | None = None,
) -> tuple[CoCreationResponse, CoCreationSessionState | None]:
    """Recover, gate, and commit one co-creation turn.

    Fail-closed gates, in order: unknown/wrong-principal session, completed
    session, stale revision, question ceiling (BEFORE any Hermes call). A
    committed response is the only mutation path.
    """
    state = store.recover(request.session_id, request.authorization_binding)
    if state is None:
        error = StructuredError(ErrorCode.UNAUTHORIZED, "The co-creation session is unavailable.", False)
        return CoCreationResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id,
            request.base_revision, CoCreationOutcome.ERROR, error=error,
        ), None
    if state.phase == "complete":
        error = StructuredError(ErrorCode.INVALID_INPUT, "The co-creation session is complete.", False)
        return CoCreationResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id,
            request.base_revision, CoCreationOutcome.ERROR, error=error,
        ), None
    if state.revision != request.base_revision:
        error = StructuredError(ErrorCode.REVISION_CONFLICT, "The session revision is stale.", True)
        return CoCreationResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id,
            request.base_revision, CoCreationOutcome.ERROR, error=error,
        ), None
    if state.question_count >= QUESTION_CEILING:
        error = StructuredError(
            ErrorCode.CEILING_REACHED,
            "The session reached the question ceiling.", False,
        )
        return CoCreationResponse(
            PROTOCOL_VERSION, request.request_id, request.session_id,
            request.base_revision, CoCreationOutcome.ERROR, error=error,
        ), None
    response = await invoke_bounded_co_creation(provider, request, capabilities, cancellation)
    if response.outcome in {CoCreationOutcome.ERROR, CoCreationOutcome.UNAVAILABLE}:
        return response, None
    return response, store.commit(request, response)