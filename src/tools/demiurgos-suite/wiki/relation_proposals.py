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

from relation_proposing import pair_key

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
    """Stable id keyed by the UNORDERED pair plus type (S4).

    ``A -> B`` and ``B -> A`` must collapse into one queue entry, so the pair is
    normalized before hashing. The stored ``source_key`` still says which side
    holds the quote, and accepting writes there.
    """
    left, right = pair_key(source_key, target_id)
    raw = f"{left}\x1f{right}\x1f{relationship_type}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _preferred(candidate: Proposal, current: Proposal) -> bool:
    """Deterministic winner for the two directions of the same pair.

    Higher confidence wins; a tie is broken by the lexicographically smaller
    source key. The comparison is commutative, so the winner never depends on
    which batch (or which call) saw it first — batch composition cannot change
    the stored side.
    """
    if candidate.confidence != current.confidence:
        return candidate.confidence > current.confidence
    return candidate.source_key < current.source_key


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
    # Re-key every entry with the unordered identity: a pre-S4 store may hold
    # both directions (or old directional ids), and loading must collapse them
    # without losing the side that holds the evidence.
    by_key: dict[str, Proposal] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_path = entry.get("source_path")
        source_key = entry.get("source_key")
        target_id = entry.get("target_id")
        if not all(isinstance(v, str) and v for v in (source_path, source_key, target_id)):
            continue
        confidence = entry.get("confidence")
        relationship_type = str(entry.get("relationship_type") or "")
        key = proposal_id(source_key, target_id, relationship_type)
        proposal = Proposal(
            # Keep the stored id so an in-flight accept/reject keeps working;
            # pre-S4 ids are directional but still address one queue entry.
            id=str(entry.get("id") or key),
            source_path=source_path,
            source_key=source_key,
            target_id=target_id,
            relationship_type=relationship_type,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else 0.0,
            evidence=str(entry.get("evidence") or ""),
            created_at=str(entry.get("created_at") or ""),
        )
        current = by_key.get(key)
        if current is None or _preferred(proposal, current):
            by_key[key] = proposal
    return [by_key[key] for key in sorted(by_key)]


def add_proposals(world_dir: Path, proposals: Iterable[Proposal]) -> list[Proposal]:
    """Append proposals, deduped by the unordered pair + type.

    Returns only the proposals that created a new queue entry. When a new
    proposal describes the same pair from the other direction, the deterministic
    winner keeps its own ``source_path``/``source_key``/``target_id`` so the
    accept path always writes on the side that holds the quote.
    """
    with _LOCK:
        existing = load_proposals(world_dir)
        by_key = {
            proposal_id(
                proposal.source_key, proposal.target_id, proposal.relationship_type
            ): proposal
            for proposal in existing
        }
        added: list[Proposal] = []
        changed = False
        for proposal in proposals:
            key = proposal_id(
                proposal.source_key, proposal.target_id, proposal.relationship_type
            )
            current = by_key.get(key)
            if current is None:
                by_key[key] = proposal
                added.append(proposal)
                changed = True
            elif _preferred(proposal, current):
                by_key[key] = proposal
                changed = True
        if not changed:
            return []
        _write(world_dir, list(by_key.values()))
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
