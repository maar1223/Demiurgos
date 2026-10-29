# -*- coding: utf-8 -*-
"""Open the operating system's folder dialog, from the server (step 5).

Why here and not in the browser: a web page cannot hand the server an absolute
folder path. ``<input type="file">`` uploads byte CONTENT (that is what the
importer and the chat attachments use), while choosing a destination needs the
server to know a path and to write there without uploading gigabytes.

The server does run on the machine the author is sitting at, so it can open the
system dialog itself: ``zenity`` on a POSIX desktop and a PowerShell
``FolderBrowserDialog`` on Windows. When neither is available — headless server,
remote access — the caller must fall back to the clickable suggestions plus the
manual path, and this module says so instead of failing obscurely.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Sequence

#: A dialog is a human action: five minutes, then we give up and say so.
DIALOG_TIMEOUT_SECONDS = 300

#: The window title shown by the dialog. Kept plain: every platform escapes it
#: differently and a quote in it would break the command line.
TITLE = "Elegir carpeta para tu contenido"


class DialogUnavailable(RuntimeError):
    """No native folder dialog can be opened on this host."""


class DialogFailed(RuntimeError):
    """The dialog exists but could not answer (it crashed, or it timed out)."""


def dialog_command(
    *, platform: str | None = None, initial: str | None = None
) -> list[str] | None:
    """The command that opens a folder dialog here, or ``None``.

    Kept pure and injectable: the same function answers for both platforms in
    the suite, without spawning anything.
    """
    system = platform if platform is not None else os.name
    if system == "nt":
        if shutil.which("powershell") is None:
            return None
        script = (
            "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$d.Description = '{TITLE}'; $d.ShowNewFolderButton = $true; "
            + (f"$d.SelectedPath = '{initial}'; " if initial else "")
            + "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
            "{ [Console]::Out.Write($d.SelectedPath) } else { exit 1 }"
        )
        return ["powershell", "-STA", "-NoProfile", "-NonInteractive", "-Command", script]

    for tool in ("zenity", "kdialog", "qarma"):
        if shutil.which(tool) is None:
            continue
        if tool == "zenity":
            command = ["zenity", "--file-selection", "--directory", f"--title={TITLE}"]
            if initial:
                command.append(f"--filename={initial.rstrip('/')}/")
            return command
        if tool == "kdialog":
            command = ["kdialog", "--getexistingdirectory"]
            if initial:
                command.append(str(initial))
            command.append("--title")
            command.append(TITLE)
            return command
        command = ["qarma", "--file-selection", "--directory", f"--title={TITLE}"]
        if initial:
            command.append(f"--filename={initial.rstrip('/')}/")
        return command
    return None


Runner = Callable[[Sequence[str], int], subprocess.CompletedProcess]


def _default_run(command: Sequence[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 — a fixed argv, never a shell
        list(command),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def pick_directory(
    *,
    initial: str | Path | None = None,
    platform: str | None = None,
    run: Runner | None = None,
    timeout: int = DIALOG_TIMEOUT_SECONDS,
) -> Path | None:
    """Open the dialog and return the chosen folder, or ``None`` if cancelled.

    Raises :class:`DialogUnavailable` when this host has no dialog, and
    :class:`DialogFailed` when it exists but did not answer — the caller must be
    able to tell "the author said no" from "this feature cannot work here".
    """
    command = dialog_command(
        platform=platform, initial=None if initial is None else str(initial)
    )
    if command is None:
        raise DialogUnavailable(
            "no native folder dialog is available on this host"
        )
    runner = run or _default_run
    try:
        result = runner(command, timeout)
    except subprocess.TimeoutExpired as exc:
        raise DialogFailed("the folder dialog did not answer in time") from exc
    except OSError as exc:
        raise DialogFailed(f"the folder dialog could not start: {exc}") from exc

    if result.returncode == 1:
        return None
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        raise DialogFailed(detail or f"the folder dialog exited {result.returncode}")
    chosen = (result.stdout or "").strip()
    if not chosen:
        return None
    return Path(chosen).expanduser()


def is_available(*, platform: str | None = None) -> bool:
    """Whether a dialog can be opened here at all."""
    return dialog_command(platform=platform) is not None
