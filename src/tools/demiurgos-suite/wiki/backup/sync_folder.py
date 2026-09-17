# -*- coding: utf-8 -*-
"""Sync-folder discovery and streaming/mirror classification (WU-12).

Two responsibilities, both about TELLING THE TRUTH before a byte is written:

* :func:`discover_candidates` SUGGESTS folders a synced client is likely to own,
  per platform. Suggestions are suggestions: none is used without the user
  confirming it, and the folder picker is always offered on every OS
  (REQ-SF-1). Discovery never hardcodes a destination path, drive letter or
  provider name — every path comes from an injected environment, registry
  reader, home directory or drive-type probe.
* :func:`classify_target` reports whether a chosen folder is a STREAMING/virtual
  location (unsynced changes live in a clearable cache — block) or a MIRRORED
  local copy (accept). It only fires a verdict on a VERIFIED signal; everything
  else is ``unknown`` and is accepted with an informational note, because a
  heuristic guess must never block (REQ-SF-3, SC-SF-3.3).

**Every OS touchpoint is injected** — ``environ``, ``registry_reader``,
``drive_type``, ``platform``, ``home`` and ``mounts_reader`` — so both the
Windows logic and the Linux mount-table signal are fully unit-testable without a
real registry, drive type or mount, and the module is hermetic under test.

**UNVERIFIED signals (deliberately NOT implemented as verified):**

* OneDrive Files On-Demand placeholder attributes
  (``FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS``, ``0x400000``): never inspected.
* Dropbox Smart Sync and iCloud "Optimize Mac Storage" placeholder states: not
  measured, so no signal.
* The real ``GetDriveTypeW`` value reported for the Google Drive virtual drive:
  not measured. The code path below is written against ``DRIVE_REMOTE`` plus a
  ``My Drive``/``Shared drives`` marker at the drive root; if the real value
  differs the signal simply does not fire and the target stays ``unknown``
  (a safe false-negative, never a false "streaming" verdict).

Three signals are treated as verified: the ``DRIVE_REMOTE`` + drive-root marker
pair, a bounded walk whose ``stat()`` raises for a not-materialized entry, and —
on Linux — a mount table whose longest matching mount point for the target is a
``fuse``/``fuse.*`` filesystem, because a FUSE mount is an illusion over the
network, not local storage. OneDrive's ``%OneDrive%`` being a reparse point is a
usability signal (fall back to the registry), not a streaming verdict.

**Honest copy (REQ-SF-4).** The status/copy surface here reports the LOCAL write
only. :data:`FORBIDDEN_DELIVERY_VOCABULARY` (es-ES and en) and
:func:`find_dishonest_status_keys` gate every string and payload key so no
upload, sync-state or cloud field can be added silently. The live
``/api/backup/status`` response is WU-14's router; this module owns the constants
and the builder it will consume.
"""

from __future__ import annotations

import os
import string
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from backup.transport.base import TargetCapabilities

# Windows ``GetDriveTypeW`` codes, as the injected ``drive_type`` probe returns
# them. Only FIXED and REMOTE drive a verdict; the rest are documented so a probe
# can pass a raw value without this module inventing a mapping.
DRIVE_FIXED = 3
DRIVE_REMOTE = 4

MODE_MIRRORED = "mirrored"
MODE_STREAMING = "streaming"
MODE_UNKNOWN = "unknown"

PROVIDER_ONEDRIVE = "onedrive"
PROVIDER_GOOGLE_DRIVE = "google_drive"
PROVIDER_ICLOUD = "icloud"
PROVIDER_UNKNOWN = "unknown"

SOURCE_ENV = "env"
SOURCE_REGISTRY = "registry"
SOURCE_HEURISTIC = "heuristic"
SOURCE_USER = "user"

CONFIDENCE_VERIFIED = "verified"
CONFIDENCE_HEURISTIC = "heuristic"

