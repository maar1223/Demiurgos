# -*- coding: utf-8 -*-
"""demiurgos-skills-directory (WU 0.2) — idempotent installer YAML merge.

``merge_skills_external_dirs`` registers the Demiurgos-owned skills folder
(``data/methodology/skills``) in the dedicated product profile's
``skills.external_dirs`` exactly once, preserving sibling keys
(``creation_nudge_interval``) and every other top-level key (design
Decision 5, spec ``demiurgos-skills-directory``).

Covered scenarios:
- First run creates exactly one skills block.
- Re-run is idempotent (one entry, one block, file untouched).
- skills.creation_nudge_interval and every other top-level key are preserved.
- Existing external_dirs is appended, not replaced.
- Scalar external_dirs is coerced to a list without data loss.
- Missing / empty / non-mapping config produces a valid mapping, never a crash.
- The merge never touches platform_toolsets (skills stays off until Etapa 3).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import yaml

from hermes_profile_config import merge_skills_external_dirs, resolve_skills_dir


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_first_run_creates_exactly_one_skills_block(tmp_path):
    """Spec 'First run creates exactly one skills block': one `skills:` block
    containing external_dirs with the skills path, and no other top-level key."""
    config = tmp_path / "config.yaml"
    skills = tmp_path / "data" / "methodology" / "skills"

    assert merge_skills_external_dirs(config, skills) is True

    data = _read_yaml(config)
    assert list(data) == ["skills"]
    assert data["skills"]["external_dirs"] == [str(skills.resolve())]


def test_rerun_is_idempotent(tmp_path):
    """Spec 'Re-run is idempotent': one entry, one block, and a no-op run
    reports False without rewriting the file."""
    config = tmp_path / "config.yaml"
    skills = tmp_path / "data" / "methodology" / "skills"

    assert merge_skills_external_dirs(config, skills) is True
    before = config.read_bytes()
    assert merge_skills_external_dirs(config, skills) is False
    assert config.read_bytes() == before

    data = _read_yaml(config)
    assert len(data["skills"]["external_dirs"]) == 1
    assert list(data) == ["skills"]


def test_sibling_key_creation_nudge_interval_preserved(tmp_path):
    """Spec 'Sibling keys are preserved': creation_nudge_interval and every
    other pre-existing top-level key survive the merge."""
    config = tmp_path / "config.yaml"
    skills = tmp_path / "data" / "methodology" / "skills"
    config.write_text(
        textwrap.dedent(
            """\
            model: test-model
            skills:
              creation_nudge_interval: 3
            """
        ),
        encoding="utf-8",
    )

    assert merge_skills_external_dirs(config, skills) is True

    data = _read_yaml(config)
    assert data["skills"]["creation_nudge_interval"] == 3
    assert data["model"] == "test-model"
    assert data["skills"]["external_dirs"] == [str(skills.resolve())]


def test_existing_external_dirs_appended_not_replaced(tmp_path):
    """Spec 'Existing external_dirs is appended, not replaced': the pre-existing
    entry stays and the skills path is added after it."""
    config = tmp_path / "config.yaml"
    skills = tmp_path / "data" / "methodology" / "skills"
    preexisting = str((tmp_path / "other-skills").resolve())
    config.write_text(
        textwrap.dedent(
            f"""\
            skills:
              external_dirs:
                - {preexisting}
            """
        ),
        encoding="utf-8",
    )

    assert merge_skills_external_dirs(config, skills) is True

    data = _read_yaml(config)
    assert data["skills"]["external_dirs"] == [preexisting, str(skills.resolve())]


def test_scalar_external_dirs_coerced_to_list(tmp_path):
    """Spec 'Scalar external_dirs is coerced safely': a lone string becomes a
    list containing the original string plus the skills path — no data loss."""
    config = tmp_path / "config.yaml"
    skills = tmp_path / "data" / "methodology" / "skills"
    scalar = str((tmp_path / "scalar-dir").resolve())
    config.write_text(
        textwrap.dedent(
            f"""\
            skills:
              external_dirs: {scalar}
            """
        ),
        encoding="utf-8",
    )

    assert merge_skills_external_dirs(config, skills) is True

    data = _read_yaml(config)
    assert data["skills"]["external_dirs"] == [scalar, str(skills.resolve())]


def test_missing_config_starts_from_empty_mapping(tmp_path):
    """Spec 'Missing or empty config starts from an empty mapping': the merge
    creates the parent directory and a valid mapping."""
    config = tmp_path / "nested" / "config.yaml"
    skills = tmp_path / "data" / "methodology" / "skills"

    assert merge_skills_external_dirs(config, skills) is True

    data = _read_yaml(config)
    assert data["skills"]["external_dirs"] == [str(skills.resolve())]


def test_empty_config_starts_from_empty_mapping(tmp_path):
    """Spec 'Missing or empty config starts from an empty mapping': an empty
    file is treated as an empty mapping."""
    config = tmp_path / "config.yaml"
    skills = tmp_path / "data" / "methodology" / "skills"
    config.write_text("", encoding="utf-8")

    assert merge_skills_external_dirs(config, skills) is True

    data = _read_yaml(config)
    assert data["skills"]["external_dirs"] == [str(skills.resolve())]


def test_non_mapping_config_does_not_crash(tmp_path):
    """Spec 'Non-mapping config does not crash the install': a YAML list is
    discarded and a valid mapping is written."""
    config = tmp_path / "config.yaml"
    skills = tmp_path / "data" / "methodology" / "skills"
    config.write_text("- just\n- a\n- list\n", encoding="utf-8")

    assert merge_skills_external_dirs(config, skills) is True

    data = _read_yaml(config)
    assert data["skills"]["external_dirs"] == [str(skills.resolve())]


def test_scalar_skills_value_replaced_with_mapping(tmp_path):
    """A non-mapping `skills` value is replaced with a mapping without crashing."""
    config = tmp_path / "config.yaml"
    skills = tmp_path / "data" / "methodology" / "skills"
    config.write_text("skills: legacy-scalar\n", encoding="utf-8")

    assert merge_skills_external_dirs(config, skills) is True

    data = _read_yaml(config)
    assert isinstance(data["skills"], dict)
    assert data["skills"]["external_dirs"] == [str(skills.resolve())]


def test_registered_entry_is_resolved_absolute_path(tmp_path, monkeypatch):
    """Spec 'Folder path is registered in the product profile': the entry is the
    expanded, resolved absolute path even for a ~-containing input."""
    config = tmp_path / "config.yaml"
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    skills = Path("~/data/methodology/skills")

    assert merge_skills_external_dirs(config, skills) is True

    data = _read_yaml(config)
    expected = str((home / "data" / "methodology" / "skills").resolve())
    assert data["skills"]["external_dirs"] == [expected]


def test_merge_never_enables_skills_toolset(tmp_path):
    """Spec 'skills toolset stays disabled until Etapa 3': the merge writes only
    skills.external_dirs and never touches platform_toolsets.api_server."""
    config = tmp_path / "config.yaml"
    skills = tmp_path / "data" / "methodology" / "skills"
    config.write_text(
        textwrap.dedent(
            """\
            platform_toolsets:
              api_server:
                - file
                - terminal
            """
        ),
        encoding="utf-8",
    )

    merge_skills_external_dirs(config, skills)

    data = _read_yaml(config)
    assert data["platform_toolsets"]["api_server"] == ["file", "terminal"]
    assert "skills" not in data["platform_toolsets"]["api_server"]


def test_resolve_skills_dir_points_at_owned_folder(tmp_path):
    """The helper resolves the canonical owned folder under a checkout root."""
    repo_root = tmp_path / "checkout"
    expected = (repo_root / "data" / "methodology" / "skills").resolve()
    assert resolve_skills_dir(repo_root) == expected


# -- ensure_skills_toolset (WU-3.1, REQ-NC-3) ---------------------------------


def test_ensure_skills_toolset_enabled_adds_skills_preserves_siblings(tmp_path):
    """Spec 'Flag ON enables the toolset in the dedicated profile': `skills` is
    appended to platform_toolsets.api_server and every other key/tool survives."""
    from hermes_profile_config import ensure_skills_toolset

    config = tmp_path / "config.yaml"
    config.write_text(
        textwrap.dedent(
            """\
            model: test-model
            platform_toolsets:
              api_server:
                - file
                - terminal
            """
        ),
        encoding="utf-8",
    )

    assert ensure_skills_toolset(config, enabled=True) is True

    data = _read_yaml(config)
    assert data["platform_toolsets"]["api_server"] == ["file", "terminal", "skills"]
    assert data["model"] == "test-model"
    assert not list(config.parent.glob(f".{config.name}.*.tmp"))


def test_ensure_skills_toolset_enabled_creates_missing_keys(tmp_path):
    """A config without platform_toolsets gets the key created, not crashed on."""
    from hermes_profile_config import ensure_skills_toolset

    config = tmp_path / "nested" / "config.yaml"
    assert ensure_skills_toolset(config, enabled=True) is True
    assert _read_yaml(config)["platform_toolsets"]["api_server"] == ["skills"]


def test_ensure_skills_toolset_disabled_removes_only_skills(tmp_path):
    """Spec 'Flag OFF removes only skills': sibling tools and unrelated blocks
    (skills.external_dirs) are preserved byte-for-byte."""
    from hermes_profile_config import ensure_skills_toolset

    config = tmp_path / "config.yaml"
    config.write_text(
        textwrap.dedent(
            """\
            model: test-model
            skills:
              external_dirs:
                - /some/dir
            platform_toolsets:
              api_server:
                - file
                - skills
                - terminal
            """
        ),
        encoding="utf-8",
    )

    assert ensure_skills_toolset(config, enabled=False) is True

    data = _read_yaml(config)
    assert data["platform_toolsets"]["api_server"] == ["file", "terminal"]
    assert data["model"] == "test-model"
    assert data["skills"]["external_dirs"] == ["/some/dir"]


def test_ensure_skills_toolset_desired_state_is_noop_byte_identical(tmp_path):
    """Spec 'Flag OFF leaves the toolset unchanged' (REQ-NC-3 scenario 3): when
    the config is already in the desired state the writer returns False and
    writes nothing — a zero-ON config stays byte-identical."""
    from hermes_profile_config import ensure_skills_toolset

    config = tmp_path / "config.yaml"
    config.write_text(
        "platform_toolsets:\n  api_server:\n    - file\n", encoding="utf-8"
    )
    before = config.read_bytes()
    assert ensure_skills_toolset(config, enabled=False) is False
    assert config.read_bytes() == before

    config_on = tmp_path / "config-on.yaml"
    config_on.write_text(
        "platform_toolsets:\n  api_server:\n    - file\n    - skills\n",
        encoding="utf-8",
    )
    before_on = config_on.read_bytes()
    assert ensure_skills_toolset(config_on, enabled=True) is False
    assert config_on.read_bytes() == before_on


def test_ensure_skills_toolset_scalar_api_server_coerced(tmp_path):
    """A scalar api_server is coerced to a list without data loss."""
    from hermes_profile_config import ensure_skills_toolset

    config = tmp_path / "config.yaml"
    config.write_text(
        "platform_toolsets:\n  api_server: file\n", encoding="utf-8"
    )
    assert ensure_skills_toolset(config, enabled=True) is True
    assert _read_yaml(config)["platform_toolsets"]["api_server"] == ["file", "skills"]


def test_ensure_skills_toolset_missing_config_starts_empty(tmp_path):
    """A missing config produces a valid mapping with the skills tool."""
    from hermes_profile_config import ensure_skills_toolset

    config = tmp_path / "nested" / "config.yaml"
    assert ensure_skills_toolset(config, enabled=True) is True
    data = _read_yaml(config)
    assert data["platform_toolsets"]["api_server"] == ["skills"]