"""Bounded Engram polling cadence with read-only signal delivery."""

from __future__ import annotations

import threading
import time
from typing import Callable, Iterable

from .watcher import Signal, SignalDeduplicator


DEFAULT_INTERVAL_SECONDS = 60.0
MIN_INTERVAL_SECONDS = 30.0
MAX_INTERVAL_SECONDS = 15 * 60.0


def bounded_interval(seconds: float) -> float:
    """Clamp a configured cadence to the Phase 5 safety bounds."""
    return max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, float(seconds)))


class Poller:
    """Poll Engram on a bounded cadence and emit deduplicated signals."""

    def __init__(self, poll: Callable[[], Iterable[Signal]],
                 callback: Callable[[Signal], None] | None = None, *,
                 interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
                 deduplicator: SignalDeduplicator | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.interval_seconds = bounded_interval(interval_seconds)
        self._next_interval = self.interval_seconds
        self._poll = poll
        self._callback = callback
        self._deduplicator = deduplicator or SignalDeduplicator()
        self._sleep = sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._running = False
        self._last_error = ""
        self._last_poll = 0
        self.poll_count = 0
        self.emitted = 0

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def next_interval(self) -> float:
        return self._next_interval

    @property
    def last_error(self) -> str:
        return self._last_error

    def set_callback(self, callback: Callable[[Signal], None]) -> None:
        self._callback = callback

    def set_deduplicator(self, deduplicator: SignalDeduplicator) -> None:
        self._deduplicator = deduplicator

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._stop.clear()
            self._running = True
            self._thread = threading.Thread(target=self._run, name="engram-sync-poller",
                                            daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._lock:
            self._running = False
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def run_once(self) -> list[Signal]:
        """Poll once; errors stay in health state and never cause writes."""
        try:
            result = self._poll() or []
            signals = [result] if isinstance(result, Signal) else list(result)
        except Exception as error:  # boundary must keep the daemon alive
            self._last_error = type(error).__name__
            self._next_interval = bounded_interval(self._next_interval * 2)
            return []

        self.poll_count += 1
        self._last_error = ""
        self._next_interval = self.interval_seconds
        for signal in signals:
            if self._deduplicator.accept(signal) and self._callback is not None:
                self.emitted += 1
                self._callback(signal)
        return signals

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self._next_interval)
