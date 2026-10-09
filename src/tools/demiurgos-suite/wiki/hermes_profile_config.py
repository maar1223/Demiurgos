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

``provision_test_profile`` (WU-3, REQ-TPP-1..5) reuses the same idempotent
writers to build a dedicated ``HERMES_HOME``-layout test profile for the live
probe: it enables the ``demiurgos-idea-capture`` plugin, adds the ``skills``
toolset, registers the owned skills folder, disables the telegram platform
(REQ-TPP-6, WU-4), and raises ``logging.level`` to ``DEBUG`` (REQ-LPH-8, WU-4).
It refuses the personal ``~/.hermes`` profile (P0-8) and never writes outside
the requested root.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

#: Canonical location of the Demiurgos-owned skills folder under a checkout root.
SKILLS_DIR_REL = Path("data") / "methodology" / "skills"

#: The gateway plugin a provisioned test profile must opt into (REQ-TPP-1).
PLUGIN_NAME = "demiurgos-idea-capture"

#: The personal Hermes profile provisioning must never touch (P0-8, REQ-TPP-4).
PERSONAL_HERMES_HOME = Path.home() / ".hermes"


class ProfileProvisioningError(RuntimeError):
    """Refused to provision a profile (P0-8 personal home, or a bad root)."""


def is_personal_hermes_home(root: Path) -> bool:
    """True when ``root`` resolves to the personal ``~/.hermes`` profile (P0-8)."""
    return Path(root).expanduser().resolve() == PERSONAL_HERMES_HOME.resolve()


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


def merge_plugins_enabled(config_path: Path, plugin_name: str) -> bool:
    """Ensure ``config_path`` has ONE ``plugins.enabled`` list containing ``plugin_name``.

    Same idempotent-YAML shape as :func:`merge_skills_external_dirs`: idempotent,
    preserves every sibling key, coerces a scalar/missing list, and never crashes
    on a missing/empty/non-mapping config. Returns True when written, False when
    the entry was already present.
    """
    import yaml

    data = {}
    if config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        data["plugins"] = plugins
    enabled = plugins.get("enabled")
    if not isinstance(enabled, list):
        enabled = [enabled] if isinstance(enabled, str) else []
        plugins["enabled"] = enabled
    if plugin_name in enabled:
        return False
    enabled.append(plugin_name)
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


def merge_platform_disabled(config_path: Path, platform_name: str) -> bool:
    """Ensure ``platforms.<platform_name>.enabled`` is ``False`` (idempotent).

    Sets the explicit-disable marker the gateway's env pass honors
    (``gateway/config_loader.py:142-143`` -> ``gateway/config_env.py:184-190`` /
    ``:385-386``), so no environment credential can start that adapter — for
    telegram this avoids the non-retryable startup conflict that exits the
    gateway ``78`` (REQ-TPP-6). Same idempotent-YAML shape as
    :func:`merge_plugins_enabled`: preserves every sibling key, coerces a
    non-mapping platform block, and returns True when written, False when the
    platform was already disabled.
    """
    import yaml

    data = {}
    if config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    platforms = data.get("platforms")
    if not isinstance(platforms, dict):
        platforms = {}
        data["platforms"] = platforms
    block = platforms.get(platform_name)
    if not isinstance(block, dict):
        block = {}
        platforms[platform_name] = block
    if block.get("enabled") is False:
        return False
    block["enabled"] = False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return True


def merge_logging_level(config_path: Path, level: str) -> bool:
    """Ensure ``logging.level`` equals ``level`` (idempotent; REQ-LPH-8).

    Raises the dedicated profile's ``agent.log`` to ``DEBUG`` so the gateway's
    hook-registration lines (``hermes_cli/plugins.py:914``, DEBUG-only) become
    observable. Same idempotent-YAML shape as :func:`merge_plugins_enabled`:
    preserves every sibling key, coerces a non-mapping ``logging`` block, and
    returns True when written, False when the level already matched.
    """
    import yaml

    data = {}
    if config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    logging_block = data.get("logging")
    if not isinstance(logging_block, dict):
        logging_block = {}
        data["logging"] = logging_block
    if logging_block.get("level") == level:
        return False
    logging_block["level"] = level
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return True


def provision_test_profile(root: Path, repo_root: Path) -> Path:
    """Provision a dedicated ``HERMES_HOME``-layout test profile under ``root``.

    Writes ``<root>/config.yaml`` with the five effects required by the live
    probe's config-level evidence: the ``demiurgos-idea-capture`` plugin opt-in
    (REQ-TPP-1), the ``skills`` toolset in ``platform_toolsets.api_server``
    (REQ-TPP-2), the owned ``skills.external_dirs`` (REQ-TPP-3), a telegram-free
    platform block (REQ-TPP-6), and ``logging.level: DEBUG`` (REQ-LPH-8) so the
    gateway's hook-registration lines become observable in ``agent.log``.

    Refuses the personal ``~/.hermes`` profile and writes nothing under it
    (REQ-TPP-4, P0-8). Re-running is a no-op for all five writers. Returns the
    path of the written ``config.yaml``.
    """
    root = Path(root).expanduser().resolve()
    if is_personal_hermes_home(root):
        raise ProfileProvisioningError(
            f"refused to provision the personal profile {PERSONAL_HERMES_HOME} "
            "(P0-8); target a dedicated test profile root instead"
        )
    root.mkdir(parents=True, exist_ok=True)
    config = root / "config.yaml"
    merge_plugins_enabled(config, PLUGIN_NAME)
    ensure_skills_toolset(config, enabled=True)
    merge_skills_external_dirs(config, resolve_skills_dir(repo_root))
    merge_platform_disabled(config, "telegram")
    merge_logging_level(config, "DEBUG")
    return config