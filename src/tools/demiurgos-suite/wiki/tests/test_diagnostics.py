# -*- coding: utf-8 -*-
"""Diagnostics document (Phase 1, S5/S6, task T1.5).

The bug report carries one structured ``diagnostics`` document: the newest
operations and assistant turns, already bounded and redacted, with no world
text, prompt body, answer body, ``.env`` value or account identity (S6).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import assistant_turns  # noqa: E402
import operations_ring  # noqa: E402
from assistant_turns import build_turn, record_turn  # noqa: E402
from operations_ring import append_bounded_record, hash_world  # noqa: E402

import diagnostics  # noqa: E402


def _ops_path(tmp_path: Path) -> Path:
    return tmp_path / "operations-ring.jsonl"


def _turns_path(tmp_path: Path) -> Path:
    return tmp_path / "assistant-turns.jsonl"


def _operation(run_id: str, ts: str, **overrides) -> dict:
    record = {
        "ts": ts,
        "run_id": run_id,
        "method": "POST",
        "endpoint": "/api/{mundo}/import",
        "world_hash": None,
        "status": 200,
        "duration_ms": 5,
        "error_code": None,
    }
    record.update(overrides)
    return record


def _append_operation(path: Path, record: dict) -> None:
    assert append_bounded_record(
        path,
        record,
        max_entries=operations_ring.MAX_ENTRIES,
        max_bytes=operations_ring.MAX_BYTES,
    )


def test_shape_and_schema_with_two_seeded_journals(tmp_path: Path) -> None:
    ops = _ops_path(tmp_path)
    turns = _turns_path(tmp_path)
    for index in range(3):
        _append_operation(ops, _operation("op-%d" % index, "2026-11-24T00:00:0%dZ" % index))
    for index in range(2):
        assert record_turn(
            build_turn(
                request_id="req-%d" % index,
                run_id="run-%d" % index,
                world="Vibrantes",
                completed=True,
                tools=[{"name": "graph_search", "ok": True, "duration_ms": 3}],
            ),
            path=turns,
        )

    document = diagnostics.build_diagnostics(
        operations_path=ops,
        turns_path=turns,
        generated_at="2026-11-24T00:00:00Z",
    )

    assert document["schema"] == diagnostics.SCHEMA
    assert document["generated_at"] == "2026-11-24T00:00:00Z"
    assert document["truncated"] is False
    assert document["redacted_lines"] == 0

    operations = document["operations"]
    assert operations["kept"] == 3
    assert operations["limit"] == diagnostics.DEFAULT_OPERATIONS
    assert operations["max_entries"] == operations_ring.MAX_ENTRIES
    # Newest-first, as both journal readers return them.
    assert [record["run_id"] for record in operations["records"]] == [
        "op-2",
        "op-1",
        "op-0",
    ]

    turns_doc = document["assistant_turns"]
    assert turns_doc["kept"] == 2
    assert turns_doc["limit"] == diagnostics.DEFAULT_TURNS
    assert turns_doc["max_entries"] == assistant_turns.MAX_TURNS
    assert len(turns_doc["records"]) == 2


def test_byte_budget_drops_the_oldest_record(tmp_path: Path) -> None:
    ops = _ops_path(tmp_path)
    # Fewer than DEFAULT_OPERATIONS so every record is read: the only reason
    # the oldest disappears is the byte budget, not the reader's limit.
    for index in range(40):
        _append_operation(
            ops,
            _operation("op-%02d" % index, "2026-11-24T00:%02d:00Z" % index),
        )

    document = diagnostics.build_diagnostics(
        operations_path=ops,
        turns_path=tmp_path / "absent-turns.jsonl",
        max_bytes=600,
    )

    encoded = json.dumps(document, sort_keys=True, ensure_ascii=False).encode("utf-8")
    assert len(encoded) <= 600
    assert document["truncated"] is True
    kept_ids = [record["run_id"] for record in document["operations"]["records"]]
    assert "op-39" in kept_ids  # the newest record survives
    assert "op-00" not in kept_ids  # the oldest record is dropped
    assert document["operations"]["kept"] == len(kept_ids)


def test_a_secret_value_is_redacted_and_counted(tmp_path: Path) -> None:
    ops = _ops_path(tmp_path)
    secret = "sk-" + "a" * 40
    _append_operation(
        ops,
        _operation("op-secret", "2026-11-24T00:00:00Z", endpoint="leak " + secret),
    )

    document = diagnostics.build_diagnostics(
        operations_path=ops,
        turns_path=tmp_path / "absent-turns.jsonl",
    )

    dumped = json.dumps(document, ensure_ascii=False)
    assert secret not in dumped
    assert "[redacted:" in dumped
    assert document["redacted_lines"] >= 1


def test_a_world_name_never_reaches_the_document(tmp_path: Path) -> None:
    turns = _turns_path(tmp_path)
    assert record_turn(
        build_turn(
            request_id="req-world",
            run_id="run-world",
            world="Vibrantes",
            completed=True,
            tools=[{"name": "graph_search", "ok": True, "duration_ms": 4}],
        ),
        path=turns,
    )

    document = diagnostics.build_diagnostics(
        operations_path=tmp_path / "absent-operations.jsonl",
        turns_path=turns,
    )

    dumped = json.dumps(document, ensure_ascii=False)
    assert "Vibrantes" not in dumped
    record = document["assistant_turns"]["records"][0]
    assert record["world_hash"] == hash_world("Vibrantes")


def test_missing_journals_produce_the_empty_shape(tmp_path: Path) -> None:
    document = diagnostics.build_diagnostics(
        operations_path=tmp_path / "does-not-exist-ops.jsonl",
        turns_path=tmp_path / "does-not-exist-turns.jsonl",
    )

    assert document["schema"] == diagnostics.SCHEMA
    assert document["truncated"] is False
    assert document["redacted_lines"] == 0
    assert document["operations"] == {
        "records": [],
        "kept": 0,
        "limit": diagnostics.DEFAULT_OPERATIONS,
        "max_entries": operations_ring.MAX_ENTRIES,
    }
    assert document["assistant_turns"] == {
        "records": [],
        "kept": 0,
        "limit": diagnostics.DEFAULT_TURNS,
        "max_entries": assistant_turns.MAX_TURNS,
    }


def test_cli_writes_the_same_document(tmp_path: Path) -> None:
    out = tmp_path / "diagnostics.json"
    assert diagnostics.main(["--out", str(out)]) == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    expected = diagnostics.build_diagnostics()
    assert set(written) == set(expected)
    assert written["schema"] == diagnostics.SCHEMA
    assert written["operations"]["records"] == expected["operations"]["records"]


def test_cli_on_an_unwritable_out_path_returns_one(tmp_path: Path) -> None:
    out = tmp_path / "missing-parent" / "diagnostics.json"
    assert diagnostics.main(["--out", str(out)]) == 1


# --- review follow-ups (verifier probes, T1.5) -----------------------------


def test_default_budget_trims_oldest_across_both_journals(tmp_path: Path) -> None:
    """S5/S6: a heavy pair of journals still fits MAX_BYTES, newest kept."""
    ops = _ops_path(tmp_path)
    turns = _turns_path(tmp_path)
    for index in range(50):
        _append_operation(
            ops,
            _operation(
                "op-%02d" % index,
                "2000-01-01T00:%02d:00Z" % index,
                endpoint="/api/{mundo}/" + "x" * 250 + "/%d" % index,
            ),
        )
    for index in range(20):
        assert record_turn(
            build_turn(
                request_id="req-%02d" % index,
                run_id="run-%02d" % index,
                world="Mundo%d" % index,
                model="m" * 80,
                semantic_state="s" * 40,
                semantic_action="a" * 40,
                completed=False,
                close_reason="stream_error",
                tools=[
                    {"name": "tool-%02d" % j, "ok": False, "duration_ms": 7}
                    for j in range(3)
                ],
            ),
            path=turns,
        )

    document = diagnostics.build_diagnostics(
        operations_path=ops,
        turns_path=turns,
        generated_at="2026-11-24T00:00:00Z",
    )
    encoded = json.dumps(document, sort_keys=True, ensure_ascii=False).encode("utf-8")
    assert len(encoded) <= diagnostics.MAX_BYTES
    assert document["truncated"] is True
    assert document["operations"]["kept"] == len(document["operations"]["records"]) > 0
    assert (
        document["assistant_turns"]["kept"]
        == len(document["assistant_turns"]["records"])
        > 0
    )
    assert document["operations"]["records"][0]["run_id"] == "op-49"
    assert document["assistant_turns"]["records"][0]["run_id"] == "run-19"


def test_trimming_drops_the_globally_oldest_record_first(tmp_path: Path) -> None:
    """S5: trimming is oldest-first across BOTH journals, not per journal."""
    ops = _ops_path(tmp_path)
    turns = _turns_path(tmp_path)
    seeded = {}
    for index in range(5):
        ts = "2026-03-0%dT00:00:00Z" % (index + 1)
        _append_operation(ops, _operation("op-%d" % index, ts))
        seeded["op-%d" % index] = ts
    for index in range(5):
        # Every turn is OLDER than every operation: the oldest turns go first.
        ts = "2026-01-0%dT00:00:00Z" % (index + 1)
        assert append_bounded_record(
            turns,
            {
                "ts": ts,
                "request_id": "r%d" % index,
                "run_id": "run-%d" % index,
                "world_hash": None,
                "model": None,
                "semantic_state": None,
                "semantic_action": None,
                "evidence_status": "none",
                "tools": [],
                "stage_timings": {"gate_ms": 1, "run_ms": 2},
                "status": "completed",
                "close_reason": None,
                "error_code": None,
            },
            max_entries=assistant_turns.MAX_TURNS,
            max_bytes=assistant_turns.MAX_BYTES,
        )
        seeded["run-%d" % index] = ts

    document = diagnostics.build_diagnostics(
        operations_path=ops,
        turns_path=turns,
        max_bytes=2400,
        generated_at="2026-11-24T00:00:00Z",
    )
    kept = [record["run_id"] for record in document["operations"]["records"]]
    kept += [record["run_id"] for record in document["assistant_turns"]["records"]]
    dropped = [key for key in seeded if key not in kept]
    assert dropped, "the budget must force at least one drop"
    assert max(seeded[key] for key in dropped) <= min(seeded[key] for key in kept)
    assert "op-4" in kept and "run-4" in kept


def test_redaction_walks_nested_lists_and_leaves_keys(tmp_path: Path) -> None:
    """S6: a secret nested in a list of dicts is redacted and counted."""
    secret = "sk-" + "a" * 40
    ops = _ops_path(tmp_path)
    assert append_bounded_record(
        ops,
        {
            "ts": "2026-11-24T00:00:00Z",
            "run_id": "r",
            "tools": [{"name": secret, "ok": True, "duration_ms": 1}],
        },
        max_entries=operations_ring.MAX_ENTRIES,
        max_bytes=operations_ring.MAX_BYTES,
    )

    document = diagnostics.build_diagnostics(
        operations_path=ops,
        turns_path=tmp_path / "absent-turns.jsonl",
        generated_at="2026-11-24T00:00:00Z",
    )
    dumped = json.dumps(document, ensure_ascii=False)
    assert secret not in dumped
    assert "[redacted:" in dumped
    assert document["redacted_lines"] == 1


def test_redacted_lines_counts_only_what_survived_the_trim(tmp_path: Path) -> None:
    """S5: a dropped record's placeholders are gone, so its hits are not counted."""
    secret = "sk-" + "a" * 40
    ops = _ops_path(tmp_path)
    for index in range(6):
        _append_operation(
            ops,
            _operation(
                "op-%d" % index,
                "2026-11-24T00:00:0%dZ" % index,
                endpoint="/api/{mundo}/%s/%d" % (secret, index),
            ),
        )

    document = diagnostics.build_diagnostics(
        operations_path=ops,
        turns_path=tmp_path / "absent-turns.jsonl",
        max_bytes=700,
        generated_at="2026-11-24T00:00:00Z",
    )

    placeholders = json.dumps(document, ensure_ascii=False).count("[redacted:")
    assert document["truncated"] is True
    assert document["redacted_lines"] == placeholders


def test_the_cli_file_obeys_the_budget_it_writes(tmp_path: Path) -> None:
    """S5: the written (indented) file is bounded, not only the compact form."""
    ops = _ops_path(tmp_path)
    for index in range(50):
        _append_operation(
            ops,
            _operation(
                "op-%02d" % index,
                "2026-11-24T00:%02d:00Z" % index,
                endpoint="/api/{mundo}/" + "x" * 200 + "/%d" % index,
            ),
        )
    out = tmp_path / "diagnostics.json"

    import diagnostics as diag_module

    real_build = diag_module.build_diagnostics
    diag_module.build_diagnostics = lambda **kwargs: real_build(
        operations_path=ops, **kwargs
    )
    try:
        assert diag_module.main(["--out", str(out)]) == 0
    finally:
        diag_module.build_diagnostics = real_build

    assert out.stat().st_size <= diagnostics.MAX_BYTES
