# -*- coding: utf-8 -*-
"""WU-3.0 — real-Hermes pre-flight probe gate (REQ-NC-1), behavior-neutral.

The gate for the entire Hermes Etapa 3 cut (proposal D-gate, design §7 WU-3.0,
spec REQ-NC-1): nothing may enable the native channel (per-world flag ON,
``skills`` toolset enable, or live promotion) until a probe has proven **all
four** conditions against a dedicated Hermes TEST profile:

(a) both gateway hooks are registered and live — the ``pre_tool_call``
    ``skill_manage`` veto and the ``pre_llm_call`` cache-clear;
(b) enabling ``skills`` in ``platform_toolsets.api_server`` of the dedicated
    profile has the intended effect (the model can see/load native skills);
(c) the in-process cache-clear works (``clear_skills_system_prompt_cache_safe``
    through the ``pre_llm_call`` seam);
(d) ``skill_manage`` is vetoed (blocked), fail-closed.

It also records the design's open question Q1 — does the toolset flip need a
gateway restart? — as ``Q1_GATEWAY_RESTART_REQUIRED``, consumed by the WU-3.4
runbook.

Environment honesty (mandatory): the deterministic tests below run EVERYWHERE
and prove the four conditions to the level provable without a gateway process.
The live-gateway test (``test_live_gateway_probe``) boots the real Hermes
gateway on a dedicated test profile and is skipped here with an exact reason
when no such profile exists — never fabricated.

Covered tasks: 3.0.1 (test profile via ``assistant_settings._resolve_profile_paths``,
read-only, P0-8 isolation), 3.0.2 (hooks live), 3.0.3 (toolset effect + Q1),
3.0.4 (cache-clear), 3.0.5 (skill_manage veto), 3.0.6 (behavior-neutrality),
3.0.7 (``_probe_passed`` gate predicate, default closed), 3.0.8 (no production
surface changed — the dedicated config and live folder stay byte-identical).
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import api_server
import hermes_gateway_hooks as hooks
from assistant_settings import _resolve_profile_paths
from hermes_gateway_hooks import (
    SKILL_MANAGE_BLOCK_MESSAGE,
    clear_skills_system_prompt_cache_safe,
    revision_marker_signature,
)
from hermes_profile_config import (
    SEED_SKILL_NAME,
    merge_skills_external_dirs,
    resolve_skills_dir,
)

import hermes_probe_support as probe_support

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

_PLUGIN_INIT = (
    REPO_ROOT / ".hermes" / "plugins" / "demiurgos-idea-capture" / "__init__.py"
)

#: The personal Hermes profile the probe MUST never resolve to or write (P0-8).
_PERSONAL_HERMES_HOME = Path.home() / ".hermes"

#: Q1 answer (recorded for the WU-3.4 runbook; pinned by
#: ``test_q1_toolset_flip_takes_effect_without_gateway_restart`` against the
#: installed runtime source): ``platform_toolsets`` is resolved PER AGENT TURN
#: and the gateway config is re-read when the file's ``(mtime_ns, size)``
#: changes, so flipping ``skills`` in lands on the next turn — NO restart.
#: ``False`` means a restart is NOT required.
Q1_GATEWAY_RESTART_REQUIRED = False


# Re-point the local error types at the shared helper's (REQ-LPH-5): the helper
# is the single authority for the P0-8 predicate and the root resolver.
_ProbeIsolationError = probe_support.ProbeIsolationError
_ProbeUnavailable = probe_support.ProbeUnavailable


def _assert_not_personal_profile(root: Path) -> None:
    """P0-8 hard guard delegate: the shared helper owns the predicate."""
    probe_support.assert_not_personal_profile(root)


@dataclass(frozen=True)
class _ProbeProfile:
    """A dedicated Hermes TEST profile: ``HERMES_HOME`` layout, default active."""

    root: Path
    config: Path  # == _resolve_profile_paths().config


def _make_test_profile(base: Path, monkeypatch: pytest.MonkeyPatch) -> _ProbeProfile:
    """Build a dedicated TEST profile under ``base`` and resolve it exactly the
    way the runtime resolves the dedicated product profile (read-only)."""
    root = (base / "hermes-home").resolve()
    root.mkdir(parents=True, exist_ok=True)
    _assert_not_personal_profile(root)
    monkeypatch.setenv("HERMES_HOME", str(root))
    paths = _resolve_profile_paths()
    assert paths.root == root, "profile resolution must match the test root"
    return _ProbeProfile(root=root, config=paths.config)


def _load_plugin():
    """Import the gateway plugin module in-process (stdlib-only module body)."""
    assert _PLUGIN_INIT.is_file(), f"plugin not found: {_PLUGIN_INIT}"
    spec = importlib.util.spec_from_file_location(
        "demiurgos_probe_plugin", _PLUGIN_INIT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    """The imported gateway plugin module (the real code, not a mock)."""
    return _load_plugin()


def _snapshot_tree(root: Path) -> dict[str, str]:
    """sha256 snapshot of every file under ``root`` (relative path -> digest)."""
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _counting_clearer(monkeypatch: pytest.MonkeyPatch):
    """Install the first-candidate cache clearer (records calls); second is None."""
    calls: list[bool] = []

    def clearer():
        calls.append(True)

    monkeypatch.setitem(
        sys.modules,
        "agent.prompt_builder",
        SimpleNamespace(clear_skills_system_prompt_cache=clearer),
    )
    monkeypatch.setitem(
        sys.modules, "prompt_builder", SimpleNamespace(clear_skills_system_prompt_cache=None)
    )
    return calls


# -- (a) hooks registered and live (3.0.2) -----------------------------------


def test_plugin_register_wires_both_gateway_hooks(plugin):
    """(a) registration: ``register()`` wires the ``pre_tool_call`` veto and the
    ``pre_llm_call`` cache-clear, both outside the ai-mode branch."""
    source = inspect.getsource(plugin.register)
    assert 'ctx.register_hook("pre_tool_call", _veto_skill_manage_hook)' in source
    assert 'ctx.register_hook("pre_llm_call", _invalidate_skills_cache_hook)' in source
    for line in source.splitlines():
        if "register_hook" in line and "_veto_skill_manage_hook" in line:
            assert line.startswith("    ctx.register_hook("), line
        if "register_hook" in line and "_invalidate_skills_cache_hook" in line:
            assert line.startswith("    ctx.register_hook("), line


def test_pre_tool_call_wrapper_is_live(plugin):
    """(a) live: the registered ``pre_tool_call`` wrapper fires against the pure
    veto — blocking ``skill_manage`` and allowing every other tool, never
    raising."""
    assert plugin._veto_skill_manage_hook(tool_name="skill_manage") == {
        "action": "block",
        "message": SKILL_MANAGE_BLOCK_MESSAGE,
    }
    for name in ("skills_list", "skill_view", "read", "bash", "capture_idea", "", None):
        assert plugin._veto_skill_manage_hook(tool_name=name) is None


def test_pre_llm_call_wrapper_is_live(plugin):
    """(a) live: the registered ``pre_llm_call`` wrapper returns ``None`` (the
    guidance-neutral contract) and never raises, even with a missing marker
    (Etapa 0 unconditional-clear degrade path in a non-gateway process)."""
    result = plugin._invalidate_skills_cache_hook()
    assert result is None


def test_pre_llm_call_wrapper_forwards_marker_path(plugin):
    """(c) registration: the invalidation wrapper routes the resolved
    revision-marker path into the guarded clearer — that is the seam WU-3.1's
    promotion invalidates through."""
    source = inspect.getsource(plugin._invalidate_skills_cache_hook)
    assert (
        "clear_skills_system_prompt_cache_safe(marker_path=_SKILLS_REVISION_MARKER)"
        in source
    )


# -- (b) skills toolset effect (3.0.3) ---------------------------------------


def test_baseline_profile_toolset_excludes_skills(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """(b) baseline: the dedicated profile starts skills-free — the pre-flip
    shape that the probe itself never mutates."""
    profile = _make_test_profile(tmp_path, monkeypatch)
    profile.config.write_text(
        "platform_toolsets:\n  api_server:\n    - file\n    - terminal\n",
        encoding="utf-8",
    )
    data = yaml.safe_load(profile.config.read_text(encoding="utf-8"))
    assert data["platform_toolsets"]["api_server"] == ["file", "terminal"]
    assert "skills" not in data["platform_toolsets"]["api_server"]


def test_toolset_flip_expresses_skills_for_api_server(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """(b) intended effect, config level: with ``skills`` enabled under
    ``platform_toolsets.api_server``, the dedicated profile config carries the
    flip the runtime resolves per turn (Q1 test below) — the model is offered
    the read-only skills tools from the next turn on."""
    profile = _make_test_profile(tmp_path, monkeypatch)
    profile.config.write_text(
        "platform_toolsets:\n  api_server:\n    - file\n    - terminal\n",
        encoding="utf-8",
    )
    data = yaml.safe_load(profile.config.read_text(encoding="utf-8"))
    data["platform_toolsets"]["api_server"].append("skills")
    profile.config.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    flipped = yaml.safe_load(profile.config.read_text(encoding="utf-8"))
    assert "skills" in flipped["platform_toolsets"]["api_server"]


def _hermes_agent_dir() -> Path | None:
    """Resolve the installed Hermes agent root (runtime source evidence)."""
    override = os.environ.get("DEMIURGOS_HERMES_AGENT_DIR", "").strip()
    if override:
        return Path(override)
    candidate = Path.home() / ".hermes" / "hermes-agent"
    if (candidate / "gateway" / "run_turn.py").is_file():
        return candidate
    return None


def test_q1_toolset_flip_takes_effect_without_gateway_restart():
    """Q1 evidence (pinned to the installed runtime source, consumed by the
    WU-3.4 runbook): the api_server toolset is resolved PER AGENT TURN via
    ``_get_platform_tools`` and the gateway config is cached on
    ``(mtime_ns, size)`` — an atomic temp+replace write (always a new mtime)
    is re-read on the next turn, so the ``skills`` flip needs NO gateway
    restart. Fails loudly if the installed runtime drifts from that contract."""
    agent = _hermes_agent_dir()
    if agent is None:
        pytest.skip(
            "installed hermes-agent runtime not found; Q1 stays "
            f"Q1_GATEWAY_RESTART_REQUIRED={Q1_GATEWAY_RESTART_REQUIRED} "
            "from the WU-3.0 probe artifact (install dir or "
            "DEMIURGOS_HERMES_AGENT_DIR required)"
        )
    run_turn = (agent / "gateway" / "run_turn.py").read_text(encoding="utf-8")
    config_py = (agent / "hermes_cli" / "config.py").read_text(encoding="utf-8")
    tools_config = (agent / "hermes_cli" / "tools_config.py").read_text(encoding="utf-8")

    # Per-turn toolset resolution on the run path.
    assert "def _resolve_turn_toolsets" in run_turn
    assert "_get_platform_tools(user_config, platform_key)" in run_turn
    # The turn path loads the gateway config per turn (not a boot snapshot).
    assert "user_config = _load_gateway_config()" in run_turn
    # The config read is cached on (mtime_ns, size): a rewritten config is
    # re-read next turn — the flip lands without a restart.
    assert "cache_key = (st.st_mtime_ns, st.st_size)" in config_py
    # platform_toolsets is the live per-platform enabled-list source.
    assert 'config.get("platform_toolsets")' in tools_config

    assert Q1_GATEWAY_RESTART_REQUIRED is False


# -- (c) in-process cache-clear (3.0.4) --------------------------------------


@pytest.fixture
def fresh_guard(monkeypatch: pytest.MonkeyPatch):
    """Reset the in-process last-seen marker so guard tests stay isolated."""
    monkeypatch.setattr(hooks, "_LAST_SEEN_MARKER", hooks._UNSEEN)


def test_marker_change_triggers_single_clear_then_noop(
    tmp_path, monkeypatch: pytest.MonkeyPatch, fresh_guard
):
    """(c) in-process seam: a marker change makes the next turn clear once; an
    unchanged marker is a no-op (guard recorded) — the exact 'marker change
    clears on the next gateway turn' contract."""
    marker = tmp_path / ".demiurgos-revision"
    marker.write_bytes(b"rev-1\n")
    calls = _counting_clearer(monkeypatch)

    assert clear_skills_system_prompt_cache_safe(marker_path=str(marker)) is True
    assert len(calls) == 1
    assert clear_skills_system_prompt_cache_safe(marker_path=str(marker)) is True
    assert len(calls) == 1  # unchanged marker: no-op

    marker.write_bytes(b"rev-2\n")
    assert clear_skills_system_prompt_cache_safe(marker_path=str(marker)) is True
    assert len(calls) == 2


