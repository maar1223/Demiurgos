# -*- coding: utf-8 -*-
"""Inventory — the data root's REAL member set, discovered not listed (WU-7).

The candidate set is derived from ``os.scandir(data_root)`` plus a recursive
walk, never from a literal list of top-level names (REQ-BE-2, SC-BE-2.1). Two
tables decide what is taken:

* :data:`TOP_LEVEL_RULES` — the subtree policy for a member the data layout
  recognizes (``ideas/``, ``mundos/<World>/``, ``skills/``, ``plantillas/``,
  ``data/``, ``config/``). The table selects a WALK POLICY only: it never drives
  discovery and never rewrites a member's case. A discovered member it does not
  recognize is still INCLUDED by default and reported as
  ``findings: unclassified_top_level`` (REQ-CDL-2, SC-CDL-2.2), so a new
  top-level folder is never silently dropped and a new SUBfolder of a known
  member is included by construction.
* :data:`EXCLUSION_RULES` — the explicit, enumerable exclusion table
  (world-trash content, import spool, probes, the ``data/`` secrets class — auth
  sessions, local machine state and process locks — VCS / code-index / virtualenv
  directories, the project's own source/tooling paths at the checkout root,
  installed dependency trees and tool caches, mount residue, SQLite
  sidecars, the two operational DBs, the out-of-scope archive, and secrets).
  Every match is recorded on :attr:`Inventory.excluded` with a reason string, and
  the match is made HERE by rule — no call site special-cases a path
  (REQ-BE-1, SC-BE-1.3).

**The ``data/`` folder mixes databases with secrets.** It holds the four
databases the backup owns, the two it must not take, author content under
``data/methodology/``, and operational material that must never leave the
machine (``sessions.json`` auth session hashes, ``local-state.json`` local
machine state, ``idea-capture.lock``). Because a narrow sqlite-only walk would
drop the author content, the folder is walked recursively and the operational
material is refused by a reasoned exclusion CLASS scoped to ``data/`` — each row
matches a role, so an equivalent new file is caught by the same rule.

Case-collision detection (WU-7b) lives here: :func:`detect_case_collisions`
compares TOP-LEVEL members by their NFC + ``casefold()`` key, and
:func:`build_inventory` ABORTS with :class:`CaseCollisionError` when any two
would collapse to one name on a case-insensitive destination (REQ-CDL-2,
SC-CDL-2.1). The scope is the top level, exactly as the spec words it ("one
canonical case per top-level name"); the motivating ``ideas/`` vs
``mundos/Ideas/`` pair sits at DIFFERENT levels, so it is not a top-level
collision and is not detected here. A same-level nested collision is caught
later by the transport's staged-path check (REQ-BE-9, SC-BE-9.1).
``canonical_case`` is still the NFC-normalized name exactly as discovered — the
inventory never invents a spelling.
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
#:
#: ``data/`` is the real operational member: the six SQLite stores resolve to
#: ``<data root>/data/<name>.sqlite3`` (import_store, co_creation_session_store,
#: guided_session_store, conversation_memory_store, world checkpoints,
#: idea-capture), and ``data/methodology/`` is author content that MUST be
#: staged. It is walked RECURSIVELY rather than sqlite-only, because a
#: sqlite-only walk would silently drop ``data/methodology/``. The secrets that
#: also live in this folder (auth sessions, local machine state, lock files) are
#: refused by :data:`EXCLUSION_RULES` instead — see the ``data/`` exclusion class.
#:
#: The former ``estado`` / ``taller`` rows named top-level members that do not
#: exist on disk: the real layout puts every store under ``data/``. Those dead
#: rows are replaced by this one. (The SDD spec/design/tasks artifacts still say
#: ``estado/``; the code is authoritative and the archive phase applies that
#: correction — see the note in the tests.)
TOP_LEVEL_RULES: tuple[SubtreeRule, ...] = (
    SubtreeRule(member="ideas", subtree="ideas/*"),
    SubtreeRule(member="mundos", subtree="mundos/<World>/*"),
    # `skills/` has no row here: it is excluded outright by EXCLUSION_RULES, so
    # no walk policy is ever consulted for it.
    SubtreeRule(member="plantillas", subtree="plantillas/*"),
    SubtreeRule(member="data", subtree="data/*"),
    SubtreeRule(member="config", subtree="config/* (no secrets)"),
)


@dataclass(frozen=True)
class ExclusionRule:
    """One row of the exclusion table (REQ-BE-1, SC-BE-1.3).

    ``scope`` selects how ``pattern`` is matched against a candidate path:

    * ``"subtree"`` — the relative path equals ``pattern`` or starts with it as a
      directory prefix.
    * ``"name"`` — the basename globs ``pattern`` anywhere in the tree.
    * ``"name_in_subtree"`` — the relative path sits under ``under`` AND its
      basename globs ``pattern``. This is the safe-by-construction scope for the
      ``data/`` secrets class: it can only ever match inside ``under``, so a
      same-named file elsewhere in the tree is untouched.
    * ``"top_level_name"`` — the relative path is a TOP-LEVEL entry (it carries
      no ``/``) AND its name globs ``pattern``. This is the safe-by-construction
      scope for the checkout's own root files (``README*``, ``start-*.ps1``): a
      same-named file inside a world is never matched, so author data survives.
    """

    pattern: str
    reason: str
    scope: str = "name"
    under: str = ""


#: The explicit exclusion table. Every match is surfaced on ``excluded[]`` with
#: its reason, so the manifest is self-explaining and an exclusion can never
#: vanish silently.
#:
#: The ``data/`` class (WARNING-2 fix) refuses the operational material that
#: shares the folder with the databases and author content. Each row matches a
#: ROLE, not a single filename, so an equivalent new file is caught by the same
#: rule: any auth-session document (``sessions.json`` today, a future
#: ``telegram-sessions.json``), any local machine-state document
#: (``local-state.json`` today), and any process lock (``idea-capture.lock``
#: today). The four databases the backup owns are NOT matched — they carry no
#: ``.json``/``.lock`` name and are sqlite files — while the two that must stay
#: out are refused by their own rows above.
EXCLUSION_RULES: tuple[ExclusionRule, ...] = (
    ExclusionRule("data/world-trash", "excluded:world-trash-content", "subtree"),
    ExclusionRule("data/import-spool", "excluded:import-spool-transient", "subtree"),
    ExclusionRule("data/probes", "excluded:probes-regenerable", "subtree"),
    ExclusionRule(
        "sessions.json",
        "excluded:auth-session-material",
        "name_in_subtree",
        "data",
    ),
    ExclusionRule(
        "*-sessions.json",
        "excluded:auth-session-material",
        "name_in_subtree",
        "data",
    ),
    ExclusionRule(
        "local-state.json",
        "excluded:local-machine-state",
        "name_in_subtree",
        "data",
    ),
    ExclusionRule(
        "*-state.json",
        "excluded:local-machine-state",
        "name_in_subtree",
        "data",
    ),
    ExclusionRule(
        "*.lock",
        "excluded:process-lock-file",
        "name_in_subtree",
        "data",
    ),
    ExclusionRule("_archivo_produccion", "excluded:out-of-scope-archive", "subtree"),
    # --- Project code and tooling (the checkout IS the data root) -----------
    # The data root is the whole project checkout, so without these rows every
    # snapshot carried the source tree: any build, edit or ``git`` operation
    # scheduled a large backup, and a restore would overwrite code with the
    # snapshot's stale copy. These paths are already versioned in git, so the
    # snapshot only needs to carry what git does NOT track.
    #
    # Directories use ``subtree`` (the top-level name and everything below it),
    # which also lets the watcher and the change detector ignore edits inside
    # them. The match is anchored at the top level: a same-named folder deeper
    # in the tree — ``mundos/World/docs``, ``mundos/World/src`` — never matches,
    # because dropping it would be the silent author-data loss the design
    # forbids. Root files use ``top_level_name`` for the same reason, so a
    # world's own ``README.md`` survives.
    #
    # The user's data is DELIBERATELY ABSENT: ``mundos/`` and ``ideas/`` are
    # gitignored, so the backup is their only protection and must keep it.
    ExclusionRule("src", "excluded:project-source-code", "subtree"),
    ExclusionRule("frontend", "excluded:project-source-code", "subtree"),
    ExclusionRule("desktop", "excluded:project-source-code", "subtree"),
    ExclusionRule("docs", "excluded:project-documentation", "subtree"),
    ExclusionRule("skills", "excluded:agent-skill-definitions", "subtree"),
    ExclusionRule("scripts", "excluded:project-setup-scripts", "subtree"),
    ExclusionRule("sdd", "excluded:sdd-workflow-artifacts", "subtree"),
    ExclusionRule(".github", "excluded:ci-configuration", "subtree"),
    ExclusionRule(".hermes", "excluded:agent-tooling-config", "subtree"),
    ExclusionRule(".opencode", "excluded:agent-tooling-config", "subtree"),
    ExclusionRule(".atl", "excluded:agent-tooling-config", "subtree"),
    ExclusionRule(".impeccable", "excluded:agent-tooling-config", "subtree"),
    ExclusionRule(
        "install.sh", "excluded:project-setup-scripts", "top_level_name"
    ),
    ExclusionRule(
        "install.ps1", "excluded:project-setup-scripts", "top_level_name"
    ),
    ExclusionRule(
        "start-*.ps1", "excluded:project-setup-scripts", "top_level_name"
    ),
    ExclusionRule("README*", "excluded:project-documentation", "top_level_name"),
    ExclusionRule("AGENTS.md", "excluded:project-documentation", "top_level_name"),
    ExclusionRule(
        "Agente_Maestro.md", "excluded:project-documentation", "top_level_name"
    ),
    ExclusionRule("COMANDOS.md", "excluded:project-documentation", "top_level_name"),
    ExclusionRule("LEEME.md", "excluded:project-documentation", "top_level_name"),
    ExclusionRule(
        "REGLAS_LENGUAJE.md", "excluded:project-documentation", "top_level_name"
    ),
    ExclusionRule(
        "Plantilla_Guion.md", "excluded:project-documentation", "top_level_name"
    ),
    ExclusionRule(
        "engram-export.json", "excluded:agent-memory-export", "top_level_name"
    ),
    ExclusionRule(".gitignore", "excluded:vcs-configuration", "top_level_name"),
    ExclusionRule(".gitattributes", "excluded:vcs-configuration", "top_level_name"),
    ExclusionRule(
        ".migration-baseline.txt",
        "excluded:migration-baseline-artifact",
        "top_level_name",
    ),
    ExclusionRule(".git", "excluded:vcs-metadata"),
    ExclusionRule(".codegraph", "excluded:code-index-regenerable"),
    # Git-tracked tooling that the table above missed. In dev the data root IS
    # the checkout, so a branch switch or a commit rewrites these paths and
    # scheduled a ~250 MB snapshot each time (observed right after a checkout).
    # They are versioned in git, so the snapshot only needs what git does NOT
    # track; user data (``mundos/``, ``ideas/``, ``data/``, ``config/``,
    # ``plantillas/``) stays included.
    ExclusionRule("odd", "excluded:odd-workflow-artifacts", "subtree"),
    ExclusionRule("tests", "excluded:project-tests", "subtree"),
    ExclusionRule("relay", "excluded:deployable-relay-worker", "subtree"),
    ExclusionRule(
        "payload_manifest.json", "excluded:generated-payload-manifest", "top_level_name"
    ),
    ExclusionRule(
        "requirements.lock", "excluded:project-dependencies", "top_level_name"
    ),
    ExclusionRule(
        "requirements-optional.txt", "excluded:project-dependencies", "top_level_name"
    ),
    ExclusionRule("LICENSE", "excluded:project-license", "top_level_name"),
    ExclusionRule(
        ".gitleaks.toml", "excluded:secret-scan-configuration", "top_level_name"
    ),
    ExclusionRule(
        ".pre-commit-config.yaml", "excluded:project-setup-scripts", "top_level_name"
    ),
    ExclusionRule(
        ".env.example", "excluded:project-setup-scripts", "top_level_name"
    ),
    # Runtime logs are the app's own writes: the API appends one line per
    # request INSIDE the data root, so including them made every request a
    # durable change and kept the engine in a self-sustaining snapshot loop
    # (each run's own log lines fed the next run). They are regenerable,
    # gitignored material, never author data. Top-level anchored: a world's own
    # ``logs`` folder deeper in the tree is still staged.
    ExclusionRule("logs", "excluded:runtime-log", "subtree"),
    ExclusionRule(".venv", "excluded:virtualenv-code"),
    # Tooling / dependency / cache directories, refused by basename ANYWHERE in
    # the tree (scope ``name``). Their names are unambiguous: a folder called
    # ``node_modules`` or ``__pycache__`` is tool output, never author lore, so
    # refusing it anywhere cannot drop a world. This is what keeps an installed
    # dependency tree and the test/tool caches out of the synced backup folder.
    #
    # Generic names are deliberately ABSENT: a folder called ``dist``, ``build``,
    # ``target``, ``out``, ``output`` or ``cache`` can legitimately hold author
    # content, and dropping it would be exactly the silent loss the design
    # forbids ("unruled members are INCLUDED by default").
    ExclusionRule("node_modules", "excluded:dependency-tree"),
    ExclusionRule("__pycache__", "excluded:python-bytecode-cache"),
    ExclusionRule(".pytest_cache", "excluded:test-run-cache"),
    ExclusionRule(".mypy_cache", "excluded:type-check-cache"),
    ExclusionRule(".ruff_cache", "excluded:linter-cache"),
    ExclusionRule(".tox", "excluded:test-matrix-virtualenv"),
    ExclusionRule(".nox", "excluded:test-matrix-virtualenv"),
    ExclusionRule("*.egg-info", "excluded:python-package-metadata"),
    ExclusionRule("venv", "excluded:virtualenv-code"),
    ExclusionRule(".DS_Store", "excluded:os-metadata"),
    ExclusionRule("Thumbs.db", "excluded:os-metadata"),
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
    # --- The backup's own reserved names -----------------------------------
    # `restore.py`'s `_is_reserved_member` owns the authoritative list: the
    # maintenance marker, every transport temp name, and the park directories a
    # restore swaps members through. They are bookkeeping, never author data, so
    # the snapshot must not carry them and a write to one must not move the
    # included-tree fingerprint. The names are MIRRORED here because `inventory`
    # cannot import `restore` (restore imports this module); a test pins them
    # against restore's constants. The marker and its temp live at the data
    # root; the park directories are named `.demiurgos-old-<id>` anywhere the
    # restore created them.
    ExclusionRule(
        ".demiurgos-maintenance.json",
        "excluded:backup-maintenance-marker",
        "top_level_name",
    ),
    ExclusionRule(
        ".demiurgos-maintenance.json.tmp-*",
        "excluded:backup-maintenance-marker-temp",
        "top_level_name",
    ),
    ExclusionRule(
        ".demiurgos-old-*",
        "excluded:backup-restore-park-dir",
        "name",
    ),
)


@dataclass(frozen=True)
class TopLevelMember:
    """One discovered top-level member, with the rule that matched it, if any.

    ``canonical_case`` is the NFC-normalized name as discovered; ``raw_name``
    keeps the on-disk spelling so a collision abort can name BOTH sources even
    when they normalize to the same string. Case collision detection (WU-7b) is
    the only place a spelling is ever questioned.
    """

    name: str
    canonical_case: str
    kind: str
    rule: SubtreeRule | None
    raw_name: str = ""


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
class CaseCollision:
    """Top-level members that collapse to one name on a case-insensitive target.

    ``key`` is the shared NFC + ``casefold()`` form; ``members`` names the
    colliding members as they exist on disk (raw, never normalized), so an abort
    message points at BOTH sources instead of silently choosing one spelling
    (REQ-CDL-2, SC-CDL-2.1).
    """

    key: str
    members: tuple[str, ...]

    def finding(self) -> Finding:
        """The ``findings: case_collision`` view a manifest can record."""
        return Finding("case_collision", self.members)


class CaseCollisionError(RuntimeError):
    """Abort: top-level members would collapse on a case-insensitive target.

    Raised by :func:`build_inventory` before any member is included, so a lossy
    staged set can never be produced (REQ-CDL-2). The collisions ride on
    :attr:`collisions` and are exposed as findings, so a caller can record and
    report them even though there is no inventory to return — the abort is not
    a finding a caller may ignore.
    """

    def __init__(self, collisions: tuple[CaseCollision, ...]) -> None:
        self.collisions = collisions
        super().__init__(_collision_message(collisions))

    @property
    def findings(self) -> tuple[Finding, ...]:
        """Every collision as ``findings: case_collision``, naming both members."""
        return tuple(collision.finding() for collision in self.collisions)


def _case_key(name: str) -> str:
    """The canonical-destination key: NFC-normalize, then ``casefold()``."""
    return unicodedata.normalize("NFC", name).casefold()


def _collision_message(collisions: tuple[CaseCollision, ...]) -> str:
    """A message naming both members of every collision."""
    named = "; ".join(
        " and ".join(repr(name) for name in collision.members)
        for collision in collisions
    )
    return (
        "case collision across top-level members after NFC + casefold "
        f"normalization: {named} would collapse to one name on a "
        "case-insensitive destination"
    )


def detect_case_collisions(
    members: tuple[TopLevelMember, ...],
) -> tuple[CaseCollision, ...]:
    """Top-level members whose NFC + ``casefold()`` keys match (REQ-CDL-2).

    The comparison is deliberately TOP-LEVEL only. The spec asks for "one
    canonical case per top-level name" and SC-CDL-2.1 gives "top-level members
    differing only by case". The motivating ``ideas/`` vs ``mundos/Ideas/`` pair
    sits at different levels (root vs inside ``mundos/``), so it is NOT a
    top-level collision and is not detected here; a same-level nested collision
    is caught by the transport's staged-path check (REQ-BE-9, SC-BE-9.1).
    """
    grouped: dict[str, list[str]] = {}
    for member in members:
        grouped.setdefault(_case_key(member.name), []).append(
            member.raw_name or member.name
        )
    collisions = [
        CaseCollision(key, tuple(sorted(grouped[key])))
        for key in sorted(grouped)
        if len(grouped[key]) > 1
    ]
    return tuple(collisions)


@dataclass(frozen=True)
class Inventory:
    """The discovered member set: included paths, exclusions and findings."""

    root: Path
    top_level: tuple[TopLevelMember, ...]
    included: tuple[str, ...]
    excluded: tuple[ExcludedPath, ...]
    findings: tuple[Finding, ...]

    @property
    def excluded_count(self) -> int:
        """How many paths the exclusion table left out, and why they are listed.

        The full listing — every path WITH the reason that matched it — is
        :attr:`excluded`; the manifest copies it verbatim, so what a run left
        out is recorded rather than trusted. This one-number summary is the
        minimum a caller (a run report or the UI) needs to surface the effect.
        Pure data: no I/O and no new document.
        """
        return len(self.excluded)


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
    ``name_in_subtree`` rows only ever match inside their ``under`` directory, so
    the ``data/`` secrets class can never refuse a same-named file elsewhere.
    """
    normalized = unicodedata.normalize("NFC", relative_path).replace("\\", "/")
    base = normalized.rsplit("/", 1)[-1]
    for rule in EXCLUSION_RULES:
        if rule.scope == "subtree":
            if normalized == rule.pattern or normalized.startswith(rule.pattern + "/"):
                return rule.reason
        elif rule.scope == "name_in_subtree":
            if (
                normalized.startswith(rule.under + "/")
                and fnmatch.fnmatch(base, rule.pattern)
            ):
                return rule.reason
        elif rule.scope == "top_level_name":
            # Root-only: a nested entry carries a "/" and is never matched, so
            # a same-named world file is untouched by a checkout-root rule.
            if "/" not in normalized and fnmatch.fnmatch(normalized, rule.pattern):
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
            raw_name=raw_name,
        ))
    return tuple(members)


def build_inventory(data_root: Path) -> Inventory:
    """Build the inventory of *data_root* from its real contents (WU-7).

    Aborts with :class:`CaseCollisionError` when two top-level members would
    collapse to one name on a case-insensitive destination; a lossy set is never
    returned (REQ-CDL-2, SC-CDL-2.1).
    """
    root = Path(data_root)
    top_level = discover_top_level(root)
    collisions = detect_case_collisions(top_level)
    if collisions:
        raise CaseCollisionError(collisions)
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
