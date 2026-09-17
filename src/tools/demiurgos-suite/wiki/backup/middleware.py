# -*- coding: utf-8 -*-
"""ASGI middleware for the backup engine: write signal and the quiesce gate (WU-11d).

Two responsibilities, both at the edge of the app so no route needs bespoke code:

* **Signal (REQ-BE-6, SC-BE-6.1).** After a request completes, call
  :func:`backup.engine.notify_data_changed` — but ONLY when every one of these
  holds: the method mutates (``POST``/``PUT``/``PATCH``/``DELETE``), the
  response is a success (``status < 300``), the path is under ``/api/``, and the
  path is neither a backup route (no self-trigger) nor a system route. A failed
  write and a read are both silent, so a 4xx never schedules a run.

* **Quiesce gate (REQ-RS-3, SC-RS-3.2).** While a restore owns the data root,
  a mutating ``/api/*`` request is rejected with ``503`` and ``Retry-After``
  BEFORE it reaches a handler, so nothing writes into a half-swapped tree.

This is a raw ASGI middleware, not ``BaseHTTPMiddleware``: it never buffers a
response body and never spawns a task group, so it cannot break streaming
responses or background tasks. The status is observed by wrapping ``send``.

The notifier and the quiesce probe are injectable, so the behaviour is asserted
without a running engine.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from backup.engine import (
    RETRY_AFTER_SECONDS,
    is_write_quiesced,
    notify_data_changed,
)

#: The methods that can change author data.
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: Only API traffic signals a backup run; static and authless paths do not.
API_PREFIX = "/api/"
#: Backup routes never signal (a run must not trigger a run); system routes are infra.
EXCLUDED_PATH_PREFIXES = ("/api/backup",)
EXCLUDED_PATHS = ("/api/system",)


def is_signalled(path: str) -> bool:
    """Whether a path may signal a run: under ``/api/`` and not excluded."""
    if not path.startswith(API_PREFIX):
        return False
    if path.startswith(EXCLUDED_PATH_PREFIXES):
        return False
    for excluded in EXCLUDED_PATHS:
        if path == excluded or path.startswith(f"{excluded}/"):
            return False
    return True


async def _send_quiesced(send: Callable[[dict], Any]) -> None:
    """Answer a blocked write with ``503`` and ``Retry-After`` (REQ-RS-3)."""
    body = json.dumps({"detail": "maintenance in progress"}).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": 503,
        "headers": [
            (b"content-type", b"application/json"),
            (b"retry-after", str(RETRY_AFTER_SECONDS).encode("ascii")),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class DataChangeNotifierMiddleware:
    """Signal the backup engine on a successful API write; refuse writes while quiesced."""

    def __init__(
        self,
        app: Any,
        *,
        notifier: Callable[[str | None], None] | None = None,
        quiesce_check: Callable[[], bool] | None = None,
    ) -> None:
        self.app = app
        self._notify = notifier or notify_data_changed
        self._quiesced = quiesce_check or is_write_quiesced

    async def __call__(self, scope: dict, receive: Any, send: Callable[[dict], Any]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        mutating = method in MUTATING_METHODS
        signalled = mutating and is_signalled(path)

        if signalled and self._quiesced():
            await _send_quiesced(send)
            return

        status: int | None = None

        async def send_wrapper(message: dict) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = message.get("status")
            await send(message)

        await self.app(scope, receive, send_wrapper)

        # A 3xx/4xx/5xx write changed nothing durable, so it never schedules a run.
        if signalled and status is not None and status < 300:
            self._notify(path)
