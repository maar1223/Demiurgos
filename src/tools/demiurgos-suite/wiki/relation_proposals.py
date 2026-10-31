"""Pending semantic relationship proposals for the on-demand sweep (P3).

Stored at ``<world>/.relations/proposals.json``. A proposal is never a write:
the Author accepts it (the target id is added through the shared frontmatter
writer) or rejects it (the pair joins P2's rejection memory).

Fail-open by design: a missing, corrupt or unreadable store means "no pending
proposals".
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

STORE_DIR = ".relations"
STORE_NAME = "proposals.json"
SCHEMA_VERSION = 1

_LOCK = threading.Lock()


@dataclass(frozen=True)
class Proposal:
    """One semantic relationship awaiting the Author's verdict."""

    id: str
    source_path: str
    source_key: str
    target_id: str
    relationship_type: str = ""
    confidence: float = 0.0
    evidence: str = ""
    created_at: str = ""


def proposal_id(source_key: str, target_id: str, relationship_type: str = "") -> str:
    """Stable id: the same pair and type always dedupe to one proposal."""
    raw = f"{source_key}\x1f{target_id}\x1f{relationship_type}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _path(world_dir: Path) -> Path:
    return Path(world_dir) / STORE_DIR / STORE_NAME


def load_proposals(world_dir: Path) -> list[Proposal]:
    path = _path(world_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.warning("relations: cannot read proposals at %s: %s", path, exc)
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("relations: corrupt proposals at %s; ignoring", path)
        return []
    entries = data.get("proposals") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    proposals: list[Proposal] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_path = entry.get("source_path")
        source_key = entry.get("source_key")
        target_id = entry.get("target_id")
        if not all(isinstance(v, str) and v for v in (source_path, source_key, target_id)):
            continue
        confidence = entry.get("confidence")
        proposals.append(
            Proposal(
                id=str(entry.get("id") or proposal_id(source_key, target_id)),
                source_path=source_path,
                source_key=source_key,
                target_id=target_id,
                relationship_type=str(entry.get("relationship_type") or ""),
                confidence=float(confidence) if isinstance(confidence, (int, float)) else 0.0,
                evidence=str(entry.get("evidence") or ""),
                created_at=str(entry.get("created_at") or ""),
            )
        )
    return proposals


def add_proposals(world_dir: Path, proposals: Iterable[Proposal]) -> list[Proposal]:
    """Append proposals, deduped by id. Returns the ones actually added."""
    with _LOCK:
        existing = load_proposals(world_dir)
        known = {proposal.id for proposal in existing}
        added = [proposal for proposal in proposals if proposal.id not in known]
        if not added:
            return []
        _write(world_dir, existing + added)
        return added


def remove_proposal(world_dir: Path, proposal_id_value: str) -> Proposal | None:
    """Drop a proposal from the queue; returns it when it existed."""
    with _LOCK:
        existing = load_proposals(world_dir)
        kept = [proposal for proposal in existing if proposal.id != proposal_id_value]
        removed = next(
            (proposal for proposal in existing if proposal.id == proposal_id_value),
            None,
        )
        if removed is None:
            return None
        _write(world_dir, kept)
        return removed


def _write(world_dir: Path, proposals: list[Proposal]) -> None:
    path = _path(world_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SCHEMA_VERSION,
        "proposals": [asdict(proposal) for proposal in sorted(proposals, key=lambda p: p.id)],
    }
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
