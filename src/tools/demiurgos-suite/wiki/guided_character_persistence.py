"""Secure persistence handoff and post-create graph reconciliation.

This module deliberately does not write files.  It prepares the payload for
the existing confirmation-gated create endpoint and reconciles graph state
after that endpoint has completed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol

from guided_character_domain import FichaProposal


IndexStatus = Literal["indexed", "pending", "failed", "dirty"]


@dataclass(frozen=True)
class SecureCreateRequest:
    """Request data for the existing ``kind=new`` gated create route."""

    section: str
    path: str
    body: dict[str, str]


def build_secure_create_request(
    proposal: FichaProposal,
    *,
    edit_id: str,
    confirmation_token: str,
    confirmation_digest: str,
) -> SecureCreateRequest:
    """Bind a reviewed proposal to the existing confirmation boundary.

    The caller must submit the returned data to ``/{section}/create``.  No
    filesystem or HTTP operation occurs here, so Hermes cannot bypass review.
    """
    if not edit_id.strip() or not confirmation_token.strip():
        raise ValueError("edit_id and confirmation token are required")
    digest = hashlib.sha256(proposal.content.encode("utf-8")).hexdigest()
    if digest != confirmation_digest:
        raise ValueError("confirmation digest does not match proposal")
    if not proposal.target.startswith("personajes/") or not proposal.target.endswith(".md"):
        raise ValueError("guided creation target must be under personajes/")
    return SecureCreateRequest(
        section="personajes",
        path=proposal.target.removeprefix("personajes/"),
        body={
            "content": proposal.content,
            "edit_id": edit_id,
            "proposed_digest": digest,
            "token": confirmation_token,
        },
    )


class GraphIndex(Protocol):
    dirty: bool
    def build(self, mundo: str) -> int: ...
    def get_entity(self, path: str) -> Any: ...


@dataclass(frozen=True)
class ReindexResult:
    operation_id: str
    content_digest: str
    index_status: IndexStatus
    retryable: bool
    message: str


class ReindexCoordinator:
    """Idempotently reconcile one durable create with the graph index."""

    def __init__(self, mundos_root: Path, index_factory: Callable[[str], GraphIndex]):
        self._mundos_root = mundos_root
        self._index_factory = index_factory
        self._results: dict[tuple[str, str], ReindexResult] = {}

    def reconcile(
        self,
        *,
        operation_id: str,
        mundo: str,
        target: str,
        content_digest: str,
    ) -> ReindexResult:
        key = (operation_id, content_digest)
        previous = self._results.get(key)
        if previous is not None and previous.index_status == "indexed":
            return previous

        full = (self._mundos_root / mundo / target).resolve()
        world_root = (self._mundos_root / mundo).resolve()
        if world_root not in full.parents or not full.is_file():
            return self._remember(key, ReindexResult(
                operation_id, content_digest, "failed", False,
                "Character was not persisted; graph indexing was not attempted.",
            ))
        actual_digest = hashlib.sha256(full.read_bytes()).hexdigest()
        if actual_digest != content_digest:
            return self._remember(key, ReindexResult(
                operation_id, content_digest, "failed", False,
                "Character content changed; graph indexing requires re-review.",
            ))

        try:
            index = self._index_factory(mundo)
            # A clean index may still predate this file. Rebuild through the
            # existing graph seam; this never repeats durable file creation.
            index.build(mundo)
            if index.dirty:
                return self._remember(key, ReindexResult(
                    operation_id, content_digest, "dirty", True,
                    "Character created; graph indexing is still dirty. Retry shortly.",
                ))
            if index.get_entity(target) is None:
                return self._remember(key, ReindexResult(
                    operation_id, content_digest, "pending", True,
                    "Character created; graph indexing is pending. Retry or reload.",
                ))
            return self._remember(key, ReindexResult(
                operation_id, content_digest, "indexed", False,
                "Character created and is visible in the graph.",
            ))
        except Exception:
            return self._remember(key, ReindexResult(
                operation_id, content_digest, "failed", True,
                "Character created; graph indexing is unavailable. Retry later.",
            ))

    def _remember(
        self, key: tuple[str, str], result: ReindexResult
    ) -> ReindexResult:
        self._results[key] = result
        return result
