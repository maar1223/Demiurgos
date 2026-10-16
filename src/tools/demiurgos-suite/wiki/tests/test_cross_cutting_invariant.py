# -*- coding: utf-8 -*-
"""Cross-cutting invariant — Etapa 1/2 changes nothing assistant-visible.

Etapa 1 (renderer + materializer + sessions + T-FU-02 hook) and Etapa 2 (trigger
approval surface + publish gate + narrow renderer delta) are additive and inert
with respect to what the model sees. Covered scenarios (spec cross-cutting
'No visible product behavior change in Etapa 2'):

- The legacy server-side projection of an active world's methodology (the
  assistant-visible system prompt) is byte-identical before and after Etapa 1
  materialization + session plumbing, and is independent of the Etapa 2
  trigger-approval provenance (the library record is never mutated; the
  projection is a pure function).
- The model-visible enabled tool set is byte-identical: ``skills`` stays absent
  from ``platform_toolsets.api_server`` and the staging root is never registered
  in ``skills.external_dirs``.
- Materialization writes nothing under the live ``data/methodology/skills/``
  folder, which keeps holding only its tracked sentinel.
- The legacy channel projection module (``contract_projection.py``) is unchanged
  versus the merge base with ``master`` (skipped when git is unavailable). The
  byte-freeze is narrowed to the projection: the later change
  ``sistema-foundational-skill`` intentionally advances ``skill_router.py`` by
  routing a transversal foundational skill (``narrative-system-creation``) into
  the legacy router pool, so the router is no longer part of this snapshot. The
  dormant-legacy **presence** guard (``test_dormant_legacy_guard.py``) keeps
  preventing its premature deletion.
- A partial Etapa 2 delivery (a subset of the two new capabilities) changes
  nothing visible: the projection is independent of whether an approval exists.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import api_server
from contract_projection import project_contract_markdown
from hermes_profile_config import merge_skills_external_dirs, resolve_skills_dir
from methodology_library import (
    DEFAULT_FLOW_TYPE,
    Activation,
    PublishedVersion,
    TriggerApproval,
    normalized_trigger_digest,
)
from methodology_trust import FOUNDATIONAL
from skill_materializer import SkillMaterializer, resolve_staging_root
from skill_session_epochs import SessionEpochRegistry, resolve_session_store_path

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

LIVE_SKILLS_DIR = REPO_ROOT / "data" / "methodology" / "skills"
INSTALL_SH = REPO_ROOT / "install.sh"

_PROJECTION = "src/tools/demiurgos-suite/wiki/contract_projection.py"

GIT_AVAILABLE = shutil.which("git") is not None


class _StubLibrary:
    """Minimal in-memory library seam (published + activations + companions)."""

    def __init__(self, *, published=(), activations=None, companions=None, native=None):
        self._published = {(p.skill_id, p.version): p for p in published}
        self._activations = dict(activations or {})
        self._companions = dict(companions or {})
        self._native = dict(native or {})

    def native_channel_enabled(self, world):
        return bool(self._native.get(world, False))

    def set_native_channel(self, world, enabled):
        if enabled:
            self._native[world] = True
        else:
            self._native.pop(world, None)

    def list_published(self):
        return list(self._published.values())

    def get_published(self, skill_id, version):
        return self._published.get((skill_id, version))

    def active_for(self, world, flow_type=DEFAULT_FLOW_TYPE):
        return self._activations.get(world)

    def list_companions(self, world):
        return list(self._companions.get(world, ()))


def _published(
    skill_id,
    version="1.0.0",
    *,
    foundational,
    source="# Body\n",
    trigger_approval=None,
):
    return PublishedVersion(
        skill_id=skill_id,
        version=version,
        name=skill_id,
        description=f"{skill_id} trigger",
        phases=("discovery",),
        language=None,
        source=source,
        digest="0" * 64,
        published_at="2026-01-01T00:00:00+00:00",
        trust_attributes=(FOUNDATIONAL,) if foundational else (),
        adjuntos=(),
        trigger_approval=trigger_approval,
    )


def _approval(text):
    return TriggerApproval(
        text=text,
        digest=normalized_trigger_digest(text),
        approved_by="author",
        approved_at="2026-01-01T00:00:00+00:00",
    )


def _activation(world, skill_id, version):
    return Activation(
        world=world,
        skill_id=skill_id,
        version=version,
        digest="0" * 64,
        activated_at="2026-01-01T00:00:00+00:00",
        flow_type=DEFAULT_FLOW_TYPE,
    )


def _library():
    transversal = _published("alpha", foundational=True)
    guided = _published("guia", foundational=False)
    return _StubLibrary(
        published=[transversal, guided],
        activations={"W": _activation("W", "guia", "1.0.0")},
    )


def _snapshot(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# -- Prompt + toolset byte-identical -----------------------------------------


def test_legacy_projection_byte_identical_after_materialization(tmp_path):
    """Scenario 'System prompt ... byte-identical to baseline': the legacy
    projection of the active world's method is unchanged by Etapa 1 render +
    materialization + session plumbing."""
    library = _library()
    guided = library.get_published("guia", "1.0.0")
    baseline = project_contract_markdown(guided).encode("utf-8")

    report = SkillMaterializer(library, project_root=tmp_path).materialize("W")
    assert report.ok is True
    assert report.revision

    SessionEpochRegistry(resolve_session_store_path(tmp_path)).observe(
        "W", report.revision
    )

    after = project_contract_markdown(guided).encode("utf-8")
    assert after == baseline


def test_legacy_projection_is_independent_of_trigger_approval():
    """Scenario 'System prompt ... byte-identical' and 'Partial Etapa 2 delivery
    still changes nothing visible': the assistant-visible projection of the
    active world's method is independent of the trigger-approval provenance, so
    a partial delivery (approval record present, absent, or stale) is invisible
    to the model."""
    unapproved = _published("guia", foundational=False)
    baseline = project_contract_markdown(unapproved).encode("utf-8")

    approved = _published(
        "guia",
        foundational=False,
        trigger_approval=_approval("guia trigger"),
    )
    stale = _published(
        "guia",
        foundational=False,
        trigger_approval=_approval("a different trigger"),
    )

    assert project_contract_markdown(approved).encode("utf-8") == baseline
    assert project_contract_markdown(stale).encode("utf-8") == baseline


def test_model_visible_tool_set_is_byte_identical(tmp_path):
    """Scenario 'System prompt and toolset are byte-identical to the Etapa 1
    baseline': the enabled model-visible tool set is unchanged by Etapa 0
    registration and an Etapa 2 materialization pass, and stays skills-free."""
    config = tmp_path / "config.yaml"
    baseline_text = "platform_toolsets:\n  api_server:\n    - file\n    - terminal\n"
    config.write_text(baseline_text, encoding="utf-8")
    baseline_tools = yaml.safe_load(baseline_text)["platform_toolsets"]["api_server"]

    live = resolve_skills_dir(tmp_path)
    merge_skills_external_dirs(config, live)
    assert SkillMaterializer(_library(), project_root=tmp_path).materialize("W").ok

    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert data["platform_toolsets"]["api_server"] == baseline_tools
    assert data["platform_toolsets"]["api_server"] == ["file", "terminal"]
    assert "skills" not in data["platform_toolsets"]["api_server"]
    # Registration landed only in skills.external_dirs, never in the tool set.
    assert str(live) in data["skills"]["external_dirs"]


def test_skills_absent_and_staging_not_registered(tmp_path):
    """Scenario 'skills is still absent from platform_toolsets.api_server' and
    the staging root is not among ``skills.external_dirs``."""
    live = resolve_skills_dir(tmp_path)
    staging = resolve_staging_root(tmp_path)
    assert staging != live

    config = tmp_path / "config.yaml"
    config.write_text(
        "platform_toolsets:\n  api_server:\n    - file\n    - terminal\n",
        encoding="utf-8",
    )
    merge_skills_external_dirs(config, live)

    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert "skills" not in data["platform_toolsets"]["api_server"]
    assert data["platform_toolsets"]["api_server"] == ["file", "terminal"]
    assert str(live) in data["skills"]["external_dirs"]
    assert str(staging) not in data["skills"]["external_dirs"]


def test_materialization_writes_nothing_under_live_folder(tmp_path):
    """Scenario 'No materialized skill leaks into the live folder': a
    materialization pass touches no byte under the registered live folder, which
    keeps holding only its tracked sentinel."""
    before = _snapshot(LIVE_SKILLS_DIR)

    report = SkillMaterializer(_library(), project_root=tmp_path).materialize("W")
    assert report.ok is True

    after = _snapshot(LIVE_SKILLS_DIR)
    assert after == before
    assert [p.name for p in LIVE_SKILLS_DIR.iterdir()] == [".gitkeep"]
    assert list(LIVE_SKILLS_DIR.rglob("SKILL.md")) == []
    # the materializer writes only to its staging tree, never to a live folder
    assert not (tmp_path / "data" / "methodology" / "skills").exists()


def test_installer_never_enables_skills_toolset():
    """Sequencing guard: the installer-written product config never enables the
    ``skills`` toolset in ``platform_toolsets.api_server`` (Etapa 3 owns that)."""
    if not INSTALL_SH.is_file():
        pytest.skip("install.sh absent")
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "platform_toolsets" not in text


# -- Legacy channel projection unchanged -------------------------------------


def test_legacy_channel_projection_unchanged_vs_merge_base():
    """Scenario 'Legacy methodology channel is untouched and still serving': the
    legacy channel projection module (``contract_projection.py``) is
    byte-unchanged versus the merge base with master.

    The freeze is narrowed to the projection. ``skill_router.py`` is
    intentionally advanced by the later change ``sistema-foundational-skill``,
    which routes a transversal foundational skill (``narrative-system-creation``)
    into the legacy router pool, so its snapshot premise no longer holds. The
    dormant-legacy presence guard (``test_dormant_legacy_guard.py``) still
    prevents premature deletion of the legacy channel."""
    if not GIT_AVAILABLE:
        pytest.skip("git unavailable")

    base = subprocess.run(
        ["git", "merge-base", "HEAD", "master"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if base.returncode != 0 or not base.stdout.strip():
        pytest.skip("merge-base with master unavailable")
    merge_base = base.stdout.strip()

    # Router excluded: `sistema-foundational-skill` deliberately routes a
    # transversal foundational skill into skill_router.py, so only the untouched
    # projection module stays byte-frozen against the merge base.
    result = subprocess.run(
        ["git", "diff", "--quiet", merge_base, "--", _PROJECTION],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"legacy channel projection changed vs merge-base {merge_base}: "
        f"{result.stdout}{result.stderr}"
    )


# -- Native channel flag gates: zero-ON byte-identical across the request matrix


class _FakeRouter:
    """Deterministic router seam whose legacy result proves the OFF control."""

    def __init__(self, skill_id="narrative-draft"):
        self._skill_id = skill_id

    async def route(self, prompt, mundo, distilled_state=None):
        return api_server.SkillRouteResult(self._skill_id, 0.9, "llm", True)


def _native_published():
    return _published("guia", foundational=False)


@pytest.fixture()
def native_matrix(tmp_path, monkeypatch):
    """Hermetic zero-ON env: dedicated profile + mundo, probe OPEN, personal
    ``~/.hermes`` never resolved (P0-8). Mirrors the WU-3.2 suppression env so
    the cross-cutting default byte-identical gate can assert the flag-OFF
    control on the same seams the flag-ON suppression is tested against."""
    project_root = tmp_path / "proyecto"
    (project_root / "mundos" / "W").mkdir(parents=True)
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    monkeypatch.setattr(api_server, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(api_server, "MUNDOS_DIR", project_root / "mundos")
    monkeypatch.setattr(api_server, "_active_world", lambda: "W")
    library = _StubLibrary(
        published=[_native_published()],
        activations={"W": _activation("W", "guia", "1.0.0")},
    )
    monkeypatch.setattr(api_server, "_methodology_library", lambda: library)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", None)
    monkeypatch.setattr(api_server, "_PROBE_PASSED", True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    api_server._NATIVE_HEALTH_MEMO.clear()
    ns = SimpleNamespace(
        project_root=project_root,
        library=library,
        hermes_home=hermes_home,
        profile_config=hermes_home / "config.yaml",
    )
    yield ns
    api_server._NATIVE_HEALTH_MEMO.clear()


def _write_profile(native_matrix, tools=("file",)):
    native_matrix.profile_config.parent.mkdir(parents=True, exist_ok=True)
    lines = ["platform_toolsets:", "  api_server:"] + [f"    - {t}" for t in tools]
    native_matrix.profile_config.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _companions():
    return [SimpleNamespace(skill_id="guia", version="1.0.0", world="W")]


def test_zero_on_state_is_legacy(native_matrix):
    """With zero worlds opted in the tri-state is ``legacy`` (REQ-NC-2 / D1)."""
    assert api_server._native_channel_enabled("W") is False
    assert api_server._active_channel_state() == "legacy"


def test_zero_on_full_request_matrix_is_byte_identical(native_matrix, monkeypatch):
    """REQ-LMP-3 / cross-cutting default byte-identical: with zero worlds opted
    in every legacy seam over the full request matrix behaves exactly as at
    baseline — (a) non-guided ``/ai/ask`` routing, (b) streaming companion
    contract, (c) ``/api/chat`` semantic gate, (d) guided contract resolver.

    Suppression applies ONLY when the flag is ON (WU-3.2); the existing suite
    is never inverted to a "deleted" expectation (D3)."""
    fake = _FakeRouter("narrative-draft")
    monkeypatch.setattr(api_server, "_SKILL_ROUTER", fake)

    # (a) non-guided /ai/ask self-contained routing: legacy router result.
    assert asyncio.run(api_server._route_skill("Hola", "W", None)) == "narrative-draft"

    # (b) streaming companion contract: the legacy marker is still emitted.
    companion = api_server._companion_contract_for("guia", _companions(), "W")
    assert companion is not None
    assert "[Companion methodology:" in companion

    # (c) /api/chat semantic gate: unwired provider fails closed, and no legacy
    # compiled-contract content leaks into the gate envelope.
    gate = asyncio.run(api_server._semantic_gate("W", "Hola"))
    assert gate.unavailable is True
    assert "compiled_contract" not in str(gate.as_dict())

    # (d) guided path resolvers: the compiled contract is not suppressed.
    assert api_server._compiled_contract_markdown("W") is not None
    # no seeded specimen carrier at baseline ⇒ None (unchanged by the flag).
    assert (
        api_server._convergence_specimen_markdown(
            "W", api_server.DEFAULT_FLOW_TYPE, None
        )
        is None
    )

    # D4 session id is unchanged when the channel is legacy.
    assert api_server._channel_session_id("sess-1") == "sess-1"


def test_zero_on_toolset_reconcile_is_config_byte_identical(native_matrix):
    """REQ-NC-3 scenario 3: with zero ON and the probe gate open the reconcile
    is a no-op and the dedicated profile config stays byte-identical."""
    _write_profile(native_matrix, ("file",))
    before = native_matrix.profile_config.read_bytes()
    assert api_server._sync_native_channel("W") is False
    assert native_matrix.profile_config.read_bytes() == before
    data = yaml.safe_load(native_matrix.profile_config.read_text(encoding="utf-8"))
    assert data["platform_toolsets"]["api_server"] == ["file"]
    assert "skills" not in data["platform_toolsets"]["api_server"]
