#!/usr/bin/env python3
"""One-time backfill: distill an existing guided session into assistant memory.

This is a migration helper for installs that already have guided conversations
from before cross-session memory existed. A fresh install has nothing to
backfill and never needs to run it.

Usage:
  .venv/bin/python scripts/backfill_assistant_memory.py \
      --session-id guided-b172977b6c6347b3b5e832c0596870f8 --dry-run
  .venv/bin/python scripts/backfill_assistant_memory.py \
      --session-id guided-b172977b6c6347b3b5e832c0596870f8
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WIKI = REPO / "src" / "tools" / "demiurgos-suite" / "wiki"
if str(WIKI) not in sys.path:
    sys.path.insert(0, str(WIKI))

from assistant_memory_store import AssistantMemoryStore  # noqa: E402
from memory_curator import (  # noqa: E402
    apply_candidates,
    build_extraction_prompt,
    parse_candidates,
)
from state_paths import resolve_state_dir  # noqa: E402

DEFAULT_GATEWAY_URL = os.getenv(
    "HERMES_GATEWAY_URL", "http://127.0.0.1:8642/v1/chat/completions",
)


def default_guided_db_path() -> Path:
    return resolve_state_dir() / "guided-sessions.sqlite3"


def build_transcript(messages: list[dict]) -> str:
    """Render a guided transcript as role-labelled text for the Curator."""
    lines: list[str] = []
    for message in messages:
        content = message.get("content") or {}
        kind = message.get("message_type") or message.get("role") or "message"
        text = content.get("text") or content.get("question") or ""
        if text:
            lines.append(f"{kind}: {text}")
        synthesis = content.get("synthesis")
        if synthesis:
            lines.append(f"{kind}_synthesis: {synthesis}")
    return "\n".join(lines)


def load_session(db_path: Path, session_id: str) -> tuple[str, list[dict]]:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT world, messages_json FROM guided_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise SystemExit(f"session {session_id!r} not found in {db_path}")
    return str(row[0]), json.loads(row[1])


def _gateway_key() -> str:
    """Resolve the gateway key from the environment or the data-root .env."""
    key = os.getenv("HERMES_GATEWAY_KEY", "").strip()
    if key:
        return key
    try:
        from data_root import resolve_data_root

        env_path = resolve_data_root() / ".env"
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("HERMES_GATEWAY_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


async def _gateway_complete(prompt: str, url: str, key: str = "") -> str:
    import httpx

    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            url,
            headers=headers,
            json={
                "model": "hermes-agent",
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", required=True)
    parser.add_argument(
        "--db", type=Path, default=None,
        help="guided-sessions.sqlite3 path (default: the app state dir)",
    )
    parser.add_argument(
        "--memory-db", type=Path, default=None,
        help="assistant-memory.sqlite3 path (default: the app state dir)",
    )
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    db_path = args.db or default_guided_db_path()
    world, messages = load_session(db_path, args.session_id)
    transcript = build_transcript(messages)
    if not transcript.strip():
        raise SystemExit("the session has an empty transcript")

    prompt = build_extraction_prompt(
        world=world,
        user_text=transcript,
        assistant_text="(guided transcript)",
        skill_hints=["guided-character"],
    )
    try:
        raw = asyncio.run(_gateway_complete(prompt, args.gateway_url, _gateway_key()))
    except Exception as exc:
        raise SystemExit(f"gateway extraction failed: {exc}") from exc
    candidates = parse_candidates(raw)
    if args.dry_run:
        print(json.dumps(
            [candidate.__dict__ for candidate in candidates],
            ensure_ascii=False, indent=2,
        ))
        return 0

    store = AssistantMemoryStore(args.memory_db) if args.memory_db else AssistantMemoryStore()
    try:
        entries = apply_candidates(
            store,
            candidates,
            world=world,
            source_session=args.session_id,
            source_turn="backfill:guided-transcript",
            confidence_threshold=args.min_confidence,
        )
    finally:
        store.close()
    print(f"stored {len(entries)} memories for world {world!r}")
    for entry in entries:
        print(f"- [{entry.status}] {entry.topic_key}: {entry.statement}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