#: The picker is a UI guarantee, not a discovery result: it is offered on EVERY
#: OS, including the picker-only platforms where discovery returns no candidate.
PICKER_ALWAYS_OFFERED = True

#: The variables a Windows OneDrive install may expose, in suggestion order.
ONEDRIVE_ENV_VARS = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
#: The two directory names that identify Google Drive's virtual-drive root.
DRIVE_MARKER_NAMES = ("My Drive", "Shared drives")
#: Directory names the Google Drive heuristic looks for.
GOOGLE_DRIVE_DIR_NAMES = ("My Drive", "Google Drive")
#: The iCloud Drive location the macOS heuristic offers as a suggestion.
MACOS_ICLOUD_RELPATH = ("Library", "Mobile Documents", "com~apple~CloudDocs")
#: Where macOS mounts Google Drive for Desktop.
MACOS_VOLUMES_ROOT = Path("/Volumes")
MACOS_GOOGLE_DRIVE_GLOB = "GoogleDrive*/My Drive"

#: A bounded walk never reads more than this many entries (REQ-SF-3).
WALK_LIMIT = 200

#: The mount table the production seam reads to detect a Linux FUSE mount.
#: It is an OS path, not author data, and the reader returns nothing when absent.
MOUNTS_PATH = Path("/proc/mounts")
#: A FUSE filesystem is the streaming shape on Linux. ``fuseblk`` (NTFS-3G) is a
#: real block-backed local mount and is deliberately NOT a FUSE fstype here.
FUSE_FSTYPE = "fuse"

#: The remedy shown when a verified streaming target is blocked (REQ-SF-3.1).
#: It is a Windows remedy: the "Mirroring" setting belongs to Google Drive for
#: Desktop and has no equivalent on Linux.
MIRRORING_REMEDY = "switch Google Drive for Desktop to Mirroring"
#: The remedy for the Linux FUSE-mount signal. "Mirroring" does not exist on
#: Linux and a FUSE mount is not a sync client, so the operator must pick a real
#: one or a folder that is genuinely local.
LINUX_STREAMING_REMEDY = (
    "this folder is a network-backed FUSE mount; use a real sync client such as "
    "abraunegg/onedrive, or choose a folder that is genuinely local storage"
)
MODE_UNKNOWN_NOTE = (
    "target mode is unknown (no verified signal) — accepted as a local folder"
)

REASON_STREAMING = "verified streaming/virtual target"
REASON_NOT_A_DIRECTORY = "target is missing or not a directory"
REASON_NOT_WRITABLE = "target directory is not writable"

# ``FILE_ATTRIBUTE_REPARSE_POINT`` (0x400) flags a reparse point on Windows. It is
# used ONLY to decide whether an env value is unusable, never as a streaming
# signal. The placeholder attribute (0x400000) is deliberately absent.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class DishonestCopyError(ValueError):
    """A copy string claims a delivery the system cannot verify (REQ-SF-4)."""


