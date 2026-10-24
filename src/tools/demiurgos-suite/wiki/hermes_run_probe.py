# -*- coding: utf-8 -*-
"""Bounded real-run readiness probe for the Hermes gateway.

Gateway liveness (``gateway_state.json`` plus a live PID) only proves the
process is up. A provider Hermes cannot resolve still accepts
``POST /v1/runs`` with 202 and fails asynchronously, so liveness can report
"active" while every assistant answer fails closed. This probe performs one
small real run through the documented runs API and reports whether the
configured provider actually completed it.

Every failure path fails closed: an unreachable gateway, a rejected
submission, a non-terminal run past the deadline, and a failed/cancelled/empty
completion are all "not accepted". The probe owns no process lifecycle: it
never starts, stops or reloads Hermes.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

import httpx

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_POLL_SECONDS = 0.5
#: Tiny prompt: the point is a completed provider turn, not its content.
ACCEPTANCE_PROMPT = "Reply with the single word: ok"
#: Stable conversation scope so repeated saves do not create a Hermes session
#: per probe.
ACCEPTANCE_SESSION_ID = "demiurgos-acceptance"
_TERMINAL_FAILURES = frozenset({"failed", "cancelled"})

Transport = Callable[[str, str, "dict[str, Any] | None", "dict[str, str]"], "tuple[int, Any]"]


def _http_transport(
    method: str,
    url: str,
    payload: "dict[str, Any] | None",
    headers: "dict[str, str]",
) -> "tuple[int, Any]":
    """Default synchronous transport: one isolated client per call."""
    with httpx.Client(timeout=httpx.Timeout(8.0, connect=4.0)) as client:
        response = client.request(method, url, json=payload, headers=headers)
        try:
            body = response.json()
        except ValueError:
            body = None
        return response.status_code, body


class HermesRunProbe:
    """Run one bounded acceptance turn and report whether it completed."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        transport: Transport | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = str(base_url or "").rstrip("/")
        self._api_key = str(api_key or "")
        self._transport = transport or _http_transport
        self._timeout_seconds = float(timeout_seconds)
        self._poll_seconds = float(poll_seconds)
        self._clock = clock
        self._sleep = sleep

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    def _call(self, method: str, url: str, payload: "dict[str, Any] | None") -> "tuple[int, Any]":
        return self._transport(method, url, payload, self._headers())

    def probe(self) -> bool:
        """True only for one completed run with a non-empty output."""
        try:
            status, body = self._call(
                "POST",
                f"{self._base_url}/runs",
                {"input": ACCEPTANCE_PROMPT, "session_id": ACCEPTANCE_SESSION_ID},
            )
            if status not in {200, 202} or not isinstance(body, Mapping):
                return False
            run_id = body.get("run_id")
            if not isinstance(run_id, str) or not run_id.strip():
                return False
            deadline = self._clock() + self._timeout_seconds
            while self._clock() < deadline:
                self._sleep(self._poll_seconds)
                status, state = self._call("GET", f"{self._base_url}/runs/{run_id}", None)
                if status != 200 or not isinstance(state, Mapping):
                    return False
                value = state.get("status")
                if value == "completed":
                    return bool(str(state.get("output") or "").strip())
                if value in _TERMINAL_FAILURES:
                    return False
            return False
        except Exception:
            return False
