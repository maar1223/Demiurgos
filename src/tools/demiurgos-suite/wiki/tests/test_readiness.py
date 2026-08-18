"""ONB-1.8 — local_editor readiness probe: storage write→read→delete round-trip.
Readiness is derived runtime truth, never configuration claims.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

from readiness import local_editor_ready, probe_local_storage  # noqa: E402


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