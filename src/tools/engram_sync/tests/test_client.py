"""RED/GREEN: client — missing binary, exit, timeout, bad JSON, authz (2.1-2.3)
plus flat-CLI argv and flat search/save output parsing."""

import subprocess
from types import SimpleNamespace

import pytest

from engram_sync.engram_client import (EngramBinaryMissing, EngramClient,
                                        EngramExitError, EngramMalformedOutput,
                                        EngramSearchTruncated, EngramTimeout,
                                        EngramUnauthorized,
                                        _parse_flat)
from engram_sync.models import Action, AuthorizedOperation


def _op(**kw):
    opts = {"domain": "ideas", "item_key": "k", "source_revision": "rev-a",
            "action": Action.KEEP_ENGRAM}
    opts.update(kw)
    return AuthorizedOperation(**opts)


def _client(monkeypatch, exc=None, code=0, out="{}", **kw):
    calls, sleeps = [], []

    def run(argv, **rest):
        calls.append(argv)
        if exc:
            raise exc
        return SimpleNamespace(returncode=code, stdout=out)

    monkeypatch.setattr("engram_sync.engram_client.subprocess.run", run)
    return EngramClient(sleep=sleeps.append, **kw), calls, sleeps


def test_read_search_parses_rows(monkeypatch):
    client, calls, _ = _client(monkeypatch, out='{"result": [{"id": 7, "title": "t"}]}')
    assert client.search("vibrantes", "drift") == [{"id": 7, "title": "t"}]
    assert calls[0] == ["engram", "search", "drift", "--project", "vibrantes",
                         "--limit", "10"]  # flat argv, no shell


@pytest.mark.parametrize("payload", [
    "[]",
    "{}",
    '{"total": 0}',
    '{"result": "not a list"}',
    '{"result": [1]}',
    '{"result": [], "total": "0"}',
])
def test_json_search_rejects_structurally_invalid_shapes(monkeypatch, payload):
    client, _, _ = _client(monkeypatch, out=payload)
    with pytest.raises(EngramMalformedOutput):
        client.search("vibrantes", "ideas")


@pytest.mark.parametrize("payload", ['{"result": []}', '{"result": [], "total": 0}'])
def test_json_search_valid_empty_result_remains_empty(monkeypatch, payload):
    client, _, _ = _client(monkeypatch, out=payload)
    assert client.search("vibrantes", "ideas") == []


def test_search_rejects_unreported_rows_at_explicit_limit(monkeypatch):
    payload = {"result": [{"id": i} for i in range(1_000)]}
    client, calls, _ = _client(monkeypatch, out=__import__("json").dumps(payload))
    with pytest.raises(EngramSearchTruncated):
        client.search("vibrantes", "ideas", limit=1_000)
    assert calls[0][-1] == "1000"


@pytest.mark.parametrize("exc,code,out,error,attempts,sleeps,exit_code", [
    (FileNotFoundError(), 0, "{}", EngramBinaryMissing, 1, [], None),
    (None, 0, "not json", EngramMalformedOutput, 1, [], None),
    (subprocess.TimeoutExpired(cmd="engram", timeout=15), 0, "{}", EngramTimeout, 3, [1.0, 4.0], None),
    (None, 2, "{}", EngramExitError, 3, [1.0, 4.0], 2),
])
def test_client_error_handling(monkeypatch, exc, code, out, error, attempts, sleeps, exit_code):
    client, calls, sleep_log = _client(monkeypatch, exc=exc, code=code, out=out)
    with pytest.raises(error) as err:
        client.search("w", "q")
    assert len(calls) == attempts and sleep_log == sleeps
    assert getattr(err.value, "result_code", None) == exit_code


@pytest.mark.parametrize("mode,op,project,topic", [
    ("read", _op(), "vibrantes", "nec/ideas/k"),  # read-only mode refuses writes
    ("read-write", _op(action="auto-merge"), "vibrantes", "nec/ideas/k"),
    ("read-write", _op(), "bad project!", "nec/ideas/k"),
    ("read-write", _op(), "vibrantes", "../escape"),
])
def test_write_without_valid_auth_never_runs(monkeypatch, mode, op, project, topic):
    client, calls, _ = _client(monkeypatch, mode=mode)
    with pytest.raises(EngramUnauthorized):
        client.save(op, project=project, topic=topic, title="t", content="c")
    assert calls == []


