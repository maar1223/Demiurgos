# -*- coding: utf-8 -*-
"""Dispatch-time launcher resolution (S1/S2 of system-restart-uses-running-root).

After an update flips ``<install_root>/current``, an in-app restart must run
the newly installed launcher, not the one this process loaded at boot.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_WIKI = Path(__file__).resolve().parents[1]
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))

import api_server  # noqa: E402

_LAUNCHER = "start-demiurgos.ps1" if os.name == "nt" else "start-demiurgos.sh"


def test_install_root_from_app_version_dir(tmp_path, monkeypatch):
    root = tmp_path / "install"
    code = root / "app" / "0.4.2"
    code.mkdir(parents=True)
    monkeypatch.setattr(api_server, "_CODE_ROOT", code)
    monkeypatch.delenv("DEMIURGOS_ROOT", raising=False)

    assert api_server._install_root() == root


def test_install_root_from_demiurgos_root_env(tmp_path, monkeypatch):
    root = tmp_path / "install"
    current = root / "current"
    current.mkdir(parents=True)
    monkeypatch.setattr(api_server, "_CODE_ROOT", tmp_path / "elsewhere")
    monkeypatch.setenv("DEMIURGOS_ROOT", str(current))

    assert api_server._install_root() == root


def test_system_launcher_uses_current_after_an_update(tmp_path, monkeypatch):
    root = tmp_path / "install"
    code = root / "app" / "0.4.2"
    code.mkdir(parents=True)
    (root / "current").symlink_to(code)
    monkeypatch.setattr(api_server, "_CODE_ROOT", code)
    monkeypatch.delenv("DEMIURGOS_ROOT", raising=False)

    assert api_server._system_launcher_path() == (
        root / "current" / "scripts" / _LAUNCHER
    )


def test_system_launcher_dev_checkout_keeps_code_root(tmp_path, monkeypatch):
    code = tmp_path / "demiurgos"
    code.mkdir()
    monkeypatch.setattr(api_server, "_CODE_ROOT", code)
    monkeypatch.delenv("DEMIURGOS_ROOT", raising=False)

    assert api_server._system_launcher_path() == code / "scripts" / _LAUNCHER
