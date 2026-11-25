# -*- coding: utf-8 -*-
"""Diagnostics document (Phase 1, S5/S6, task T1.5).

One structured document travels inside a bug report: the newest operations and
assistant turns, bounded by a JSON byte budget and redacted before assembly.
It answers "what was done, and where did it fail" without shipping a database
and without shipping author content.

Deliberate limits:

- **Metadata only.** The two journals it reads are already schema-fixed and
  carry no world name (only :func:`operations_ring.hash_world`), no prompt
  body, no answer body and no ``.env`` value (S6). This module does not widen
  either journal; it only copies the records it is given.
- **Defense in depth.** Every string value is run through
  :func:`content_scan.redact_secrets` before assembly, even though the writers
  are already clipped and schema-fixed, and the number of redacted lines is
  surfaced as ``redacted_lines``.
- **Bounded output.** The serialized document never exceeds :data:`MAX_BYTES`:
  while it is too large the OLDEST record is dropped (the lists are
  newest-first) from whichever journal still has records, and ``truncated`` is
  set. When even the empty shape cannot fit, the empty shape is returned with
  ``truncated: True``.
- **Never raises.** Both journal readers swallow storage errors and return an
  empty list for a missing or unreadable file, so a report can always carry a
  diagnostics document.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import assistant_turns
import content_scan
import operations_ring

SCHEMA = "demiurgos.diagnostics/v1"
MAX_BYTES = 24 * 1024
DEFAULT_OPERATIONS = 50
DEFAULT_TURNS = 20


def _redact_value(value: Any) -> tuple[Any, int]:
    """A redacted copy of ``value`` plus the number of redacted lines.

    Dict keys are left untouched (they are the fixed schema); every string
    value, including those nested in dicts and lists, is scanned.
    """
    if isinstance(value, str):
        return content_scan.redact_secrets(value)
    if isinstance(value, Mapping):
        total = 0
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            clean, hits = _redact_value(item)
            redacted[key] = clean
            total += hits
        return redacted, total
    if isinstance(value, (list, tuple)):
        total = 0
        items: list[Any] = []
        for item in value:
            clean, hits = _redact_value(item)
            items.append(clean)
            total += hits
        return items, total
    return value, 0


def _redact_records(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[int]]:
    """Redacted copies of ``records`` and the hit count of each one.

    The per-record counts are kept so ``redacted_lines`` stays honest after the
    budget trimming drops records: a dropped record's placeholders are gone
    from the document, so its hits must not be counted.
    """
    redacted: list[dict[str, Any]] = []
    hits_by_record: list[int] = []
    for record in records:
        clean, hits = _redact_value(record)
        redacted.append(clean if isinstance(clean, dict) else {})
        hits_by_record.append(hits)
    return redacted, hits_by_record


def _encoded(document: dict[str, Any], indent: int | None = None) -> bytes:
    """The budgeted serialization; ``indent`` is the one the caller will write."""
    return json.dumps(
        document, indent=indent, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")


def _oldest_journal(document: dict[str, Any]) -> str | None:
    """Which journal holds the oldest record, or ``None`` when both are empty.

    Both journals return newest-first, so the oldest record of a journal is its
    last element. ``ts`` is an ISO-8601 second stamp on both sides, so a plain
    string comparison orders the two journals against each other.
    """
    candidates: list[tuple[str, dict[str, Any]]] = []
    for name in ("operations", "assistant_turns"):
        records = document[name]["records"]
        if records:
            candidates.append((name, records[-1]))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: str(pair[1].get("ts") or ""))
    return candidates[0][0]


def build_diagnostics(
    *,
    operations_path: Path | None = None,
    turns_path: Path | None = None,
    operations_limit: int = DEFAULT_OPERATIONS,
    turns_limit: int = DEFAULT_TURNS,
    max_bytes: int = MAX_BYTES,
    generated_at: str | None = None,
    indent: int | None = None,
) -> dict[str, Any]:
    """Build the bounded, redacted diagnostics document; never raises.

    ``operations_path`` / ``turns_path`` default to each journal's state-dir
    path when omitted. Records are redacted before they are assembled, then the
    document is trimmed oldest-first until it fits ``max_bytes``. ``indent`` is
    the serialization the caller will write (the CLI writes an indented file),
    and the budget is measured against THAT serialization so the written file is
    bounded too, not just the delivered document.
    """
    raw_operations = operations_ring.recent_operations(
        path=operations_path, limit=operations_limit
    )
    raw_turns = assistant_turns.recent_turns(path=turns_path, limit=turns_limit)
    operations, operation_hits = _redact_records(raw_operations)
    turns, turn_hits = _redact_records(raw_turns)
    hits_by_journal = {"operations": operation_hits, "assistant_turns": turn_hits}

    document: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": (
            generated_at if generated_at is not None else operations_ring.iso_now()
        ),
        "truncated": False,
        "redacted_lines": sum(operation_hits) + sum(turn_hits),
        "operations": {
            "records": operations,
            "kept": len(operations),
            "limit": operations_limit,
            "max_entries": operations_ring.MAX_ENTRIES,
        },
        "assistant_turns": {
            "records": turns,
            "kept": len(turns),
            "limit": turns_limit,
            "max_entries": assistant_turns.MAX_TURNS,
        },
    }

    while len(_encoded(document, indent)) > max_bytes:
        journal = _oldest_journal(document)
        if journal is None:
            break
        document[journal]["records"].pop()
        hits_by_journal[journal].pop()
        document[journal]["kept"] = len(document[journal]["records"])
        # A dropped record takes its placeholders with it: recount so the
        # reported number matches what the document actually contains.
        document["redacted_lines"] = sum(hits_by_journal["operations"]) + sum(
            hits_by_journal["assistant_turns"]
        )
        document["truncated"] = True

    return document


def main(argv: list[str] | None = None) -> int:
    """Write the diagnostics document to ``--out``; ``1`` when it cannot."""
    parser = argparse.ArgumentParser(prog="diagnostics")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    document = build_diagnostics(indent=2)
    try:
        Path(args.out).write_text(
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        print("diagnostics: could not write %s" % args.out, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