def test_authorized_write_fixed_argv_no_secret_leak(monkeypatch):
    secret = "super-secret-token-xyz"
    client, calls, _ = _client(monkeypatch, exc=FileNotFoundError(), mode="read-write")
    with pytest.raises(EngramBinaryMissing) as err:
        client.save(_op(), project="vibrantes", topic="nec/ideas/k",
                    title="Idea", content=secret)
    assert calls[0] == ["engram", "save", "Idea", secret, "--project", "vibrantes",
                        "--topic", "nec/ideas/k"]
    assert "--topic-key" not in calls[0] and "--capture-prompt" not in calls[0]
    assert secret not in str(err.value)


# --- Flat CLI compatibility (engram v1.20.0: `engram search`, `engram save`) ---

FLAT_TWO = """Found 2 memories:

[1] #607 (architecture) — sdd/wiki-backend/verify-report
    ## Verification Report

**Change**: wiki-backend
    2026-07-01 18:28:27 | project: demiurgos | scope: project

[2] #760 (bugfix) — Verification Report — PR #3
    **What**: fixed a bug
**Why**: because
    2026-07-12 12:04:30 | project: demiurgos | scope: project
"""


def test_flat_search_argv_and_parsed_rows(monkeypatch):
    client, calls, _ = _client(monkeypatch, out=FLAT_TWO)
    rows = client.search("vibrantes", "drift")
    assert calls[0] == ["engram", "search", "drift", "--project", "vibrantes",
                        "--limit", "10"]
    assert rows == [
        {"id": 607, "title": "sdd/wiki-backend/verify-report", "type": "architecture",
         "content": "## Verification Report\n\n**Change**: wiki-backend"},
        {"id": 760, "title": "Verification Report — PR #3", "type": "bugfix",
         "content": "**What**: fixed a bug\n**Why**: because"},
    ]


def test_flat_search_empty_result_returns_rows(monkeypatch):
    client, _, _ = _client(monkeypatch, out='No memories found for: "ideas"')
    assert client.search("vibrantes", "ideas") == []
    client, _, _ = _client(monkeypatch, out="Found 0 memories:\n")
    assert client.search("vibrantes", "ideas") == []


def test_flat_search_unrecognized_output_raises_malformed(monkeypatch):
    client, _, _ = _client(monkeypatch, out="totally unrecognized output")
    with pytest.raises(EngramMalformedOutput):
        client.search("w", "q")


def test_parse_flat_rejects_non_flat_output():
    assert _parse_flat("not the flat format") is None
    assert _parse_flat("") is None


def test_flat_save_argv_and_text_output(monkeypatch):
    client, calls, _ = _client(monkeypatch, out="Saved observation #123",
                               mode="read-write")
    result = client.save(_op(), project="vibrantes", topic="nec/ideas/k",
                         title="Idea", content="Body")
    assert calls[0] == ["engram", "save", "Idea", "Body", "--project", "vibrantes",
                        "--topic", "nec/ideas/k"]
    assert result == {"id": "123"}


def test_flat_save_json_output_and_unknown_text(monkeypatch):
    client, calls, _ = _client(monkeypatch, out='{"id": 9, "ok": true}', mode="read-write")
    assert client.save(_op(), project="vibrantes", topic="nec/ideas/k",
                       title="Idea", content="Body") == {"id": 9, "ok": True}
    assert calls[0] == ["engram", "save", "Idea", "Body", "--project", "vibrantes",
                        "--topic", "nec/ideas/k"]
    client, _, _ = _client(monkeypatch, out="done", mode="read-write")
    assert client.save(_op(), project="vibrantes", topic="nec/ideas/k",
                       title="Idea", content="Body") == {}
