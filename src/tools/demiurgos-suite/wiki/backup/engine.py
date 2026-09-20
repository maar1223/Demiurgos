# -*- coding: utf-8 -*-
"""Backup engine lifecycle: debounced trigger, worker, watchdog and quiesce (WU-11).

The engine is the write side of REQ-BE-6. It schedules ONE backup run a few
seconds after the last change and coalesces a burst into that single run.

**The hook is cheap on purpose.** :func:`notify_data_changed` is called from a
request path, so it performs NO I/O: it reads the active engine and delegates to
:meth:`BackupEngine.notify`, which takes a lock, moves a deadline and pushes one
token onto a queue. Everything expensive — inventory, hashing, SQLite backup,
publish — happens on the worker thread.

**Three triggers feed ONE deadline (SC-BE-6.3).**

1. the ASGI middleware / direct callers (Layer A/B) call ``notify``;
2. a watchdog observer rooted at the data root calls ``notify`` per real event;
3. a periodic reconciliation tick (default 300 s) compares a data-root
   fingerprint and calls ``notify`` only when it diverges — the backstop for
   mounts where filesystem events are never delivered.

**Debounce arithmetic (SC-BE-6.1/6.2).** ``notify`` sets
``_deadline = clock() + debounce``; the worker blocks on the injected waiter
with a timeout equal to the remaining window, so a save at ``t0`` runs at
``t0 + debounce`` and 20 edits inside the window still produce ONE run at the
last edit + ``debounce``. The window is clamped from
``DEMIURGOS_BACKUP_DEBOUNCE_SECONDS`` into ``[5, 10]`` seconds.

**Quiesce (REQ-RS-3).** :meth:`BackupEngine.quiesce` raises a marker and drops
the pending deadline; the middleware then rejects mutating ``/api/*`` requests
with ``503`` + ``Retry-After``. The marker survives a crash, so the next start
refuses to write until it is explicitly resolved (:meth:`resume`).

**Injection.** ``clock``, ``waiter``, ``observer_factory`` and ``reconcile``
are injectable and the default observer degrades to a no-op when ``watchdog``
is not installed, so the engine is constructible without a real data root and
the suite never sleeps and never leaves a non-daemon thread behind. The worker
thread is a daemon, so it can never block interpreter exit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from backup.inventory import match_exclusion

logger = logging.getLogger("demiurgos-backup")

#: The debounce window: an 8 s default clamped to [5, 10] seconds.
DEFAULT_DEBOUNCE_SECONDS = 8.0
MIN_DEBOUNCE_SECONDS = 5.0
MAX_DEBOUNCE_SECONDS = 10.0
DEBOUNCE_ENV_VAR = "DEMIURGOS_BACKUP_DEBOUNCE_SECONDS"
#: Backstop for mounts where filesystem events are not delivered.
DEFAULT_RECONCILE_SECONDS = 300.0
#: The marker that makes the middleware reject writes while a restore owns the root.
QUIESCE_MARKER_NAME = ".demiurgos-maintenance.json"
MAINTENANCE_SCHEMA_VERSION = 1
#: Seconds advertised in the ``Retry-After`` header of the 503 response.
RETRY_AFTER_SECONDS = 5
#: The path recorded for a change the reconciliation backstop detected.
RECONCILE_PATH = "<reconcile>"
THREAD_NAME = "demiurgos-backup-engine"

#: One backup run. Zero-arity so the engine holds no transport or path special case.
Runner = Callable[[], Any]


class DataRootObserver(Protocol):
    """What the engine needs from a filesystem observer: start and stop."""

    def start(self) -> None:
        """Begin delivering change callbacks."""

    def stop(self) -> None:
        """Stop delivering change callbacks; safe to call twice."""


class NoopObserver:
    """A do-nothing observer — used when ``watchdog`` is unavailable or injected.

    It exists so the default observer seam degrades instead of failing: a
    machine without ``watchdog`` still runs the reconciliation backstop, and a
    test can inject this observer to prove the engine owns no thread it cannot
    stop.
    """

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _WatchdogObserver:
    """Thin adapter over a scheduled ``watchdog`` observer."""

    def __init__(self, observer: Any) -> None:
        self._observer = observer

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=2.0)


#: The watchdog event types that mean "durable bytes changed". The read-only
#: types (``opened``/``closed``/``closed_no_write``, and ``accessed`` where the
#: backend emits it) are deliberately ABSENT: inotify delivers them for pure
#: READS, and this engine READS every admitted file on each run — counting them
#: would let each run schedule the next one (a self-sustaining snapshot loop on
#: Linux; Windows never reports opens, which is why it went unseen there).
DURABLE_EVENT_TYPES = frozenset({"created", "modified", "deleted", "moved"})


def is_durable_event(event_type: str) -> bool:
    """Whether a watchdog ``event_type`` means the tree actually changed.

    Only a real mutation may schedule a backup (REQ-BE-6): a read-only event is
    ignored so a run's own reads never feed the next run.
    """
    return event_type in DURABLE_EVENT_TYPES


def default_observer_factory(
    data_root: Path, on_change: Callable[[str], None]
) -> DataRootObserver:
    """Watch *data_root* recursively, honoring the inventory exclusion table.

    ``watchdog`` is an optional dependency: when it is absent the factory
    degrades to a no-op observer (the reconciliation tick still covers changes),
    so the engine never fails to start over a missing watcher.
    """
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except Exception:  # noqa: BLE001 — an optional dependency, never fatal
        logger.info("watchdog unavailable; filesystem events disabled")
        return NoopObserver()

    root = Path(data_root)

    class _Handler(FileSystemEventHandler):
        """Translate one watchdog event into a change callback, per exclusion rule."""

        def on_any_event(self, event: Any) -> None:
            # Ignore read-only events BEFORE any path work: a backup run reads
            # the whole tree, so signalling on its own reads would schedule the
            # next run and loop forever.
            if not is_durable_event(str(getattr(event, "event_type", ""))):
                return
            raw = getattr(event, "dest_path", None) or getattr(event, "src_path", "")
            if not raw:
                return
            try:
                relative = Path(raw).resolve().relative_to(root).as_posix()
            except ValueError:
                return
            if match_exclusion(relative) is None:
                on_change(relative)

    observer = Observer()
    try:
        observer.schedule(_Handler(), str(root), recursive=True)
    except OSError as exc:
        logger.warning("could not watch %s: %s", root, exc)
        return NoopObserver()
    return _WatchdogObserver(observer)


class _DataRootChangeDetector:
    """A cheap fingerprint of the included file tree — the event-loss backstop.

    Every call hashes ``(relative path, size, mtime_ns)`` for the files the
    exclusion table admits and reports whether that digest moved since the
    previous call. The first call establishes the baseline and reports no
    change, so starting the engine never schedules a spurious run.
    """

    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)
        self._previous: str | None = None

    def __call__(self) -> bool:
        current = self._scan()
        changed = self._previous is not None and current != self._previous
        self._previous = current
        return changed

    def _scan(self) -> str:
        stamped: list[tuple[str, int, int]] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            relative_dir = os.path.relpath(dirpath, self._root)
            prefix = "" if relative_dir == os.curdir else f"{relative_dir}/"
            dirnames[:] = [
                name for name in dirnames
                if match_exclusion(f"{prefix}{name}") is None
            ]
            for name in filenames:
                relative = f"{prefix}{name}"
                if match_exclusion(relative) is not None:
                    continue
                try:
                    stat = os.stat(os.path.join(dirpath, name))
                except OSError:
                    continue
                stamped.append(
                    (relative.replace(os.sep, "/"), stat.st_size, stat.st_mtime_ns)
                )
        stamped.sort()
        return hashlib.sha256(repr(stamped).encode("utf-8")).hexdigest()


class _QueueWaiter:
    """Production waiter: blocks on the engine's notify queue."""

    def __init__(self) -> None:
        self._queue: queue.Queue[object] = queue.Queue()

    def notify(self) -> None:
        """Wake the worker. One unbounded put — never blocks the request path."""
        self._queue.put(object())

    def wait(self, timeout: float) -> bool:
        """Block up to *timeout*; ``True`` when a token arrived, ``False`` on timeout."""
        try:
            self._queue.get(timeout=timeout)
            self._queue.task_done()
            return True
        except queue.Empty:
            return False


