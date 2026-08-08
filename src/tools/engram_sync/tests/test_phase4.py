"""RED/GREEN: Phase 4a — stale confirmation, plain reports, bounded previews,
confirmation rules, fail-closed apply, no-write guarantees (4.1-4.3)."""

import json

import pytest

from engram_sync.adapter import AdapterRegistry
from engram_sync.cli import main
from engram_sync.journal import RunJournal, operation_id
from engram_sync.models import (Action, Classification, NormalizedItem,
                                SourceRef, SourceState)
from engram_sync.views import (action_for, build_report, file_diff, preview_for,
                               scan, severity)
from engram_sync.confirm import (ConfirmError, ConfirmedChoice, allowed_actions,
                                 confirm, homogeneous_batch)
from engram_sync.canonicalize import fingerprint


def _item(domain="ideas", key="k", local=None, remote=None,
          classification=Classification.LOCAL_ONLY):
    return NormalizedItem(domain=domain, item_key=key, local=local, remote=remote,
                          classification=classification)


def _src(loc="file:a.md", content=None, state=SourceState.PRESENT):
    fp = fingerprint(content or {})
    return SourceRef(location=loc, revision=fp, content=content or {},
                     fingerprint=fp, state=state)


class FakeAdapter:
    def __init__(self, items=None, domain="ideas"):
        self.domain, self.items = domain, items or []

    def discover(self):
        return list(self.items)

    def preview(self, item, action):
        return None

    def apply(self, op):
        raise NotImplementedError("phase 1 adapters are read-only")


def test_scan_repeat_identical_ordered():
    reg = AdapterRegistry()
    reg.register(FakeAdapter([_item(key="b"), _item(key="a")]))
    reg.register(FakeAdapter([_item(domain="arc-state", key="z")], domain="arc-state"))
    out = scan(reg)
    assert [(i.domain, i.item_key) for i in out] == \
        [("arc-state", "z"), ("ideas", "a"), ("ideas", "b")]
    assert scan(reg) == out


def test_report_plain_language_preview_bounded():
    items = [_item(classification=Classification.LOCAL_ONLY),
             _item(key="r", remote=_src(), classification=Classification.ENGRAM_ONLY),
             _item(key="d", local=_src(content={"x": 1}), remote=_src(content={"x": 2}),
                   classification=Classification.DIVERGENT),
             _item(key="i", local=_src(state=SourceState.INVALID),
                   classification=Classification.INVALID)]
    report = build_report(items)
    assert any("Only in your workspace" in l for l in report.lines)
    assert any("Only in memory" in l for l in report.lines)
    assert severity(items[0]) == "info" and severity(items[2]) == "warning"
    assert severity(items[3]) == "error" and action_for(items[3]) is Action.DEFER
    assert action_for(items[0]) is Action.KEEP_LOCAL
    assert action_for(items[1]) is Action.KEEP_ENGRAM
    local = _src(loc="file:a.md", content={"text": "one\ntwo\nthree"})
    remote = _src(loc="engram:7", content={"text": "one\nTWO\nthree"})
    diff = file_diff(local, remote)
    assert diff.startswith("file:a.md") and "TWO" in diff
    p = preview_for(_item(key="k", local=local, remote=remote,
                          classification=Classification.DIVERGENT), Action.KEEP_LOCAL)
    assert p.label and p.detail  # progressive detail present
    big = _src(content={"text": "x" * 5000})
    eng = preview_for(_item(key="k", remote=big,
                            classification=Classification.ENGRAM_ONLY), Action.KEEP_ENGRAM)
    assert len(eng.detail) < 800  # bounded, not dumped
    assert "(untitled saved copy)" in eng.detail


def test_allowed_actions_and_batch_rules():
    assert Action.KEEP_LOCAL in allowed_actions(Classification.LOCAL_ONLY)
    assert Action.KEEP_ENGRAM in allowed_actions(Classification.ENGRAM_ONLY)
    assert set(allowed_actions(Classification.DIVERGENT)) == \
        {Action.KEEP_LOCAL, Action.KEEP_ENGRAM, Action.DEFER}
    assert allowed_actions(Classification.INVALID) == (Action.DEFER,)
    assert allowed_actions(Classification.EQUIVALENT) == (Action.DEFER,)
    same = [ConfirmedChoice("ideas", "a", Action.KEEP_LOCAL, "r1"),
            ConfirmedChoice("ideas", "b", Action.KEEP_LOCAL, "r2")]
    assert homogeneous_batch(same) is True
    assert homogeneous_batch([ConfirmedChoice("ideas", "a", Action.KEEP_LOCAL, "r1"),
                              ConfirmedChoice("ideas", "b", Action.KEEP_ENGRAM, "r2")]) is False
    assert homogeneous_batch([ConfirmedChoice("ideas", "a", Action.KEEP_LOCAL, "r1"),
                              ConfirmedChoice("arc-state", "b", Action.KEEP_LOCAL, "r2")]) is False


