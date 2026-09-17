# -*- coding: utf-8 -*-
"""Retirement hygiene — the legacy rclone sync surface stays gone (WU-16).

Covers REQ-BE-10 and its scenarios:

* **SC-BE-10.1 — legacy surface gone, no destructive mirror.** The seven retired
  files are absent, the retired ``/sync`` command that referenced two of them is
  absent, and NO code path performs a delete-at-destination mirror of the data
  root. The last clause is asserted STRUCTURALLY, not by name: the transport
  contract declares exactly the nine non-destructive verbs (no ``sync``/``mirror``
  and no delete-at-destination verb), the concrete folder transport declares no
  such verb either, and not one module in ``backup/`` shells out to any external
  tool — so a mirror binary can never be invoked from the engine.
* **SC-BE-10.2 — zero imports from the retired package.** The engine and API
  modules contain zero references to the retired ``web-config-ui`` package; the
  import statements of the whole wiki runtime are scanned with :mod:`ast` so a
  real import (not a documented mention) is what fails the check.

The retired surface was a **destructive** one: ``sync-now.*``/``start-sync.*``
ran ``rclone sync <project> Demiurgos:`` — a mirror with delete-at-destination —
and ``install-sync.*`` configured it. ``rclone-filters.txt`` even hardcoded the
capitalised ``+ /Ideas/**`` that misses the real lowercase ``ideas/``. Removing
them keeps the structural absence declared in ``backup/transport/base.py``
honest instead of merely aspirational.

MANUAL VERIFICATION CHECKLIST (task 16.4) — RECORDED, NOT EXECUTED
=================================================================
None of the items below can run in this environment: they need real sync
clients, real Windows, real streaming mounts and a second machine. They are
recorded here so the maintainer can execute them, and each item states exactly
which UNVERIFIED claim it converts to verified. This suite does NOT claim any of
them as passed.

1. **One real run into a real synced folder (Google Drive for Desktop set to
   Mirroring), then inspect the tree visually.**
   Converts UNVERIFIED → verified: the published layout exists and is complete
   (``Demiurgos/{current,snapshots/<UTC-ISO>,meta,world-trash-index}``), no
   ``world-trash`` *content* is written, no torn/temp-named file is visible, and
   the sync client actually uploads the published bytes. The automated tests use
   a ``tmp_path`` folder and never exercise a real sync client.

2. **Real Windows:** presence of ``%OneDrive%``; the moved-folder case hitting
   the registry ``HKCU\\Software\\Microsoft\\OneDrive\\Accounts\\*\\UserFolder``
   value; the actual ``GetDriveTypeW`` value returned for Google Drive's ``G:``
   virtual drive; and OneDrive Files On-Demand placeholder attributes
   (``FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS``).
   Converts UNVERIFIED → verified: REQ-SF-2's registry fallback path on a real
   install, and the design's explicitly UNVERIFIED streaming signals. PR 12
   deliberately implemented only signals measured on hardware, so this item is
   what promotes the rest from a design note to a verified signal.

3. **A real streaming mount:** confirm the block fires, the Mirroring remedy is
   shown, and nothing is published.
   Converts UNVERIFIED → verified: SC-SF-3.1 on real hardware — ``probe()``
   reports ``writable=False``, ``/api/backup/run`` refuses to start, zero bytes
   are written and the remedy text is the one surfaced. The automated test uses
   a simulated streaming marker.

4. **Debounce timing observed once live:** one run starts 5–10 s after the last
   edit and a burst coalesces into a single run.
   Converts UNVERIFIED → verified: SC-BE-6.1/6.2 with the real worker thread and
   the real watchdog observer. The automated test injects a fake clock and never
   observes wall-clock scheduling.

5. **Restore onto a second machine** from a real synced folder.
   Converts UNVERIFIED → verified: SC-RS-3.1 end to end — validation, atomic
   swap, SQLite restore and index regeneration on a different machine, which is
   the point of the whole change. The automated restore test runs in a temporary
   root on one machine and cannot prove cross-machine recovery from a synced
   folder.

6. **``install.ps1`` smoke on real Windows** (fresh environment).
   Converts UNVERIFIED → verified: REQ-DR-2.2 clean-machine install — the
   ``platformdirs`` dependency installs from the manifest and the first run
   writes the ``data-root.json`` pointer — plus launcher propagation to the API
   process on the real OS. The automated tests assert the rendered launcher env,
   not a real install.
=================================================================
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
if str(_WIKI) not in sys.path:
    sys.path.insert(0, str(_WIKI))


def _repo_root() -> Path:
    """The checkout root: ascend to the directory that holds ``.git``.

    Deliberately NOT ``Path(__file__).resolve().parents[N]``: the slice forbids
    new ``parents[3..6]`` literals anywhere under the scanned tree, so the root
    is discovered by a sentinel walk instead of a fixed depth.
    """
    for ancestor in _HERE.parents:
        if (ancestor / ".git").exists():
            return ancestor
    raise AssertionError("repository root (.git) not found above this test file")


REPO_ROOT = _repo_root()
BACKUP_DIR = _WIKI / "backup"
BASE_MODULE = BACKUP_DIR / "transport" / "base.py"
FOLDER_MODULE = BACKUP_DIR / "transport" / "folder.py"

# REQ-BE-10: the retired destructive sync surface. ``scripts/*-sync.*`` and the
# filter file performed / configured ``rclone sync`` (delete-at-destination).
RETIRED_FILES = (
    "scripts/install-sync.sh",
    "scripts/install-sync.ps1",
    "scripts/sync-now.sh",
    "scripts/sync-now.ps1",
    "scripts/start-sync.sh",
    "scripts/start-sync.ps1",
    "rclone-filters.txt",
)

# The retired Hermes ``/sync`` command referenced ``sync-now.ps1`` and
# ``start-sync.ps1``; deleting it is what leaves the repo with zero dangling
# references. It has no value beyond the rclone surface: its whole body is "run
# the sync scripts", and the new engine is a local-write-only folder backup
# driven by the UI, not a ``/sync`` command.
RETIRED_COMMAND = "src/commands/sync-drive.md"

RETIRED_PACKAGE_MARKERS = ("web-config-ui", "web_config_ui")

# The nine non-destructive verbs of REQ-BE-8, frozen in design order.
EXPECTED_PROTOCOL_VERBS = frozenset(
    {
        "probe",
        "ensure_layout",
        "publish_current",
        "publish_snapshot",
        "prune",
        "list_snapshots",
        "read_meta",
        "write_meta",
        "fetch",
    }
)

# Mirrors the retired ``rclone sync``. ``prune`` is deliberately absent: policy
# snapshot deletion is the ONE allowed deletion (REQ-BE-7) and it never touches
# ``current/``.
FORBIDDEN_VERBS = frozenset(
    {
        "sync",
        "mirror",
        "mirror_to",
        "delete",
        "delete_at_destination",
        "remove",
        "unlink",
        "rmtree",
        "purge",
        "wipe",
    }
)

# Import roots that would let the engine invoke an external mirror binary. None
# of them appears in ``backup/``; the check is the structural guarantee that no
# module shells out at all.
FORBIDDEN_IMPORT_ROOTS = frozenset({"subprocess", "pty"})

# Attribute calls that shell out even without importing ``subprocess``.
FORBIDDEN_CALLS = frozenset(
    {
        ("os", "system"),
        ("os", "popen"),
        ("os", "execv"),
        ("os", "execvp"),
        ("os", "spawnv"),
        ("os", "spawnvp"),
        ("shutil", "which"),
        ("asyncio", "create_subprocess_shell"),
        ("asyncio", "create_subprocess_exec"),
    }
)

# Exact string literals that name a mirror binary. Docstrings legitimately
# mention the retired tool in prose, so only exact equality is flagged.
MIRROR_BINARY_NAMES = frozenset({"rclone", "robocopy", "rsync"})


def _python_sources(root: Path, *, skip_tests: bool = False) -> list[Path]:
    """Every runtime ``*.py`` under *root*, without caches or test modules."""
    sources: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        relative_parts = path.relative_to(root).parts
        if "__pycache__" in relative_parts:
            continue
        if skip_tests and "tests" in relative_parts:
            continue
        if "web-config-ui" in relative_parts:
            continue
        sources.append(path)
    return sources


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _method_names(tree: ast.Module, class_name: str) -> set[str]:
    """The functions declared directly in *class_name* (not nested classes)."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                member.name
                for member in node.body
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    raise AssertionError(f"class {class_name!r} not found in the parsed module")