def test_cache_clear_seam_degrades_without_raising_outside_gateway(
    plugin, monkeypatch: pytest.MonkeyPatch
):
    """(c) honest degrade: when no clearer module is importable the seam reports
    False and the wrapper stays a no-op — never raising into the turn. The
    isolation is explicit because a later plugin-loading test can put the real
    hermes-agent on ``sys.path`` mid-suite (suite-order independent)."""
    monkeypatch.setitem(sys.modules, "agent.prompt_builder", None)
    monkeypatch.setitem(sys.modules, "prompt_builder", None)
    assert clear_skills_system_prompt_cache_safe() is False  # no clearer present
    assert plugin._invalidate_skills_cache_hook() is None


# -- (d) skill_manage veto fail-closed (3.0.5) -------------------------------


def test_veto_is_fail_closed_for_skill_manage():
    """(d) fail-closed: ``skill_manage`` is either blocked with a non-empty
    message (Hermes requires it for a block directive) or, for non-matching
    tools, allowed — there is no path that silently permits skill_manage."""
    directive = hooks.skill_manage_veto("skill_manage")
    assert directive == {"action": "block", "message": SKILL_MANAGE_BLOCK_MESSAGE}
    assert isinstance(SKILL_MANAGE_BLOCK_MESSAGE, str) and SKILL_MANAGE_BLOCK_MESSAGE
    assert hooks.skill_manage_veto("skills_list") is None
    assert hooks.skill_manage_veto("skill_view") is None