def test_confirm_stale_source_no_writes_fresh_report_required(tmp_path, tree_snapshot):
    """4.1: source changed before persistence -> nothing written, fresh report."""
    reg = AdapterRegistry()
    adapter = FakeAdapter()
    reg.register(adapter)
    stale_dir = tmp_path / "stale"
    stale_dir.mkdir()
    before = tree_snapshot(stale_dir)
    choice = ConfirmedChoice("ideas", "k", Action.KEEP_LOCAL, "revision-v1")
    adapter.items = [_item(key="k", local=_src(content={"text": "v2"}),
                           classification=Classification.LOCAL_ONLY)]
    with pytest.raises(ConfirmError) as err:
        confirm(reg, [choice], journal=RunJournal(stale_dir / "sync"))
    assert "fresh report" in str(err.value)
    assert tree_snapshot(stale_dir) == before  # zero writes: no journal, no files


def test_confirm_apply_refused_fail_closed_journaled(tmp_path):
    local = _src(content={"text": "v1"})
    reg = AdapterRegistry()
    reg.register(FakeAdapter([_item(key="k", local=local,
                                    classification=Classification.LOCAL_ONLY)]))
    journal = RunJournal(tmp_path / "sync")
    res = confirm(reg, [ConfirmedChoice("ideas", "k", Action.KEEP_LOCAL, local.revision)],
                  journal=journal, confirmation="APPLY")
    assert res[0].applied is False
    entry = journal.find(operation_id("ideas", "k", local.revision, "file:a.md", "keep-local"))
    assert entry is not None and entry.state == "failed"


# --- Phase 4b (task 4.4): CLI + session-start scan (restored from preserved sources) ---

@pytest.fixture(autouse=True)
def no_real_engram(monkeypatch):
    """Scans never invoke the real Engram binary in tests."""
    monkeypatch.setattr("engram_sync.engram_client.EngramClient.search",
                        lambda self, project, query, limit=10: [])


def _seed(tmp_path):
    (tmp_path / "mundos" / "vibrantes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "mundos" / "Ideas").mkdir(parents=True, exist_ok=True)
    idea = tmp_path / "mundos" / "Ideas" / "2026-08-07-sample.md"
    idea.write_text(("---\nid: \"b1c2d3e4-f5a6-7890-abcd-ef1234567890\"\n"
                     "slug: \"2026-08-07-sample\"\n"
                     "timestamp: \"2026-08-07T10:00:00Z\"\nsource: \"direct\"\n"
                     "type: \"idea_loose\"\ntags: []\nstatus: \"synced\"\n---\n\nBody\n"),
                    encoding="utf-8")


def test_cli_help_scan_session_start_domains(tmp_path, capsys, tree_snapshot):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "scan" in out and "report" in out and "confirm" in out and "--root" in out
    assert "journal" not in out.lower()  # no storage jargon in help
    _seed(tmp_path)
    before = tree_snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "scan"]) == 0
    out = capsys.readouterr().out
    assert "item(s) need attention" in out and "engram" not in out.lower()
    assert main(["--root", str(tmp_path), "scan", "--session-start"]) == 0
    out = capsys.readouterr().out
    assert "Session start" in out and "Nothing was changed" in out
    assert tree_snapshot(tmp_path) == before  # informational counts only
    assert main(["--root", str(tmp_path), "scan", "domains"]) == 0
    assert "ideas" in capsys.readouterr().out
    assert main(["scan", "--root", str(tmp_path), "--session-start"]) == 0
    assert "Nothing was changed" in capsys.readouterr().out


def test_cli_confirm_fail_closed_and_unknown_action(tmp_path, capsys):
    choices = tmp_path / "choices.json"
    choices.write_text(json.dumps({"confirmation": "APPLY", "choices":
                                   [{"domain": "ideas", "item_key": "k",
                                     "action": "keep-engram",
                                     "source_revision": "r1"}]}), encoding="utf-8")
    assert main(["--root", str(tmp_path), "confirm", str(choices),
                 "--confirm", "APPLY"]) == 2
    captured = capsys.readouterr()
    assert "fresh report" in captured.err and "not applied" in captured.err
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"confirmation": "APPLY", "choices":
                               [{"domain": "ideas", "item_key": "k",
                                 "action": "explode", "source_revision": "r1"}]}),
                   encoding="utf-8")
    assert main(["--root", str(tmp_path), "confirm", str(bad),
                 "--confirm", "APPLY"]) == 2


def test_cli_scan_engram_outage_graceful_no_writes(tmp_path, capsys, tree_snapshot,
                                                   monkeypatch):
    """Engram unreachable -> plain note on stderr, exit 0, local data unchanged."""
    from engram_sync.engram_client import EngramError

    def _boom(self, project, query, limit=10):
        raise EngramError("engram exited with code 1")

    monkeypatch.setattr("engram_sync.engram_client.EngramClient.search", _boom)
    _seed(tmp_path)
    before = tree_snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "scan"]) == 0
    captured = capsys.readouterr()
    assert "saved memory is unreachable" in captured.err
    assert "local data is unchanged" in captured.err
    assert tree_snapshot(tmp_path) == before  # zero writes on outage
