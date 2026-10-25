# -*- coding: utf-8 -*-
"""Observer signal tests for WU-11/REQ-BE-6: only real writes schedule a run.

Regression for the Linux snapshot loop. ``watchdog`` over inotify delivers
``opened`` and ``closed_no_write`` for PURE READS, and every backup run reads
the whole data root. Without an event-type gate, each run signalled on its own
reads, scheduled the next run eight seconds later, and the destination filled
with snapshots while the app sat idle.

Two proofs:

* the predicate keeps every read-only event type out and lets every durable one
  through, so a write is never lost either;
* against a REAL observer, reading a file signals nothing while writing it does.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.engine import default_observer_factory, is_durable_event  # noqa: E402

#: The read-only event types watchdog 6 emits (observed over inotify).
READ_EVENT_TYPES = ("opened", "closed", "closed_no_write")
#: The event types that mean bytes changed on disk (watchdog 6, observed).
DURABLE_EVENT_TYPES = ("created", "modified", "deleted", "moved")


@pytest.mark.parametrize("event_type", READ_EVENT_TYPES)
def test_a_read_only_event_never_signals(event_type: str) -> None:
    assert is_durable_event(event_type) is False


@pytest.mark.parametrize("event_type", DURABLE_EVENT_TYPES)
def test_a_durable_event_signals(event_type: str) -> None:
    assert is_durable_event(event_type) is True


def test_an_unknown_event_type_never_signals() -> None:
    assert is_durable_event("something-new") is False


def _wait_for(predicate: Callable[[], bool], timeout: float) -> bool:
    """Poll *predicate* until it is true or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="inotify read events (opened/closed_no_write) are Linux-only",
)
def test_a_read_signals_nothing_and_a_write_signals(tmp_path: Path) -> None:
    pytest.importorskip("watchdog")
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")

    calls: list[str] = []
    observer = default_observer_factory(tmp_path, calls.append)
    observer.start()
    try:
        time.sleep(0.3)  # let the watcher settle before the reads
        for _ in range(5):
            target.read_text(encoding="utf-8")
        time.sleep(0.5)
        assert calls == [], f"a pure read signalled {calls!r}"

        target.write_text("y", encoding="utf-8")
        assert _wait_for(lambda: bool(calls), timeout=5.0), "a write did not signal"
    finally:
        observer.stop()


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="inotify events are Linux-only",
)
def test_a_runtime_log_write_never_signals_while_author_data_does(
    tmp_path: Path,
) -> None:
    """``logs/`` writes must not schedule a backup (regression).

    The app writes its runtime log on every request, and the log lives inside
    the data root. Without an exclusion, serving the UI kept the engine in a
    self-sustaining snapshot loop; author data must still signal.
    """
    pytest.importorskip("watchdog")
    (tmp_path / "logs").mkdir()
    (tmp_path / "ideas").mkdir()
    log = tmp_path / "logs" / "demiurgos-api.log"
    note = tmp_path / "ideas" / "nota.md"

    calls: list[str] = []
    observer = default_observer_factory(tmp_path, calls.append)
    observer.start()
    try:
        time.sleep(0.3)  # let the watcher settle
        for _ in range(5):
            with log.open("a", encoding="utf-8") as handle:
                handle.write("INFO GET /api/backup/status 200 OK\n")
        time.sleep(0.5)
        assert calls == [], f"a runtime log write signalled {calls!r}"

        note.write_text("x", encoding="utf-8")
        assert _wait_for(
            lambda: any(path.startswith("ideas") for path in calls), 3.0
        ), "author data did not signal"
        assert not any(path.startswith("logs") for path in calls), calls
    finally:
        observer.stop()
