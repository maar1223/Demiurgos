"""Unit tests for ``scripts/hermes_tts_voice.py``.

Covers the pure language/voice resolution logic and the ``edge-tts`` synthesis
call (with the subprocess mocked). ``scripts/`` is not an importable package,
so the module is loaded directly from its file path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "hermes_tts_voice.py"
_SPEC = importlib.util.spec_from_file_location("hermes_tts_voice", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
tts = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tts)


# ---------------------------------------------------------------------------
# Voice constants
# ---------------------------------------------------------------------------

def test_voice_constants_cover_both_languages():
    assert tts.VOICES == {
        "es": "es-MX-DaliaNeural",
        "en": "en-US-AriaNeural",
    }


# ---------------------------------------------------------------------------
# resolve_language
# ---------------------------------------------------------------------------

def test_env_wins_over_env_file():
    assert tts.resolve_language(
        {"DEMIURGOS_LANGUAGE": "en"}, "DEMIURGOS_LANGUAGE=es\n"
    ) == "en"


def test_env_file_used_when_env_absent():
    assert tts.resolve_language({}, "DEMIURGOS_LANGUAGE=en\n") == "en"


def test_default_is_es_when_nothing_configured():
    assert tts.resolve_language({}, None) == "es"
    assert tts.resolve_language({}, "") == "es"


@pytest.mark.parametrize("value", ["fr", "ES-AR", "", "de", "es-ar"])
def test_unknown_env_value_falls_back_to_es(value):
    assert tts.resolve_language({"DEMIURGOS_LANGUAGE": value}, None) == "es"


def test_empty_env_value_does_not_fall_through_to_env_file():
    # The key being present in the environment wins, even when empty.
    assert tts.resolve_language(
        {"DEMIURGOS_LANGUAGE": ""}, "DEMIURGOS_LANGUAGE=en\n"
    ) == "es"


def test_env_value_is_normalized_to_lowercase():
    assert tts.resolve_language({"DEMIURGOS_LANGUAGE": "EN"}, None) == "en"


def test_env_file_ignores_comments_blanks_and_strips_quotes():
    text = (
        "# Demiurgos UI language\n"
        "\n"
        'DEMIURGOS_LANGUAGE = "en"\n'
        "OTHER_KEY=value\n"
    )
    assert tts.resolve_language({}, text) == "en"


def test_env_file_tolerates_export_prefix_and_single_quotes():
    assert tts.resolve_language({}, "export DEMIURGOS_LANGUAGE='en'\n") == "en"


# ---------------------------------------------------------------------------
# resolve_voice
# ---------------------------------------------------------------------------

def test_resolve_voice_es():
    assert tts.resolve_voice("es") == "es-MX-DaliaNeural"


def test_resolve_voice_en():
    assert tts.resolve_voice("en") == "en-US-AriaNeural"


@pytest.mark.parametrize("language", ["fr", "", "es-ar", "de"])
def test_resolve_voice_unknown_falls_back_to_es(language):
    assert tts.resolve_voice(language) == "es-MX-DaliaNeural"


# ---------------------------------------------------------------------------
# read_env_language_file
# ---------------------------------------------------------------------------

def test_read_env_language_file_reads_root_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEMIURGOS_LANGUAGE=en\n", encoding="utf-8")
    monkeypatch.setenv("DEMIURGOS_ROOT", str(tmp_path))
    monkeypatch.delenv("DEMIURGOS_DATA_ROOT", raising=False)
    assert tts.read_env_language_file() == "DEMIURGOS_LANGUAGE=en\n"


def test_read_env_language_file_falls_back_to_data_root(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("DEMIURGOS_LANGUAGE=en\n", encoding="utf-8")
    monkeypatch.delenv("DEMIURGOS_ROOT", raising=False)
    monkeypatch.setenv("DEMIURGOS_DATA_ROOT", str(tmp_path))
    assert tts.read_env_language_file() is not None


def test_read_env_language_file_returns_none_when_unreadable(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMIURGOS_ROOT", str(tmp_path))
    monkeypatch.delenv("DEMIURGOS_DATA_ROOT", raising=False)
    assert tts.read_env_language_file() is None


# ---------------------------------------------------------------------------
# synthesize
# ---------------------------------------------------------------------------

def _fake_run(record, *, returncode=0, create_output=True, content=b"audio"):
    def _run(command, check, capture_output):
        record["command"] = command
        record["kwargs"] = {"check": check, "capture_output": capture_output}
        if create_output:
            Path(command[-1]).write_bytes(content)
        return SimpleNamespace(returncode=returncode, stdout=b"", stderr=b"boom")

    return _run


def test_synthesize_builds_expected_command(monkeypatch, tmp_path):
    text_path = tmp_path / "in.txt"
    text_path.write_text("hola", encoding="utf-8")
    output_path = tmp_path / "out.mp3"
    record: dict[str, object] = {}

    monkeypatch.setattr(tts.subprocess, "run", _fake_run(record))
    tts.synthesize(text_path, output_path, "es-MX-DaliaNeural", "/opt/edge-tts")

    command = record["command"]
    assert command[0] == "/opt/edge-tts"
    assert command[command.index("--voice") + 1] == "es-MX-DaliaNeural"
    assert command[command.index("-f") + 1] == str(text_path)
    assert command[command.index("--write-media") + 1] == str(output_path)
    assert record["kwargs"] == {"check": False, "capture_output": True}
    assert output_path.read_bytes() == b"audio"


def test_synthesize_raises_on_nonzero_exit(monkeypatch, tmp_path):
    text_path = tmp_path / "in.txt"
    text_path.write_text("hola", encoding="utf-8")
    record: dict[str, object] = {}

    monkeypatch.setattr(tts.subprocess, "run", _fake_run(record, returncode=1))
    with pytest.raises(tts.TtsSynthesisError):
        tts.synthesize(text_path, tmp_path / "out.mp3", "en-US-AriaNeural", "edge-tts")


def test_synthesize_raises_when_output_missing(monkeypatch, tmp_path):
    text_path = tmp_path / "in.txt"
    text_path.write_text("hola", encoding="utf-8")
    record: dict[str, object] = {}

    monkeypatch.setattr(tts.subprocess, "run", _fake_run(record, create_output=False))
    with pytest.raises(tts.TtsSynthesisError):
        tts.synthesize(text_path, tmp_path / "out.mp3", "en-US-AriaNeural", "edge-tts")


def test_synthesize_raises_when_output_empty(monkeypatch, tmp_path):
    text_path = tmp_path / "in.txt"
    text_path.write_text("hola", encoding="utf-8")
    record: dict[str, object] = {}

    monkeypatch.setattr(
        tts.subprocess, "run", _fake_run(record, content=b"")
    )
    with pytest.raises(tts.TtsSynthesisError):
        tts.synthesize(text_path, tmp_path / "out.mp3", "en-US-AriaNeural", "edge-tts")


def test_synthesize_discards_stale_output_before_running(monkeypatch, tmp_path):
    """Defect A: a pre-existing non-empty output must not yield false success."""
    text_path = tmp_path / "in.txt"
    text_path.write_text("hola", encoding="utf-8")
    output_path = tmp_path / "out.mp3"
    output_path.write_bytes(b"STALE")
    record: dict[str, object] = {}

    # The subprocess "succeeds" (exit 0) but writes nothing.
    monkeypatch.setattr(tts.subprocess, "run", _fake_run(record, create_output=False))
    with pytest.raises(tts.TtsSynthesisError):
        tts.synthesize(text_path, output_path, "es-MX-DaliaNeural", "/opt/edge-tts")
    assert not output_path.exists()


def test_synthesize_removes_stale_output_on_success_too(monkeypatch, tmp_path):
    """Defect A: the output written this run is the only content left behind."""
    text_path = tmp_path / "in.txt"
    text_path.write_text("hola", encoding="utf-8")
    output_path = tmp_path / "out.mp3"
    output_path.write_bytes(b"STALE-STALE-STALE")
    record: dict[str, object] = {}

    monkeypatch.setattr(tts.subprocess, "run", _fake_run(record, content=b"fresh"))
    tts.synthesize(text_path, output_path, "es-MX-DaliaNeural", "/opt/edge-tts")
    assert output_path.read_bytes() == b"fresh"


def test_synthesize_wraps_spawn_oserror(monkeypatch, tmp_path):
    """Defect B: a non-spawnable binary must surface as TtsSynthesisError."""
    text_path = tmp_path / "in.txt"
    text_path.write_text("hola", encoding="utf-8")

    def _boom(command, check, capture_output):
        raise PermissionError("not executable")

    monkeypatch.setattr(tts.subprocess, "run", _boom)
    with pytest.raises(tts.TtsSynthesisError):
        tts.synthesize(
            text_path, tmp_path / "out.mp3", "es-MX-DaliaNeural", "/opt/edge-tts"
        )


# ---------------------------------------------------------------------------
# find_edge_tts
# ---------------------------------------------------------------------------

def test_find_edge_tts_fallback_requires_executable(monkeypatch, tmp_path):
    """Defect B: a non-executable fallback binary is not a usable edge-tts."""
    fallback = tmp_path / "edge-tts"
    fallback.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(tts, "FALLBACK_EDGE_TTS", fallback)
    monkeypatch.setattr(tts.shutil, "which", lambda _name: None)

    fallback.chmod(0o644)
    assert tts.find_edge_tts() is None

    fallback.chmod(0o755)
    assert tts.find_edge_tts() == str(fallback)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def test_main_wrong_argument_count_returns_2(capsys):
    assert tts.main([]) == 2
    assert "usage:" in capsys.readouterr().err


def test_main_missing_input_file_returns_nonzero(capsys, tmp_path):
    code = tts.main([str(tmp_path / "missing.txt"), str(tmp_path / "out.mp3")])
    assert code == 1
    assert "cannot read input" in capsys.readouterr().err


def test_main_empty_input_returns_nonzero(capsys, tmp_path):
    text_path = tmp_path / "in.txt"
    text_path.write_text("   \n", encoding="utf-8")
    code = tts.main([str(text_path), str(tmp_path / "out.mp3")])
    assert code == 1
    assert "empty" in capsys.readouterr().err


def test_main_non_utf8_input_returns_nonzero(capsys, tmp_path):
    """Defect C: invalid UTF-8 must fail cleanly, not with a traceback."""
    text_path = tmp_path / "in.txt"
    text_path.write_bytes(b"\xff\xfe\x00\x00 not utf-8")
    code = tts.main([str(text_path), str(tmp_path / "out.mp3")])
    assert code == 1
    assert "cannot read input" in capsys.readouterr().err
