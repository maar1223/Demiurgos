# -*- coding: utf-8 -*-
"""Assistant turn record (Phase 1, S5, task T1.4).

The report has to explain a failed assistant turn without shipping a prompt or
an answer: one bounded JSONL record per turn with the run id, the tools that
ran, the evidence state, the gate decision, the model and the stage timings.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from operations_ring import hash_world  # noqa: E402
from assistant_turns import (  # noqa: E402
    MAX_TOOLS,
    build_turn,
    read_model_name,
    recent_turns,
    record_turn,
)


def _turn(**overrides) -> dict:
    base = {
        "request_id": "activity-1",
        "run_id": "run-1",
        "world": "Vibrantes",
        "model": "deepseek-v4",
        "semantic_state": "allow",
        "semantic_action": "answer",
        "completed": True,
        "tools": [{"name": "graph_search", "ok": True, "duration_ms": 120}],
        "context_count": 0,
        "gate_ms": 800,
        "run_ms": 4200,
        "close_reason": "terminal_completed",
    }
    base.update(overrides)
    return build_turn(**base)


# --- evidence and status mapping -------------------------------------------


def test_a_completed_turn_with_a_tool_counts_as_complete_evidence():
    turn = _turn()
    assert turn["evidence_status"] == "complete"
    assert turn["status"] == "completed"
    assert turn["error_code"] is None


def test_a_completed_turn_without_any_evidence_is_reported_as_none():
    turn = _turn(tools=[], context_count=0)
    assert turn["evidence_status"] == "none"


def test_injected_context_counts_as_evidence():
    turn = _turn(tools=[], context_count=2)
    assert turn["evidence_status"] == "complete"


def test_a_turn_that_closed_without_terminal_is_incomplete_and_named():
    turn = _turn(completed=False, close_reason="silence_timeout", run_ms=9000)
    assert turn["evidence_status"] == "complete"  # a tool did succeed
    assert turn["status"] == "failed"
    assert turn["error_code"] == "assistant.silence_timeout"


def test_a_tool_that_failed_is_incomplete_evidence():
    turn = _turn(tools=[{"name": "graph_search", "ok": False, "duration_ms": 5}])
    assert turn["evidence_status"] == "incomplete"


def test_a_disconnected_turn_is_reported_as_disconnected():
    turn = _turn(completed=False, disconnected=True)
    assert turn["status"] == "disconnected"


def test_a_budget_close_is_a_failure():
    assert _turn(completed=False, close_reason="budget_exceeded")["status"] == "failed"


def test_an_unknown_close_reason_is_not_guessed():
    turn = _turn(completed=False, close_reason="stream_ended")
    assert turn["status"] == "unknown"


# --- schema discipline -----------------------------------------------------


def test_the_world_is_stored_only_as_a_hash():
    turn = _turn()
    assert "Vibrantes" not in json.dumps(turn)
    assert turn["world_hash"] == hash_world("Vibrantes")


def test_the_tool_list_is_bounded_and_each_name_clipped():
    tools = [{"name": "t" * 200, "ok": True, "duration_ms": 1} for _ in range(MAX_TOOLS + 5)]
    turn = _turn(tools=tools)
    assert len(turn["tools"]) == MAX_TOOLS
    assert all(len(tool["name"]) <= 80 for tool in turn["tools"])


def test_stage_timings_are_integers_or_none():
    turn = _turn(gate_ms=None, run_ms=12.4)
    assert turn["stage_timings"] == {"gate_ms": None, "run_ms": 12}


# --- storage ---------------------------------------------------------------


def test_a_recorded_turn_survives_a_new_process_read(tmp_path):
    ring = tmp_path / "assistant-turns.jsonl"

    assert record_turn(_turn(), path=ring)

    turns = recent_turns(path=ring)
    assert len(turns) == 1
    assert turns[0]["run_id"] == "run-1"
    assert turns[0]["ts"]


def test_turns_are_kept_newest_first_and_capped(tmp_path):
    ring = tmp_path / "assistant-turns.jsonl"
    for index in range(5):
        record_turn(_turn(run_id=f"run-{index}"), path=ring, max_turns=3)

    turns = recent_turns(path=ring)
    assert [turn["run_id"] for turn in turns] == ["run-4", "run-3", "run-2"]


def test_an_unwritable_turn_file_never_raises(tmp_path):
    blocked = tmp_path / "turns-as-directory"
    blocked.mkdir()

    assert record_turn(_turn(), path=blocked) is False
    assert recent_turns(path=blocked) == []


# --- model identity --------------------------------------------------------


def test_the_model_name_is_read_from_the_profile(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("model:\n  default: deepseek-v4\n  provider: custom\n", encoding="utf-8")
    assert read_model_name(config) == "deepseek-v4"


def test_a_missing_or_broken_profile_yields_no_model(tmp_path):
    assert read_model_name(tmp_path / "absent.yaml") is None
    broken = tmp_path / "broken.yaml"
    broken.write_text("model: [\n", encoding="utf-8")
    assert read_model_name(broken) is None
    empty = tmp_path / "empty.yaml"
    empty.write_text("logging:\n  level: info\n", encoding="utf-8")
    assert read_model_name(empty) is None