# --- SC-BE-10.1: the legacy surface is gone --------------------------------


def test_retired_sync_files_are_absent() -> None:
    present = [rel for rel in RETIRED_FILES if (REPO_ROOT / rel).exists()]
    assert present == [], f"retired rclone sync files still present: {present}"


def test_retired_sync_command_is_absent() -> None:
    assert not (REPO_ROOT / RETIRED_COMMAND).exists(), (
        "the retired /sync command still references deleted scripts"
    )


# --- SC-BE-10.1: no destructive mirror is reachable ------------------------


def test_transport_protocol_declares_no_destructive_verb() -> None:
    verbs = _method_names(_parse(BASE_MODULE), "BackupTransport")
    assert verbs == set(EXPECTED_PROTOCOL_VERBS)
    assert verbs & FORBIDDEN_VERBS == set(), (
        f"destructive verb reintroduced in the transport contract: "
        f"{sorted(verbs & FORBIDDEN_VERBS)}"
    )


def test_folder_transport_declares_no_destructive_verb() -> None:
    methods = _method_names(_parse(FOLDER_MODULE), "FolderTransport")
    assert methods & FORBIDDEN_VERBS == set(), (
        f"destructive verb reintroduced in FolderTransport: "
        f"{sorted(methods & FORBIDDEN_VERBS)}"
    )


