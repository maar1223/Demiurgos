"""RED/durable contract tests for the SQLite-backed GuidedSessionStore.

Covers: 30-day TTL, immutable methodology/version snapshot pinning, and the
guarantee that operational tokens/digests/authorizations are never serialized.
Pending proposals survive a durable restart only through revalidation; legacy
or unknown sessions fail closed without any silent migration.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from guided_character_protocol import (  # noqa: E402
    GuidedRequest,
    GuidedResponse,
    Outcome,
    PROTOCOL_VERSION,
)
import guided_session_store  # noqa: E402
from guided_session_store import (  # noqa: E402
    GuidedSessionStore,
    MethodologySnapshot,
    SESSION_TTL,
    default_db_path,
)


def _snapshot(version: str = "builtin") -> MethodologySnapshot:
    return MethodologySnapshot(
        skill_id="guided-character-v1",
        skill_version=version,
        compiled_contract_digest="contract-digest-v1",
    )


def _request(session_id: str, auth: str, revision: int = 0) -> GuidedRequest:
    return GuidedRequest(
        PROTOCOL_VERSION, "req-1", session_id, "nec", revision, auth,
        "I need a character",
    )


def _delta_response(request: GuidedRequest) -> GuidedResponse:
    return GuidedResponse(
        PROTOCOL_VERSION, request.request_id, request.session_id,
        request.base_revision, Outcome.DELTA,
        provenance=("test:run",),
        delta={"name": "Pert", "desire": "freedom"},
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_session_younger_than_ttl_survives_durable_restart(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    first = GuidedSessionStore(db)
    first.create("s-1", "nec", "author-1", methodology_snapshot=_snapshot())
    first.close()

    restarted = GuidedSessionStore(db)
    state = restarted.recover("s-1", "author-1")
    assert state is not None
    assert state.revision == 0
    assert state.world == "nec"
    assert restarted.requires_revalidation("s-1", "author-1") is False


def test_default_configuration_resolves_to_durable_local_path(monkeypatch, tmp_path: Path) -> None:
    """The no-argument default must be a stable file, never ``:memory:``."""
    default = tmp_path / "data" / "guided-sessions.sqlite3"
    monkeypatch.setattr(guided_session_store, "default_db_path", lambda: default)

    resolved = default_db_path()
    # Portable: on Windows Path renders backslashes, so compare components
    # rather than a forward-slash suffix.
    assert resolved.parent.name == "data"
    assert resolved.name == "guided-sessions.sqlite3"
    assert ":memory:" not in str(resolved)

    store = GuidedSessionStore()
    assert store._db_path == str(default)  # noqa: SLF001
    assert default.exists()
    store.close()


def test_default_configuration_recovers_across_two_instances(monkeypatch, tmp_path: Path) -> None:
    """Two stores built with the default (no db_path) share the same durable
    file, so a session created by one survives a restart opened by the other."""
    default = tmp_path / "data" / "guided-sessions.sqlite3"
    monkeypatch.setattr(guided_session_store, "default_db_path", lambda: default)

    first = GuidedSessionStore()
    first.create("s-default-1", "nec", "author-1", methodology_snapshot=_snapshot())
    first.close()

    restarted = GuidedSessionStore()
    state = restarted.recover("s-default-1", "author-1")
    assert state is not None
    assert state.revision == 0
    assert state.world == "nec"
    assert restarted.methodology_snapshot("s-default-1", "author-1") == _snapshot()
    restarted.close()


def test_explicit_memory_path_still_supported(monkeypatch, tmp_path: Path) -> None:
    """``db_path=":memory:"`` remains an explicit hermetic escape hatch and is
    NOT upgraded to a recoverable session (two instances cannot share it)."""
    default = tmp_path / "data" / "guided-sessions.sqlite3"
    monkeypatch.setattr(guided_session_store, "default_db_path", lambda: default)

    first = GuidedSessionStore(":memory:")
    assert first._db_path == ":memory:"  # noqa: SLF001
    first.create("s-mem-1", "nec", "author-1", methodology_snapshot=_snapshot())
    first.close()

    second = GuidedSessionStore(":memory:")
    assert second.recover("s-mem-1", "author-1") is None
    second.close()


def test_immutable_methodology_snapshot_is_pinned_at_create(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = GuidedSessionStore(db)
    snapshot = _snapshot("builtin")
    store.create("s-1", "nec", "author-1", methodology_snapshot=snapshot)
    request = _request("s-1", "author-1")
    state = store.commit(request, _delta_response(request))
    assert state is not None and state.revision == 1

    pinned = store.methodology_snapshot("s-1", "author-1")
    assert pinned == snapshot
    assert pinned.skill_id == "guided-character-v1"
    assert pinned.skill_version == "builtin"
    assert pinned.compiled_contract_digest == "contract-digest-v1"
    assert pinned.as_dict() == {
        "skill_id": "guided-character-v1",
        "skill_version": "builtin",
        "compiled_contract_digest": "contract-digest-v1",
        "flow_type": None,
    }

    restarted = GuidedSessionStore(db)
    assert restarted.methodology_snapshot("s-1", "author-1") == snapshot


def test_snapshot_is_frozen_and_never_rewritten(tmp_path: Path) -> None:
    snapshot = _snapshot("builtin")
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.skill_version = "v2"  # type: ignore[misc]

    db = tmp_path / "sessions.sqlite3"
    store = GuidedSessionStore(db)
    store.create("s-1", "nec", "author-1", methodology_snapshot=snapshot)
    request = _request("s-1", "author-1")
    store.commit(request, _delta_response(request))
    store.accept_proposal("s-1", "author-1", 1, "name")
    assert store.methodology_snapshot("s-1", "author-1") == _snapshot("builtin")


def test_session_older_than_ttl_is_discarded_and_fails_closed(tmp_path: Path) -> None:
    assert SESSION_TTL == timedelta(days=30)
    db = tmp_path / "sessions.sqlite3"
    store = GuidedSessionStore(db)
    store.create("s-1", "nec", "author-1", methodology_snapshot=_snapshot())
    far_future = _now() + timedelta(days=31)

    restarted = GuidedSessionStore(db)
    assert restarted.recover("s-1", "author-1", now=far_future) is None
    assert restarted.revalidate_pending("s-1", "author-1", 0, now=far_future) is None
    assert restarted.requires_revalidation("s-1", "author-1") is False


def test_discard_expired_removes_rows(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = GuidedSessionStore(db)
    store.create("s-1", "nec", "author-1")
    store.create("s-2", "nec", "author-1")
    store.create("s-3", "nec", "author-1")

    pruned = store.discard_expired(now=_now() + timedelta(days=31))
    assert pruned == 3
    assert store.recover("s-1", "author-1") is None
    assert store.recover("s-2", "author-1") is None
    assert store.recover("s-3", "author-1") is None


def _collect_keys(value: object, forbidden: set[str], keys: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if any(word in key.lower() for word in forbidden):
                keys.add(key)
            _collect_keys(item, forbidden, keys)
    elif isinstance(value, list):
        for item in value:
            _collect_keys(item, forbidden, keys)


def test_no_token_digest_or_authorization_serialization(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = GuidedSessionStore(db)
    store.create(
        "s-1", "nec", "author-1",
        methodology_snapshot=_snapshot(), relation_goal="New character: sister of Rhyz",
    )
    store.begin_confirmation("s-1", "author-1", "Create Rhyz's sister", "Start? (yes/no)")
    request = _request("s-1", "author-1", revision=1)
    store.commit(request, _delta_response(request))

    conn = sqlite3.connect(str(db))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(guided_sessions)")]
    conn.close()

    forbidden_column = {"token", "digest", "authorization"}
    for column in columns:
        assert not any(word in column.lower() for word in forbidden_column), column

    row = store._read_row("s-1", "author-1")  # noqa: SLF001
    assert row is not None
    # Operational state (messages + candidate) must never carry token/digest/
    # authorization keys. The methodology snapshot's compiled-contract digest is
    # contract identity, not an operational artifact, and is exempt.
    forbidden_keys: set[str] = set()
    for blob in ("messages_json", "candidate_json"):
        _collect_keys(json.loads(row[blob]), forbidden_column, forbidden_keys)
    assert forbidden_keys == set()

    recovered = store.recover("s-1", "author-1")
    assert recovered is not None
    assert "token" not in recovered.candidate.accepted_canon
    assert not any("digest" in key.lower() for key in recovered.candidate.proposals)


def test_revalidate_pending_marks_unconfirmed_proposal_after_restart(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    first = GuidedSessionStore(db)
    first.create("s-1", "nec", "author-1", methodology_snapshot=_snapshot())
    request = _request("s-1", "author-1")
    state = first.commit(request, _delta_response(request))
    assert state is not None and state.candidate.proposals
    assert first.requires_revalidation("s-1", "author-1") is False
    first.close()

    restarted = GuidedSessionStore(db)
    revalidated = restarted.revalidate_pending("s-1", "author-1", state.revision)
    assert revalidated is not None
    assert restarted.requires_revalidation("s-1", "author-1") is True

    fresh = restarted.commit(_request("s-1", "author-1", revision=state.revision), _delta_response(_request("s-1", "author-1", revision=state.revision)))
    assert fresh is not None
    assert restarted.requires_revalidation("s-1", "author-1") is False


def test_revalidate_pending_fails_closed_on_stale_revision(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = GuidedSessionStore(db)
    store.create("s-1", "nec", "author-1")
    request = _request("s-1", "author-1")
    store.commit(request, _delta_response(request))
    assert store.revalidate_pending("s-1", "author-1", 0) is None


def test_revalidate_pending_fails_closed_on_wrong_principal(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = GuidedSessionStore(db)
    store.create("s-1", "nec", "author-1")
    assert store.revalidate_pending("s-1", "other", 0) is None
    assert store.recover("s-1", "other") is None


def test_unknown_or_legacy_session_fails_closed_without_migration(tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    store = GuidedSessionStore(db)
    assert store.recover("legacy-session-1", "author-1") is None
    assert store.revalidate_pending("legacy-session-1", "author-1", 0) is None
    assert store.requires_revalidation("legacy-session-1", "author-1") is False
    assert store.methodology_snapshot("legacy-session-1", "author-1") is None

    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM guided_sessions").fetchone()[0]
    conn.close()
    assert count == 0


def test_flow_profile_pin_round_trips(tmp_path: Path) -> None:
    """S1/S8: the resolved profile is pinned with the snapshot and survives reload."""
    from guided_flow import GuidedFlowDeclaration, resolve_profile

    profile = resolve_profile(GuidedFlowDeclaration.from_mapping({
        "flow_id": "guided-system",
        "entity_type": "sistema",
        "ui_copy_key": "system",
        "index": True,
        "intent": {"terms": ["sistema"], "verbs": ["crear"]},
    }))
    assert profile is not None
    db = tmp_path / "sessions.sqlite3"
    store = GuidedSessionStore(db)
    snapshot = MethodologySnapshot(
        skill_id="narrative-system-creation",
        skill_version="1.1",
        compiled_contract_digest="digest",
        flow_type="guided-system",
        profile=profile.as_dict(),
    )
    store.create("s-profile", "nec", "author-1", methodology_snapshot=snapshot)

    restarted = GuidedSessionStore(db)
    pinned = restarted.methodology_snapshot("s-profile", "author-1")
    assert pinned is not None
    assert pinned.profile == profile.as_dict()
    assert pinned.as_dict()["profile"] == profile.as_dict()
