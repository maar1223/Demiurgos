# -*- coding: utf-8 -*-
"""Idempotent YAML merge for the Demiurgos-owned skills folder (WU 0.2).

The installer (``install.sh``) owns the dedicated product profile
(``$HERMES_CONFIG``) and registers the checkout's skills folder through
``skills.external_dirs``. The legacy ``cat >> ... skills:`` append could
duplicate the block on re-runs; this module replaces it with a single,
idempotent merge that preserves sibling keys (``creation_nudge_interval``)
and every other top-level key.

Contract (design Decision 5)::

    merge_skills_external_dirs(config_path, skills_dir) -> bool
        True  when the config was written,
        False when the entry was already present.

The merge never crashes on missing/empty/non-mapping configs: it starts from
``{}`` and always produces a valid mapping. ``resolve_skills_dir`` is the
canonical resolver of the owned folder under a checkout root, used by the
installer so the registered path is a single source of truth.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

#: Canonical location of the Demiurgos-owned skills folder under a checkout root.
SKILLS_DIR_REL = Path("data") / "methodology" / "skills"


def resolve_skills_dir(repo_root: Path) -> Path:
    """Resolve the owned skills folder under a checkout root.

    Returns the absolute, symlink-free path of
    ``<repo_root>/data/methodology/skills``.
    """
    return (Path(repo_root) / SKILLS_DIR_REL).expanduser().resolve()


def merge_skills_external_dirs(config_path: Path, skills_dir: Path) -> bool:
    """Ensure ``config_path`` has ONE ``skills.external_dirs`` list containing ``skills_dir``.

    Idempotent; preserves ``creation_nudge_interval`` and every other key.
    Returns True when written, False when the entry was already present.
    """
    import yaml

    data = {}
    if config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    skills = data.get("skills")
    if not isinstance(skills, dict):
        skills = {}
        data["skills"] = skills
    dirs = skills.get("external_dirs")
    if not isinstance(dirs, list):
        dirs = [dirs] if isinstance(dirs, str) else []
        skills["external_dirs"] = dirs
    entry = str(Path(skills_dir).expanduser().resolve())
    if entry in dirs:
        return False
    dirs.append(entry)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return True


def ensure_skills_toolset(config_path: Path, *, enabled: bool) -> bool:
    """Add or remove ONLY ``skills`` in ``platform_toolsets.api_server``.

    Runtime reconcile writer (design Q2, spec REQ-NC-3): loading the YAML,
    ensuring ``platform_toolsets.api_server`` is a list, appending ``"skills"``
    when ``enabled`` or removing only ``"skills"`` when not — every other key,
    tool, and block is preserved. The write is atomic (temp sibling +
    ``os.replace``) and the whole operation never crashes on missing/empty/
    non-mapping configs.

    Returns True when the file was written, False when it already was in the
    desired state (so a zero-world-OFF config without ``skills`` is a no-op
    that leaves the dedicated profile byte-identical).
    """
    import yaml

    data = {}
    if config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    toolsets = data.get("platform_toolsets")
    if not isinstance(toolsets, dict):
        toolsets = {}
        data["platform_toolsets"] = toolsets
    tools = toolsets.get("api_server")
    if not isinstance(tools, list):
        tools = [tools] if isinstance(tools, str) else []
        toolsets["api_server"] = tools
    if enabled:
        if "skills" in tools:
            return False
        tools.append("skills")
    else:
        if "skills" not in tools:
            return False
        tools = [tool for tool in tools if tool != "skills"]
        toolsets["api_server"] = tools
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_name(f".{config_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        os.replace(str(tmp), str(config_path))
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return True