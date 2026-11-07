"""Offline tests for the one-time guided-session backfill helper."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[5] / "scripts" / "backfill_assistant_memory.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("backfill_assistant_memory", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["backfill_assistant_memory"] = module
    spec.loader.exec_module(module)
    return module


def test_build_transcript_renders_author_and_assistant_turns() -> None:
    module = _load_script()
    transcript = module.build_transcript([
        {"message_type": "author_input", "content": {"text": "quiero crear un personaje"}},
        {"message_type": "assistant_response", "content": {
            "question": "¿Quién es?",
            "synthesis": "Aún no sabemos el nombre.",
        }},
    ])
    assert "author_input: quiero crear un personaje" in transcript
    assert "assistant_response: ¿Quién es?" in transcript
    assert "assistant_response_synthesis: Aún no sabemos el nombre." in transcript


def test_load_session_reads_world_and_messages(tmp_path: Path) -> None:
    module = _load_script()
    db = tmp_path / "guided-sessions.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE guided_sessions (session_id TEXT PRIMARY KEY, world TEXT, messages_json TEXT)"
    )
    conn.execute(
        "INSERT INTO guided_sessions VALUES (?, ?, ?)",
        ("guided-1", "Vibrantes", json.dumps([{"message_type": "author_input", "content": {"text": "hola"}}])),
    )
    conn.commit()
    conn.close()

    world, messages = module.load_session(db, "guided-1")
    assert world == "Vibrantes"
    assert messages[0]["content"]["text"] == "hola"
