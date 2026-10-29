# -*- coding: utf-8 -*-
"""The native folder dialog, opened by the server (step 5).

The browser cannot name a server folder, so the server opens the OS dialog where
it runs. What matters: a cancel is not an error, a host without a dialog says so
instead of hanging, and both platforms build a fixed argv (never a shell).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import folder_dialog
from folder_dialog import (
    DialogFailed,
    DialogUnavailable,
    dialog_command,
    is_available,
    pick_directory,
)


class _Result:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_zenity_is_used_when_it_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        folder_dialog.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None
    )
    command = dialog_command(platform="posix", initial="/media/disco")
    assert command is not None
    assert command[0] == "zenity"
    assert "--directory" in command
    assert any(part.startswith("--filename=/media/disco") for part in command)


def test_no_dialog_on_this_host_is_reported_not_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(folder_dialog.shutil, "which", lambda name: None)
    assert dialog_command(platform="posix") is None
    assert is_available(platform="posix") is False
    with pytest.raises(DialogUnavailable):
        pick_directory(platform="posix")


def test_a_chosen_folder_comes_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        folder_dialog.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None
    )
    result = pick_directory(
        initial=None,
        platform="posix",
        run=lambda command, timeout: _Result(0, stdout="/media/disco/MisMundos\n"),
    )
    assert result == Path("/media/disco/MisMundos")


def test_cancelling_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        folder_dialog.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None
    )
    assert (
        pick_directory(platform="posix", run=lambda command, timeout: _Result(1)) is None
    )


def test_a_dialog_that_never_answers_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        folder_dialog.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None
    )

    def hang(command, timeout):
        raise subprocess.TimeoutExpired(cmd=list(command), timeout=timeout)

    with pytest.raises(DialogFailed) as failure:
        pick_directory(platform="posix", run=hang)
    assert "in time" in str(failure.value)


def test_the_windows_command_is_a_fixed_argv_with_a_folder_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        folder_dialog.shutil,
        "which",
        lambda name: "powershell" if name == "powershell" else None,
    )
    command = dialog_command(platform="nt")
    assert command is not None
    assert command[:2] == ["powershell", "-STA"]
    script = command[-1]
    assert "FolderBrowserDialog" in script
    assert "ShowDialog" in script
