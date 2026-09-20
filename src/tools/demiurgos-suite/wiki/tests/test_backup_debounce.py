# -*- coding: utf-8 -*-
"""Debounced, coalescing trigger tests for WU-11 (REQ-BE-6, SC-BE-6.1/6.2/6.3).

The engine's clock and waiter are injected, so the schedule is exercised with a
VIRTUAL clock: a burst of edits is applied by moving that clock, and the run is
observed by pumping the loop. No test sleeps and no test waits for a real
debounce window.

Three proofs:

* a single save runs inside ``[t0+5, t0+10]`` (SC-BE-6.1);
* 20 edits inside the window produce exactly ONE run, covering every changed
  path, and that run also lands inside ``[t0+5, t0+10]`` (SC-BE-6.2);
* the reconciliation tick feeds the SAME deadline when a change is detected
  (SC-BE-6.3), and the debounce window is clamped to ``[5, 10]`` seconds.

The thread tests use a gate waiter and a bounded rendezvous, so they complete
without a sleep; every test asserts that no engine thread is left behind, and
the worker is a daemon.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from backup.engine import (  # noqa: E402
    DEFAULT_DEBOUNCE_SECONDS,
    MAX_DEBOUNCE_SECONDS,
    MIN_DEBOUNCE_SECONDS,
    QUIESCE_MARKER_NAME,
    THREAD_NAME,
    BackupEngine,
    NoopObserver,
    is_write_quiesced,
    resolve_debounce_seconds,
    set_active_engine,
)

#: The debounce the schedule tests pin: the documented default.
DEBOUNCE = DEFAULT_DEBOUNCE_SECONDS
#: The task's own scenario: 20 edits inside 3 s.
EDITS = 20
#: 20 edits over 1.425 s — inside the 3 s burst — with a clean margin under t0+10.
SPACING = 0.075


class VirtualClock:
    """A monotonic-clock stand-in the test moves by hand. Never reads real time."""

    def __init__(self, start: float = 1000.0) -> None:
        self._lock = threading.Lock()
        self._now = start

    def __call__(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> float:
        with self._lock:
            self._now += seconds
            return self._now


class RecordingRunner:
    """A runner that records each call and signals the first one."""

    def __init__(self) -> None:
        self.calls = 0
        self.ran = threading.Event()

    def __call__(self) -> dict:
        self.calls += 1
        self.ran.set()
        return {"call": self.calls}


class GateWaiter:
    """A deterministic waiter: the test releases every wait explicitly.

    ``timeout`` is ignored on purpose — the virtual clock defines when a
    deadline elapses, and the test releases the worker after moving it. No real
    time is ever waited on.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._permits = 0
        self._parked = threading.Event()

    def notify(self) -> None:
        with self._condition:
            self._permits += 1
            self._condition.notify_all()

    def wait(self, timeout: float) -> bool:  # noqa: ARG002 — the gate defines the wake
        with self._condition:
            self._parked.set()
            while self._permits == 0:
                self._condition.wait()
            self._permits -= 1
        self._parked.clear()
        return True

    def wait_for_park(self, timeout: float = 2.0) -> bool:
        """Bounded rendezvous: returns as soon as the worker parks."""
        return self._parked.wait(timeout)


def _engine_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == THREAD_NAME]


@pytest.fixture
def engine_factory():
    """Build a frozen engine: virtual clock, no observer, a recording runner."""
    created: list[BackupEngine] = []

    def build(**overrides) -> tuple[BackupEngine, RecordingRunner, VirtualClock]:
        runner = RecordingRunner()
        clock = VirtualClock()
        settings = {
            "clock": clock,
            "debounce_seconds": DEBOUNCE,
            "reconcile_interval": None,
            "observer_factory": lambda root, on_change: NoopObserver(),
        }
        settings.update(overrides)
        engine = BackupEngine(runner, **settings)
        created.append(engine)
        return engine, runner, clock

    yield build
    for engine in created:
        engine.stop(timeout=2.0)
    set_active_engine(None)


# ---------------------------------------------------------------------------
# SC-BE-6.1 — one save, one run, inside [t0+5, t0+10]
# ---------------------------------------------------------------------------


