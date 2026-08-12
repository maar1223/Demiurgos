"""Focused PR3 tests for secure create handoff and graph reconciliation."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from guided_character_domain import FichaProposal  # noqa: E402
from guided_character_persistence import (  # noqa: E402
    ReindexCoordinator,
    build_secure_create_request,
)


def _proposal(content: str = "---\ntype: Personaje\n---\n") -> FichaProposal:
    return FichaProposal("personajes/aria.md", content, "basis")


def test_secure_create_handoff_is_digest_bound_and_does_not_write(tmp_path: Path) -> None:
    proposal = _proposal()
    digest = hashlib.sha256(proposal.content.encode()).hexdigest()
    request = build_secure_create_request(
        proposal,
        edit_id="proposal-1",
        confirmation_token="single-use-token",
        confirmation_digest=digest,
    )
    assert request.section == "personajes"
    assert request.path == "aria.md"
    assert request.body["proposed_digest"] == digest
    assert not (tmp_path / "personajes" / "aria.md").exists()

    with pytest.raises(ValueError, match="digest"):
        build_secure_create_request(
            proposal,
            edit_id="proposal-1",
            confirmation_token="single-use-token",
            confirmation_digest="0" * 64,
        )


class FakeIndex:
    def __init__(self, status: str = "clean", visible: bool = True, fail: bool = False):
        self.dirty = status == "dirty"
        self.visible = visible
        self.fail = fail
        self.builds = 0

    def build(self, mundo: str) -> int:
        self.builds += 1
        if self.fail:
            raise RuntimeError("index outage")
        self.dirty = False
        return 1

    def get_entity(self, path: str):
        return {"path": path} if self.visible else None


def _coordinator(tmp_path: Path, index: FakeIndex) -> ReindexCoordinator:
    target = tmp_path / "vibrantes" / "personajes" / "aria.md"
    target.parent.mkdir(parents=True)
    target.write_text("content", encoding="utf-8")
    return ReindexCoordinator(tmp_path, lambda mundo: index)


def test_reindex_is_digest_bound_and_idempotent(tmp_path: Path) -> None:
    index = FakeIndex()
    coordinator = _coordinator(tmp_path, index)
    digest = hashlib.sha256(b"content").hexdigest()
    first = coordinator.reconcile(
        operation_id="op-1", mundo="vibrantes", target="personajes/aria.md", content_digest=digest
    )
    second = coordinator.reconcile(
        operation_id="op-1", mundo="vibrantes", target="personajes/aria.md", content_digest=digest
    )
    assert first.index_status == second.index_status == "indexed"
    assert index.builds == 1


@pytest.mark.parametrize(
    ("index", "status"),
    [(FakeIndex("dirty"), "indexed"), (FakeIndex(visible=False), "pending"), (FakeIndex(fail=True), "failed")],
)
def test_reindex_reports_dirty_pending_and_outage_safely(
    tmp_path: Path, index: FakeIndex, status: str
) -> None:
    coordinator = _coordinator(tmp_path, index)
    digest = hashlib.sha256(b"content").hexdigest()
    result = coordinator.reconcile(
        operation_id="op-1", mundo="vibrantes", target="personajes/aria.md", content_digest=digest
    )
    assert result.index_status == status
    assert result.retryable is (status != "indexed")
    assert "Character created" in result.message