# -- behavior-neutrality (3.0.6) ---------------------------------------------


def test_probe_profile_guard_refuses_personal_home(
    monkeypatch: pytest.MonkeyPatch
):
    """P0-8 isolation: the probe refuses to resolve or write the personal
    ``~/.hermes`` profile — fail-closed, never a silent fallback."""
    monkeypatch.setenv("HERMES_HOME", str(_PERSONAL_HERMES_HOME))
    with pytest.raises(_ProbeIsolationError):
        _assert_not_personal_profile(_resolve_profile_paths().root)


def test_probe_run_is_behavior_neutral(
    tmp_path, monkeypatch: pytest.MonkeyPatch, plugin
):
    """(3.0.6 / REQ-NC-1 scenario 3) a probe session against a dedicated TEST
    profile leaves the baseline surface byte-identical: the dedicated profile
    config, the repo's live ``data/methodology/skills/`` folder, and (via the
    P0-8 guard) any personal profile stay untouched. The probe writes ONLY
    inside its own test profile root."""
    # Baseline surface: a dedicated profile config that the probe must not touch.
    dedicated_root = tmp_path / "dedicated-profile"
    dedicated_root.mkdir()
    baseline = "platform_toolsets:\n  api_server:\n    - file\n    - terminal\n"
    dedicated_config = dedicated_root / "config.yaml"
    dedicated_config.write_text(baseline, encoding="utf-8")
    dedicated_before = dedicated_config.read_bytes()
    live_before = _snapshot_tree(resolve_skills_dir(REPO_ROOT))

    # A probe session against ITS OWN test profile.
    profile = _make_test_profile(tmp_path, monkeypatch)
    profile.config.write_text(baseline, encoding="utf-8")
    assert profile.root != dedicated_root.resolve()
    _ = _inspect_live_guard_chain(plugin)  # veto + cache wrappers fire

    assert dedicated_config.read_bytes() == dedicated_before
    assert _snapshot_tree(resolve_skills_dir(REPO_ROOT)) == live_before
    # Everything the probe wrote lives under the test profile root.
    written = {
        path.relative_to(profile.root).as_posix()
        for path in profile.root.rglob("*")
        if path.is_file()
    }
    assert written == {"config.yaml"}


