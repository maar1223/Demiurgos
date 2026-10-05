# -*- coding: utf-8 -*-
"""demiurgos-skills-directory (WU 0.2) — .gitignore guard + Etapa 0 sequencing.

The owned skills folder (``data/methodology/skills/``) is a tracked-but-empty
foundation in Etapa 0: only ``.gitkeep`` is versioned, generated runtime content
under it is ignored, and ``data/methodology/seeds/`` stays tracked (spec
``demiurgos-skills-directory``). The sequencing guard (spec cross-cutting
'No materialized skill visible before Etapa 3') asserts the folder holds only
``.gitkeep`` and that the installer-written product config never enables the
``skills`` toolset in ``platform_toolsets.api_server``.

``git check-ignore`` cells are skipped when ``git`` is unavailable; a text-scan
fallback asserts the exact ``.gitignore`` patterns instead.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

GITIGNORE = REPO_ROOT / ".gitignore"
INSTALL_SH = REPO_ROOT / "install.sh"
SKILLS_DIR = REPO_ROOT / "data" / "methodology" / "skills"
SEEDS_DIR = REPO_ROOT / "data" / "methodology" / "seeds"

GIT_AVAILABLE = shutil.which("git") is not None


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _git_check_ignore(path: str) -> int | None:
    """Exit code of ``git check-ignore -q <path>`` (0 = ignored), or None when
    git is unavailable (caller falls back to the text scan)."""
    if not GIT_AVAILABLE:
        return None
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode


def test_generated_skill_content_is_ignored():
    """Spec 'Generated content is not tracked': a materialized
    data/methodology/skills/<skill>/SKILL.md never appears as a change."""
    path = "data/methodology/skills/example-skill/SKILL.md"
    code = _git_check_ignore(path)
    if code is not None:
        assert code == 0  # ignored
    else:
        assert "data/methodology/skills/*" in _text(GITIGNORE)


def test_gitkeep_is_not_ignored():
    """Spec 'Folder and .gitkeep are tracked': the placeholder stays versioned."""
    path = "data/methodology/skills/.gitkeep"
    code = _git_check_ignore(path)
    if code is not None:
        assert code == 1  # not ignored
    else:
        assert "!data/methodology/skills/.gitkeep" in _text(GITIGNORE)


def test_seeds_folder_is_not_ignored():
    """Spec (gitignore half): data/methodology/seeds/ stays tracked — no
    .gitignore pattern excludes it."""
    path = "data/methodology/seeds/narrative-character-creation/source.md"
    code = _git_check_ignore(path)
    if code is not None:
        assert code == 1  # not ignored
    else:
        patterns = [
            line.strip()
            for line in _text(GITIGNORE).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert not any("seeds" in pat for pat in patterns)


def test_skills_folder_holds_only_gitkeep_in_etapa_0():
    """Sequencing guard (spec 'No materialized skill visible before Etapa 3'):
    the folder is a tracked-but-empty foundation — only .gitkeep, no SKILL.md."""
    assert [p.name for p in SKILLS_DIR.iterdir()] == [".gitkeep"]
    assert list(SKILLS_DIR.rglob("SKILL.md")) == []


def test_installer_never_enables_skills_toolset():
    """Sequencing guard: the installer-written product config never enables
    `skills` in platform_toolsets.api_server (that flip belongs to Etapa 3)."""
    text = _text(INSTALL_SH)
    assert "platform_toolsets" not in text
    assert "api_server" not in text