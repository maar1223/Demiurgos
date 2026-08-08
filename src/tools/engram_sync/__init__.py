"""engram_sync — reconciliation core; client/journal are internal plumbing
wrapped in plain language by Phase-4 reports."""

from .adapter import AdapterRegistry, DomainAdapter
from .canonicalize import canonical_json, fingerprint
from .compare import classify
from .engram_client import EngramClient
from .journal import JournalEntry, RunJournal, operation_id
from .models import (Action, ApplyResult, AuthorizedOperation, Classification,
                     NormalizedItem, Preview, SourceRef, SourceState)
from .daemon import Daemon, Lifecycle, Readiness
from .poller import (DEFAULT_INTERVAL_SECONDS, MAX_INTERVAL_SECONDS,
                     MIN_INTERVAL_SECONDS, Poller, bounded_interval)
from .watcher import Signal, SignalDeduplicator, Watcher
from .integration import IntegrationResult, apply_confirmation, scan_and_report

__all__ = ["Action", "AdapterRegistry", "ApplyResult", "AuthorizedOperation",
           "Classification", "DomainAdapter", "EngramClient", "JournalEntry",
           "NormalizedItem", "Preview", "RunJournal", "SourceRef", "SourceState",
            "canonical_json", "classify", "fingerprint", "operation_id",
            "Daemon", "Lifecycle", "Readiness", "Poller", "Watcher", "Signal",
             "SignalDeduplicator", "IntegrationResult", "apply_confirmation",
             "scan_and_report", "bounded_interval", "DEFAULT_INTERVAL_SECONDS",
            "MIN_INTERVAL_SECONDS", "MAX_INTERVAL_SECONDS"]
