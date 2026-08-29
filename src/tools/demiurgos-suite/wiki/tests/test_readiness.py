"""ONB-1.8 — local_editor readiness probe: storage write→read→delete round-trip.
Readiness is derived runtime truth, never configuration claims.

Also covers the auth-google-vault identity contract (R-ID1, 7.6): the
identity card is ``configured`` ONLY when ``DEMIURGOS_AUTH_MODE=google`` AND
``GOOGLE_CLIENT_ID`` are set; registry claims never configure it.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from readiness import (  # noqa: E402
    identity_configured,
    local_editor_ready,
    probe_local_storage,
    project_cards,
    project_offline,
)


def test_probe_round_trips_and_cleans_up(tmp_path: Path) -> None:
    result = probe_local_storage(tmp_path)
    assert result["probe"] == "local_editor"
    assert result["ok"] is True
    probe_dir = tmp_path / "data" / "probes"
    assert list(probe_dir.iterdir()) == [], "probe file must be deleted"


def test_local_editor_ready_derives_from_probe(tmp_path: Path) -> None:
    assert local_editor_ready(tmp_path) is True


def test_probe_fails_safely_when_storage_is_unwritable(tmp_path: Path) -> None:
    blocked = tmp_path / "data"
    blocked.write_text("occupied", encoding="utf-8")  # data/ is a file, not a dir
    result = probe_local_storage(tmp_path)
    assert result["probe"] == "local_editor"
    assert result["ok"] is False
    assert result["detail"]
    assert local_editor_ready(tmp_path) is False


def test_probe_readback_mismatch_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_write = Path.write_text

    def broken_write(self, *args, **kwargs):
        # Whatever the probe intends to write, the disk returns tampered bytes.
        return real_write(self, "tampered", *args[1:], **kwargs)

    monkeypatch.setattr(Path, "write_text", broken_write)
    result = probe_local_storage(tmp_path)
    assert result["ok"] is False
    assert "mismatch" in result["detail"]


# ---------------------------------------------------------------------------
# 7.6 — identity card dedicated contract (R-ID1, S-ID1a/b)
# ---------------------------------------------------------------------------


def test_identity_configured_when_google_mode_and_client_id_set(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "google")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client.apps.googleusercontent.com")
    cards = project_cards({}, worlds=[], probe_ok=True)
    assert cards["identity"] == "configured"
    # The identity contract is local configuration, not connectivity: it must
    # never surface as remote-pending (R-ID1).
    assert "identity" not in project_offline(cards)["remote_pending"]


def test_identity_pending_when_mode_is_not_google(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client.apps.googleusercontent.com")
    cards = project_cards({}, worlds=[], probe_ok=True)
    assert cards["identity"] == "pending"


def test_identity_pending_when_client_id_missing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "google")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    cards = project_cards({}, worlds=[], probe_ok=True)
    assert cards["identity"] == "pending"


def test_identity_pending_ignores_registry_claims(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    cards = project_cards(
        {"capabilities": {"identity": "configured"}}, worlds=[], probe_ok=True)
    assert cards["identity"] == "pending"


def test_identity_configured_helper_contract(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "google")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "c")
    assert identity_configured() is True
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "GOOGLE")
    assert identity_configured() is True  # mode is case-normalized
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
    assert identity_configured() is False
    monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "google")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert identity_configured() is False