def test_a_single_save_runs_inside_the_debounce_window(engine_factory) -> None:
    engine, runner, clock = engine_factory()
    t0 = clock()

    engine.notify("ideas/alpha.md")

    assert engine.pending_deadline == t0 + DEBOUNCE
    clock.advance(DEBOUNCE - 0.1)
    assert engine.pump() is False
    assert runner.calls == 0

    run_at = clock.advance(0.1)
    assert engine.pump() is True

    elapsed = run_at - t0
    assert MIN_DEBOUNCE_SECONDS <= elapsed <= MAX_DEBOUNCE_SECONDS
    assert runner.calls == 1
    assert engine.runs == 1
    assert engine.pending_deadline is None


def test_no_run_happens_before_the_window_elapses(engine_factory) -> None:
    engine, runner, _clock = engine_factory()
    engine.notify()

    # The clock never moves: the deadline can never be reached.
    for _ in range(10):
        assert engine.pump() is False
    assert runner.calls == 0


# ---------------------------------------------------------------------------
# SC-BE-6.2 — 20 edits inside 3 s coalesce into ONE run
# ---------------------------------------------------------------------------


def test_twenty_edits_in_three_seconds_produce_exactly_one_run(engine_factory) -> None:
    engine, runner, clock = engine_factory()
    t0 = clock()

    for index in range(EDITS):
        clock.advance(SPACING)
        engine.notify(f"ideas/{index}.md")

    last_edit = clock()
    assert last_edit - t0 < 3.0, "the burst must stay inside the scenario's 3 s"
    assert engine.events == EDITS
    # Every edit moved the deadline: no run started while the burst was live.
    assert runner.calls == 0
    assert engine.pending_deadline == last_edit + DEBOUNCE

    clock.advance(DEBOUNCE - 0.1)
    assert engine.pump() is False
    assert runner.calls == 0

    run_at = clock.advance(0.1)
    assert engine.pump() is True

    assert runner.calls == 1, "the burst must coalesce into a single run"
    elapsed = run_at - t0
    assert MIN_DEBOUNCE_SECONDS <= elapsed <= MAX_DEBOUNCE_SECONDS
    assert len(engine.last_paths) == EDITS, "the one run covers every changed path"


def test_a_second_burst_opens_a_new_window(engine_factory) -> None:
    engine, runner, clock = engine_factory()
    engine.notify("ideas/alpha.md")
    clock.advance(DEBOUNCE)
    assert engine.pump() is True

    engine.notify("ideas/beta.md")
    clock.advance(DEBOUNCE - 0.1)
    assert engine.pump() is False
    clock.advance(0.1)
    assert engine.pump() is True
    assert runner.calls == 2


# ---------------------------------------------------------------------------
# SC-BE-6.3 — the reconciliation tick feeds the SAME deadline
# ---------------------------------------------------------------------------


def test_reconciliation_tick_feeds_the_same_deadline(engine_factory) -> None:
    state = {"changed": False}
    engine, runner, clock = engine_factory(
        reconcile_interval=300.0,
        reconcile=lambda: state["changed"],
    )

    assert engine.pump() is False  # baseline tick scheduled, nothing changed
    assert runner.calls == 0

    state["changed"] = True
    clock.advance(300.0)
    assert engine.pump() is False
    assert engine.pending_deadline == clock() + DEBOUNCE, "the tick uses the same deadline"

    clock.advance(DEBOUNCE)
    assert engine.pump() is True
    assert runner.calls == 1


def test_an_unchanged_reconcile_tick_schedules_nothing(engine_factory) -> None:
    engine, runner, clock = engine_factory(
        reconcile_interval=300.0,
        reconcile=lambda: False,
    )
    engine.pump()
    clock.advance(300.0)
    assert engine.pump() is False
    assert engine.pending_deadline is None
    assert runner.calls == 0


# ---------------------------------------------------------------------------
# The durable gate: a run needs a REAL change to the included tree (REQ-BE-6)
# ---------------------------------------------------------------------------


def _armable_root(tmp_path: Path) -> Path:
    """A real data root with one included world file and one excluded code file."""
    root = tmp_path / "data-root"
    (root / "mundos").mkdir(parents=True)
    (root / "mundos" / "alpha.md").write_text("alpha", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "code.py").write_text("code", encoding="utf-8")
    return root