@dataclass(frozen=True)
class Candidate:
    """A suggested destination folder and the provenance of the suggestion.

    ``source`` is one of :data:`SOURCE_ENV`, :data:`SOURCE_REGISTRY`,
    :data:`SOURCE_HEURISTIC` or :data:`SOURCE_USER`; ``confidence`` is
    :data:`CONFIDENCE_VERIFIED` (a real location the platform reports) or
    :data:`CONFIDENCE_HEURISTIC` (a guess). A manually picked folder is always
    ``provider="unknown"``, ``source="user"``, ``confidence="heuristic"`` and is
    never presented as sync-verified.
    """

    path: Path
    provider: str
    source: str
    confidence: str

    def to_dict(self) -> dict[str, str]:
        """The persistence record: path, provider, source, confidence."""
        return {
            "path": str(self.path),
            "provider": self.provider,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class TargetDecision:
    """The warn/block verdict for a chosen target, from its capabilities.

    ``accepted`` is the write gate: when ``False`` no run may publish. A
    streaming block carries the :data:`MIRRORING_REMEDY`; an unknown mode is
    accepted WITH a note; a mirrored target is accepted silently.
    """

    accepted: bool
    capabilities: TargetCapabilities
    remedy: str | None = None
    note: str | None = None
    reason: str | None = None


# --------------------------------------------------------------------------
# Injected filesystem seams
# --------------------------------------------------------------------------
def default_drive_type(path: Path) -> int | None:
    """Real ``GetDriveTypeW`` on Windows; ``None`` on every other platform.

    This is the production half of the ``drive_type`` seam: tests inject a fake
    probe instead, so no test ever reads a real drive type.
    """
    if sys.platform != "win32":  # pragma: no cover - platform dependent
        return None
    try:  # pragma: no cover - Windows only
        import ctypes

        return int(ctypes.windll.kernel32.GetDriveTypeW(str(path)))
    except Exception:  # pragma: no cover - defensive
        return None


def default_mounts_reader() -> list[str]:
    """Read the real mount table (``/proc/mounts``); ``[]`` when it is absent.

    This is the production half of the ``mounts_reader`` seam: it reads the
    host's table for the Linux FUSE-mount signal. Tests inject a fake table
    instead, so no test ever mounts FUSE or depends on the host's mounts.
    """
    try:
        return MOUNTS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


class _ScandirEntry:
    """Adapter exposing the injected-walk contract over an ``os.DirEntry``.

    ``follow_symlinks=False`` keeps a broken symlink from being read as a
    not-materialized placeholder: its ``lstat`` succeeds, so it is not a
    streaming signal.
    """

    __slots__ = ("name", "_entry")

    def __init__(self, entry: os.DirEntry[str]) -> None:
        self.name = entry.name
        self._entry = entry

    def is_dir(self) -> bool:
        return self._entry.is_dir(follow_symlinks=False)

    def stat(self) -> os.stat_result:
        return self._entry.stat(follow_symlinks=False)


def bounded_walk(root: Path, limit: int = WALK_LIMIT) -> Iterable[Any]:
    """Yield at most *limit* entries under *root*, depth-first.

    A walk that cannot list a directory yields nothing for it rather than
    failing: discovery is advisory and must never raise at the UI. Entries are
    duck-typed (``.name``, ``.is_dir()``, ``.stat()``) so a test can inject its
    own view without touching a real filesystem.
    """
    if not root.is_dir():
        return
    stack = [root]
    produced = 0
    while stack and produced < limit:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            if produced >= limit:
                return
            produced += 1
            yield _ScandirEntry(entry)
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
            except OSError:
                continue


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------
def _normalize_platform(value: str | None) -> str:
    """Map ``sys.platform``-style values onto ``windows``/``macos``/``linux``."""
    raw = (value or sys.platform).lower()
    if raw.startswith("win") or raw in {"cygwin", "msys"}:
        return "windows"
    if raw.startswith("darwin") or raw in {"mac", "macos"}:
        return "macos"
    return "linux"


def _is_reparse_point(path: Path) -> bool:
    """True when *path* is a symlink or carries the Windows reparse attribute."""
    try:
        if path.is_symlink():
            return True
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _usable_directory(path: Path) -> bool:
    """A real, non-reparse directory — the only env/registry value worth keeping."""
    try:
        return path.is_dir() and not _is_reparse_point(path)
    except OSError:
        return False


def _dedupe(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Drop repeated paths, keeping the first (highest-confidence) occurrence."""
    seen: set[str] = set()
    out: list[Candidate] = []
    for candidate in candidates:
        key = os.path.normcase(str(candidate.path))
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _onedrive_candidates(
    environ: Mapping[str, str],
    registry_reader: Callable[[], Iterable[str]] | None,
    home: Path,
) -> list[Candidate]:
    """OneDrive: env values first, registry ``UserFolder`` as the fallback.

    A value that is absent, a reparse point, or not a directory cannot be used,
    so when no env value qualifies the injected ``registry_reader`` resolves the
    real location from ``HKCU\\Software\\Microsoft\\OneDrive\\Accounts\\*``
    (REQ-SF-2, SC-SF-2.1).
    """
    found: list[Candidate] = []
    for variable in ONEDRIVE_ENV_VARS:
        raw = environ.get(variable)
        if not raw:
            continue
        path = Path(raw).expanduser()
        if _usable_directory(path):
            found.append(
                Candidate(path, PROVIDER_ONEDRIVE, SOURCE_ENV, CONFIDENCE_VERIFIED)
            )
    if found:
        return _dedupe(found)
    if registry_reader is not None:
        for raw in registry_reader() or ():
            path = Path(raw).expanduser()
            if _usable_directory(path):
                found.append(
                    Candidate(
                        path, PROVIDER_ONEDRIVE, SOURCE_REGISTRY, CONFIDENCE_VERIFIED
                    )
                )
    return _dedupe(found)


def _windows_fixed_roots(drive_type: Callable[[Path], int | None]) -> list[Path]:
    """The fixed drive roots a bounded Google Drive scan may inspect.

    The letter is built at runtime from the alphabet — no drive letter is
    hardcoded anywhere in this module (REQ-SF-1, SC-SF-1.2).
    """
    if drive_type is None:
        return []
    roots: list[Path] = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:{os.sep}")
        try:
            if drive_type(root) == DRIVE_FIXED:
                roots.append(root)
        except OSError:
            continue
    return roots


def _google_drive_candidates(
    drive_type: Callable[[Path], int | None], home: Path
) -> list[Candidate]:
    """Google Drive heuristics: home-relative names plus a bounded drive scan.

    Every candidate is ``heuristic`` and therefore never auto-selected
    (SC-SF-2.2); the user confirms it or picks another folder.
    """
    candidates: list[Candidate] = []
    bases = [
        home / "My Drive",
        home / "Google Drive",
        home / "Google Drive" / "My Drive",
    ]
    for root in _windows_fixed_roots(drive_type):
        bases.extend(root / name for name in GOOGLE_DRIVE_DIR_NAMES)
    for base in bases:
        if base.is_dir():
            candidates.append(
                Candidate(
                    base,
                    PROVIDER_GOOGLE_DRIVE,
                    SOURCE_HEURISTIC,
                    CONFIDENCE_HEURISTIC,
                )
            )
    return candidates


def _windows_candidates(
    environ: Mapping[str, str],
    registry_reader: Callable[[], Iterable[str]] | None,
    drive_type: Callable[[Path], int | None],
    home: Path,
) -> list[Candidate]:
    """Windows discovery: OneDrive first, then Google Drive heuristics only.

    Dropbox, Nextcloud, iCloud and every other client are picker-only here —
    they expose no documented location, so no candidate is invented (REQ-SF-2).
    """
    candidates = _onedrive_candidates(environ, registry_reader, home)
    candidates.extend(_google_drive_candidates(drive_type, home))
    return _dedupe(candidates)


def _macos_candidates(environ: Mapping[str, str], home: Path) -> list[Candidate]:
    """macOS heuristics: Google Drive mounts and the iCloud Drive container.

    Both are guesses, so both are ``heuristic`` and never auto-selected. The
    ``/Volumes`` glob is skipped when the directory does not exist, so the scan
    is a no-op off macOS rather than a touch of an unrelated path.
    """
    candidates: list[Candidate] = []
    if MACOS_VOLUMES_ROOT.is_dir():
        for match in sorted(MACOS_VOLUMES_ROOT.glob(MACOS_GOOGLE_DRIVE_GLOB)):
            if match.is_dir():
                candidates.append(
                    Candidate(
                        match,
                        PROVIDER_GOOGLE_DRIVE,
                        SOURCE_HEURISTIC,
                        CONFIDENCE_HEURISTIC,
                    )
                )
    icloud = home.joinpath(*MACOS_ICLOUD_RELPATH)
    if icloud.is_dir():
        candidates.append(
            Candidate(icloud, PROVIDER_ICLOUD, SOURCE_HEURISTIC, CONFIDENCE_HEURISTIC)
        )
    for base in (home / "My Drive", home / "Google Drive"):
        if base.is_dir():
            candidates.append(
                Candidate(
                    base,
                    PROVIDER_GOOGLE_DRIVE,
                    SOURCE_HEURISTIC,
                    CONFIDENCE_HEURISTIC,
                )
            )
    return candidates


def discover_candidates(
    *,
    environ: Mapping[str, str] | None = None,
    registry_reader: Callable[[], Iterable[str]] | None = None,
    drive_type: Callable[[Path], int | None] | None = None,
    platform: str | None = None,
    home: Path | None = None,
) -> list[Candidate]:
    """Suggest synced folders for *platform*, with every touchpoint injected.

    Windows reads the OneDrive env vars and falls back to the registry; Google
    Drive gets heuristics only; every other client is picker-only. macOS gets
    heuristics; Linux gets no candidate because every OneDrive/Google Drive
    desktop client there is third-party and must be chosen by the operator —
    there is no deferred transport to own it. The recommended Linux client is the
    ``abraunegg/onedrive`` sync client; a FUSE mount (``onedriver``) is the
    streaming shape :func:`classify_target` rejects, not a sync replacement.
    Whatever is returned — including an empty list — the caller MUST still offer
    the picker, so any user-chosen folder works (REQ-SF-1).

    ``drive_type=None`` disables the bounded fixed-drive scan; production passes
    :func:`default_drive_type`, and tests inject a fake to stay hermetic.
    """
    environment = os.environ if environ is None else environ
    resolved_home = Path(home) if home is not None else Path.home()
    probe = default_drive_type if drive_type is None else drive_type
    system = _normalize_platform(platform)

    if system == "windows":
        return _windows_candidates(environment, registry_reader, probe, resolved_home)
    if system == "macos":
        return _macos_candidates(environment, resolved_home)
    return []


def manual_candidate(folder: str | os.PathLike[str]) -> Candidate:
    """Record a folder the user picked: ``unknown``/``user``/``heuristic``.

    A manually picked folder requires explicit UI confirmation and is never
    presented as sync-verified (REQ-SF-2, REQ-SF-4).
    """
    return Candidate(Path(folder), PROVIDER_UNKNOWN, SOURCE_USER, CONFIDENCE_HEURISTIC)


def requires_confirmation(candidate: Candidate) -> bool:
    """Every suggestion needs the user's explicit confirmation (REQ-SF-2)."""
    return True


def is_auto_selectable(candidate: Candidate) -> bool:
    """Whether a candidate may be PRE-SELECTED as a suggestion.

    Only a platform-reported (verified) candidate qualifies, and even then the
    destination is not used without confirmation. A heuristic — Google Drive,
    macOS heuristics, or any manual pick — is never auto-selected (SC-SF-2.2).
    """
    return (
        candidate.confidence == CONFIDENCE_VERIFIED
        and candidate.source != SOURCE_USER
    )


# --------------------------------------------------------------------------
# Streaming vs mirror classification
# --------------------------------------------------------------------------
def _drive_kind(
    target: Path, drive_type: Callable[[Path], int | None] | None
) -> int | None:
    """The injected drive type for *target*, or ``None`` when unavailable."""
    if drive_type is None:
        return None
    try:
        return drive_type(target)
    except OSError:
        return None


def _drive_root(target: Path) -> Path:
    """The volume root of *target* (a Windows drive root, or ``/`` on POSIX)."""
    anchor = target.anchor
    return Path(anchor) if anchor else Path(os.sep)


def _iter_walk(
    walk: Callable[[Path, int], Iterable[Any]], root: Path
) -> Iterable[Any]:
    try:
        return walk(root, WALK_LIMIT)
    except OSError:
        return ()


def _drive_root_has_markers(
    target: Path, walk: Callable[[Path, int], Iterable[Any]]
) -> bool:
    """True when the volume root holds the Drive markers (verified signal a)."""
    for entry in _iter_walk(walk, _drive_root(target)):
        if entry.name not in DRIVE_MARKER_NAMES:
            continue
        try:
            if entry.is_dir():
                return True
        except OSError:
            continue
    return False


def _walk_signal(target: Path, walk: Callable[[Path, int], Iterable[Any]]) -> str:
    """``streaming`` on an unstattable entry, else ``clean``/``empty``.

    A ``stat()`` that raises means the entry is a not-materialized placeholder —
    a verified streaming signal (REQ-SF-3).
    """
    saw_entry = False
    for entry in _iter_walk(walk, target):
        saw_entry = True
        try:
            entry.stat()
        except OSError:
            return MODE_STREAMING
    return "clean" if saw_entry else "empty"


# POSIX mount tables escape whitespace and backslashes in every field
# (mount(8), fstab(5)); a mount point with a space arrives as ``\040``.
_MOUNT_UNESCAPES: tuple[tuple[str, str], ...] = (
    ("\\040", " "),
    ("\\011", "\t"),
    ("\\012", "\n"),
    ("\\134", "\\"),
)


def _unescape_mount_field(field: str) -> str:
    """Decode the octal escapes a mount table uses inside a field."""
    for escaped, plain in _MOUNT_UNESCAPES:
        field = field.replace(escaped, plain)
    return field


def _mount_entries(lines: Iterable[str]) -> list[tuple[str, str]]:
    """``(mount_point, fstype)`` pairs from ``/proc/mounts``-shaped lines.

    A line without at least the three standard fields is skipped rather than
    guessed at: the table is advisory, so a malformed entry can only fail to
    fire the signal, never invent one.
    """
    entries: list[tuple[str, str]] = []
    for line in lines:
        fields = line.split()
        if len(fields) < 3:
            continue
        entries.append((_unescape_mount_field(fields[1]), fields[2]))
    return entries


def _mount_point_of(
    absolute: str, entries: Iterable[tuple[str, str]]
) -> tuple[str, str] | None:
    """The longest mount point containing *absolute*, with its filesystem type.

    Longest-prefix matching handles nested mounts: the innermost filesystem is
    the one the target actually lives on. The root mount normalizes to the empty
    prefix, which every absolute path starts with.
    """
    best: tuple[str, str] | None = None
    for mount_point, fstype in entries:
        prefix = mount_point.rstrip("/")
        if absolute == prefix or absolute.startswith(prefix + "/"):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, fstype)
    return best


def _is_fuse_fstype(fstype: str) -> bool:
    """True for ``fuse`` and ``fuse.*``; ``False`` for ``fuseblk`` and others.

    ``fuseblk`` (NTFS-3G) and ``fusectl`` back a real local mount, so treating
    them as streaming would be a false positive, not a verified signal.
    """
    return fstype == FUSE_FSTYPE or fstype.startswith(FUSE_FSTYPE + ".")


def _fuse_mount_streaming(
    target: Path, mounts_reader: Callable[[], Iterable[str]] | None
) -> bool:
    """A VERIFIED streaming signal from the mount table (Linux FUSE); else ``False``.

    No heuristic: when the reader is unavailable, raises, returns nothing, or its
    longest match for *target* is not a FUSE filesystem, the signal does not fire.
    """
    reader = default_mounts_reader if mounts_reader is None else mounts_reader
    try:
        lines = list(reader())
        absolute = os.path.abspath(os.fspath(target))
    except OSError:
        return False
    entry = _mount_point_of(absolute, _mount_entries(lines))
    return entry is not None and _is_fuse_fstype(entry[1])


def _classify_mode(
    target: Path,
    drive_type: Callable[[Path], int | None] | None,
    walk: Callable[[Path, int], Iterable[Any]],
    mounts_reader: Callable[[], Iterable[str]] | None = None,
) -> str:
    """The mode verdict from verified signals only; ``unknown`` otherwise."""
    if _fuse_mount_streaming(target, mounts_reader):
        return MODE_STREAMING
    kind = _drive_kind(target, drive_type)
    if kind == DRIVE_REMOTE and _drive_root_has_markers(target, walk):
        return MODE_STREAMING
    signal = _walk_signal(target, walk)
    if signal == MODE_STREAMING:
        return MODE_STREAMING
    if kind == DRIVE_FIXED and signal == "clean":
        return MODE_MIRRORED
    return MODE_UNKNOWN


def _is_writable_directory(target: Path) -> bool:
    try:
        if not target.is_dir():
            return False
        return os.access(target, os.W_OK)
    except OSError:
        return False


def classify_target(
    path: Path,
    *,
    drive_type: Callable[[Path], int | None] | None = None,
    walk: Callable[[Path, int], Iterable[Any]] | None = None,
    mounts_reader: Callable[[], Iterable[str]] | None = None,
) -> TargetCapabilities:
    """Classify *path* as ``mirrored``, ``streaming`` or ``unknown``.

    ``streaming`` requires a VERIFIED signal — ``DRIVE_REMOTE`` plus a drive-root
    marker, a bounded walk hitting an unstattable entry, or the Linux mount table
    showing a ``fuse``/``fuse.*`` filesystem on the target's longest mount point.
    ``mirrored`` requires ``DRIVE_FIXED`` plus a bounded walk that reads every
    entry. Anything else is ``unknown``: the unmeasured signals listed in the
    module docstring never produce a verdict, and a heuristic guess never blocks
    (SC-SF-3.3).

    A verified streaming target reports ``writable=False``, so no run can publish
    into a cache that may be cleared or corrupted. ``same_volume_as_data_root``
    stays ``False`` here — the data root is not part of this seam.

    ``mounts_reader`` defaults to reading the real ``/proc/mounts``; a test
    injects a fake table, so no test mounts FUSE or reads the host's mounts.
    """
    target = Path(path)
    mode = _classify_mode(target, drive_type, walk or bounded_walk, mounts_reader)
    writable = mode != MODE_STREAMING and _is_writable_directory(target)
    return TargetCapabilities(
        kind="folder",
        path=str(target),
        writable=writable,
        same_volume_as_data_root=False,
        mode_hint=mode,
    )


def evaluate_target(
    path: Path,
    *,
    drive_type: Callable[[Path], int | None] | None = None,
    walk: Callable[[Path, int], Iterable[Any]] | None = None,
    mounts_reader: Callable[[], Iterable[str]] | None = None,
) -> TargetDecision:
    """The warn/block policy for a target, ready to gate ``/api/backup/run``.

    * verified ``streaming`` — rejected, no bytes written, with a remedy that
      fits the verified signal;
    * ``mirrored`` — accepted silently;
    * ``unknown`` — accepted with an informational note;
    * missing / not-a-directory / not-writable — rejected with a specific reason.

    The remedy is signal-appropriate: the Linux FUSE-mount signal carries
    :data:`LINUX_STREAMING_REMEDY`, because "Mirroring" is a Google Drive for
    Desktop setting that does not exist on Linux. Every other streaming signal
    keeps the Windows :data:`MIRRORING_REMEDY`. Choosing by signal (not by an OS
    argument) also keeps the production call sites correct without passing one.

    ``classify_target`` uses the same signals, so the transport's ``probe()`` and
    this gate cannot disagree about a verified status.
    """
    target = Path(path)
    resolved_walk = walk or bounded_walk
    capabilities = classify_target(
        target,
        drive_type=drive_type,
        walk=resolved_walk,
        mounts_reader=mounts_reader,
    )
    if capabilities.mode_hint == MODE_STREAMING:
        remedy = (
            LINUX_STREAMING_REMEDY
            if _fuse_mount_streaming(target, mounts_reader)
            else MIRRORING_REMEDY
        )
        return TargetDecision(
            False, capabilities, remedy=remedy, reason=REASON_STREAMING
        )
    if not target.is_dir():
        return TargetDecision(False, capabilities, reason=REASON_NOT_A_DIRECTORY)
    if capabilities.writable:
        note = MODE_UNKNOWN_NOTE if capabilities.mode_hint == MODE_UNKNOWN else None
        return TargetDecision(True, capabilities, note=note)
    return TargetDecision(False, capabilities, reason=REASON_NOT_WRITABLE)


# --------------------------------------------------------------------------
# Honest copy gate (REQ-SF-4)
# --------------------------------------------------------------------------
#: Delivery claims the system cannot verify, in es-ES and en. None may appear in
#: a user-facing string or an API payload (SC-SF-4.2, SC-BUI-3.1).
FORBIDDEN_DELIVERY_VOCABULARY: tuple[str, ...] = (
    "respaldado en la nube",
    "respaldado en Drive",
    "sincronizado con la nube",
    "sincronizado en la nube",
    "subido a Drive",
    "backed up to the cloud",
    "backed up to Drive",
    "synced to the cloud",
    "synced to Drive",
    "uploaded to",
    "en la nube",
)

#: Status-payload keys that would imply a delivery Demiurgos cannot verify.
FORBIDDEN_STATUS_KEY_PREFIXES: tuple[str, ...] = ("upload", "cloud")
FORBIDDEN_STATUS_KEYS: tuple[str, ...] = ("sync_state",)


def find_forbidden_vocabulary(text: str) -> tuple[str, ...]:
    """Every forbidden delivery phrase present in *text* (case-insensitive)."""
    lowered = text.casefold()
    return tuple(
        term for term in FORBIDDEN_DELIVERY_VOCABULARY if term.casefold() in lowered
    )


def assert_honest_copy(text: str) -> None:
    """Raise :class:`DishonestCopyError` when *text* claims cloud delivery."""
    found = find_forbidden_vocabulary(text)
    if found:
        raise DishonestCopyError(
            "cloud-delivery vocabulary is forbidden: " + ", ".join(found)
        )


def find_dishonest_status_keys(payload: Any) -> tuple[str, ...]:
    """Every payload key that implies upload/sync/cloud state, recursively.

    Walks nested mappings and sequences so a delivery field cannot hide one
    level down (REQ-SF-4, SC-SF-4.1).
    """
    findings: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                name = str(key).casefold()
                if name.startswith(FORBIDDEN_STATUS_KEY_PREFIXES) or (
                    name in FORBIDDEN_STATUS_KEYS
                ):
                    findings.append(str(key))
                visit(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                visit(item)

    visit(payload)
    return tuple(findings)


def local_write_copy(
    folder: str | os.PathLike[str],
    *,
    written_at: str | None = None,
    language: str = "en",
) -> str:
    """The honest copy string: the LOCAL write only, in en or es.

    It says the folder is where Demiurgos wrote — never that a client uploaded
    or synced anything (REQ-SF-4, SC-BUI-3.1).
    """
    stamp = written_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if language == "es":
        return f"Escrito en {folder} — {stamp} UTC"
    return f"Written to {folder} — {stamp} UTC"


def build_local_write_status(
    *,
    destination: str | os.PathLike[str],
    written_at: str,
    status: str,
    current_entries: int,
) -> dict[str, Any]:
    """The local-write half of ``/api/backup/status`` — no delivery field.

    WU-14's router composes this with a candidate record. The shape is
    deliberately flat and closed: :func:`find_dishonest_status_keys` rejects any
    variant that grows an upload/sync/cloud field (REQ-SF-4, SC-SF-4.1).
    """
    return {
        "destination": str(destination),
        "written_at": written_at,
        "status": status,
        "current_entries": current_entries,
    }
