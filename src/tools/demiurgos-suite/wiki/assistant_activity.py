"""Hermes runs activity adapter with fail-closed evidence handling.

The adapter uses only the documented Hermes API server contract. Hermes run
events identify the run and tool name, but do not expose a structured world
file result. Consequently this module reports verified graph tool lifecycle
activity while never treating labels, previews, or free text as file evidence.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, AsyncIterator, Callable, Mapping, Protocol

import httpx


INCOMPLETE_EVIDENCE_WARNING = "Evidence incomplete."
NEUTRAL_EVIDENCE_WARNING = "No confirmed world evidence."
SEARCH_WORLD_LABEL = "Search world"
READ_WORLD_LABEL = "Read world"
ACTIVITY_UNAVAILABLE_REASON = "file_evidence_contract_unverified"
PROVIDER_ACTIVITY_FAILURE_REASON = "provider_activity_unavailable"

_ALLOWLIST = {"graph_search": SEARCH_WORLD_LABEL, "graph_read": READ_WORLD_LABEL}
_VALID_SECTIONS = {"lore", "personajes", "referencias", "media"}
_INTERNAL_PATH_PARTS = {".papelera", ".history"}
_REQUIRED_FEATURES = (
    "run_submission",
    "run_status",
    "run_events_sse",
    "run_stop",
    "tool_progress_events",
)
_TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled"}


def _single_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class HermesCapabilities:
    """The stable, allowlisted capability facts used by this integration."""

    object_name: str
    platform: str
    features: frozenset[str]


@dataclass(frozen=True)
class CapabilityAssessment:
    admitted: bool
    reason: str
    capabilities: HermesCapabilities | None


def assess_hermes_capabilities(value: Mapping[str, Any]) -> CapabilityAssessment:
    """Admit only the documented runs/events/stop contract."""
    if not isinstance(value, Mapping):
        return CapabilityAssessment(False, ACTIVITY_UNAVAILABLE_REASON, None)
    object_name = value.get("object")
    platform = value.get("platform")
    features_value = value.get("features")
    if not _single_string(object_name) or not _single_string(platform):
        return CapabilityAssessment(False, ACTIVITY_UNAVAILABLE_REASON, None)
    if not isinstance(features_value, Mapping):
        return CapabilityAssessment(False, ACTIVITY_UNAVAILABLE_REASON, None)
    enabled = frozenset(
        name for name, enabled_value in features_value.items()
        if isinstance(name, str) and enabled_value is True
    )
    if not set(_REQUIRED_FEATURES).issubset(enabled):
        return CapabilityAssessment(False, ACTIVITY_UNAVAILABLE_REASON, None)
    return CapabilityAssessment(
        True,
        "",
        HermesCapabilities(object_name, platform, enabled),
    )


@dataclass(frozen=True)
class HermesActivityRequest:
    request_id: str
    prompt: str
    session_id: str = ""


class HermesActivityAdapter(Protocol):
    available: bool
    capability: CapabilityAssessment

    async def probe(self) -> CapabilityAssessment:
        """Probe the documented capability endpoint before enabling activity."""

    async def start(self, request: HermesActivityRequest) -> str:
        """Start one correlated run and return its opaque run id."""

    async def status(self, run_id: str) -> Mapping[str, Any]:
        """Read one documented run status for stream reconciliation."""

    async def cancel(self, run_id: str) -> None:
        """Stop one previously accepted run."""

    def events(self, run_id: str) -> AsyncIterator[Mapping[str, Any]]:
        """Yield structured events for one accepted run."""


class HermesRunsActivityAdapter:
    """HTTP adapter for Hermes' documented ``/v1/runs`` API."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str,
        client_provider: Callable[[], httpx.AsyncClient],
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client_provider = client_provider
        self.available = False
        self.capability = CapabilityAssessment(False, ACTIVITY_UNAVAILABLE_REASON, None)
        self._probed = False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def probe(self) -> CapabilityAssessment:
        if self._probed:
            return self.capability
        self._probed = True
        try:
            response = await self._client_provider().get(
                f"{self.base_url}/capabilities",
                headers=self._headers(),
            )
            if response.status_code != 200:
                self.capability = CapabilityAssessment(
                    False,
                    PROVIDER_ACTIVITY_FAILURE_REASON,
                    None,
                )
            else:
                self.capability = assess_hermes_capabilities(response.json())
        except Exception:
            self.capability = CapabilityAssessment(
                False,
                PROVIDER_ACTIVITY_FAILURE_REASON,
                None,
            )
        self.available = self.capability.admitted
        return self.capability

    async def start(self, request: HermesActivityRequest) -> str:
        payload: dict[str, str] = {"input": request.prompt}
        if request.session_id:
            payload["session_id"] = request.session_id
        response = await self._client_provider().post(
            f"{self.base_url}/runs",
            json=payload,
            headers=self._headers(),
        )
        if response.status_code not in {200, 202}:
            raise RuntimeError("Hermes run submission failed")
        body = response.json()
        run_id = body.get("run_id") if isinstance(body, Mapping) else None
        status = body.get("status") if isinstance(body, Mapping) else None
        if not _single_string(run_id) or not _single_string(status):
            raise RuntimeError("Hermes returned an invalid run submission")
        return run_id

    async def status(self, run_id: str) -> Mapping[str, Any]:
        response = await self._client_provider().get(
            f"{self.base_url}/runs/{run_id}",
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise RuntimeError("Hermes run status unavailable")
        body = response.json()
        if not isinstance(body, Mapping) or body.get("run_id") != run_id:
            raise RuntimeError("Hermes returned an invalid run status")
        return body

    async def cancel(self, run_id: str) -> None:
        response = await self._client_provider().post(
            f"{self.base_url}/runs/{run_id}/stop",
            headers=self._headers(),
        )
        if response.status_code not in {200, 202, 204}:
            raise RuntimeError("Hermes run stop failed")

    async def _event_stream(self, run_id: str) -> AsyncIterator[Mapping[str, Any]]:
        data_lines: list[str] = []
        async with self._client_provider().stream(
            "GET",
            f"{self.base_url}/runs/{run_id}/events",
            headers={**self._headers(), "Accept": "text/event-stream"},
        ) as response:
            if response.status_code != 200:
                raise RuntimeError("Hermes run events unavailable")
            async for line in response.aiter_lines():
                if line == "":
                    if data_lines:
                        try:
                            payload = json.loads("\n".join(data_lines))
                        except (TypeError, ValueError):
                            payload = None
                        if isinstance(payload, Mapping):
                            yield payload
                    data_lines = []
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
        if data_lines:
            try:
                payload = json.loads("\n".join(data_lines))
            except (TypeError, ValueError):
                payload = None
            if isinstance(payload, Mapping):
                yield payload

    def events(self, run_id: str) -> AsyncIterator[Mapping[str, Any]]:
        return self._event_stream(run_id)


class ActivityUnavailable(RuntimeError):
    """Raised when the provider contract has not been admitted."""


@dataclass(frozen=True)
class ActivityEvent:
    request_id: str
    item_id: str
    operation: str
    status: str
    path: str | None = None
    warning: str | None = None

    @property
    def kind(self) -> str:
        return "activity"

    def as_dict(self) -> dict[str, str]:
        result = {
            "kind": self.kind,
            "request_id": self.request_id,
            "item_id": self.item_id,
            "operation": self.operation,
            "status": self.status,
        }
        if self.path is not None:
            result["path"] = self.path
        if self.warning is not None:
            result["warning"] = self.warning
        return result


@dataclass(frozen=True)
class AnswerEvent:
    request_id: str
    response: str

    @property
    def kind(self) -> str:
        return "answer"

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "request_id": self.request_id, "response": self.response}