def _inspect_live_guard_chain(plugin) -> tuple[dict | None, None]:
    """Drive the two registered hook wrappers once (live chain, never raises)."""
    veto = plugin._veto_skill_manage_hook(tool_name="skill_manage")
    cache = plugin._invalidate_skills_cache_hook()
    assert veto == {"action": "block", "message": SKILL_MANAGE_BLOCK_MESSAGE}
    assert cache is None
    return veto, cache


# -- _probe_passed gate predicate (3.0.7) ------------------------------------


def test_probe_gate_defaults_closed():
    """(REQ-NC-1 scenario 2) until the probe passes, the enablement gate is
    closed: flag ON, toolset enable and promotion are all blocked (consumed by
    WU-3.1/3.2 ``_materialize_skills``)."""
    assert api_server._probe_passed() is False


def test_probe_gate_opens_only_when_probe_passed(monkeypatch: pytest.MonkeyPatch):
    """(3.0.7) the predicate is the openable gate: a recorded probe pass opens
    it; the default stays closed. Behavior-neutral by construction — nothing
    consumes the gate yet."""
    assert api_server._probe_passed() is False
    monkeypatch.setattr(api_server, "_PROBE_PASSED", True)
    assert api_server._probe_passed() is True


# -- live gateway probe (3.0.1/3.0.3 live; honest skip unless provisioned) ----


