"""Conflict records — W11 working documents for the Conflictos section.

One folder, one record format, three states:

* ``proposed`` — a semantic candidate the model proposed and the Author has not
  decided yet (S3). It carries the two quotes that justify it.
* ``decided`` — the Author's answer: ``intentional`` (known, never an error),
  ``muted`` (grouped apart, recoverable) or ``structural`` (escalated rupture).
* ``rejected`` — the Author said the model was wrong. The pair is remembered so
  it is never proposed again.

"Resolved" is not a state: it is what happens when the data stops
contradicting, and the record then stays as history.

Records are Markdown with YAML frontmatter and a readable body under
``mundos/<mundo>/conflictos/``. They are not entities, never enter the graph and
never change canon by themselves.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import yaml

from okf_contract import safe_slug_from_id

DECISIONS = ("intentional", "muted", "structural")
STATES = ("proposed", "decided", "rejected")
DECISIONS_DIR = "conflictos"

_FRONTMATTER = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


@dataclass(frozen=True)
class ConflictDecision:
    """One record, with the world-relative path of its file."""

    conflict_id: str
    decision: str = ""
    state: str = "decided"
    code: str = ""
    path: str = ""
    name: str = ""
    reference: str | None = None
    field: str | None = None
    decided_at: str = ""
    detected_at: str = ""
    note: str = ""
    file: str = ""
    # Semantic evidence (S3): both quotes and the pair they talk about.
    source_a: str = ""
    source_b: str = ""
    quote_a: str = ""
    quote_b: str = ""
    conflict_type: str = ""
    confidence: float = 0.0
    pair_left: str = ""
    pair_right: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _record_slug(conflict_id: str) -> str:
    base = safe_slug_from_id(conflict_id) or "conflict"
    digest = hashlib.sha1(conflict_id.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


def _record_body(record: ConflictDecision, note: str) -> str:
    if record.state == "proposed":
        lines = [
            "# Semantic conflict proposal",
            "",
            f"- source: `{record.source_a}`",
            f"- target: `{record.source_b}`",
            f"- type: `{record.conflict_type}`",
            "",
            f"> {record.quote_a}",
            "",
            f"> {record.quote_b}",
        ]
    else:
        lines = [
            f"# Conflict decision: {record.decision or record.state}",
            "",
            f"- code: `{record.code}`",
            f"- ficha: `{record.path}`",
        ]
        if record.reference:
            lines.append(f"- reference: `{record.reference}`")
        if record.field:
            lines.append(f"- field: `{record.field}`")
        if record.quote_a or record.quote_b:
            lines.append("")
            lines.append(f"> {record.quote_a}")
            lines.append("")
            lines.append(f"> {record.quote_b}")
        lines.append("")
        lines.append(note.strip() or "No note.")
    return "\n".join(lines) + "\n"


def _frontmatter(record: ConflictDecision, note: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "conflict_id": record.conflict_id,
        "state": record.state,
        "code": record.code,
        "path": record.path,
        "name": record.name,
        "reference": record.reference,
        "field": record.field,
    }
    if record.state == "proposed":
        data["origin"] = "semantic"
    else:
        data["decision"] = record.decision
        data["decided_at"] = record.decided_at
        data["note"] = note.strip()

    # Evidence survives every state: a decided or rejected record still shows
    # why the conflict was reported in the first place.
    evidence = {
        "conflict_type": record.conflict_type,
        "source_a": record.source_a,
        "source_b": record.source_b,
        "pair_left": record.pair_left,
        "pair_right": record.pair_right,
        "quote_a": record.quote_a,
        "quote_b": record.quote_b,
        "detected_at": record.detected_at,
    }
    for key, value in evidence.items():
        if value:
            data[key] = value
    if record.confidence:
        data["confidence"] = record.confidence
    return data


def _write_record(
    world_dir: Path, record: ConflictDecision, note: str = ""
) -> ConflictDecision:
    relative = f"{DECISIONS_DIR}/{_record_slug(record.conflict_id)}.md"
    target = Path(world_dir) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = "---\n"
    payload += yaml.safe_dump(
        _frontmatter(record, note), sort_keys=False, allow_unicode=True
    )
    payload += "---\n\n" + _record_body(record, note)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, target)
    return ConflictDecision(**{**record.__dict__, "file": relative})


def record_decision(
    world_dir: Path,
    conflict: Mapping[str, Any],
    decision: str,
    note: str = "",
) -> ConflictDecision:
    """Create or update the decision for one conflict. Never touches canon.

    An existing semantic proposal keeps its evidence: the decision is written on
    top of it, so the record still shows why the conflict was reported.
    """
    if decision not in DECISIONS:
        raise ValueError(
            f"unknown decision {decision!r}; expected one of {', '.join(DECISIONS)}"
        )
    conflict_id = str(conflict.get("id") or "")
    if not conflict_id:
        raise ValueError("a conflict decision needs the conflict id")

    world_dir = Path(world_dir)
    existing = load_records(world_dir).get(conflict_id)
    record = ConflictDecision(
        conflict_id=conflict_id,
        decision=decision,
        state="decided",
        code=str(conflict.get("code") or (existing.code if existing else "")),
        path=str(conflict.get("path") or (existing.path if existing else "")),
        name=str(conflict.get("name") or (existing.name if existing else "")),
        reference=(
            conflict["reference"]
            if conflict.get("reference") is not None
            else (existing.reference if existing else None)
        ),
        field=(
            conflict["field"]
            if conflict.get("field") is not None
            else (existing.field if existing else None)
        ),
        decided_at=_now(),
        note=note.strip(),
        source_a=existing.source_a if existing else "",
        source_b=existing.source_b if existing else "",
        quote_a=existing.quote_a if existing else "",
        quote_b=existing.quote_b if existing else "",
        conflict_type=existing.conflict_type if existing else "",
        confidence=existing.confidence if existing else 0.0,
        pair_left=existing.pair_left if existing else "",
        pair_right=existing.pair_right if existing else "",
        detected_at=existing.detected_at if existing else "",
    )
    return _write_record(world_dir, record, note)


def record_proposal(
    world_dir: Path,
    *,
    conflict_id: str,
    source_a: str,
    source_b: str,
    path: str,
    name: str,
    quote_a: str,
    quote_b: str,
    conflict_type: str,
    confidence: float = 0.0,
    pair_left: str = "",
    pair_right: str = "",
) -> ConflictDecision:
    """Store one semantic candidate. Idempotent by ``conflict_id``."""
    record = ConflictDecision(
        conflict_id=conflict_id,
        state="proposed",
        code="semantic-contradiction",
        path=path,
        name=name,
        reference=conflict_type,
        detected_at=_now(),
        source_a=source_a,
        source_b=source_b,
        quote_a=quote_a,
        quote_b=quote_b,
        conflict_type=conflict_type,
        confidence=confidence,
        pair_left=pair_left,
        pair_right=pair_right,
    )
    return _write_record(world_dir, record)


def reject_proposal(world_dir: Path, conflict_id: str, note: str = "") -> bool:
    """Mark a proposal as a model mistake. Returns False when there is none."""
    world_dir = Path(world_dir)
    record = load_records(world_dir).get(conflict_id)
    if record is None or record.state != "proposed":
        return False
    rejected = ConflictDecision(
        **{**record.__dict__, "state": "rejected", "decided_at": _now(), "note": note.strip()}
    )
    _write_record(world_dir, rejected, note)
    return True


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
    state = str(frontmatter.get("state") or "decided")
    decision = str(frontmatter.get("decision") or "")
    if not conflict_id or state not in STATES:
        return None
    if state == "decided" and decision not in DECISIONS:
        return None
    return ConflictDecision(
        conflict_id=conflict_id,
        decision=decision,
        state=state,
        code=str(frontmatter.get("code") or ""),
        path=str(frontmatter.get("path") or ""),
        name=str(frontmatter.get("name") or ""),
        reference=frontmatter.get("reference"),
        field=frontmatter.get("field"),
        decided_at=str(frontmatter.get("decided_at") or ""),
        detected_at=str(frontmatter.get("detected_at") or ""),
        note=str(frontmatter.get("note") or ""),
        file=path.relative_to(world_dir).as_posix(),
        source_a=str(frontmatter.get("source_a") or ""),
        source_b=str(frontmatter.get("source_b") or ""),
        quote_a=str(frontmatter.get("quote_a") or ""),
        quote_b=str(frontmatter.get("quote_b") or ""),
        conflict_type=str(frontmatter.get("conflict_type") or ""),
        confidence=_confidence(frontmatter.get("confidence")),
        pair_left=str(frontmatter.get("pair_left") or ""),
        pair_right=str(frontmatter.get("pair_right") or ""),
    )


def load_records(world_dir: Path) -> dict[str, ConflictDecision]:
    """Read every valid record. An absent folder means no records."""
    records_dir = Path(world_dir) / DECISIONS_DIR
    if not records_dir.is_dir():
        return {}
    records: dict[str, ConflictDecision] = {}
    for path in sorted(records_dir.glob("*.md")):
        record = _parse_record(path, Path(world_dir))
        if record is not None:
            records[record.conflict_id] = record
    return records


def load_decisions(world_dir: Path) -> dict[str, ConflictDecision]:
    """Only the Author's decisions (``state: decided``)."""
    return {
        conflict_id: record
        for conflict_id, record in load_records(world_dir).items()
        if record.state == "decided"
    }


