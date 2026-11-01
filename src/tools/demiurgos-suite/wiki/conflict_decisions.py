"""Conflict decisions — W11 records for the Conflictos section (S2).

A decision is the Author's answer to a deterministic conflict, stored as a
Markdown record with YAML frontmatter and a readable body under
``mundos/<mundo>/conflictos/``. Records are working documents: they are not
entities, never enter the graph and never change canon by themselves.

Closed decision set:

* ``intentional`` — a known contradiction, shown as known instead of an error.
* ``muted`` — the Author does not want to see it; hidden from the panel.
* ``structural`` — escalated as a rupture of the world's foundational rules.

"Resolved" is not a decision: it is what happens when the data stops
contradicting, and the record then stays as history.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from okf_contract import safe_slug_from_id

DECISIONS = ("intentional", "muted", "structural")
DECISIONS_DIR = "conflictos"

_FRONTMATTER = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


@dataclass(frozen=True)
class ConflictDecision:
    """One recorded decision, with the world-relative path of its record."""

    conflict_id: str
    decision: str
    code: str = ""
    path: str = ""
    name: str = ""
    reference: str | None = None
    field: str | None = None
    decided_at: str = ""
    note: str = ""
    file: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _record_slug(conflict_id: str) -> str:
    base = safe_slug_from_id(conflict_id) or "conflict"
    digest = hashlib.sha1(conflict_id.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


def _record_body(decision: str, conflict: Mapping[str, Any], note: str) -> str:
    lines = [
        f"# Conflict decision: {decision}",
        "",
        f"- code: `{conflict.get('code', '')}`",
        f"- ficha: `{conflict.get('path', '')}`",
    ]
    if conflict.get("reference"):
        lines.append(f"- reference: `{conflict.get('reference')}`")
    if conflict.get("field"):
        lines.append(f"- field: `{conflict.get('field')}`")
    lines.append("")
    lines.append(note.strip() or "No note.")
    return "\n".join(lines) + "\n"


def _write_record(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    payload += "---\n\n" + body
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def record_decision(
    world_dir: Path,
    conflict: Mapping[str, Any],
    decision: str,
    note: str = "",
) -> ConflictDecision:
    """Create or update the record for one conflict. Never touches canon."""
    if decision not in DECISIONS:
        raise ValueError(
            f"unknown decision {decision!r}; expected one of {', '.join(DECISIONS)}"
        )
    conflict_id = str(conflict.get("id") or "")
    if not conflict_id:
        raise ValueError("a conflict decision needs the conflict id")

    world_dir = Path(world_dir)
    relative = f"{DECISIONS_DIR}/{_record_slug(conflict_id)}.md"
    decided_at = _now()
    frontmatter = {
        "conflict_id": conflict_id,
        "code": str(conflict.get("code") or ""),
        "decision": decision,
        "path": str(conflict.get("path") or ""),
        "name": str(conflict.get("name") or ""),
        "reference": conflict.get("reference"),
        "field": conflict.get("field"),
        "decided_at": decided_at,
        "note": note.strip(),
    }
    _write_record(
        world_dir / relative,
        frontmatter,
        _record_body(decision, conflict, note),
    )
    return ConflictDecision(
        conflict_id=conflict_id,
        decision=decision,
        code=frontmatter["code"],
        path=frontmatter["path"],
        name=frontmatter["name"],
        reference=frontmatter["reference"],
        field=frontmatter["field"],
        decided_at=decided_at,
        note=frontmatter["note"],
        file=relative,
    )


def _parse_record(path: Path, world_dir: Path) -> ConflictDecision | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = _FRONTMATTER.match(text)
    if match is None:
        return None
    try:
        frontmatter = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(frontmatter, dict):
        return None
    conflict_id = str(frontmatter.get("conflict_id") or "")
    decision = str(frontmatter.get("decision") or "")
    if not conflict_id or decision not in DECISIONS:
        return None
    return ConflictDecision(
        conflict_id=conflict_id,
        decision=decision,
        code=str(frontmatter.get("code") or ""),
        path=str(frontmatter.get("path") or ""),
        name=str(frontmatter.get("name") or ""),
        reference=frontmatter.get("reference"),
        field=frontmatter.get("field"),
        decided_at=str(frontmatter.get("decided_at") or ""),
        note=str(frontmatter.get("note") or ""),
        file=path.relative_to(world_dir).as_posix(),
    )


def load_decisions(world_dir: Path) -> dict[str, ConflictDecision]:
    """Read every valid record. An absent folder means no decisions."""
    records_dir = Path(world_dir) / DECISIONS_DIR
    if not records_dir.is_dir():
        return {}
    decisions: dict[str, ConflictDecision] = {}
    for path in sorted(records_dir.glob("*.md")):
        decision = _parse_record(path, Path(world_dir))
        if decision is not None:
            decisions[decision.conflict_id] = decision
    return decisions


def clear_decision(world_dir: Path, conflict_id: str) -> bool:
    """Delete the record for one conflict. Returns False when there is none."""
    world_dir = Path(world_dir)
    decision = load_decisions(world_dir).get(conflict_id)
    if decision is None:
        return False
    target = world_dir / decision.file
    try:
        target.unlink()
    except OSError:
        return False
    return True


def apply_decisions(
    conflicts: Iterable[Mapping[str, Any]],
    decisions: Mapping[str, ConflictDecision],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Project the computed conflicts through the recorded decisions.

    ``muted`` conflicts disappear; ``intentional`` ones stay as known (never
    counted as errors); ``structural`` ones stay as errors with the escalation
    flagged. The summary counts what the panel header shows.
    """
    payload: list[dict[str, Any]] = []
    by_code: dict[str, int] = {}
    errors = 0
    warnings = 0
    known = 0
    muted = 0

    for conflict in conflicts:
        conflict_id = str(conflict.get("id") or "")
        decision = decisions.get(conflict_id)
        code = str(conflict.get("code") or "")
        if decision is not None and decision.decision == "muted":
            muted += 1
            continue

        item = dict(conflict)
        item["decision"] = decision.decision if decision is not None else None
        payload.append(item)
        by_code[code] = by_code.get(code, 0) + 1

        if item["decision"] == "intentional":
            known += 1
            continue
        if conflict.get("severity") == "error":
            errors += 1
        else:
            warnings += 1

    return payload, {
        "total": len(payload),
        "errors": errors,
        "warnings": warnings,
        "known": known,
        "muted": muted,
        "by_code": dict(sorted(by_code.items())),
    }