# ---------------------------------------------------------------------------
# The process-wide hook
# ---------------------------------------------------------------------------

_registry_lock = threading.Lock()
_active_engine: "BackupEngine | None" = None


def set_active_engine(engine: "BackupEngine | None") -> None:
    """Bind (or clear) the engine a module-level :func:`notify_data_changed` reaches."""
    global _active_engine
    with _registry_lock:
        _active_engine = engine


def active_engine() -> "BackupEngine | None":
    """The engine currently serving module-level notifications, if any."""
    return _active_engine


def notify_data_changed(path: str | None = None) -> None:
    """Signal that author data changed. Non-blocking, thread-safe, no I/O.

    Safe to call from a request handler, an ASGI middleware or a filesystem
    watcher: it reads the active engine and delegates to
    :meth:`BackupEngine.notify`, which is a lock, a timestamp and a queue put.
    With no engine running it is a cheap no-op.
    """
    engine = _active_engine
    if engine is None:
        return
    engine.notify(path)


def is_write_quiesced() -> bool:
    """Whether mutating writes must be refused right now (REQ-RS-3)."""
    engine = _active_engine
    return bool(engine is not None and engine.is_quiesced)


def resolve_debounce_seconds(environ: Mapping[str, str] | None = None) -> float:
    """The debounce window from the environment, clamped into ``[5, 10]``.

    An absent, unparsable or out-of-range value falls back to the default or to
    the nearest bound, so the window can never collapse to zero (a runaway run
    per edit) nor grow past 10 s (SC-BE-6.1).
    """
    raw = str((environ if environ is not None else os.environ).get(DEBOUNCE_ENV_VAR, "")).strip()
    if not raw:
        return DEFAULT_DEBOUNCE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; using %ss", DEBOUNCE_ENV_VAR, raw, DEFAULT_DEBOUNCE_SECONDS)
        return DEFAULT_DEBOUNCE_SECONDS
    return min(max(value, MIN_DEBOUNCE_SECONDS), MAX_DEBOUNCE_SECONDS)