def _dedicated_test_root_from_env() -> Path:
    """Resolve the dedicated TEST profile root via the shared helper (REQ-LPH-5).

    Raises ``ProbeUnavailable`` when not provisioned and ``ProbeIsolationError``
    when the root resolves to the personal profile."""
    return probe_support.resolve_dedicated_profile_root()


def _boot_and_probe_gateway(
    hermes_bin: str,
    home: Path,
    *,
    timeout: float = probe_support.DEFAULT_TIMEOUT,
) -> probe_support.ProbeResult:
    """Delegate the real boot/read/teardown to the shared helper (REQ-LPH-5)."""
    return probe_support.boot_and_probe_gateway(hermes_bin, home, timeout=timeout)


def _assert_profile_condition_b_config_level(home: Path) -> None:
    """Condition (b) at config level (REQ-NC-1): the provisioned profile carries
    the ``skills`` toolset AND the owned skills external dir."""
    data = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    assert "skills" in data["platform_toolsets"]["api_server"], (
        "condition (b): skills toolset missing from platform_toolsets.api_server"
    )
    external = data.get("skills", {}).get("external_dirs", [])
    assert str(resolve_skills_dir(REPO_ROOT)) in external, (
        "condition (b): owned skills dir missing from skills.external_dirs"
    )


def test_live_gateway_probe(plugin):
    """(3.0.1/3.0.3 live) Boot the real Hermes gateway on a dedicated TEST
    profile and assert the four conditions end-to-end.

    Enabled only with ``DEMIURGOS_PROBE_LIVE=1`` and a provisioned dedicated
    profile; otherwise SKIPPED with the exact reason (the only running gateway
    is the personal profile, which the probe must never touch, P0-8), so the
    deterministic in-process probe above is the executed evidence. A failing run
    here FAILS loudly, never silently passes. Condition (a) is asserted from the
    gateway log; (c)/(d) are proven in-process via the registered hook callables;
    (b) is asserted at config level (model-level (b) is deferred, not claimed)."""
    if not probe_support.live_probe_enabled():
        pytest.skip(
            "live gateway probe disabled (DEMIURGOS_PROBE_LIVE=1 required); "
            "WU-3.0 deterministic in-process probe executed instead"
        )
    hermes_bin = shutil.which("hermes")
    if hermes_bin is None:
        pytest.skip("hermes binary not found on PATH")
    try:
        home = _dedicated_test_root_from_env()
    except _ProbeUnavailable as exc:
        pytest.skip(str(exc))
    except _ProbeIsolationError as exc:
        pytest.fail(str(exc))  # isolation is a hard fail, never a skip

    try:
        result = _boot_and_probe_gateway(hermes_bin, home)
    except probe_support.ProbeLogDriftError as exc:
        pytest.skip(str(exc))  # log-path drift is an honest skip, never a pass

    # (a) live: both hooks registered, observed from the gateway log.
    assert result.booted, (
        "gateway did not come up with hook evidence; "
        f"returncode={result.returncode}"
    )
    joined = "\n".join(result.hook_evidence).lower()
    assert (
        "registered hook: pre_tool_call" in joined
        and "registered hook: pre_llm_call" in joined
    ), (
        "both 'registered hook: pre_tool_call' and 'registered hook: pre_llm_call' "
        f"must appear in the gateway log; saw {result.hook_evidence!r}"
    )

    # (c)/(d) live, in-process: the registered hook callables fire fail-closed.
    _inspect_live_guard_chain(plugin)

    # (b) config level against the provisioned profile.
    _assert_profile_condition_b_config_level(home)


# -- runtime-anchor guard: agent.log path (R6) -------------------------------


