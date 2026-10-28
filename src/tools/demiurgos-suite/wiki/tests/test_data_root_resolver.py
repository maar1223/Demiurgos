# -*- coding: utf-8 -*-
"""Data-root resolver tests — resolution order, atomic pointer, no fallback.

Covers WU-1 of portable-data-root-drive-backup: ``data_root.resolve_data_root``,
``read_pointer``, ``write_pointer`` and the atomicity of the bootstrap pointer
(REQ-DR-1/2/4, SC-DR-1.1/1.2/1.3/2.1/4.1). Every test injects ``environ`` and
``config_dir`` so nothing touches the real process env or the real user config
dir.

Also covers WU-1 of hermes-probe-closure: the optional-``platformdirs``
stdlib fallback (REQ-PLR-3/4/5). Those tests inject the resolver's own seams
(``_HAS_PLATFORMDIRS``/``_platformdirs``/``_is_windows`` plus ``HOME``/
``XDG_CONFIG_HOME``/``APPDATA``) so they never touch the real user config dir.
"""

import json
import os
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


# -- hermes-probe-closure WU-1: optional platformdirs, stdlib fallback --------
# REQ-PLR-3: the pointer location above is preserved byte-for-byte when
# platformdirs is importable. The cases below pin the fallback (REQ-PLR-4) and
# the preserved failure/atomic contract (REQ-PLR-5) when it is absent.


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX XDG/~/.config fallback; Windows uses %APPDATA%",
)
def test_pointer_path_falls_back_to_xdg_config_home_without_platformdirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """REQ-PLR-4: absent platformdirs + non-blank ``$XDG_CONFIG_HOME``."""
    monkeypatch.setattr(data_root, "_HAS_PLATFORMDIRS", False)
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    assert (
        data_root.pointer_path()
        == xdg / data_root.APP_NAME / data_root.POINTER_NAME
    )


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX XDG/~/.config fallback; Windows uses %APPDATA%",
)
@pytest.mark.parametrize("xdg_value", [None, "", "   "])
def test_pointer_path_falls_back_to_home_config_without_xdg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, xdg_value: str | None
):
    """REQ-PLR-4: absent platformdirs + unset/blank XDG -> ``~/.config``."""
    monkeypatch.setattr(data_root, "_HAS_PLATFORMDIRS", False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    if xdg_value is None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", xdg_value)

    assert (
        data_root.pointer_path()
        == home / ".config" / data_root.APP_NAME / data_root.POINTER_NAME
    )


def test_pointer_path_falls_back_to_appdata_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """REQ-PLR-4: absent platformdirs + Windows -> ``%APPDATA%``."""
    monkeypatch.setattr(data_root, "_HAS_PLATFORMDIRS", False)
    monkeypatch.setattr(data_root, "_is_windows", lambda: True)
    appdata = tmp_path / "appdata"
    monkeypatch.setenv("APPDATA", str(appdata))

    assert (
        data_root.pointer_path()
        == appdata / data_root.APP_NAME / data_root.POINTER_NAME
    )


def test_fallback_does_not_shadow_platformdirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """REQ-PLR-3: present platformdirs + a set XDG never uses the fallback."""
    pd_root = tmp_path / "pd"

    class _StubPlatformdirs:
        @staticmethod
        def user_config_dir(name: str) -> str:
            return str(pd_root / name)

    monkeypatch.setattr(data_root, "_HAS_PLATFORMDIRS", True)
    monkeypatch.setattr(data_root, "_platformdirs", _StubPlatformdirs)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert (
        data_root.pointer_path()
        == pd_root / data_root.APP_NAME / data_root.POINTER_NAME
    )


def test_no_config_without_platformdirs_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """REQ-PLR-5: absent platformdirs, no env, no pointer -> raise."""
    monkeypatch.setattr(data_root, "_HAS_PLATFORMDIRS", False)
    cfg = _config(tmp_path)

    with pytest.raises(DataRootNotConfigured):
        data_root.resolve_data_root(environ={}, config_dir=cfg)


def test_malformed_pointer_without_platformdirs_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """REQ-PLR-5: absent platformdirs + malformed pointer -> raise."""
    monkeypatch.setattr(data_root, "_HAS_PLATFORMDIRS", False)
    cfg = _config(tmp_path)
    cfg.mkdir()
    data_root.pointer_path(cfg).write_text("{not json", encoding="utf-8")

    with pytest.raises(DataRootNotConfigured):
        data_root.resolve_data_root(environ={}, config_dir=cfg)


def test_pointer_write_is_atomic_without_platformdirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """REQ-PLR-5: the atomic staged-temp + ``os.replace`` pointer is preserved."""
    monkeypatch.setattr(data_root, "_HAS_PLATFORMDIRS", False)
    cfg = _config(tmp_path)
    root_a = tmp_path / "root-a"
    root_a.mkdir()
    root_b = tmp_path / "root-b"
    root_b.mkdir()

    data_root.write_pointer(root_a, config_dir=cfg)
    assert data_root.read_pointer(cfg) == root_a.resolve()

    def interrupted(src, dst):
        raise OSError("simulated interruption mid-write")

    with monkeypatch.context() as m:
        m.setattr(data_root.os, "replace", interrupted)
        with pytest.raises(OSError):
            data_root.write_pointer(root_b, config_dir=cfg)

    # the previous COMPLETE record survived and no temp residue remains
    assert data_root.read_pointer(cfg) == root_a.resolve()
    assert [p.name for p in cfg.iterdir() if data_root._TMP_MARKER in p.name] == []

    data_root.write_pointer(root_b, config_dir=cfg)
    assert data_root.read_pointer(cfg) == root_b.resolve()
    assert [p.name for p in cfg.iterdir() if data_root._TMP_MARKER in p.name] == []


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


# ---------------------------------------------------------------------------
# State root (machine-local) — the other half of the sync boundary.
#
# Step 1 is deliberately resolver-only: no store consumes it yet, so nothing
# changes behaviour. These cells pin the two properties that matter — machine
# state has a platform home (never fails), and it can never be dragged inside
# the author's (possibly cloud-synced) content root by the pointer.
# ---------------------------------------------------------------------------


def test_state_root_defaults_to_platformdirs_user_data_dir():
    if not data_root._HAS_PLATFORMDIRS:
        pytest.skip("platformdirs is not importable in this interpreter")
    # ``environ={}``: the suite exports a hermetic DEMIURGOS_STATE_ROOT, so the
    # no-override default is asserted through the injection seam, not the env.
    assert data_root.resolve_state_root(environ={}) == Path(
        data_root._platformdirs.user_data_dir(data_root.APP_NAME)
    )


def test_state_root_env_override_wins(tmp_path: Path):
    override = tmp_path / "state"
    resolved = data_root.resolve_state_root(
        environ={data_root.ENV_STATE_ROOT: str(override)},
        state_dir=tmp_path / "ignored",
    )
    assert resolved == override.resolve()


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_state_env_is_ignored(tmp_path: Path, blank: str):
    injected = tmp_path / "injected"
    assert (
        data_root.resolve_state_root(
            environ={data_root.ENV_STATE_ROOT: blank}, state_dir=injected
        )
        == injected
    )


def test_state_root_injection_seam(tmp_path: Path):
    injected = tmp_path / "state"
    assert data_root.resolve_state_root(environ={}, state_dir=injected) == injected


def test_state_root_never_raises_without_a_data_root(tmp_path: Path):
    """Machine state has a platform home: nothing to configure, nothing to fail."""
    injected = tmp_path / "state"
    assert data_root.resolve_state_root(environ={}, state_dir=injected) == injected


def test_state_root_never_reads_the_data_root_pointer(tmp_path: Path):
    """A configured data root must never drag machine state inside it."""
    cfg = _config(tmp_path)
    pointed = tmp_path / "pointed-root"
    pointed.mkdir()
    data_root.write_pointer(pointed, config_dir=cfg)
    injected = tmp_path / "state"

    resolved = data_root.resolve_state_root(environ={}, state_dir=injected)
    assert resolved == injected
    assert resolved != pointed / "data"


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX XDG fallback; Windows uses %LOCALAPPDATA%",
)
def test_state_root_falls_back_to_xdg_data_home_without_platformdirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Absent platformdirs + non-blank ``$XDG_DATA_HOME`` (POSIX only)."""
    monkeypatch.setattr(data_root, "_HAS_PLATFORMDIRS", False)
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))

    assert data_root.resolve_state_root(environ={}) == xdg / data_root.APP_NAME


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX XDG/~/.local/share fallback; Windows uses %LOCALAPPDATA%",
)
@pytest.mark.parametrize("xdg_value", [None, "", "   "])
def test_state_root_falls_back_to_home_share_without_xdg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, xdg_value: str | None
):
    monkeypatch.setattr(data_root, "_HAS_PLATFORMDIRS", False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    if xdg_value is None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_DATA_HOME", xdg_value)

    assert (
        data_root.resolve_state_root(environ={})
        == home / ".local" / "share" / data_root.APP_NAME
    )


def test_state_root_falls_back_to_localappdata_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(data_root, "_HAS_PLATFORMDIRS", False)
    monkeypatch.setattr(data_root, "_is_windows", lambda: True)
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    assert data_root.resolve_state_root(environ={}) == local / data_root.APP_NAME
