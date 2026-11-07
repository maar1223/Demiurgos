"""Independent regression probes for durable session binding (S1-S6).

Complements ``test_durable_session_binding.py``: adds local-dev prefix
coverage, pre-fix adoption without data/schema rewrite, adversarial foreign
bindings, default-identity behaviour for direct store users, and the S4
unauthenticated guard. Derived from the independent verifier run.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))
_SUITE = _WIKI.parent
if str(_SUITE) not in sys.path:
    sys.path.insert(0, str(_SUITE))

import api_server  # noqa: E402
from co_creation_session_store import CoCreationSessionStore  # noqa: E402
from guided_session_store import GuidedSessionStore  # noqa: E402

_INSTALL = "install:install_0123456789abcdef01234567"
_EPHEMERAL = ("credentials-session-", "local-dev-session-")


def _normalize(value: str) -> str:
    return _INSTALL if value.startswith(_EPHEMERAL) else value


@pytest.mark.parametrize("first,second", [
    ("credentials-session-a", "credentials-session-b"),
    ("local-dev-session-a", "local-dev-session-b"),
])
def test_guided_relogin_recovery_s1(tmp_path, first, second):
    store = GuidedSessionStore(tmp_path / "g.sqlite3", binding_normalizer=_normalize)
    store.create("g", "W", first)
    assert store.recover("g", second) is not None


def test_co_creation_relogin_recovery_s1(tmp_path):
    store = CoCreationSessionStore(tmp_path / "c.sqlite3", binding_normalizer=_normalize)
    store.create("c", "principal", "credentials-session-a", world="W", author_input="hola")
    assert store.recover("c", "credentials-session-b") is not None


def test_guided_legacy_adoption_without_rewrite_s2(tmp_path):
    path = tmp_path / "g.sqlite3"
    legacy = GuidedSessionStore(path)
    legacy.create("g", "W", "credentials-session-old")
    before = sqlite3.connect(path).execute(
        "select owner_binding, updated_at from guided_sessions where session_id='g'"
    ).fetchone()
    schema_before = [r[1] for r in sqlite3.connect(path).execute(
        "PRAGMA table_info(guided_sessions)")]
    upgraded = GuidedSessionStore(path, binding_normalizer=_normalize)
    assert upgraded.recover("g", "credentials-session-new") is not None
    after = sqlite3.connect(path).execute(
        "select owner_binding, updated_at from guided_sessions where session_id='g'"
    ).fetchone()
    schema_after = [r[1] for r in sqlite3.connect(path).execute(
        "PRAGMA table_info(guided_sessions)")]
    assert before == after
    assert schema_before == schema_after


def test_co_legacy_adoption_s2(tmp_path):
    path = tmp_path / "c.sqlite3"
    legacy = CoCreationSessionStore(path)
    legacy.create("c", "principal", "credentials-session-old", world="W", author_input="x")
    upgraded = CoCreationSessionStore(path, binding_normalizer=_normalize)
    assert upgraded.recover("c", "credentials-session-new") is not None


@pytest.mark.parametrize("foreign", [
    "install:other",
    "someone-else",
    "xcredentials-session-foo",
    "",
    "local-dev-session",
    "credentials-session",
])
def test_foreign_bindings_rejected_s3(tmp_path, foreign):
    store = GuidedSessionStore(tmp_path / "g.sqlite3", binding_normalizer=_normalize)
    store.create("g", "W", "credentials-session-a")
    assert store.recover("g", foreign) is None


def test_co_foreign_binding_rejected_s3(tmp_path):
    store = CoCreationSessionStore(tmp_path / "c.sqlite3", binding_normalizer=_normalize)
    store.create("c", "principal", "credentials-session-a", world="W", author_input="x")
    assert store.recover("c", "install:other") is None


def test_default_normalizer_is_identity_s5(tmp_path):
    guided = GuidedSessionStore(tmp_path / "g.sqlite3")
    guided.create("g", "W", "alpha")
    assert guided.recover("g", "alpha") is not None
    assert guided.recover("g", "beta") is None
    co = CoCreationSessionStore(tmp_path / "c.sqlite3")
    co.create("c", "principal", "alpha", world="W", author_input="x")
    assert co.recover("c", "alpha") is not None
    assert co.recover("c", "beta") is None


def test_new_rows_store_install_binding_s6(tmp_path):
    gdb = tmp_path / "g.sqlite3"
    g = GuidedSessionStore(gdb, binding_normalizer=_normalize)
    g.create("g", "W", "credentials-session-a")
    stored = sqlite3.connect(gdb).execute(
        "select owner_binding from guided_sessions where session_id='g'"
    ).fetchone()[0]
    assert stored == _INSTALL
    cdb = tmp_path / "c.sqlite3"
    c = CoCreationSessionStore(cdb, binding_normalizer=_normalize)
    c.create("c", "principal", "local-dev-session-a", world="W", author_input="x")
    stored = sqlite3.connect(cdb).execute(
        "select authorization_binding from co_creation_sessions where session_id='c'"
    ).fetchone()[0]
    assert stored == _INSTALL


def test_production_normalizer_is_install_scoped_s6(monkeypatch):
    monkeypatch.setattr(api_server, "_local_state", lambda: object())
    monkeypatch.setattr(api_server, "_install_identity", lambda state: "install_stable")
    norm = api_server._durable_session_binding
    assert norm("credentials-session-x") == "install:install_stable"
    assert norm("local-dev-session-x") == "install:install_stable"
    assert norm("install:keep") == "install:keep"
    assert norm("") == ""


def test_unauthenticated_cannot_recover_s4(tmp_path, monkeypatch):
    mundos = tmp_path / "mundos"
    (mundos / "test_mundo" / "lore").mkdir(parents=True)
    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    api_server._LOCAL_STATE = None
    with api_server._local_session_lock:
        api_server._sessions.clear()
    # Keep the probe hermetic: never touch the real state-directory database.
    store = GuidedSessionStore(
        tmp_path / "g.sqlite3", binding_normalizer=_normalize,
    )
    store.create("g-unauth", "test_mundo", "credentials-session-owner")
    monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", store)
    anon = TestClient(api_server.app, client=("127.0.0.1", 50000))
    assert anon.get("/api/test_mundo/guided/session/g-unauth").status_code == 401
