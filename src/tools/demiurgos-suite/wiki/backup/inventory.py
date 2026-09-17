# -*- coding: utf-8 -*-
"""Inventory — the data root's REAL member set, discovered not listed (WU-7).

The candidate set is derived from ``os.scandir(data_root)`` plus a recursive
walk, never from a literal list of top-level names (REQ-BE-2, SC-BE-2.1). Two
tables decide what is taken:

* :data:`TOP_LEVEL_RULES` — the subtree policy for a member the data layout
  recognizes (``ideas/``, ``mundos/<World>/``, ``skills/``, ``plantillas/``,
  ``taller/``, ``estado/``, ``config/``). The table selects a WALK POLICY only:
  it never drives discovery and never rewrites a member's case. A discovered
  member it does not recognize is still INCLUDED by default and reported as
  ``findings: unclassified_top_level`` (REQ-CDL-2, SC-CDL-2.2), so a new
  top-level folder is never silently dropped and a new SUBfolder of a known
  member is included by construction.
* :data:`EXCLUSION_RULES` — the explicit, enumerable exclusion table
  (world-trash content, import spool, probes, VCS / code-index / virtualenv
  directories, mount residue, SQLite sidecars, the two operational DBs, the
  out-of-scope archive, and secrets). Every match is recorded on
  :attr:`Inventory.excluded` with a reason string, and the match is made HERE by
  rule — no call site special-cases a path (REQ-BE-1, SC-BE-1.3).

Case-collision detection (two siblings whose NFC + ``casefold()`` forms match)
is deliberately NOT here: that is WU-7b, and this module must not resolve a
spelling on its own (REQ-CDL-2.1). ``canonical_case`` is therefore the
NFC-normalized name exactly as discovered — the inventory never invents one.
"""

from __future__ import annotations

import fnmatch
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SubtreeRule:
    """Walk policy for one recognized top-level member (REQ-BE-2).

    ``subtree`` is the human-readable scope label from the design; ``sqlite_only``
    selects the narrow walk (direct ``*.sqlite3`` files) used by the ``estado/``
    rule so non-DB content beside it is never staged.
    """

    member: str
    subtree: str
    sqlite_only: bool = False


#: Recognized members -> walk policy. This does NOT drive discovery or inclusion:
#: a member absent here is still included by default (SC-BE-2.1).
TOP_LEVEL_RULES: tuple[SubtreeRule, ...] = (
    SubtreeRule(member="ideas", subtree="ideas/*"),
    SubtreeRule(member="mundos", subtree="mundos/<World>/*"),
    SubtreeRule(member="skills", subtree="skills/*"),
    SubtreeRule(member="plantillas", subtree="plantillas/*"),
    SubtreeRule(member="taller", subtree="data/methodology"),
    SubtreeRule(member="estado", subtree="data/*.sqlite3", sqlite_only=True),
    SubtreeRule(member="config", subtree="config/* (no secrets)"),
)


@dataclass(frozen=True)
class ExclusionRule:
    """One row of the exclusion table (REQ-BE-1, SC-BE-1.3).

    ``scope="subtree"`` matches the relative path exactly or as a directory
    prefix; ``scope="name"`` globs the basename anywhere in the tree.
    """

    pattern: str
    reason: str
    scope: str = "name"


#: The explicit exclusion table. Every match is surfaced on ``excluded[]`` with
#: its reason, so the manifest is self-explaining and an exclusion can never
#: vanish silently.
EXCLUSION_RULES: tuple[ExclusionRule, ...] = (
    ExclusionRule("data/world-trash", "excluded:world-trash-content", "subtree"),
    ExclusionRule("data/import-spool", "excluded:import-spool-transient", "subtree"),
    ExclusionRule("data/probes", "excluded:probes-regenerable", "subtree"),
    ExclusionRule("_archivo_produccion", "excluded:out-of-scope-archive", "subtree"),
    ExclusionRule(".git", "excluded:vcs-metadata"),
    ExclusionRule(".codegraph", "excluded:code-index-regenerable"),
    ExclusionRule(".venv", "excluded:virtualenv-code"),
    ExclusionRule(".fuse_hidden*", "excluded:mount-residue"),
    ExclusionRule("*.sqlite3-wal", "excluded:sqlite-sidecar-wal"),
    ExclusionRule("*.sqlite3-shm", "excluded:sqlite-sidecar-shm"),
    ExclusionRule("conversation-memory.sqlite3", "excluded:conversation-memory-ttl"),
    ExclusionRule("import-jobs.sqlite3", "excluded:import-jobs-operational"),
    ExclusionRule(".secrets", "excluded:secrets-never-backed-up", "subtree"),
    ExclusionRule(".env", "excluded:secrets-never-backed-up"),
    ExclusionRule(".env.*", "excluded:secrets-never-backed-up"),
    ExclusionRule("*.key", "excluded:secrets-never-backed-up"),
    ExclusionRule("*.pem", "excluded:secrets-never-backed-up"),
    ExclusionRule("credentials*", "excluded:secrets-never-backed-up"),
)


