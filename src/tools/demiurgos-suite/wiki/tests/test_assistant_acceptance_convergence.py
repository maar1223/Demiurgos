# -*- coding: utf-8 -*-
"""Startup convergence of a stale assistant acceptance (S5).

Regression: a revision saved while the runtime could not complete a run stayed
``saved-not-active`` forever, so after a restart the panel reported a working
assistant as inactive. Convergence is UP ONLY: it runs once at startup, only
when the recorded evidence for the CURRENT revision is not accepted, and it
never downgrades an accepted revision nor re-probes a healthy one.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _path in (str(_WIKI), str(_SUITE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import api_server  # noqa: E402
import assistant_settings  # noqa: E402

_REVISION = 7


class _Gateway:
    def __init__(self, running: bool) -> None:
        self._running = running
        self.calls = 0

    def is_running(self) -> bool:
        self.calls += 1
        return self._running


def _prepare(tmp_path: Path, monkeypatch, evidence, *, revision=_REVISION):
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(api_server, "_LOCAL_STATE", None)
    monkeypatch.setattr(
        assistant_settings, "current_config_revision", lambda: revision
    )
    data = tmp_path / "data"
    data.mkdir()
    payload = {"schema_version": 1, "revision": 3}
    if evidence is not None:
        payload["assistant_acceptance"] = evidence
    (data / "local-state.json").write_text(json.dumps(payload), encoding="utf-8")


def _state(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "data" / "local-state.json").read_text(encoding="utf-8"))


def _evidence(runtime: str = "saved-not-active", revision: int = _REVISION) -> dict:
    return {
        "text": "passed",
        "vision": "passed",
        "runtime": runtime,
        "revision": revision,
    }


def _wire(monkeypatch, *, running=True, probe=True):
    gateway = _Gateway(running)
    probes: list[bool] = []

    def _probe() -> bool:
        probes.append(True)
        return probe

    monkeypatch.setattr(api_server, "_assistant_gateway_probe", lambda: gateway)
    monkeypatch.setattr(api_server, "_assistant_runtime_run_probe", _probe)
    return gateway, probes


def test_a_stale_non_accepted_acceptance_converges_to_active(
    tmp_path: Path, monkeypatch
):
    _prepare(tmp_path, monkeypatch, _evidence())
    gateway, probes = _wire(monkeypatch, running=True, probe=True)

    assert api_server._converge_assistant_acceptance() is True

    evidence = _state(tmp_path)["assistant_acceptance"]
    assert evidence == {
        "text": "passed",
        "vision": "passed",
        "runtime": "accepted",
        "revision": _REVISION,
    }
    assert gateway.calls == 1
    assert probes == [True]


def test_a_failed_convergence_probe_leaves_the_evidence_untouched(
    tmp_path: Path, monkeypatch
):
    _prepare(tmp_path, monkeypatch, _evidence())
    before = _state(tmp_path)
    _wire(monkeypatch, running=True, probe=False)

    assert api_server._converge_assistant_acceptance() is False
    assert _state(tmp_path) == before


def test_an_already_accepted_revision_is_never_reprobed(tmp_path: Path, monkeypatch):
    _prepare(tmp_path, monkeypatch, _evidence("accepted"))
    _gateway, probes = _wire(monkeypatch, running=True, probe=True)

    assert api_server._converge_assistant_acceptance() is False
    assert probes == []


def test_evidence_for_another_revision_never_converges(tmp_path: Path, monkeypatch):
    _prepare(tmp_path, monkeypatch, _evidence(revision=_REVISION - 1))
    _gateway, probes = _wire(monkeypatch, running=True, probe=True)

    assert api_server._converge_assistant_acceptance() is False
    assert probes == []


def test_no_recorded_acceptance_never_converges(tmp_path: Path, monkeypatch):
    _prepare(tmp_path, monkeypatch, None)
    _gateway, probes = _wire(monkeypatch, running=True, probe=True)

    assert api_server._converge_assistant_acceptance() is False
    assert probes == []


def test_a_down_gateway_never_runs_the_probe(tmp_path: Path, monkeypatch):
    _prepare(tmp_path, monkeypatch, _evidence())
    _gateway, probes = _wire(monkeypatch, running=False, probe=True)

    assert api_server._converge_assistant_acceptance() is False
    assert probes == []


def test_missing_probe_evidence_for_the_current_revision_is_not_accepted(
    tmp_path: Path, monkeypatch
):
    """Only a saved three-proof acceptance can converge: text/vision must hold."""
    _prepare(
        tmp_path,
        monkeypatch,
        {"text": "failed", "vision": "passed", "runtime": "saved-not-active",
         "revision": _REVISION},
    )
    _gateway, probes = _wire(monkeypatch, running=True, probe=True)

    assert api_server._converge_assistant_acceptance() is False
    assert probes == []