def test_gateway_runtime_anchor_names_agent_log():
    """R6 guard: text-scan the installed runtime for the ``agent.log`` filename
    the helper depends on, mirroring the ``test_q1_...`` skip-on-absence pattern.
    Skips honestly when the pinned runtime is absent (the helper's
    ``ProbeLogDriftError`` skip is the runtime fallback)."""
    agent = _hermes_agent_dir()
    if agent is None:
        pytest.skip("installed hermes-agent runtime not found; log-path anchor unchecked")
    logging_py = agent / "hermes_logging.py"
    if not logging_py.is_file():
        pytest.skip(f"runtime anchor {logging_py} absent; log-path anchor unchecked")
    source = logging_py.read_text(encoding="utf-8")
    assert "agent.log" in source, (
        "installed runtime no longer names agent.log in hermes_logging.py; the "
        "helper's <HERMES_HOME>/logs/agent.log assumption has drifted"
    )


def test_gateway_runtime_anchor_names_registered_hook_phrasing():
    """R6/R10 guard: the installed runtime's hook-registration line keeps the
    ``registered <kind>: <key>`` phrasing the helper matches (DEBUG, plugins.py).
    A phrasing change must fail loudly, never turn the probe into a false pass."""
    agent = _hermes_agent_dir()
    if agent is None:
        pytest.skip("installed hermes-agent runtime not found; hook-marker anchor unchecked")
    plugins_py = agent / "hermes_cli" / "plugins.py"
    if not plugins_py.is_file():
        pytest.skip(f"runtime anchor {plugins_py} absent; hook-marker anchor unchecked")
    source = plugins_py.read_text(encoding="utf-8")
    assert "registered %s: %s" in source, (
        "installed runtime no longer logs 'registered %s: %s' in hermes_cli/plugins.py; "
        "the helper's 'registered hook: <name>' markers have drifted (R10)"
    )


# -- WU-3: model-level condition (b) (REQ-NC-1 / REQ-LPH-9 / REQ-TPP-7) --------

#: The model credential the dedicated profile resolves HOME-SCOPED
#: (hermes_cli/auth.py opencode-go registry tuple; REQ-TPP-7). The operator
#: supplies it via export or ``<profile>/.env`` — the dedicated profile does NOT
#: inherit the personal ``~/.hermes/.env`` (P0-8).
_MODEL_CREDENTIAL_ENV = "OPENCODE_GO_API_KEY"

#: Bounded discovery prompt maximizing the reply-names-skill evidence arm
#: (design open decision; REQ-LPH-9).
_MODEL_PROMPT = "List every skill you currently have available, by name."


def _model_credential_present(home: Path) -> bool:
    """Home-scoped model-credential check (REQ-TPP-7), P0-8 safe.

    True iff ``OPENCODE_GO_API_KEY`` is non-empty in the process env OR in
    ``<home>/.env``. NEVER reads the personal ``~/.hermes`` profile — a key
    exported there (or in its ``.env``) does NOT count for the dedicated home.
    """
    exported = (os.environ.get(_MODEL_CREDENTIAL_ENV) or "").strip()
    if exported.strip("\"'") and exported:
        return True
    env_file = Path(home) / ".env"
    if not env_file.is_file():
        return False
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        value = raw.strip().strip("\"'")
        if key.strip() == _MODEL_CREDENTIAL_ENV and value:
            return True
    return False


def _assert_skill_in_prompt_assembly(home: Path, skill_name: str) -> str:
    """DETERMINISTIC prompt-assembly sub-check (REQ-LPH-9), LABELED non-turn.

    Runs the installed runtime's ``build_skills_system_prompt()`` in a subprocess
    (Hermes venv python, ``HERMES_HOME=<home>``, ``PYTHONPATH=<agent dir>``) and
    asserts the composed ``## Skills`` / ``<available_skills>`` block names
    ``skill_name``. Skips honestly when the runtime/venv is absent. This is NOT a
    real turn and is never a substitute for the model-level evidence — it only
    proves the seeded skill is composable into the system prompt. Returns the
    evidence label so callers surface it as prompt-assembly level.
    """
    agent = _hermes_agent_dir()
    if agent is None:
        pytest.skip(
            "installed hermes-agent runtime not found; prompt-assembly sub-check "
            "unavailable (non-turn evidence skipped honestly)"
        )
    venv_py = agent / "venv" / "bin" / "python"
    if not venv_py.is_file():
        pytest.skip(
            f"Hermes venv python absent at {venv_py}; prompt-assembly sub-check "
            "unavailable (non-turn evidence skipped honestly)"
        )
    probe = (
        "import sys; "
        "from agent.prompt_builder import build_skills_system_prompt; "
        "sys.stdout.write(build_skills_system_prompt())"
    )
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    env["DEMIURGOS_HERMES_HOME"] = str(home)
    env["PYTHONPATH"] = str(agent)
    completed = subprocess.run(
        [str(venv_py), "-c", probe],
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60.0,
    )
    assert completed.returncode == 0, (
        "prompt-assembly sub-check subprocess failed: "
        f"{completed.stderr.strip()[:300] or 'no stderr'}"
    )
    composed = completed.stdout
    assert skill_name in composed, (
        "prompt-assembly sub-check: the composed ## Skills / <available_skills> "
        f"block does not name seeded skill {skill_name!r} "
        f"(got {len(composed)} bytes)"
    )
    return (
        "prompt-assembly-level evidence (deterministic, NON-turn): "
        f"{skill_name!r} present in the composed ## Skills / "
        "<available_skills> block"
    )


