"""RED/GREEN: journal — op IDs, restart, bounded retries, abandon, retention (2.4-2.5)."""

from datetime import datetime, timedelta, timezone

import pytest

from engram_sync.journal import MAX_ATTEMPTS, RunJournal, operation_id

T0 = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


def _clock(start=T0):
    value = [start]

    def now():
        value[0] += timedelta(seconds=1)
        return value[0].isoformat(timespec="seconds")

    return now


def _args(**kw):
    opts = {"run_id": "run-1", "domain": "ideas", "item_key": "portal-stones",
            "source_revision": "rev-a", "target": "engram://vibrantes/nec/ideas/k",
            "action": "keep-engram"}
    opts.update(kw)
    return opts


def test_operation_id_stable_and_sensitive():
    oid = operation_id("ideas", "k", "rev-a", "engram://v/nec/ideas/k", "keep-engram")
    assert oid == operation_id("ideas", "k", "rev-a", "engram://v/nec/ideas/k", "keep-engram")
    assert oid != operation_id("ideas", "k", "rev-b", "engram://v/nec/ideas/k", "keep-engram")
    assert len(oid) == 64


def test_plan_apply_roundtrip_deterministic(tmp_path):
    outputs = []
    for sub in ("a", "b"):
        journal = RunJournal(tmp_path / sub, now=_clock())
        op_id = journal.plan(**_args()).operation_id
        assert journal.mark(op_id, "confirmed").state == "confirmed"
        applied = journal.mark(op_id, "applied")
        assert applied.state == "applied" and journal.find(op_id) == applied
        outputs.append(journal.path.read_text(encoding="utf-8"))
    assert outputs[0] == outputs[1]  # identical JSON rows across runs
    assert '"state":"applied"' in outputs[0]


def test_restart_reuses_id_and_never_replays(tmp_path):
    journal = RunJournal(tmp_path / "sync", now=_clock())
    op_id = journal.plan(**_args()).operation_id
    journal.mark(op_id, "applied")
    restarted = RunJournal(tmp_path / "sync", now=_clock())  # same dir, new instance
    assert restarted.find(op_id) == journal.find(op_id)  # same operation ID
    assert restarted.is_resolved(op_id)  # completed write: no replay
    assert not restarted.can_retry(op_id)


def test_retries_bounded_recovered_and_exhausted(tmp_path):
    journal = RunJournal(tmp_path / "sync", now=_clock())
    op_id = journal.plan(**_args()).operation_id
    journal.mark(op_id, "failed", "2")
    journal.mark(op_id, "failed", "2")
    assert journal.can_retry(op_id) and journal.find(op_id).attempts == 2
    assert journal.mark(op_id, "recovered").state == "recovered"
    assert not RunJournal(tmp_path / "sync", now=_clock()).can_retry(op_id)
    other = RunJournal(tmp_path / "b", now=_clock())
    other_id = other.plan(**_args(item_key="other")).operation_id
    for _ in range(MAX_ATTEMPTS):
        other.mark(other_id, "failed", "2")
    assert other.find(other_id).attempts == MAX_ATTEMPTS
    assert not other.can_retry(other_id)


def test_abandon_is_explicit_terminal_state(tmp_path):
    journal = RunJournal(tmp_path / "sync", now=_clock())
    abandoned = journal.mark(journal.plan(**_args()).operation_id, "abandoned")
    assert abandoned.state == "abandoned"
    assert journal.is_resolved(abandoned.operation_id)
    assert not journal.can_retry(abandoned.operation_id)


def test_retention_prunes_old_resolved_keeps_unresolved(tmp_path):
    journal = RunJournal(tmp_path / "sync", now=_clock())
    old = journal.mark(journal.plan(**_args(item_key="old")).operation_id, "applied")
    pending = journal.mark(journal.plan(**_args(item_key="pending")).operation_id, "failed", "1")
    journal._now = _clock(T0 + timedelta(days=91))
    journal.retain()
    assert journal.find(old.operation_id) is None
    assert journal.find(pending.operation_id) is not None  # unresolved stays


def test_retention_caps_at_max_entries(tmp_path, monkeypatch):
    monkeypatch.setattr("engram_sync.journal.MAX_ENTRIES", 5)
    journal = RunJournal(tmp_path / "sync", now=_clock())
    [journal.plan(**_args(item_key=f"k{i}")) for i in range(10)]
    journal.retain()
    assert len(journal._rows()) == 5


def test_unknown_or_invalid_state_is_safe(tmp_path):
    journal = RunJournal(tmp_path / "sync", now=_clock())
    op_id = journal.plan(**_args()).operation_id
    with pytest.raises(KeyError):
        journal.mark("0" * 64, "applied")
    with pytest.raises(ValueError):
        journal.mark(op_id, "exploded")
    assert journal.find(op_id).state == "planned"  # unchanged, no partial write
