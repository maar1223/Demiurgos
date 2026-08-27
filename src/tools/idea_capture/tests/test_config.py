"""Config tests for the AI-gate mode flag (SDD idea-capture-ai-gate, task 4.1).

The capture mode resolves with env > yaml > default precedence (R-1): the
``DEMIURGOS_IDEA_CAPTURE_MODE`` env var wins, otherwise the optional
``capture_mode`` field in ``config/idea-capture.yaml``, otherwise ``ai``.
Invalid values at any layer warn and fall back to ``ai`` so the escape hatch
never takes an unknown value.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TOOLS = Path(__file__).resolve().parents[2]  # src/tools
for _p in (str(_TOOLS),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from idea_capture.config import resolve_capture_mode  # noqa: E402

_ENV = "DEMIURGOS_IDEA_CAPTURE_MODE"


def _config(tmp_path: Path, capture_mode=None) -> Path:
    path = tmp_path / "idea-capture.yaml"
    lines = ["authorized_bindings: []\n"]
    if capture_mode is not None:
        lines.append(f"capture_mode: {capture_mode}\n")
    path.write_text("".join(lines), encoding="utf-8")
    return path


# -- yaml parsing: default ai / explicit values / invalid -> ai -------------


def test_yaml_missing_defaults_to_ai(tmp_path, monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    # No yaml file at all -> default ai (fail closed, no crash).
    assert resolve_capture_mode(tmp_path / "does-not-exist.yaml") == "ai"


def test_yaml_omitted_defaults_to_ai(tmp_path, monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    assert resolve_capture_mode(_config(tmp_path)) == "ai"


def test_yaml_ai_parsed(tmp_path, monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    assert resolve_capture_mode(_config(tmp_path, "ai")) == "ai"


def test_yaml_strict_parsed(tmp_path, monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    assert resolve_capture_mode(_config(tmp_path, "strict")) == "strict"


def test_yaml_invalid_warns_and_defaults_to_ai(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv(_ENV, raising=False)
    assert resolve_capture_mode(_config(tmp_path, "garbage")) == "ai"
    assert any("garbage" in r.message and "capture_mode" in r.message
               for r in caplog.records)


# -- precedence: env > yaml > default ai -------------------------------------


def test_env_wins_over_yaml(monkeypatch, tmp_path):
    monkeypatch.setenv(_ENV, "strict")
    path = _config(tmp_path, "ai")  # yaml says ai, env says strict
    assert resolve_capture_mode(path) == "strict"


def test_env_ai_wins_over_yaml_strict(monkeypatch, tmp_path):
    monkeypatch.setenv(_ENV, "ai")
    assert resolve_capture_mode(_config(tmp_path, "strict")) == "ai"


def test_yaml_strict_used_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv(_ENV, raising=False)
    assert resolve_capture_mode(_config(tmp_path, "strict")) == "strict"


def test_env_invalid_warns_and_defaults_to_ai(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv(_ENV, "garbage")
    assert resolve_capture_mode(_config(tmp_path, "strict")) == "ai"
    assert any(_ENV in r.message and "garbage" in r.message
               for r in caplog.records)