def test_an_excluded_path_event_does_not_schedule_a_run(tmp_path, engine_factory) -> None:
    """A durable event on an EXCLUDED path must not start a run.

    Regression for the class of leaks the observer cannot fully close (directory
    events, normalization edge cases, the event-loss backstop, or a future
    gap): the engine must gate the run on the included-tree fingerprint, not on
    the mere arrival of a signal. Non-vacuous: on the pre-gate code the second
    ``pump()`` returns ``True`` and the runner is called twice, so the assertion
    below fails.
    """
    root = _armable_root(tmp_path)
    engine, runner, clock = engine_factory(data_root=root)

    # Arm the gate: the first scheduled run takes the baseline fingerprint.
    engine.notify("mundos/alpha.md")
    clock.advance(DEBOUNCE)
    assert engine.pump() is True
    assert runner.calls == 1

    # A write under an EXCLUDED path changes nothing the snapshot takes.
    (root / "src" / "code.py").write_text("code changed", encoding="utf-8")
    engine.notify("src/code.py")
    clock.advance(DEBOUNCE)

    assert engine.pump() is False, "an excluded-path event must not schedule a run"
    assert runner.calls == 1


def test_an_included_path_event_still_schedules_exactly_one_run(
    tmp_path, engine_factory
) -> None:
    """A genuine change to an INCLUDED path still produces exactly one run."""
    root = _armable_root(tmp_path)
    target = root / "mundos" / "alpha.md"
    engine, runner, clock = engine_factory(data_root=root)

    engine.notify("mundos/alpha.md")
    clock.advance(DEBOUNCE)
    assert engine.pump() is True
    assert runner.calls == 1

    target.write_text("alpha changed", encoding="utf-8")
    engine.notify("mundos/alpha.md")
    clock.advance(DEBOUNCE)

    assert engine.pump() is True, "a real data change must still schedule a run"
    assert runner.calls == 2, "exactly one run for the one genuine change"
    assert engine.pump() is False, "the run does not schedule another run"


def test_backup_reserved_artifacts_never_schedule_a_run(tmp_path, engine_factory) -> None:
    """The marker, its temp and the park directory are not author data.

    They are excluded from the inventory, so writing them leaves the included
    tree byte-identical and the gate drops the run. Without the exclusion the
    marker would be an included path and each write would move the fingerprint.
    """
    root = _armable_root(tmp_path)
    engine, runner, clock = engine_factory(data_root=root)

    engine.notify("mundos/alpha.md")
    clock.advance(DEBOUNCE)
    assert engine.pump() is True
    assert runner.calls == 1

    (root / QUIESCE_MARKER_NAME).write_text("{}", encoding="utf-8")
    (root / f"{QUIESCE_MARKER_NAME}.tmp-deadbeef").write_text("{}", encoding="utf-8")
    (root / ".demiurgos-old-abc" / "ideas").mkdir(parents=True)
    (root / ".demiurgos-old-abc" / "ideas" / "a.md").write_text("x", encoding="utf-8")
    engine.notify(QUIESCE_MARKER_NAME)
    clock.advance(DEBOUNCE)

    assert engine.pump() is False, "backup bookkeeping must not schedule a run"
    assert runner.calls == 1


# ---------------------------------------------------------------------------
# The debounce window is clamped into [5, 10]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, DEFAULT_DEBOUNCE_SECONDS),
        ("", DEFAULT_DEBOUNCE_SECONDS),
        ("not-a-number", DEFAULT_DEBOUNCE_SECONDS),
        ("1", MIN_DEBOUNCE_SECONDS),
        ("60", MAX_DEBOUNCE_SECONDS),
        ("6.5", 6.5),
    ],
)
def test_debounce_resolution_is_clamped(raw, expected) -> None:
    environ = {} if raw is None else {"DEMIURGOS_BACKUP_DEBOUNCE_SECONDS": raw}
    assert resolve_debounce_seconds(environ) == expected


def test_the_engine_uses_the_clamped_environment_value(engine_factory) -> None:
    engine, _runner, _clock = engine_factory(
        debounce_seconds=None, environ={"DEMIURGOS_BACKUP_DEBOUNCE_SECONDS": "1"}
    )
    assert engine.debounce_seconds == MIN_DEBOUNCE_SECONDS


