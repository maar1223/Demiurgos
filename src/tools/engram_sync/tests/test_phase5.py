"""Phase 5 trigger and daemon behavior: debounce, cadence, dedupe, lifecycle."""

from engram_sync.daemon import Daemon, Lifecycle
from engram_sync.poller import (DEFAULT_INTERVAL_SECONDS, MAX_INTERVAL_SECONDS,
                                 MIN_INTERVAL_SECONDS, Poller, bounded_interval)
from engram_sync.watcher import Signal, SignalDeduplicator, Watcher


def _signal(source="file", fingerprint="fp-1", revision="", operation_id=""):
    return Signal(source=source, domain="ideas", item_key="idea-a",
                  fingerprint=fingerprint, revision=revision,
                  operation_id=operation_id)


def test_repeated_file_signals_are_debounced_and_deliver_once():
    received = []
    watcher = Watcher(received.append, debounce_seconds=0.5)
    watcher.start()
    assert watcher.submit(_signal()) is True
    assert watcher.submit(_signal()) is False
    assert watcher.flush() == 1
    assert received == [_signal()]
    watcher.stop()


def test_changed_fingerprint_replaces_pending_signal():
    received = []
    watcher = Watcher(received.append, debounce_seconds=0.5)
    watcher.start()
    watcher.submit(_signal(fingerprint="old"))
    watcher.submit(_signal(fingerprint="new"))
    watcher.flush()
    assert received == [_signal(fingerprint="new")]
    watcher.stop()


def test_deduplication_uses_file_fingerprint_revision_and_operation_id():
    dedupe = SignalDeduplicator()
    assert dedupe.accept(_signal(fingerprint="file-1")) is True
    assert dedupe.accept(_signal(source="poll", fingerprint="file-1")) is False
    assert dedupe.accept(_signal(source="engram", fingerprint="file-2",
                                 revision="rev-1")) is True
    assert dedupe.accept(_signal(source="poll", fingerprint="other",
                                 revision="rev-1")) is False
    assert dedupe.accept(_signal(source="file", fingerprint="next",
                                 operation_id="op-1")) is True
    assert dedupe.accept(_signal(source="worker", fingerprint="worker",
                                 operation_id="op-1")) is False
    assert dedupe.suppressed == 3


def test_poller_cadence_is_bounded_and_errors_back_off():
    assert bounded_interval(1) == MIN_INTERVAL_SECONDS
    assert bounded_interval(DEFAULT_INTERVAL_SECONDS) == DEFAULT_INTERVAL_SECONDS
    assert bounded_interval(99999) == MAX_INTERVAL_SECONDS
    poller = Poller(lambda: (_ for _ in ()).throw(RuntimeError("offline")),
                    interval_seconds=MIN_INTERVAL_SECONDS)
    assert poller.run_once() == []
    assert poller.next_interval == 60.0
    assert poller.run_once() == []
    assert poller.next_interval == 120.0
    poller.stop()


def test_poller_emits_unique_engram_revision_only():
    received = []
    poller = Poller(lambda: [_signal(source="poll", fingerprint="", revision="r1")],
                    received.append)
    assert len(poller.run_once()) == 1
    assert len(poller.run_once()) == 1
    assert received == [_signal(source="poll", fingerprint="", revision="r1")]
    assert poller.poll_count == 2


class FakeComponent:
    def __init__(self):
        self.running = False
        self.starts = 0
        self.stops = 0
        self.callback = None
        self.deduplicator = None

    def set_callback(self, callback):
        self.callback = callback

    def set_deduplicator(self, deduplicator):
        self.deduplicator = deduplicator

    def start(self):
        self.starts += 1
        self.running = True

    def stop(self):
        self.stops += 1
        self.running = False


def test_daemon_lifecycle_health_restart_and_readiness():
    watcher, poller = FakeComponent(), FakeComponent()
    received = []
    daemon = Daemon(watcher, poller, on_signal=received.append,
                    readiness_checks={"recovery": True, "conflicts": True})
    assert daemon.state is Lifecycle.STOPPED and not daemon.ready()
    assert daemon.start() is True
    assert daemon.state is Lifecycle.RUNNING and daemon.ready()
    health = daemon.health()
    assert health["watcher_running"] and health["poller_running"]
    assert health["readiness"]["no_data_loss"] is True
    assert daemon.restart() is True
    assert daemon.health()["restart_count"] == 1
    assert watcher.starts == 2 and poller.starts == 2
    assert daemon.stop() is True
    assert daemon.state is Lifecycle.STOPPED and not daemon.health()["ready"]


def test_daemon_readiness_fails_closed_when_a_gate_is_not_proven():
    watcher, poller = FakeComponent(), FakeComponent()
    daemon = Daemon(watcher, poller,
                    readiness_checks={"recovery": True, "conflicts": True,
                                      "authorization": False})
    assert daemon.start() is False
    assert daemon.state is Lifecycle.STOPPED
    assert watcher.starts == 0 and poller.starts == 0
    readiness = daemon.readiness()
    assert readiness.authorization is False
    assert readiness.ready is False and daemon.health()["ready"] is False
    assert daemon.health()["last_error"] == "readiness gates are unproven"


def test_daemon_restart_stays_stopped_when_readiness_is_lost():
    watcher, poller = FakeComponent(), FakeComponent()
    recovery = [True]
    gates = {"recovery": lambda: recovery[0], "conflicts": True, "authorization": True}
    daemon = Daemon(watcher, poller, readiness_checks=gates)
    assert daemon.start() is True
    recovery[0] = False
    assert daemon.restart() is False
    assert daemon.state is Lifecycle.STOPPED
    assert not watcher.running and not poller.running