def _utc_stamp() -> str:
    """The marker's wall-clock stamp (observability only, never the schedule)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class BackupEngine:
    """Debounced, coalescing backup trigger with a single daemon worker.

    ``runner`` performs one run; it is called on the worker thread, never on the
    request path, and an exception it raises is isolated (the worker survives).
    """

    def __init__(
        self,
        runner: Runner,
        *,
        data_root: Path | None = None,
        debounce_seconds: float | None = None,
        reconcile_interval: float | None = DEFAULT_RECONCILE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        waiter: Any | None = None,
        observer_factory: Callable[[Path, Callable[[str], None]], DataRootObserver] | None = None,
        reconcile: Callable[[], bool] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._runner = runner
        self._data_root = None if data_root is None else Path(data_root)
        self._debounce = (
            resolve_debounce_seconds(environ)
            if debounce_seconds is None
            else min(max(float(debounce_seconds), MIN_DEBOUNCE_SECONDS), MAX_DEBOUNCE_SECONDS)
        )
        self._reconcile_interval = reconcile_interval
        self._clock = clock
        self._waiter = waiter if waiter is not None else _QueueWaiter()
        self._observer_factory = observer_factory or default_observer_factory
        self._reconcile = (
            reconcile
            if reconcile is not None
            else (_DataRootChangeDetector(self._data_root) if self._data_root else None)
        )
        self._on_error = on_error

        self._lock = threading.Lock()
        self._deadline: float | None = None
        self._next_reconcile: float | None = None
        self._changed: set[str] = set()
        self._quiesced = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._observer: DataRootObserver | None = None

        self._events = 0
        self._runs = 0
        self._last_run_at: float | None = None
        self._last_result: Any = None
        self._last_error: BaseException | None = None
        self._last_paths: tuple[str, ...] = ()

    # -- observable state --------------------------------------------------

    @property
    def debounce_seconds(self) -> float:
        """The clamped debounce window, in seconds."""
        return self._debounce

    @property
    def reconcile_interval(self) -> float | None:
        """Seconds between reconciliation ticks, or ``None`` when disabled."""
        return self._reconcile_interval

    @property
    def pending_deadline(self) -> float | None:
        """The scheduled run's deadline on the injected clock, or ``None``."""
        with self._lock:
            return self._deadline

    @property
    def events(self) -> int:
        """How many change signals were coalesced so far."""
        return self._events

    @property
    def runs(self) -> int:
        """How many runs started."""
        return self._runs

    @property
    def last_result(self) -> Any:
        """What the most recent successful run returned."""
        return self._last_result

    @property
    def last_error(self) -> BaseException | None:
        """The most recent run's exception, if it failed."""
        return self._last_error

    @property
    def last_paths(self) -> tuple[str, ...]:
        """The changed paths the most recent run covered."""
        return self._last_paths

    @property
    def is_quiesced(self) -> bool:
        """Whether writes are refused: the in-memory flag or the on-disk marker."""
        return self._quiesced.is_set() or self._marker_present()

    @property
    def worker_alive(self) -> bool:
        """Whether the worker thread is currently running."""
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    # -- the hook ----------------------------------------------------------

    def notify(self, path: str | None = None) -> None:
        """Move the deadline and wake the worker. A lock, a timestamp, a put.

        No I/O and no work: this is the only method a request path may reach.
        Signals are dropped while quiesced, so a restore's swap cannot schedule a
        run against a half-swapped root.
        """
        if self._quiesced.is_set():
            return
        now = self._clock()
        with self._lock:
            self._deadline = now + self._debounce
            self._events += 1
            if path:
                self._changed.add(path)
        self._waiter.notify()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the observer and the single worker thread (idempotent)."""
        if self.worker_alive:
            return
        self._stop.clear()
        now = self._clock()
        self._next_reconcile = (
            None if self._reconcile_interval is None
            else now + float(self._reconcile_interval)
        )
        self._load_marker()
        if not self._quiesced.is_set():
            self._start_observer()
        self._thread = threading.Thread(
            target=self._loop, name=THREAD_NAME, daemon=True
        )
        self._thread.start()
        set_active_engine(self)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the worker (and observer) and drop any pending deadline.

        A deadline still pending is DROPPED, not flushed: the next start's
        reconciliation pass catches whatever changed (SC-BE-6.3). The thread is
        a daemon, so even a run that outlives *timeout* cannot block exit.
        """
        self._stop.set()
        self._waiter.notify()
        self._stop_observer()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self._thread = None
        with self._lock:
            self._deadline = None
        if _active_engine is self:
            set_active_engine(None)

    # -- quiesce / resume --------------------------------------------------

    def quiesce(self) -> None:
        """Refuse mutating writes: raise the marker, stop watching, drop the deadline.

        The marker is written BEFORE any caller swaps the tree, so a crash
        mid-swap leaves the API read-only until ``resume`` resolves it
        (SC-RS-3.2) — never a silent torn state.
        """
        self._quiesced.set()
        with self._lock:
            self._deadline = None
        self._stop_observer()
        self._write_marker()

    def resume(self) -> None:
        """Clear the maintenance marker and watch again (SC-RS-3.2)."""
        self._quiesced.clear()
        self._clear_marker()
        if self.worker_alive:
            self._start_observer()

    # -- the worker --------------------------------------------------------

    def pump(self) -> bool:
        """One non-blocking loop iteration. ``True`` when a run started.

        Public so a caller can drive the loop deterministically with an injected
        clock — the worker calls it after every wait.
        """
        if self._stop.is_set():
            return False
        now = self._clock()
        if self._reconcile_interval is not None and self._next_reconcile is None:
            self._next_reconcile = now + float(self._reconcile_interval)
        with self._lock:
            due = self._deadline is not None and now >= self._deadline
            if due:
                self._deadline = None
        if due:
            self._run()
            return True
        if self._next_reconcile is not None and now >= self._next_reconcile:
            self._next_reconcile = now + float(self._reconcile_interval or 0.0)
            changed = True if self._reconcile is None else bool(self._reconcile())
            if changed:
                self.notify(RECONCILE_PATH)
        return False

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._waiter.wait(self._wait_timeout())
            if self._stop.is_set():
                break
            self.pump()

    def _wait_timeout(self) -> float:
        """Seconds until the next thing that must happen (deadline or tick)."""
        now = self._clock()
        waits: list[float] = []
        if self._next_reconcile is not None:
            waits.append(self._next_reconcile - now)
        with self._lock:
            if self._deadline is not None:
                waits.append(self._deadline - now)
        if not waits:
            return float(self._reconcile_interval or 0.0) or DEFAULT_RECONCILE_SECONDS
        return max(0.0, min(waits))

    def _run(self) -> None:
        """Run the runner on the worker thread; an exception never kills the worker."""
        self._runs += 1
        self._last_paths = tuple(sorted(self._changed))
        self._changed.clear()
        self._last_run_at = self._clock()
        try:
            self._last_result = self._runner()
        except Exception as exc:  # noqa: BLE001 — a failed run must not stop the engine
            self._last_error = exc
            logger.exception("backup run failed")
            if self._on_error is not None:
                self._on_error(exc)

    # -- observer ----------------------------------------------------------

    def _start_observer(self) -> None:
        if self._observer is not None or self._data_root is None:
            return
        try:
            observer = self._observer_factory(self._data_root, self.notify)
            observer.start()
        except Exception as exc:  # noqa: BLE001 — watching is best-effort
            logger.warning("filesystem observer could not start: %s", exc)
            self._observer = None
            return
        self._observer = observer

    def _stop_observer(self) -> None:
        observer = self._observer
        self._observer = None
        if observer is None:
            return
        try:
            observer.stop()
        except Exception as exc:  # noqa: BLE001 — never raise from shutdown
            logger.warning("filesystem observer could not stop: %s", exc)

    # -- maintenance marker ------------------------------------------------

    def _marker_path(self) -> Path | None:
        return None if self._data_root is None else self._data_root / QUIESCE_MARKER_NAME

    def _marker_present(self) -> bool:
        path = self._marker_path()
        return bool(path is not None and path.exists())

    def _load_marker(self) -> None:
        if self._marker_present():
            logger.warning(
                "maintenance marker present at %s; engine stays quiesced until resume()",
                self._marker_path(),
            )
            self._quiesced.set()

    def _write_marker(self) -> None:
        path = self._marker_path()
        if path is None:
            return
        payload = json.dumps(
            {"schema_version": MAINTENANCE_SCHEMA_VERSION, "quiesced_at": _utc_stamp()},
            sort_keys=True,
        )
        temp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
        try:
            temp.write_text(payload, encoding="utf-8")
            os.replace(temp, path)
        finally:
            try:
                temp.unlink()
            except OSError:
                pass

    def _clear_marker(self) -> None:
        path = self._marker_path()
        if path is None:
            return
        try:
            path.unlink()
        except FileNotFoundError:
            pass
