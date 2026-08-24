"""Canonical world creation authority (OC7/OC8, world-workshop W9/W10).

Creates a NEW world tree under ``mundos/{name}`` with the lowercase canonical
folders ``lore/ personajes/`` plus an optional empty OC8 Lore skeleton
(``lore/{reglas,lugares,culturas,criaturas,facciones,artefactos,historia}``).

Rules enforced here:
- Safe lowercase-normalized names only; traversal/symlink escapes rejected.
- System folders (``_context``/``.history``/``.papelera``) and transversal
  views (``relaciones``/``canon``/``conflictos``/``propuestas``) are NEVER
  created — they are not content sections (W9/W10, OC8).
- Imported/Author-owned trees are NEVER touched (W10). A pre-existing world
  that is not a previously-created canonical skeleton is a COLLISION and is
  rejected without mutation.
- Repetition of the same creation request is idempotent (ALREADY_EXISTS).

This module is pure and filesystem-scoped: it writes ONLY under the given
``mundos_dir``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

# Canonical minimum tree (OKF / OC7).
CANONICAL_DIRS = ("lore", "personajes")

# Optional empty Lore skeleton for NEW worlds only (OC8). Empty folders only —
# never generated content.
OC8_LORE_SKELETON = (
    "reglas",
    "lugares",
    "culturas",
    "criaturas",
    "facciones",
    "artefactos",
    "historia",
)

# System directories that are never content sections (W10).
SYSTEM_DIRS = frozenset({"_context", ".history", ".papelera"})

# Transversal (semantic) views that are never physical folders (OC8/W9).
TRANSVERSAL_DIRS = frozenset({"relaciones", "canon", "conflictos", "propuestas"})

# Names reserved at the worlds root.
RESERVED_NAMES = frozenset({"Ideas"})

# Legacy (uppercase) top-level layout folders — never the canonical tree (OC7).
# Their presence marks a world as using the legacy layout, which runtime
# case-sensitive paths do not recognize.
LEGACY_FOLDERS = ("Lore", "Personajes")

# Canonical OKF content sections the importer may write fichas into. This is
# the section/path authority for importer H1 scopes: ``resolve_target``
# validates every structured-import target against these sections
# (importador-auto-frontmatter). System dirs and transversal views are never
# content sections and are therefore never permitted (OC7/W9/W10).
IMPORTER_SCOPE_SECTIONS = ("lore", "personajes", "referencias")


class WorldResultKind(Enum):
    """Machine-readable outcome of a world-creation request."""

    CREATED = "created"
    ALREADY_EXISTS = "already_exists"  # idempotent repeat of a canonical tree
    INVALID_NAME = "invalid_name"
    COLLISION = "collision"  # existing Author-owned/imported tree — never mutated
    IO_ERROR = "io_error"


@dataclass(frozen=True)
class WorldResult:
    """Outcome of ``create_world``. ``path`` is the created/resolved root."""

    kind: WorldResultKind
    name: str
    path: Path | None = None
    message: str = ""


def normalize_world_name(raw: str | None) -> str | None:
    """Normalize a world name or return None when it is unsafe.

    Rules mirror the runtime resolver's visibility rules (``_resolve_mundo_dir``):
    a single safe path segment, not hidden/``_``-prefixed, not the shared
    ``Ideas`` bucket, no path separators/absolute/dot segments. The name is
    trimmed; the canonical tree folders are lowercase regardless.
    """
    if not isinstance(raw, str):
        return None
    name = raw.strip()
    if not name:
        return None
    if name in {".", ".."} or set(name) <= {"."}:
        return None
    if Path(name).name != name:  # separators / absolute paths / dot segments
        return None
    if "\\" in name:  # defensive: backslash is a separator on other platforms
        return None
    if name.startswith((".", "_")):
        return None
    if name in RESERVED_NAMES:
        return None
    return name


def create_world(
    mundos_dir: Path,
    name: str | None,
    *,
    lore_skeleton: bool = False,
) -> WorldResult:
    """Create a canonical new world tree. See module docstring for the rules.

    ``lore_skeleton`` adds the optional empty OC8 folders under ``lore/``.
    """
    normalized = normalize_world_name(name)
    if normalized is None:
        return WorldResult(
            WorldResultKind.INVALID_NAME,
            name or "",
            message="El nombre del mundo no es válido.",
        )

    root = Path(mundos_dir).resolve()
    try:
        if not root.is_dir():
            root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return WorldResult(WorldResultKind.IO_ERROR, normalized, message=str(exc))

    target = (root / normalized).resolve()
    if target.parent != root:
        # Symlink escape: resolving the name leaves the worlds root.
        return WorldResult(
            WorldResultKind.COLLISION,
            normalized,
            message="El mundo existe como enlace fuera del árbol de mundos.",
        )

    # Path-based escape guard (independent of existence): a directly malicious
    # symlinked parent would already be caught by the parent check above, but
    # keep the explicit containment assertion for auditability.
    if target.is_symlink():
        try:
            real_parent = target.parent.resolve()
        except OSError:
            real_parent = None
        if real_parent != root:
            return WorldResult(
                WorldResultKind.COLLISION,
                normalized,
                message="Ruta del mundo fuera del árbol de mundos.",
            )

    if target.is_dir() or target.is_symlink():
        if _is_canonical_clean(target, lore_skeleton=lore_skeleton):
            # Idempotent repeat of a previously created canonical skeleton.
            return WorldResult(
                WorldResultKind.ALREADY_EXISTS,
                normalized,
                path=target,
                message="El mundo canónico ya existe.",
            )
        return WorldResult(
            WorldResultKind.COLLISION,
            normalized,
            path=target,
            message="Ya existe un mundo con ese nombre que no se puede reemplazar.",
        )
    if target.exists():
        return WorldResult(
            WorldResultKind.COLLISION,
            normalized,
            path=target,
            message="Ya existe un archivo con ese nombre.",
        )

    try:
        target.mkdir(parents=False)
        for sub in CANONICAL_DIRS:
            (target / sub).mkdir(parents=True, exist_ok=True)
        if lore_skeleton:
            for sub in OC8_LORE_SKELETON:
                (target / "lore" / sub).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return WorldResult(
            WorldResultKind.IO_ERROR,
            normalized,
            message=str(exc),
        )
    return WorldResult(
        WorldResultKind.CREATED,
        normalized,
        path=target,
        message="Mundo creado.",
    )


def detect_legacy_layout(mundos_dir: Path) -> list[dict]:
    """Read-only legacy-layout detection (ONB-4.2).

    Scans ``mundos/`` for worlds whose top level uses the legacy uppercase
    folders ``Lore``/``Personajes`` instead of the canonical lowercase
    ``lore``/``personajes`` (OC7). Each finding is
    ``{"world": <name>, "folders": [folder, ...]}``.

    Detection is STRICTLY read-only: it never renames, moves, deletes, or
    writes anything. Runtime paths are case-sensitive, so a legacy folder is
    invisible to the canonical readers; migration is a separate,
    explicitly-approved step (ONB-4.3) and never automatic. Visibility rules
    mirror ``_list_worlds`` (hidden/``_``-prefixed entries and ``Ideas`` are
    skipped); names are compared as directory-entry strings, so a world with
    only the lowercase canonical folders is never reported even on
    case-insensitive filesystems.
    """
    findings: list[dict] = []
    root = Path(mundos_dir)
    try:
        if not root.is_dir():
            return findings
        entries = sorted(root.iterdir())
    except OSError:
        return findings
    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name.startswith((".", "_")) or entry.name == "Ideas":
            continue
        try:
            top_dir_names = {
                child.name for child in entry.iterdir() if child.is_dir()
            }
        except OSError:
            continue
        found = [folder for folder in LEGACY_FOLDERS if folder in top_dir_names]
        if found:
            findings.append({"world": entry.name, "folders": found})
    return findings


def _is_canonical_clean(root: Path, *, lore_skeleton: bool) -> bool:
    """True when *root* holds exactly an empty canonical skeleton.

    Used to distinguish an idempotent repeat (safe) from an Author-owned tree
    (COLLISION — W10). A clean tree has no files and only the canonical dirs
    (plus, when requested, the empty OC8 skeleton under ``lore/``).
    """
    try:
        top_entries = list(root.iterdir())
    except OSError:
        return False
    if not top_entries:
        return False  # an empty dir is ambiguous — treat as not canonical
    if any(entry.is_file() or entry.is_symlink() for entry in top_entries):
        return False
    top_names = {entry.name for entry in top_entries}
    if not top_names.issubset(CANONICAL_DIRS):
        return False
    for sub in CANONICAL_DIRS:
        sub_dir = root / sub
        if not sub_dir.is_dir():
            return False
        try:
            content = list(sub_dir.iterdir())
        except OSError:
            return False
        if sub == "lore" and lore_skeleton:
            # Lore holds only (possibly partial) empty OC8 skeleton dirs.
            if any(entry.is_file() or entry.is_symlink() for entry in content):
                return False
            lore_names = {entry.name for entry in content}
            if not lore_names.issubset(OC8_LORE_SKELETON):
                return False
        elif content:
            # Non-skeleton canonical dirs must be empty (no Author content).
            return False
    return True


def canonical_dirs() -> tuple[str, ...]:
    return CANONICAL_DIRS


def oc8_skeleton_dirs() -> tuple[str, ...]:
    return OC8_LORE_SKELETON


def is_importer_scope_permitted(canonical_section: str) -> bool:
    """Permit an importer H1 scope only under a canonical OKF section.

    The structured importer (importador-auto-frontmatter) may only materialize
    fichas under the canonical content sections (``lore``/``personajes``/
    ``referencias``). Any other top-level target — a system dir
    (``_context``/``.history``/``.papelera``), a transversal view
    (``relaciones``/``canon``/``conflictos``/``propuestas``), or an unknown
    section — is rejected: the importer never guesses a path (OC7/W9/W10).
    """
    return (canonical_section or "").strip().lower() in IMPORTER_SCOPE_SECTIONS


def forbidden_dir_names() -> Iterable[str]:
    return SYSTEM_DIRS | TRANSVERSAL_DIRS