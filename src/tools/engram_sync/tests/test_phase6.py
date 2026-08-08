"""Phase 6 integration gate: authorization, apply, journal, and recovery."""

import json

import pytest

from engram_sync.adapter import AdapterRegistry
from engram_sync.confirm import ConfirmError, ConfirmedChoice, confirm
from engram_sync.integration import apply_confirmation, scan_and_report
from engram_sync.journal import RunJournal, operation_id
from engram_sync.models import (Action, ApplyResult, Classification, NormalizedItem,
                                SourceRef)


def _source(location="file:item.md", text="v1"):
    from engram_sync.canonicalize import fingerprint

    fp = fingerprint({"text": text})
    return SourceRef(location=location, revision=fp, content={"text": text},
                     fingerprint=fp)


class WritableAdapter:
    domain = "ideas"

    def __init__(self, item, failure=None):
        self.item = item
        self.failure = failure
        self.applies = []

    def discover(self):
        return [self.item]

    def preview(self, item, action):
        return None

    def apply(self, operation):
        self.applies.append(operation)
        if self.failure:
            raise self.failure
        return ApplyResult(operation.item_key, "saved", "test double applied")


def _registry(item, failure=None):
    registry = AdapterRegistry()
    adapter = WritableAdapter(item, failure=failure)
    registry.register(adapter)
    return registry, adapter


def _item(text="v1"):
    local = _source(text=text)
    return NormalizedItem("ideas", "item", local=local, remote=None,
                          classification=Classification.LOCAL_ONLY)


def test_integration_scan_report_confirm_apply_and_journal(tmp_path):
    registry, adapter = _registry(_item())
    journal = RunJournal(tmp_path / ".demiurgos-sync")
    report = scan_and_report(registry)
    assert report.items[0].item_key == "item"
    assert report.report.actionable == 1

    results = apply_confirmation(
        registry,
        [ConfirmedChoice("ideas", "item", Action.KEEP_LOCAL,
                         report.items[0].local.revision)],
        journal,
        confirmation="APPLY",
        run_id="phase6-test",
    )
    assert results[0].applied is True
    assert len(adapter.applies) == 1
    op = operation_id("ideas", "item", report.items[0].local.revision,
                      "file:item.md", "keep-local")
    entry = journal.find(op)
    assert entry is not None and entry.state == "applied"
    assert entry.run_id == "phase6-test"


def test_confirmation_is_required_before_journal_or_apply(tmp_path):
    registry, adapter = _registry(_item())
    journal = RunJournal(tmp_path / ".demiurgos-sync")
    with pytest.raises(ConfirmError, match="explicit confirmation"):
        confirm(registry,
                [ConfirmedChoice("ideas", "item", Action.KEEP_LOCAL,
                                 _item().local.revision)], journal)
    assert adapter.applies == []
    assert not journal.path.exists()


def test_dry_run_validates_but_never_journals_or_applies(tmp_path):
    registry, adapter = _registry(_item())
    journal = RunJournal(tmp_path / ".demiurgos-sync")
    result = apply_confirmation(
        registry,
        [ConfirmedChoice("ideas", "item", Action.KEEP_LOCAL, _item().local.revision)],
        journal,
        confirmation="APPLY",
        dry_run=True,
    )
    assert result[0].applied is False and "dry-run" in result[0].message
    assert adapter.applies == []
    assert not journal.path.exists()


def test_failed_apply_is_journaled_and_does_not_replay(tmp_path):
    registry, adapter = _registry(_item(), failure=RuntimeError("test failure"))
    journal = RunJournal(tmp_path / ".demiurgos-sync")
    result = confirm(
        registry,
        [ConfirmedChoice("ideas", "item", Action.KEEP_LOCAL, _item().local.revision)],
        journal,
        confirmation="APPLY",
    )
    assert result[0].applied is False
    op = operation_id("ideas", "item", _item().local.revision,
                      "file:item.md", "keep-local")
    assert journal.find(op).state == "failed"
    assert journal.find(op).attempts == 1
    assert len(adapter.applies) == 1


def test_resolved_operation_is_idempotent_and_unresolved_is_blocked(tmp_path):
    registry, adapter = _registry(_item())
    journal = RunJournal(tmp_path / ".demiurgos-sync")
    choice = ConfirmedChoice("ideas", "item", Action.KEEP_LOCAL, _item().local.revision)
    assert confirm(registry, [choice], journal, confirmation="APPLY")[0].applied
    again = confirm(registry, [choice], journal, confirmation="APPLY")
    assert again[0].applied is False and "already completed" in again[0].message
    assert len(adapter.applies) == 1

    other_registry, _ = _registry(_item())
    pending = RunJournal(tmp_path / "pending")
    pending.plan(run_id="old", domain="ideas", item_key="item",
                 source_revision=_item().local.revision, target="file:item.md",
                 action="keep-local")
    with pytest.raises(ConfirmError, match="recovery evidence"):
        confirm(other_registry, [choice], pending, confirmation="APPLY")


def test_malformed_confirmation_document_is_rejected_without_work(tmp_path):
    from engram_sync.cli import main

    choices = tmp_path / "choices.json"
    choices.write_text(json.dumps([{"domain": "ideas", "item_key": "item",
                                    "action": "keep-local", "source_revision": "r"}]),
                       encoding="utf-8")
    assert main(["--root", str(tmp_path), "confirm", str(choices),
                 "--confirm", "APPLY"]) == 2
    assert not (tmp_path / ".demiurgos-sync" / "journal.jsonl").exists()


def test_rollback_and_session_start_guidance_are_present():
    from pathlib import Path

    package = Path(__file__).resolve().parents[1]
    rollback = package / "ROLLBACK.md"
    agents = package.parents[2] / "AGENTS.md"
    assert "disable" in rollback.read_text(encoding="utf-8").lower()
    assert "Nothing was changed" in agents.read_text(encoding="utf-8")
