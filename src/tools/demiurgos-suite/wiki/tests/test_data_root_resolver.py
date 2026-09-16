# -*- coding: utf-8 -*-
"""Data-root resolver tests — resolution order, atomic pointer, no fallback.

Covers WU-1 of portable-data-root-drive-backup: ``data_root.resolve_data_root``,
``read_pointer``, ``write_pointer`` and the atomicity of the bootstrap pointer
(REQ-DR-1/2/4, SC-DR-1.1/1.2/1.3/2.1/4.1). Every test injects ``environ`` and
``config_dir`` so nothing touches the real process env or the real user config
dir.
"""

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import data_root  # noqa: E402
from data_root import DataRootNotConfigured  # noqa: E402


def _config(tmp_path: Path) -> Path:
    return tmp_path / "config"


def _file_bytes(root: Path) -> dict[str, int]:
    return {
        str(p.relative_to(root)): p.stat().st_size
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_data_root_not_configured_is_a_runtime_error():
    assert issubclass(DataRootNotConfigured, RuntimeError)


def test_env_override_wins(tmp_path: Path):
    cfg = _config(tmp_path)
    pointed = tmp_path / "pointed-root"
    pointed.mkdir()
    env_root = tmp_path / "env-root"
    env_root.mkdir()
    data_root.write_pointer(pointed, config_dir=cfg)
    before = data_root.pointer_path(cfg).read_bytes()

    resolved = data_root.resolve_data_root(
        environ={data_root.ENV_VAR: str(env_root)}, config_dir=cfg
    )

    assert resolved == env_root.resolve()
    # the pointer is never rewritten by an env override
    assert data_root.pointer_path(cfg).read_bytes() == before


def test_pointer_fallback(tmp_path: Path):
    cfg = _config(tmp_path)
    root = tmp_path / "chosen root"  # a space proves path normalization
    root.mkdir()
    data_root.write_pointer(root, config_dir=cfg)

    resolved = data_root.resolve_data_root(environ={}, config_dir=cfg)

    assert resolved == root.resolve()
    assert resolved.is_absolute()


def test_missing_sources_fail_loudly(tmp_path: Path):
    cfg = _config(tmp_path)

    with pytest.raises(DataRootNotConfigured) as excinfo:
        data_root.resolve_data_root(environ={}, config_dir=cfg)

    message = str(excinfo.value)
    # the typed error names BOTH sources ...
    assert data_root.ENV_VAR in message
    assert str(data_root.pointer_path(cfg)) in message
    # ... and no path inside the code checkout is ever returned
    assert str(Path(data_root.__file__).resolve().parent) not in message


def test_blank_env_is_ignored(tmp_path: Path):
    cfg = _config(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    data_root.write_pointer(root, config_dir=cfg)

    resolved = data_root.resolve_data_root(
        environ={data_root.ENV_VAR: "   "}, config_dir=cfg
    )

    assert resolved == root.resolve()


def test_read_pointer_without_file_returns_none(tmp_path: Path):
    assert data_root.read_pointer(_config(tmp_path)) is None


def test_pointer_records_the_path_only(tmp_path: Path):
    cfg = _config(tmp_path)
    root = tmp_path / "root"
    root.mkdir()

    data_root.write_pointer(root, config_dir=cfg)

    payload = json.loads(data_root.pointer_path(cfg).read_text(encoding="utf-8"))
    assert set(payload) == {"schema_version", "data_root", "updated_at"}
    assert payload["schema_version"] == data_root.SCHEMA_VERSION
    assert payload["data_root"] == str(root.resolve())


def test_pointer_path_defaults_to_platformdirs_config_dir():
    import platformdirs

    expected = (
        Path(platformdirs.user_config_dir(data_root.APP_NAME)) / data_root.POINTER_NAME
    )
    assert data_root.pointer_path() == expected


@pytest.mark.parametrize(
    "raw, reason",
    [
        ("{not json", "not valid JSON"),
        ("[1, 2, 3]", "not a JSON object"),
        ('{"schema_version": 1}', "no usable 'data_root'"),
        ('{"schema_version": 1, "data_root": ""}', "no usable 'data_root'"),
        ('{"schema_version": 1, "data_root": "   "}', "no usable 'data_root'"),
        ('{"schema_version": 1, "data_root": 42}', "no usable 'data_root'"),
        ('{"schema_version": 99, "data_root": "/x"}', "unsupported schema_version"),
    ],
)
def test_corrupt_or_partial_pointer_fails_loudly(tmp_path: Path, raw: str, reason: str):
    cfg = _config(tmp_path)
    cfg.mkdir()
    data_root.pointer_path(cfg).write_text(raw, encoding="utf-8")

    with pytest.raises(DataRootNotConfigured) as excinfo:
        data_root.read_pointer(cfg)
    message = str(excinfo.value)
    assert str(data_root.pointer_path(cfg)) in message
    assert reason in message

    # a corrupt pointer NEVER falls back to a code-relative path
    with pytest.raises(DataRootNotConfigured):
        data_root.resolve_data_root(environ={}, config_dir=cfg)


def test_pointer_write_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _config(tmp_path)
    root_a = tmp_path / "root-a"
    root_a.mkdir()
    root_b = tmp_path / "root-b"
    root_b.mkdir()

    data_root.write_pointer(root_a, config_dir=cfg)
    before = data_root.pointer_path(cfg).read_bytes()

    def interrupted(src, dst):
        raise OSError("simulated interruption mid-write")

    with monkeypatch.context() as m:
        m.setattr(data_root.os, "replace", interrupted)
        with pytest.raises(OSError):
            data_root.write_pointer(root_b, config_dir=cfg)

    # the previous COMPLETE record survived, byte for byte ...
    assert data_root.pointer_path(cfg).read_bytes() == before
    assert data_root.read_pointer(cfg) == root_a.resolve()
    # ... and no temp residue remains
    assert [p.name for p in cfg.iterdir() if data_root._TMP_MARKER in p.name] == []

    # a successful rewrite yields the new complete record, still no residue
    data_root.write_pointer(root_b, config_dir=cfg)
    assert data_root.read_pointer(cfg) == root_b.resolve()
    assert [p.name for p in cfg.iterdir() if data_root._TMP_MARKER in p.name] == []


def test_pointer_moves_no_bytes(tmp_path: Path):
    root = tmp_path / "data-root"
    (root / "mundos").mkdir(parents=True)
    (root / "ideas").mkdir()
    (root / "config").mkdir()
    (root / "mundos" / "Avalor.md").write_bytes(b"# Avalor\n")
    (root / "ideas" / "a.md").write_bytes(b"# A\n")
    (root / "ideas" / "b.md").write_bytes(b"# B\n")
    (root / "config" / "app.json").write_bytes(b'{"ok": true}\n')
    cfg = _config(tmp_path)

    before = _file_bytes(root)

    data_root.write_pointer(root, config_dir=cfg)
    resolved = data_root.resolve_data_root(environ={}, config_dir=cfg)

    assert resolved == root.resolve()
    # file count and byte total under the root are unchanged: no migration ran
    assert _file_bytes(root) == before
    # the pointer lives in the config dir, NOT under the data root
    assert not list(root.rglob(f"{data_root.POINTER_NAME}*"))
    assert data_root.pointer_path(cfg).is_file()