def test_destructive_verb_scan_catches_a_regression() -> None:
    """The verb scan actually bites: a ``sync``/``delete`` verb is caught."""
    tree = ast.parse(
        "class RegressedTransport:\n"
        "    def sync(self):\n        ...\n"
        "    def delete_at_destination(self):\n        ...\n"
        "    def probe(self):\n        ...\n"
    )
    methods = _method_names(tree, "RegressedTransport")
    assert methods & FORBIDDEN_VERBS == {"sync", "delete_at_destination"}


def _shell_out_offenders(paths: list[Path]) -> list[str]:
    """Every shell-out site in *paths*: a forbidden import, call, or binary name."""
    offenders: list[str] = []
    for path in paths:
        tree = _parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
                if roots & FORBIDDEN_IMPORT_ROOTS:
                    offenders.append(f"{path.name}:{node.lineno} import {sorted(roots)}")
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    offenders.append(f"{path.name}:{node.lineno} from {node.module}")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    if (func.value.id, func.attr) in FORBIDDEN_CALLS:
                        offenders.append(
                            f"{path.name}:{node.lineno} {func.value.id}.{func.attr}()"
                        )
            elif isinstance(node, ast.Constant) and node.value in MIRROR_BINARY_NAMES:
                offenders.append(f"{path.name}:{node.lineno} literal {node.value!r}")
    return offenders


def test_no_backup_module_shells_out_to_a_mirror_tool() -> None:
    """No module in ``backup/`` can invoke an external tool, mirror or not."""
    offenders = _shell_out_offenders(_python_sources(BACKUP_DIR))
    assert offenders == [], "backup/ shells out to an external tool: " + "; ".join(
        offenders
    )


def test_shell_out_scan_catches_a_regression(tmp_path: Path) -> None:
    """The scan actually bites: an import, an ``os.system`` call and a binary name."""
    (tmp_path / "regressed.py").write_text(
        'import subprocess\n'
        'subprocess.run(["rclone", "sync", "src", "dst"])\n'
        'os.system("robocopy a b /MIR")\n',
        encoding="utf-8",
    )
    offenders = _shell_out_offenders([tmp_path / "regressed.py"])
    assert any("import" in item and "subprocess" in item for item in offenders)
    assert any("os.system()" in item for item in offenders)
    assert any("'rclone'" in item for item in offenders)


# --- SC-BE-10.2: zero references to the retired package --------------------


def _retired_import_offenders(paths: list[Path]) -> list[str]:
    """Every import statement in *paths* that names the retired package."""
    offenders: list[str] = []
    for path in paths:
        tree = _parse(path)
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                if any(marker in name for marker in RETIRED_PACKAGE_MARKERS):
                    offenders.append(f"{path.name}:{node.lineno} {name}")
    return offenders


def test_no_runtime_import_references_the_retired_package() -> None:
    """Import statements across the wiki runtime never name ``web-config-ui``."""
    offenders = _retired_import_offenders(_python_sources(_WIKI, skip_tests=True))
    assert offenders == [], "imports reference the retired package: " + "; ".join(
        offenders
    )


def test_retired_import_scan_catches_a_regression(tmp_path: Path) -> None:
    """A mention in a docstring is fine; a real import is caught."""
    (tmp_path / "mentions_are_fine.py").write_text(
        '"""Historical note: the retired web-config-ui tree is preserved."""\n',
        encoding="utf-8",
    )
    (tmp_path / "imports_are_not.py").write_text(
        "from web_config_ui import backup\n", encoding="utf-8"
    )
    assert _retired_import_offenders([tmp_path / "mentions_are_fine.py"]) == []
    assert _retired_import_offenders([tmp_path / "imports_are_not.py"]) != []


def test_new_engine_modules_contain_no_retired_package_reference() -> None:
    """The new engine package is exhaustively free of the retired package name."""
    offenders: list[str] = []
    for path in (_WIKI / "data_root.py", *_python_sources(BACKUP_DIR)):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in RETIRED_PACKAGE_MARKERS:
            if marker in text:
                offenders.append(f"{path.name}: {marker}")
    assert offenders == [], "new modules reference the retired package: " + "; ".join(
        offenders
    )
