"""World importer — in-process cooperative-cancellation registry.

A tiny, dependency-free module shared by the import router and the import
service so the ``cancel`` endpoints can raise an in-process cooperative cancel
signal that a long-running synchronous ``analyze`` observes between Hermes
funnel chunks. Keeping it in its own module avoids a circular import: the
router imports the service at module scope (``from import_service import
ImportService``), so importing ``_request_cancel`` from the router back into
the service would deadlock on a partially-initialized module. This module has
no dependencies, so both can import it safely.

The signal is deliberately in-process only: ``analyze`` is synchronous within
the server process, so a ``threading.Event`` per ``job_id`` is enough. Each
``analyze`` clears the signal on entry (``_clear_cancel``) so a fresh run never
starts cancelled; the cancel endpoints set it (``_request_cancel``); the funnel
polls it (``_is_cancel_requested``) between chunks to stop NEW Hermes work.
"""

from __future__ import annotations

import threading

_CANCEL_LOCK = threading.Lock()
_CANCEL_EVENTS: dict[str, threading.Event] = {}


def _request_cancel(job_id: str) -> None:
    """Raise the cooperative-cancel signal for ``job_id`` (idempotent)."""
    with _CANCEL_LOCK:
        _CANCEL_EVENTS.setdefault(job_id, threading.Event()).set()


def _is_cancel_requested(job_id: str) -> bool:
    """True when a cooperative cancel has been requested for ``job_id``."""
    with _CANCEL_LOCK:
        event = _CANCEL_EVENTS.get(job_id)
    return event is not None and event.is_set()


def _clear_cancel(job_id: str) -> None:
    """Clear any pending cancel signal for ``job_id`` (start of each analyze)."""
    with _CANCEL_LOCK:
        _CANCEL_EVENTS.pop(job_id, None)
