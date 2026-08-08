"""Debounced file signals and cross-trigger deduplication.

The watcher receives file changes from an OS watcher or another read-only
scanner. It never reads or writes a source itself; the reconciliation layer
decides what a signal means.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import threading
from typing import Callable, Iterable


@dataclass(frozen=True)
class Signal:
    """A source change identified by stable, non-content-sensitive metadata."""

    source: str
    domain: str
    item_key: str
    fingerprint: str = ""
    revision: str = ""
    operation_id: str = ""


class SignalDeduplicator:
    """Suppress repeated file, Engram, poll, and worker notifications.

    Fingerprints and revisions are tracked independently so a poll signal can
    suppress a prior file or Engram signal. Worker signals are never emitted
    without an operation ID and are suppressed after the originating signal.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._operations: set[str] = set()
        self._fingerprints: set[tuple[str, str, str]] = set()
        self._revisions: set[tuple[str, str, str]] = set()
        self._bare: set[tuple[str, str]] = set()
        self.accepted = 0
        self.suppressed = 0

    def accept(self, signal: Signal) -> bool:
        """Record and accept a new signal, or suppress an already-seen one."""
        with self._lock:
            if signal.source == "worker":
                self.suppressed += 1
                return False

            operation_seen = bool(signal.operation_id and
                                  signal.operation_id in self._operations)
            fingerprint_key = ((signal.domain, signal.item_key, signal.fingerprint)
                               if signal.fingerprint else None)
            revision_key = ((signal.domain, signal.item_key, signal.revision)
                            if signal.revision else None)
            bare_key = (signal.domain, signal.item_key)
            evidence_seen = ((fingerprint_key is not None and
                              fingerprint_key in self._fingerprints) or
                             (revision_key is not None and
                              revision_key in self._revisions) or
                             (not signal.operation_id and
                              fingerprint_key is None and revision_key is None and
                              bare_key in self._bare))
            if operation_seen or evidence_seen:
                self.suppressed += 1
                return False

            if signal.operation_id:
                self._operations.add(signal.operation_id)
            if fingerprint_key is not None:
                self._fingerprints.add(fingerprint_key)
            if revision_key is not None:
                self._revisions.add(revision_key)
            if not signal.operation_id and fingerprint_key is None and revision_key is None:
                self._bare.add((signal.domain, signal.item_key))
            self.accepted += 1
            return True

    def clear(self) -> None:
        """Forget trigger history after an explicit daemon reset."""
        with self._lock:
            self._operations.clear()
            self._fingerprints.clear()
            self._revisions.clear()
            self._bare.clear()
            self.accepted = 0
            self.suppressed = 0


class Watcher:
    """500 ms debounce boundary for file signals.

    ``submit`` is the adapter boundary for watchdog, polling, or tests. The
    optional ``flush`` method makes the debounce behavior deterministic without
    waiting in tests or forcing a specific filesystem watcher dependency.
    """

    def __init__(self, callback: Callable[[Signal], None] | None = None,
                 *, debounce_seconds: float = 0.5,
                 deduplicator: SignalDeduplicator | None = None) -> None:
        if debounce_seconds < 0:
            raise ValueError("debounce must not be negative")
        self._callback = callback
        self.debounce_seconds = debounce_seconds
        self._deduplicator = deduplicator or SignalDeduplicator()
        self._lock = threading.RLock()
        self._pending: dict[tuple[str, str], tuple[Signal, threading.Timer]] = {}
        self._running = False
        self._observer = None
        self.emitted = 0

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def deduplicator(self) -> SignalDeduplicator:
        return self._deduplicator

    def set_callback(self, callback: Callable[[Signal], None]) -> None:
        self._callback = callback

    def set_deduplicator(self, deduplicator: SignalDeduplicator) -> None:
        with self._lock:
            self._deduplicator = deduplicator

    def start(self, paths: Iterable[str | Path] = (),
              signal_factory: Callable[[Path, str], Signal] | None = None) -> None:
        paths = tuple(Path(path) for path in paths)
        if paths and signal_factory is None:
            raise ValueError("signal_factory is required for filesystem watching")
        with self._lock:
            self._running = True
        if paths:
            self._start_observer(paths, signal_factory)

    def stop(self) -> None:
        with self._lock:
            self._running = False
            pending = list(self._pending.values())
            self._pending.clear()
        for _, timer in pending:
            timer.cancel()
        observer = self._observer
        self._observer = None
        if observer is not None:
            observer.stop()
            observer.join(timeout=2)

    def submit(self, signal: Signal) -> bool:
        """Submit a file signal and schedule its debounced delivery."""
        with self._lock:
            if not self._running or not self._deduplicator.accept(signal):
                return False
            key = (signal.domain, signal.item_key)
            previous = self._pending.pop(key, None)
            if previous is not None:
                previous[1].cancel()
            timer = threading.Timer(self.debounce_seconds, self._deliver, (key, signal))
            timer.daemon = True
            self._pending[key] = (signal, timer)
            timer.start()
            return True

    on_event = submit

    def flush(self, domain: str | None = None, item_key: str | None = None) -> int:
        """Deliver pending signals immediately; intended for tests and shutdown."""
        with self._lock:
            keys = list(self._pending)
            if domain is not None:
                keys = [key for key in keys if key[0] == domain]
            if item_key is not None:
                keys = [key for key in keys if key[1] == item_key]
            pending = [(key, self._pending.pop(key)) for key in keys]
        for key, (signal, timer) in pending:
            timer.cancel()
            with self._lock:
                running = self._running
            if running and self._callback is not None:
                self.emitted += 1
                self._callback(signal)
        return len(pending)

    def _deliver(self, key: tuple[str, str], signal: Signal | None) -> None:
        with self._lock:
            pending = self._pending.pop(key, None)
            if pending is None:
                return
            signal = pending[0]
            if not self._running:
                return
        if self._callback is not None:
            self.emitted += 1
            self._callback(signal)

    def _start_observer(self, paths: tuple[Path, ...], signal_factory) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError as error:
            with self._lock:
                self._running = False
            raise ImportError("watchdog is required for filesystem watching") from error

        watcher = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    watcher._filesystem_event(Path(event.src_path), signal_factory)

            def on_modified(self, event):
                if not event.is_directory:
                    watcher._filesystem_event(Path(event.src_path), signal_factory)

            def on_deleted(self, event):
                if not event.is_directory:
                    watcher._filesystem_event(Path(event.src_path), signal_factory)

        observer = Observer()
        scheduled = False
        for path in paths:
            if path.is_dir():
                observer.schedule(Handler(), str(path), recursive=True)
                scheduled = True
        if scheduled:
            observer.start()
            self._observer = observer

    def _filesystem_event(self, path: Path, signal_factory) -> None:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digest = ""
        self.submit(signal_factory(path, digest))