# ---------------------------------------------------------------------------
# Quiesce / resume (REQ-RS-3 — mechanism only; the 503 is asserted in the
# middleware suite and the full restore flow in WU-13)
# ---------------------------------------------------------------------------


def test_quiesce_writes_a_marker_and_drops_notifications(tmp_path, engine_factory) -> None:
    engine, runner, _clock = engine_factory(data_root=tmp_path)

    engine.quiesce()
    assert engine.is_quiesced
    assert (tmp_path / QUIESCE_MARKER_NAME).is_file()

    engine.notify("ideas/alpha.md")
    assert engine.pending_deadline is None, "a quiesced engine schedules nothing"
    assert engine.events == 0
    assert engine.pump() is False
    assert runner.calls == 0

    engine.resume()
    assert not engine.is_quiesced
    assert not (tmp_path / QUIESCE_MARKER_NAME).exists()

    engine.notify("ideas/beta.md")
    assert engine.pending_deadline is not None


def test_a_marker_left_by_a_crash_keeps_the_engine_quiesced(tmp_path) -> None:
    (tmp_path / QUIESCE_MARKER_NAME).write_text("{}", encoding="utf-8")
    engine = BackupEngine(
        RecordingRunner(),
        data_root=tmp_path,
        reconcile_interval=None,
        observer_factory=lambda root, on_change: NoopObserver(),
    )
    try:
        assert engine.is_quiesced
        engine.start()
        assert engine.is_quiesced, "a crash-surviving marker must survive the restart"
    finally:
        engine.stop(timeout=2.0)
    assert _engine_threads() == []


def test_the_module_hook_reports_quiescence(tmp_path, engine_factory) -> None:
    engine, _runner, _clock = engine_factory(data_root=tmp_path)
    set_active_engine(engine)
    try:
        assert is_write_quiesced() is False
        engine.quiesce()
        assert is_write_quiesced() is True
    finally:
        engine.resume()
        set_active_engine(None)


# ---------------------------------------------------------------------------
# Thread lifecycle: a daemon worker that is always joined, never leaked
# ---------------------------------------------------------------------------


def test_the_worker_is_a_daemon_and_is_joined_on_stop() -> None:
    runner = RecordingRunner()
    waiter = GateWaiter()
    engine = BackupEngine(
        runner,
        clock=VirtualClock(),
        waiter=waiter,
        debounce_seconds=DEBOUNCE,
        reconcile_interval=None,
    )
    engine.start()
    try:
        assert engine.worker_alive
        assert waiter.wait_for_park(2.0), "the worker must park on the injected waiter"
        active = _engine_threads()
        assert len(active) == 1
        assert active[0].daemon, "a leaked worker must never block interpreter exit"
    finally:
        engine.stop(timeout=2.0)
    assert not engine.worker_alive
    assert _engine_threads() == [], "no engine thread may outlive stop()"


def test_the_worker_runs_after_the_injected_clock_reaches_the_deadline() -> None:
    runner = RecordingRunner()
    clock = VirtualClock()
    waiter = GateWaiter()
    engine = BackupEngine(
        runner,
        clock=clock,
        waiter=waiter,
        debounce_seconds=DEBOUNCE,
        reconcile_interval=None,
    )
    engine.start()
    try:
        assert waiter.wait_for_park(2.0)
        engine.notify("ideas/alpha.md")
        clock.advance(DEBOUNCE)
        waiter.notify()
        assert runner.ran.wait(2.0), "the worker must run the runner once the deadline is due"
    finally:
        engine.stop(timeout=2.0)
    assert runner.calls == 1
    assert _engine_threads() == []


def test_stop_drops_a_pending_deadline_without_flushing_it() -> None:
    runner = RecordingRunner()
    waiter = GateWaiter()
    engine = BackupEngine(
        runner,
        clock=VirtualClock(),
        waiter=waiter,
        debounce_seconds=DEBOUNCE,
        reconcile_interval=None,
    )
    engine.start()
    try:
        assert waiter.wait_for_park(2.0)
        engine.notify("ideas/alpha.md")
    finally:
        engine.stop(timeout=2.0)
    assert engine.pending_deadline is None
    assert runner.calls == 0, "a pending deadline is dropped, never flushed at shutdown"
    assert _engine_threads() == []