def known_semantic_keys(
    records: Mapping[str, ConflictDecision],
) -> set[tuple[str, str, str]]:
    """Pairs already proposed, decided or rejected, so they are not re-proposed."""
    known: set[tuple[str, str, str]] = set()
    for record in records.values():
        if record.pair_left and record.pair_right and record.conflict_type:
            known.add((record.pair_left, record.pair_right, record.conflict_type))
    return known


def semantic_conflicts(
    records: Mapping[str, ConflictDecision],
    *,
    verify: Callable[[ConflictDecision], bool] | None = None,
) -> list[dict[str, Any]]:
    """Project proposed and decided semantic records into the panel payload.

    ``verify`` re-checks the record against the CURRENT text: a contradiction
    whose quotes no longer hold has been resolved by editing, so the record
    stays as history and is not shown as a live conflict.
    """
    payload: list[dict[str, Any]] = []
    for record in records.values():
        # Only semantic records carry a conflict_type; a decided deterministic
        # conflict is already in the computed list and must not appear twice.
        if record.state not in ("proposed", "decided") or not record.conflict_type:
            continue
        if verify is not None and not verify(record):
            continue
        payload.append(
            {
                "id": record.conflict_id,
                "code": "semantic-contradiction",
                "severity": "error",
                "path": record.path,
                "name": record.name,
                "message": "",
                "field": None,
                "reference": record.conflict_type or None,
                "decision": record.decision or None,
                "state": record.state,
                "origin": "semantic",
                "evidence_a": record.quote_a or None,
                "evidence_b": record.quote_b or None,
                "source_a": record.source_a or None,
                "source_b": record.source_b or None,
            }
        )
    return sorted(payload, key=lambda item: (item["path"], item["id"]))


