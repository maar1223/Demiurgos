"""Fail-closed lifecycle coordinator for Phase 5 triggers."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
import threading
from typing import Callable, Mapping

from .watcher import Signal, SignalDeduplicator


class Lifecycle(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True)
class Readiness:
    recovery: bool
    authorization: bool
    conflicts: bool
    no_data_loss: bool
    status: bool

    @property
    def ready(self) -> bool:
        return all(asdict(self).values())


class Daemon:
    """Run watcher and poller triggers without authorizing persistence.

    The callback receives signals only. Applying a proposal remains outside
    this daemon and therefore cannot happen as a side effect of a trigger.
    """

    def __init__(self, watcher, poller, *,
                 on_signal: Callable[[Signal], None] | None = None,
                 readiness_checks: Mapping[str, bool | Callable[[], bool]] | None = None,
                 deduplicator: SignalDeduplicator | None = None) -> None:
        self.watcher = watcher
        self.poller = poller
        self._on_signal = on_signal
        self._checks = {"recovery": False, "authorization": True,
                        "conflicts": False, "no_data_loss": True}
        self._checks.update(readiness_checks or {})
        self.deduplicator = deduplicator or SignalDeduplicator()
        self._lock = threading.RLock()
        self._state = Lifecycle.STOPPED
        self._last_error = ""
        self._started_at = ""
        self._restart_count = 0
        self._signals = 0

        self.watcher.set_callback(self._receive)
        self.poller.set_callback(self._receive)
        self.watcher.set_deduplicator(self.deduplicator)
        self.poller.set_deduplicator(self.deduplicator)

    @property
    def state(self) -> Lifecycle:
        return self._state

    def start(self) -> bool:
        with self._lock:
            if self._state is Lifecycle.RUNNING:
                return self.ready()
            if not self._gates_proven():
                self._last_error = "readiness gates are unproven"
                self._state = Lifecycle.STOPPED
                return False
            self._state = Lifecycle.STARTING
            self._last_error = ""
        try:
            self.watcher.start()
            self.poller.start()
        except Exception as error:
            self._last_error = type(error).__name__
            self._state = Lifecycle.FAILED
            try:
                self.watcher.stop()
                self.poller.stop()
            except Exception:
                pass
            return False
        with self._lock:
            self._state = Lifecycle.RUNNING
        if not self.ready():
            self.stop()
            with self._lock:
                self._last_error = "operational readiness could not be proven"
            return False
        return True

    def stop(self) -> bool:
        with self._lock:
            if self._state is Lifecycle.STOPPED:
                return True
            self._state = Lifecycle.STOPPING
        errors = []
        for component in (self.watcher, self.poller):
            try:
                component.stop()
            except Exception as error:
                errors.append(type(error).__name__)
        with self._lock:
            self._last_error = ", ".join(errors)
            self._state = Lifecycle.FAILED if errors else Lifecycle.STOPPED
        return not errors

    def restart(self) -> bool:
        if not self.stop():
            return False
        self._restart_count += 1
        return self.start()

    def _gates_proven(self) -> bool:
        for name in ("recovery", "authorization", "conflicts", "no_data_loss"):
            value = self._checks.get(name, False)
            try:
                if not bool(value() if callable(value) else value):
                    return False
            except Exception:
                return False
        return True

    def readiness(self) -> Readiness:
        def check(name: str) -> bool:
            value = self._checks.get(name, True)
            try:
                return bool(value() if callable(value) else value)
            except Exception:
                return False

        status = self._state is Lifecycle.RUNNING and self.watcher.running and self.poller.running
        return Readiness(recovery=check("recovery"),
                         authorization=check("authorization"),
                         conflicts=check("conflicts"),
                         no_data_loss=check("no_data_loss"),
                         status=status)

    def ready(self) -> bool:
        return self.readiness().ready

    def health(self) -> dict[str, object]:
        readiness = self.readiness()
        return {"state": self._state.value,
                "ready": readiness.ready,
                "readiness": asdict(readiness),
                "watcher_running": self.watcher.running,
                "poller_running": self.poller.running,
                "accepted_signals": self.deduplicator.accepted,
                "suppressed_signals": self.deduplicator.suppressed,
                "signals": self._signals,
                "restart_count": self._restart_count,
                "last_error": self._last_error}

    def _receive(self, signal: Signal) -> None:
        self._signals += 1
        if self._on_signal is not None:
            self._on_signal(signal)
