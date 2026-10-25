# -*- coding: utf-8 -*-
"""Unit tests for the bounded real-run readiness probe (S5)."""

from pathlib import Path
import sys

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from hermes_run_probe import (  # noqa: E402
    ACCEPTANCE_PROMPT,
    ACCEPTANCE_SESSION_ID,
    HermesRunProbe,
)


class _FakeTransport:
    """Scripted gateway double: records calls and returns scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[tuple[str, str, object, dict]] = []

    def __call__(self, method, url, payload, headers):
        self.calls.append((method, url, payload, dict(headers)))
        if not self._responses:
            raise AssertionError("unexpected extra gateway call")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeClock:
    def __init__(self, step: float = 0.0):
        self.now = 0.0
        self.step = step
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += self.step


def _probe(transport, clock=None, *, timeout_seconds: float = 25.0, poll_seconds: float = 0.5):
    clock = clock or _FakeClock()
    return HermesRunProbe(
        "http://127.0.0.1:8642/v1",
        api_key="gateway-fixture",
        transport=transport,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
        clock=clock.monotonic,
        sleep=clock.sleep,
    )


def test_completed_run_with_output_is_accepted():
    transport = _FakeTransport([
        (202, {"run_id": "run_1", "status": "queued"}),
        (200, {"run_id": "run_1", "status": "running"}),
        (200, {"run_id": "run_1", "status": "completed", "output": "ok"}),
    ])

    assert _probe(transport).probe() is True
    method, url, payload, headers = transport.calls[0]
    assert method == "POST"
    assert url == "http://127.0.0.1:8642/v1/runs"
    assert payload == {"input": ACCEPTANCE_PROMPT, "session_id": ACCEPTANCE_SESSION_ID}
    assert headers["Authorization"] == "Bearer gateway-fixture"
    assert transport.calls[1][0] == "GET"
    assert transport.calls[1][1] == "http://127.0.0.1:8642/v1/runs/run_1"


@pytest.mark.parametrize(
    ("terminal", "body"),
    [
        ("failed", {"status": "failed", "error": "Unknown provider 'compatible'"}),
        ("cancelled", {"status": "cancelled"}),
        ("completed-empty", {"status": "completed", "output": "   "}),
        ("completed-missing", {"status": "completed"}),
    ],
)
def test_non_success_terminal_states_are_rejected(terminal, body):
    transport = _FakeTransport([(202, {"run_id": "run_1"}), (200, {"run_id": "run_1", **body})])

    assert _probe(transport).probe() is False


@pytest.mark.parametrize("status", [400, 401, 500])
def test_run_submission_rejection_is_rejected(status):
    transport = _FakeTransport([(status, {"error": "boom"})])

    assert _probe(transport).probe() is False


def test_missing_or_blank_run_id_is_rejected():
    for body in ({}, {"run_id": ""}, {"run_id": 7}, None):
        transport = _FakeTransport([(202, body)])
        assert _probe(transport).probe() is False


def test_status_read_failure_is_rejected():
    transport = _FakeTransport([
        (202, {"run_id": "run_1"}),
        (500, {"status": "failed"}),
    ])

    assert _probe(transport).probe() is False


def test_never_terminal_run_times_out_without_unbounded_polling():
    clock = _FakeClock(step=1.0)
    transport = _FakeTransport(
        [(202, {"run_id": "run_1"})]
        + [(200, {"run_id": "run_1", "status": "running"}) for _ in range(60)]
    )

    assert _probe(transport, clock, timeout_seconds=3.0, poll_seconds=0.5).probe() is False
    # POST + a bounded number of status reads; the scripted transport would
    # raise on a fourth status read if the probe ignored the deadline.
    assert len(transport.calls) <= 4


def test_transport_failure_is_rejected():
    transport = _FakeTransport([OSError("connection refused")])

    assert _probe(transport).probe() is False


def test_a_keyless_gateway_sends_no_authorization_header():
    transport = _FakeTransport([(202, {"run_id": "run_1"}), (200, {"run_id": "run_1", "status": "completed", "output": "ok"})])
    probe = HermesRunProbe("http://127.0.0.1:8642/v1", transport=transport)

    assert probe.probe() is True
    assert "Authorization" not in transport.calls[0][3]