def clear_decision(world_dir: Path, conflict_id: str) -> bool:
    """Delete the record for one conflict. Returns False when there is none."""
    world_dir = Path(world_dir)
    record = load_records(world_dir).get(conflict_id)
    if record is None:
        return False
    target = world_dir / record.file
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

    Every conflict stays in the payload with its ``decision`` and ``state``:
    ``proposed`` ones are counted apart (the Author has not decided yet),
    ``muted`` ones are grouped apart (so the Author can undo them),
    ``intentional`` ones are counted as known instead of errors, and
    ``structural`` ones stay errors with the escalation flagged.
    """
    payload: list[dict[str, Any]] = []
    by_code: dict[str, int] = {}
    errors = 0
    warnings = 0
    known = 0
    muted = 0
    proposed = 0

    for conflict in conflicts:
        conflict_id = str(conflict.get("id") or "")
        decision = decisions.get(conflict_id)

        item = dict(conflict)
        if item.get("state") != "proposed":
            item["decision"] = decision.decision if decision is not None else None
        payload.append(item)
        code = str(conflict.get("code") or "")
        by_code[code] = by_code.get(code, 0) + 1

        if item.get("state") == "proposed":
            proposed += 1
            continue
        if item["decision"] == "muted":
            muted += 1
            continue
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
        "proposed": proposed,
        "by_code": dict(sorted(by_code.items())),
    }


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return min(1.0, max(0.0, float(value)))