@dataclass(frozen=True)
class TopLevelMember:
    """One discovered top-level member, with the rule that matched it, if any.

    ``canonical_case`` is the NFC-normalized name as discovered; case collision
    detection (WU-7b) is the only place a spelling is ever questioned.
    """

    name: str
    canonical_case: str
    kind: str
    rule: SubtreeRule | None


@dataclass(frozen=True)
class ExcludedPath:
    """A path the rules excluded, with the reason that matched it."""

    path: str
    reason: str


@dataclass(frozen=True)
class Finding:
    """A non-fatal observation about the inventory (``kind`` + ``paths``)."""

    kind: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Inventory:
    """The discovered member set: included paths, exclusions and findings."""

    root: Path
    top_level: tuple[TopLevelMember, ...]
    included: tuple[str, ...]
    excluded: tuple[ExcludedPath, ...]
    findings: tuple[Finding, ...]


def classify_member(name: str) -> SubtreeRule | None:
    """The walk policy for *name*, or ``None`` when it is unrecognized.

    Matching is case-insensitive so a differently-cased name still receives the
    right policy; the member's own spelling is never rewritten here.
    """
    folded = unicodedata.normalize("NFC", name).casefold()
    for rule in TOP_LEVEL_RULES:
        if rule.member.casefold() == folded:
            return rule
    return None


def match_exclusion(relative_path: str) -> str | None:
    """The reason *relative_path* is excluded, or ``None`` when it is taken.

    The whole table is consulted by rule — callers never special-case a path.
    """
    normalized = unicodedata.normalize("NFC", relative_path).replace("\\", "/")
    base = normalized.rsplit("/", 1)[-1]
    for rule in EXCLUSION_RULES:
        if rule.scope == "subtree":
            if normalized == rule.pattern or normalized.startswith(rule.pattern + "/"):
                return rule.reason
        elif fnmatch.fnmatch(base, rule.pattern):
            return rule.reason
    return None


def discover_top_level(data_root: Path) -> tuple[TopLevelMember, ...]:
    """Discover the top-level members with ``os.scandir`` — never a literal list."""
    members: list[TopLevelMember] = []
    for raw_name, is_dir in _sorted_children(data_root):
        name = unicodedata.normalize("NFC", raw_name)
        members.append(TopLevelMember(
            name=name,
            canonical_case=name,
            kind="dir" if is_dir else "file",
            rule=classify_member(name),
        ))
    return tuple(members)


def build_inventory(data_root: Path) -> Inventory:
    """Build the inventory of *data_root* from its real contents (WU-7)."""
    root = Path(data_root)
    top_level = discover_top_level(root)
    included: list[str] = []
    excluded: list[ExcludedPath] = []
    findings: list[Finding] = []

    for member in top_level:
        reason = match_exclusion(member.name)
        if reason is not None:
            excluded.append(ExcludedPath(member.name, reason))
            continue
        if member.rule is None:
            findings.append(Finding("unclassified_top_level", (member.name,)))
        included.append(member.name)
        if member.kind == "file":
            continue
        if member.rule is not None and member.rule.sqlite_only:
            _walk_sqlite_only(root, member.name, included, excluded)
        else:
            _walk_recursive(root, member.name, included, excluded)

    return Inventory(
        root=root,
        top_level=top_level,
        included=tuple(sorted(included)),
        excluded=tuple(sorted(excluded, key=lambda entry: entry.path)),
        findings=tuple(findings),
    )


def _is_dir(entry: os.DirEntry[str]) -> bool:
    """Directory test that reports an unreadable entry as a file, never drops it."""
    try:
        return entry.is_dir()
    except OSError:
        return False


def _sorted_children(directory: Path) -> list[tuple[str, bool]]:
    """``(name, is_dir)`` for *directory*, sorted; ``[]`` when it is unreadable."""
    entries: list[tuple[str, bool]] = []
    try:
        with os.scandir(directory) as scan:
            for entry in scan:
                entries.append((entry.name, _is_dir(entry)))
    except OSError:
        return []
    entries.sort(key=lambda item: item[0])
    return entries


def _walk_recursive(
    data_root: Path,
    relative_dir: str,
    included: list[str],
    excluded: list[ExcludedPath],
) -> None:
    """Take every entry under a known member except the exclusion table's."""
    for name, is_dir in _sorted_children(data_root / relative_dir):
        relative = f"{relative_dir}/{name}"
        reason = match_exclusion(relative)
        if reason is not None:
            excluded.append(ExcludedPath(relative, reason))
            continue
        included.append(relative)
        if is_dir:
            _walk_recursive(data_root, relative, included, excluded)


def _walk_sqlite_only(
    data_root: Path,
    relative_dir: str,
    included: list[str],
    excluded: list[ExcludedPath],
) -> None:
    """Take only direct ``*.sqlite3`` files under a sqlite-only member."""
    for name, is_dir in _sorted_children(data_root / relative_dir):
        relative = f"{relative_dir}/{name}"
        reason = match_exclusion(relative)
        if reason is None and not is_dir and fnmatch.fnmatch(name, "*.sqlite3"):
            included.append(relative)
            continue
        excluded.append(ExcludedPath(relative, reason or "excluded:estado-not-sqlite"))