@dataclass(frozen=True)
class TerminalEvent:
    request_id: str
    status: str
    warning: str | None = None

    @property
    def kind(self) -> str:
        return "terminal"

    def as_dict(self) -> dict[str, str]:
        result = {"kind": self.kind, "request_id": self.request_id, "status": self.status}
        if self.warning is not None:
            result["warning"] = self.warning
        return result


@dataclass(frozen=True)
class SemanticDecisionEvent:
    """Authoritative typed semantic outcome emitted before compatible events.

    Built only from a server-validated semantic decision: ``state`` and
    ``action`` are server-derived, ``unavailable`` marks a fail-closed outcome,
    and ``continuation`` is a safely bounded serialized continuation or None.
    Consumers MUST use this event for permission/state decisions and never
    infer them from answer text. Legacy clients may ignore the additive event.
    """

    request_id: str
    state: str
    action: str
    unavailable: bool
    continuation: dict[str, Any] | None = None

    @property
    def kind(self) -> str:
        return "semantic_decision"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "request_id": self.request_id,
            "state": self.state,
            "action": self.action,
            "unavailable": self.unavailable,
            "continuation": self.continuation,
        }


class ActivityTranslator:
    """Translate only correlated, documented Hermes run events."""

    def __init__(
        self,
        *,
        capability: CapabilityAssessment | HermesCapabilities,
        request_id: str,
        run_id: str,
        session_id: str = "",
        world_root: Path | None = None,
    ) -> None:
        if isinstance(capability, HermesCapabilities):
            capability = CapabilityAssessment(True, "", capability)
        if not capability.admitted or capability.capabilities is None:
            raise ActivityUnavailable(ACTIVITY_UNAVAILABLE_REASON)
        self.capabilities = capability.capabilities
        self.request_id = request_id
        self.run_id = run_id
        self.session_id = session_id
        # ``None`` marks the world-agnostic (global) assistant context, which
        # has no world directory and therefore no file evidence paths.
        self.world_root = Path(world_root) if world_root is not None else None
        self._items: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self._public_item_ids: dict[tuple[str, int], str] = {}
        self._closed = False
        self._terminal_emitted = False
        self._answer_emitted = False
        self._answer_parts: list[str] = []
        self._saw_correlated_event = False
        self._ambiguous_tool_completion = False

    def translate(self, raw_event: Mapping[str, Any]) -> list[ActivityEvent | AnswerEvent | TerminalEvent]:
        if self._closed or not isinstance(raw_event, Mapping):
            return []
        if raw_event.get("run_id") != self.run_id:
            return []
        event_name = raw_event.get("event")
        if not isinstance(event_name, str):
            return []
        if self.session_id and raw_event.get("session_id") not in {None, self.session_id}:
            return []
        if event_name == "tool.started":
            translated = self._translate_started(raw_event)
            self._saw_correlated_event |= bool(translated)
            return translated
        if event_name == "tool.completed":
            translated = self._translate_completed(raw_event)
            self._saw_correlated_event |= bool(translated)
            return translated
        if event_name == "message.delta":
            translated = self._translate_delta(raw_event)
            self._saw_correlated_event |= bool(translated)
            return translated
        if event_name == "run.completed":
            self._saw_correlated_event = True
            return self._translate_terminal(raw_event, "succeeded")
        if event_name in {"run.failed", "run.cancelled"}:
            self._saw_correlated_event = True
            return self._translate_terminal(raw_event, "failed")
        return []

    def finalize(self) -> list[TerminalEvent | AnswerEvent]:
        if self._terminal_emitted or self._closed:
            return []
        warning = INCOMPLETE_EVIDENCE_WARNING if self._saw_correlated_event else NEUTRAL_EVIDENCE_WARNING
        events: list[TerminalEvent | AnswerEvent] = []
        if self._answer_parts and not self._answer_emitted:
            self._answer_emitted = True
            events.append(AnswerEvent(self.request_id, "".join(self._answer_parts)))
        events.append(self._close("unknown", warning)[0])
        return events

    def _translate_started(self, raw_event: Mapping[str, Any]) -> list[ActivityEvent]:
        canonical = self._canonical_tool(raw_event.get("tool"))
        if canonical is None:
            return []
        index = len(self._items[canonical])
        public_item_id = f"item-{sum(len(items) for items in self._items.values()) + 1}"
        self._items[canonical].append((public_item_id, "running"))
        self._public_item_ids[(canonical, index)] = public_item_id
        return [ActivityEvent(self.request_id, public_item_id, _ALLOWLIST[canonical], "running")]

    def _translate_completed(self, raw_event: Mapping[str, Any]) -> list[ActivityEvent]:
        canonical = self._canonical_tool(raw_event.get("tool"))
        error = raw_event.get("error")
        if canonical is None or not isinstance(error, bool):
            return []
        running = [item for item in self._items[canonical] if item[1] == "running"]
        if len(running) != 1:
            self._ambiguous_tool_completion = True
            return []
        public_item_id, _ = running[0]
        next_status = "failed" if error else "succeeded"
        self._items[canonical] = [
            (item_id, next_status if item_id == public_item_id else status)
            for item_id, status in self._items[canonical]
        ]
        return [
            ActivityEvent(
                self.request_id,
                public_item_id,
                _ALLOWLIST[canonical],
                next_status,
                warning=INCOMPLETE_EVIDENCE_WARNING if error else None,
            )
        ]

    def _translate_delta(self, raw_event: Mapping[str, Any]) -> list[AnswerEvent]:
        delta = raw_event.get("delta")
        if not isinstance(delta, str) or not delta:
            return []
        self._answer_parts.append(delta)
        self._answer_emitted = True
        return [AnswerEvent(self.request_id, "".join(self._answer_parts))]

    def _translate_terminal(
        self,
        raw_event: Mapping[str, Any],
        status: str,
    ) -> list[AnswerEvent | TerminalEvent]:
        events: list[AnswerEvent | TerminalEvent] = []
        output = raw_event.get("output")
        if isinstance(output, str) and output and not self._answer_emitted:
            self._answer_emitted = True
            events.append(AnswerEvent(self.request_id, output))
        warning = None
        if status != "succeeded" or self._ambiguous_tool_completion:
            warning = INCOMPLETE_EVIDENCE_WARNING
        events.append(self._close(status, warning)[0])
        return events

    def _close(self, status: str, warning: str | None) -> list[TerminalEvent]:
        if self._terminal_emitted:
            return []
        self._closed = True
        self._terminal_emitted = True
        return [TerminalEvent(self.request_id, status, warning)]

    @staticmethod
    def _canonical_tool(raw_tool: object) -> str | None:
        if not _single_string(raw_tool):
            return None
        # Hermes prefixes MCP tools as ``mcp__<server>__<tool>``. Normalize so
        # the graph tools (graph_search / graph_read) are recognized regardless
        # of the MCP server name, and the activity chips still surface. Only
        # strip the MCP prefix; a bare ``graph_search`` stays as-is.
        normalized = raw_tool
        if normalized.startswith("mcp__") and "__" in normalized:
            parts = normalized.split("__", 2)
            if len(parts) == 3:
                normalized = parts[2]
        return normalized if normalized in _ALLOWLIST else None


def validate_structured_world_path(world_root: Path, raw_path: object) -> str | None:
    """Return a logical world-relative path only after canonical containment."""
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
        return None
    if "/" in raw_path and "\\" in raw_path:
        return None
    if PureWindowsPath(raw_path).is_absolute() or raw_path.startswith(("/", "\\")):
        return None

    normalized = raw_path.replace("\\", "/")
    parts = normalized.split("/")
    if not parts or any(not part or part in (".", "..") for part in parts):
        return None
    if parts[0] not in _VALID_SECTIONS or any(part in _INTERNAL_PATH_PARTS for part in parts):
        return None
    if any(part.startswith(".") for part in parts):
        return None

    root = Path(world_root).resolve()
    try:
        candidate = (root / Path(*parts)).resolve()
        relative = candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    if not candidate.is_file() or not relative.parts or relative.parts[0] not in _VALID_SECTIONS:
        return None
    return "/".join(relative.parts)