def test_live_model_level_skills_visibility():
    """Model-level condition (b) (REQ-NC-1 / REQ-LPH-9 / REQ-TPP-7): a real
    assistant turn proves the model sees/loads native skills — opt-in and honest.

    Gate off / no hermes / no profile / no credential -> NAMED skip (no boot).
    ``API_SERVER_KEY`` absent -> NAMED skip; too short -> LOUD fail.
    Prerequisites present -> boot, drive one turn, THEN:
    evidence = ``SEED_SKILL_NAME`` in ``reply_text.lower()``
    OR ``skills_list``/``skill_view`` in the tool-call trace; evidence -> PASS
    (model-level (b) recorded); else ``pytest.fail`` with the observed error,
    never a pass. Then the LABELED prompt-assembly sub-check (non-turn).
    """
    if not probe_support.model_live_enabled():
        pytest.skip(
            "model gate disabled (DEMIURGOS_MODEL_LIVE=1 required); model-level "
            "(b) stays deferred, never claimed"
        )
    hermes_bin = shutil.which("hermes")
    if hermes_bin is None:
        pytest.skip("hermes binary not found on PATH")
    try:
        home = probe_support.resolve_dedicated_profile_root()
    except probe_support.ProbeUnavailable as exc:
        pytest.skip(str(exc))
    except probe_support.ProbeIsolationError as exc:
        pytest.fail(str(exc))  # isolation is a hard fail, never a skip
    if not _model_credential_present(home):
        pytest.skip(
            f"no provider credential for the dedicated profile "
            f"({_MODEL_CREDENTIAL_ENV} in env or <home>/.env required); "
            "model-level (b) stays deferred, never claimed"
        )
    api_key = (os.environ.get("API_SERVER_KEY") or "").strip()
    if not api_key:
        pytest.skip(
            "API_SERVER_KEY unset: the assistant-turn driver cannot authenticate; "
            "model-level (b) stays deferred, never claimed"
        )
    if len(api_key) < probe_support.MIN_API_SERVER_KEY_LEN:
        pytest.fail(
            f"API_SERVER_KEY is too short ({len(api_key)} chars < "
            f"{probe_support.MIN_API_SERVER_KEY_LEN}): credentials are present "
            "but malformed — loud fail, never a pass"
        )

    turn = probe_support.drive_assistant_turn(
        hermes_bin, home, prompt=_MODEL_PROMPT, api_key=api_key
    )
    reply_lower = turn.reply_text.lower()
    evidence = (SEED_SKILL_NAME in reply_lower) or bool(
        {"skills_list", "skill_view"} & set(turn.tool_calls)
    )
    assert evidence, (
        "model-level (b): the assistant turn produced no skill-visibility "
        f"evidence (reply does not name {SEED_SKILL_NAME!r}; tool calls = "
        f"{turn.tool_calls!r}; {turn.error or 'no observed error'}) — "
        "never a false pass"
    )

    # LABELED deterministic prompt-assembly sub-check (NON-turn evidence).
    _assert_skill_in_prompt_assembly(home, SEED_SKILL_NAME)


def test_model_credential_present_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """WU3-01: the operator's process-env export counts as the home-scoped
    credential (no ``<home>/.env`` needed)."""
    home = tmp_path / "home"
    monkeypatch.delenv(_MODEL_CREDENTIAL_ENV, raising=False)
    monkeypatch.setenv(_MODEL_CREDENTIAL_ENV, "placeholder-credential-from-env")
    assert _model_credential_present(home) is True


