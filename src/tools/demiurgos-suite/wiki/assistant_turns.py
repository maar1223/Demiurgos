# -*- coding: utf-8 -*-
"""Assistant turn record (Phase 1, S5, task T1.4).

A failed assistant turn has to be diagnosable from a bug report without
shipping the prompt or the answer. One bounded JSONL record per turn carries
the run id, the tools that ran, the evidence state, the gate decision, the
model and the stage timings (S6: metadata only, the world is a hash).

It reuses :func:`operations_ring.append_bounded_record`, so both journals share
one set of bounds, one atomic compaction and one crash story.

The vocabulary is closed and defined here, not inherited from a provider:

- ``status``: ``completed`` (a terminal event arrived), ``failed`` (the stream
  closed without one for a reason a repair could explain), ``disconnected``
  (the client left) or ``unknown``.
- ``evidence_status``: ``complete`` when at least one world source reached the
  turn (an injected ficha or a tool that succeeded), ``incomplete`` when a tool
  was attempted and none succeeded, and ``none`` when nothing was used at all.
  It describes the evidence the turn had, not whether the answer arrived: a
  failed turn that did read the world is still ``complete`` here, and its
  failure shows in ``status``.
- ``error_code``: ``assistant.<close_reason>`` only for a turn that did not
  complete, so a report names why the answer never arrived.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

import state_paths
from operations_ring import (
    append_bounded_record,
    hash_world,
    iso_now,
    read_recent_records,
)

TURNS_FILENAME = "assistant-turns.jsonl"
MAX_TURNS = 100
MAX_BYTES = 256 * 1024
MAX_TOOLS = 20
MAX_NAME_CHARS = 80
EVIDENCE_STATUSES = frozenset({"complete", "incomplete", "none"})
STATUSES = frozenset({"completed", "failed", "disconnected", "unknown"})
#: Close reasons that mean the turn failed rather than being cut short by the
#: client or left in an undefined state.
FAILED_CLOSE_REASONS = frozenset(
    {"budget_exceeded", "silence_timeout", "stream_error"}
)


def default_turns_path() -> Path:
    """Where the turn journal lives: the state dir, beside the operations ring."""
    return state_paths.resolve_state_dir() / TURNS_FILENAME


def read_model_name(config_path: Path) -> str | None:
    """``model.default`` from a Hermes profile, or ``None`` when unreadable."""
    try:
        data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, Mapping):
        return None
    model = data.get("model")
    if not isinstance(model, Mapping):
        return None
    name = model.get("default")
    if isinstance(name, str) and name.strip():
        return name.strip()[:MAX_NAME_CHARS]
    return None


def _clip(value: object, limit: int = MAX_NAME_CHARS) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _int_or_none(value: object) -> int | None:
    try:
        return int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _normalize_tools(tools: object) -> list[dict[str, Any]]:
    if not isinstance(tools, (list, tuple)):
        return []
    normalized: list[dict[str, Any]] = []
    for raw in tools:
        if not isinstance(raw, Mapping):
            continue
        normalized.append(
            {
                "name": _clip(raw.get("name"), MAX_NAME_CHARS) or "",
                "ok": raw.get("ok") is True,
                "duration_ms": _int_or_none(raw.get("duration_ms")),
            }
        )
        if len(normalized) >= MAX_TOOLS:
            break
    return normalized


def _status_for(*, completed: bool, disconnected: bool, close_reason: str | None) -> str:
    if disconnected:
        return "disconnected"
    if completed:
        return "completed"
    if close_reason in FAILED_CLOSE_REASONS:
        return "failed"
    return "unknown"


def _evidence_for(*, tools: list[dict[str, Any]], context_count: int) -> str:
    if context_count > 0 or any(tool["ok"] for tool in tools):
        return "complete"
    if tools:
        return "incomplete"
    return "none"


def build_turn(
    *,
    request_id: str,
    run_id: str,
    world: object = None,
    model: str | None = None,
    semantic_state: str | None = None,
    semantic_action: str | None = None,
    completed: bool = False,
    disconnected: bool = False,
    tools: object = None,
    context_count: int = 0,
    gate_ms: object = None,
    run_ms: object = None,
    close_reason: str | None = None,
) -> dict[str, Any]:
    """The bounded, non-content record of one assistant turn."""
    normalized_tools = _normalize_tools(tools)
    status = _status_for(
        completed=completed, disconnected=disconnected, close_reason=close_reason
    )
    return {
        "request_id": _clip(request_id) or "",
        "run_id": _clip(run_id) or "",
        "world_hash": hash_world(world),
        "model": _clip(model),
        "semantic_state": _clip(semantic_state, 40),
        "semantic_action": _clip(semantic_action, 40),
        "evidence_status": _evidence_for(
            tools=normalized_tools,
            context_count=max(0, int(context_count or 0)),
        ),
        "tools": normalized_tools,
        "stage_timings": {"gate_ms": _int_or_none(gate_ms), "run_ms": _int_or_none(run_ms)},
        "status": status,
        "close_reason": _clip(close_reason, 40),
        "error_code": None if status == "completed" else f"assistant.{close_reason or 'unknown'}",
    }


def record_turn(
    turn: Mapping[str, Any],
    *,
    path: Path | None = None,
    max_turns: int = MAX_TURNS,
    max_bytes: int = MAX_BYTES,
) -> bool:
    """Append one turn record; ``False`` when storage refused it. Never raises."""
    if not isinstance(turn, Mapping):
        return False
    target = Path(path) if path is not None else default_turns_path()
    payload = dict(turn)
    payload.setdefault("ts", iso_now())
    return append_bounded_record(
        target, payload, max_entries=max_turns, max_bytes=max_bytes
    )


def recent_turns(
    *,
    limit: int = 20,
    path: Path | None = None,
    max_bytes: int = MAX_BYTES,
) -> list[dict[str, Any]]:
    """The newest turn records first; never raises."""
    target = Path(path) if path is not None else default_turns_path()
    return read_recent_records(target, limit=limit, max_bytes=max_bytes)