def test_model_credential_present_from_profile_env_file(tmp_path: Path):
    """WU3-01: ``<home>/.env`` (the dedicated profile scope) counts; the file is
    read without touching the process env and sibling keys are ignored."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(
        f"OTHER=keep\n{_MODEL_CREDENTIAL_ENV}=placeholder-credential-from-profile\n",
        encoding="utf-8",
    )
    assert _model_credential_present(home) is True


def test_model_credential_absent_when_only_personal_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """WU3-01 (P0-8): a key in the PERSONAL ``~/.hermes/.env`` does NOT count.
    The dedicated profile does not inherit personal secrets; the check only
    reads the process env and ``<home>/.env`` of the dedicated root."""
    personal = tmp_path / "personal-home" / ".hermes"
    personal.mkdir(parents=True)
    (personal / ".env").write_text(
        f"{_MODEL_CREDENTIAL_ENV}=sk-personal-only\n", encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "personal-home"))
    monkeypatch.delenv(_MODEL_CREDENTIAL_ENV, raising=False)
    home = tmp_path / "dedicated-home"
    home.mkdir()
    assert _model_credential_present(home) is False


def test_prompt_assembly_subcheck_names_seeded_skill(tmp_path: Path):
    """WU3-02: against a model-turn-provisioned profile the deterministic
    sub-check composes a ``## Skills`` / ``<available_skills>`` block naming the
    seeded skill, and the returned label is explicitly NON-turn. Skips honestly
    when the installed runtime/venv is absent."""
    agent = _hermes_agent_dir()
    if agent is None or not (agent / "venv" / "bin" / "python").is_file():
        pytest.skip(
            "installed hermes-agent runtime/venv absent; prompt-assembly "
            "sub-check proof skipped honestly"
        )
    from hermes_profile_config import provision_model_turn_profile

    root = tmp_path / "profile"
    provision_model_turn_profile(
        root,
        REPO_ROOT,
        provider="opencode-go",
        model="deepseek-v4.1-flash",
        base_url="https://opencode.ai/zen/go/v1",
    )
    label = _assert_skill_in_prompt_assembly(root, SEED_SKILL_NAME)
    assert "NON-turn" in label, "the sub-check must be labeled non-turn evidence"
    assert SEED_SKILL_NAME in label


def test_model_level_skips_when_gate_disabled(monkeypatch: pytest.MonkeyPatch):
    """WU3-03: with the ``DEMIURGOS_MODEL_LIVE`` gate off the model-level test
    skips with the named reason — no boot, no credential needed."""
    monkeypatch.delenv(probe_support.MODEL_LIVE_ENV_VAR, raising=False)
    with pytest.raises(pytest.skip.Exception, match="model gate disabled"):
        test_live_model_level_skills_visibility()


def test_model_level_skips_without_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """WU3-03: with the gate on but no resolvable provider credential the test
    skips naming ``OPENCODE_GO_API_KEY`` — before any gateway boot."""
    monkeypatch.setenv(probe_support.MODEL_LIVE_ENV_VAR, "1")
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/hermes" if name == "hermes" else None)
    home = tmp_path / "home"
    monkeypatch.setenv("DEMIURGOS_HERMES_HOME", str(home))
    monkeypatch.delenv(_MODEL_CREDENTIAL_ENV, raising=False)
    monkeypatch.delenv("API_SERVER_KEY", raising=False)
    with pytest.raises(pytest.skip.Exception, match="no provider credential"):
        test_live_model_level_skills_visibility()
    assert not (home / "driver.pid").exists(), "no gateway may boot on the skip path"


def test_model_level_fails_on_short_api_server_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """WU3-03: credentials present but ``API_SERVER_KEY`` < 16 chars is a LOUD
    fail (never a skip, never a pass) and no gateway boot happens."""
    monkeypatch.setenv(probe_support.MODEL_LIVE_ENV_VAR, "1")
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/hermes" if name == "hermes" else None)
    home = tmp_path / "home"
    monkeypatch.setenv("DEMIURGOS_HERMES_HOME", str(home))
    monkeypatch.setenv(_MODEL_CREDENTIAL_ENV, "sk-opencode-go-present")
    monkeypatch.setenv("API_SERVER_KEY", "short-key")
    with pytest.raises(pytest.fail.Exception, match="too short"):
        test_live_model_level_skills_visibility()
    assert not (home / "driver.pid").exists(), "no gateway may boot with a malformed key"