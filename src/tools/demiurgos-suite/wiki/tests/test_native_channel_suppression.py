# -*- coding: utf-8 -*-
"""WU-3.2 — per-world flag + health + toolset reconcile + suppression + fail-closed.

Covers the WU-3.2 task slice of ``hermes-etapa-3-corte`` (design §2 Q1/Q2/Q4/Q7,
§4 interfaces, §5.1 suppression matrix, §5.2 health/fail-closed matrix; spec
REQ-NC-2..6, REQ-GF-1):

- ``channel_health`` (REQ-NC-6): three-condition conjunction — toolset present
  in the dedicated profile, live folder present, promotion current (live
  revision == staging revision); per-turn evaluation with a short process-local
  memo keyed by ``(config mtime/size, marker signatures, flag)`` (tasks 3.2.2,
  3.2.4, 3.2.5).
- ``_active_channel_state`` tri-state (``legacy``/``native``/``unhealthy``) with
  fail-closed ``unhealthy`` and a loud ``logger.warning`` (tasks 3.2.3, 3.2.16,
  3.2.17).
- ``_sync_native_channel`` toolset reconcile behind the probe gate; flag ON ⇒
  ``skills`` enabled in the dedicated profile, zero-ON ⇒ byte-identical, the
  personal ``~/.hermes`` never touched (tasks 3.2.6, 3.2.7, 3.2.8).
- Suppression on all four legacy seams when the state is not ``legacy``:
  ``_route_skill`` (a), ``_companion_contract_for`` (b), ``/api/chat`` gate
  no-injection guard (c), ``_compiled_contract_markdown`` +
  ``_convergence_specimen_markdown`` (d) (tasks 3.2.9..3.2.15).
- Fail-closed matrix: flag ON + toolset absent / live missing / stale ⇒ zero
  methodology guidance, never silent legacy, warning emitted (task 3.2.16);
  flag OFF is unaffected by native health (task 3.2.17).
- Auth-gated flag route ``POST /api/{mundo}/methodologies/native-channel``
  (tasks 3.2.18, 3.2.19) + E2E harness (task 3.2.20, opt-in like WU-3.0).

Default-OFF byte-identical guard: with the flag OFF (and the probe closed
production default) every seam behaves exactly as at baseline — asserted as
controls throughout and explicitly by ``test_default_off_is_byte_identical``.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import api_server
from contract_projection import project_contract_markdown
from hermes_profile_config import resolve_skills_dir
from methodology_library import Activation, PublishedVersion
from methodology_trust import FOUNDATIONAL
from skill_materializer import revision_marker_path

import hermes_probe_support as probe_support

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
REPO_ROOT = _WIKI.parents[3]  # wiki/ -> demiurgos-suite/ -> tools/ -> src/ -> repo

WORLD = "W"
FLOW = api_server.DEFAULT_FLOW_TYPE

# A legacy-projection marker that must never reach a turn with the flag ON.
_COMPANION_MARKER = "[Companion methodology:"


# -- library / fixture seams --------------------------------------------------


def _published(
    skill_id,
    version="1.0.0",
    *,
    foundational,
    source="# Body\n",
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
        trigger_approval=None,
    )


def _activation(world, skill_id, version):
    return Activation(
        world=world,
        skill_id=skill_id,
        version=version,
        digest="0" * 64,
        activated_at="2026-01-01T00:00:00+00:00",
        flow_type=FLOW,
    )


class _StubLibrary:
    """Minimal in-memory library seam: flag + activation + published records."""

    def __init__(self, *, published=(), activations=None):
        self._flags = {}
        self._published = {(p.skill_id, p.version): p for p in published}
        self._activations = dict(activations or {})

    def native_channel_enabled(self, world):
        return bool(self._flags.get(world, False))

    def set_native_channel(self, world, enabled):
        if enabled:
            self._flags[world] = True
        else:
            self._flags.pop(world, None)

    def get_published(self, skill_id, version):
        return self._published.get((skill_id, version))

    def active_for(self, world, flow_type=FLOW):
        return self._activations.get(world)


class _FakeRouter:
    """Deterministic skill router returning a fixed winner (OFF control)."""

    def __init__(self, skill_id="narrative-draft"):
        self.skill_id = skill_id
        self.calls = []

    async def route(self, prompt, mundo, *, distilled_state=None):
        self.calls.append((prompt, mundo, distilled_state))
        return api_server.SkillRouteResult(self.skill_id, 0.9, "llm", True)


def _snapshot_tree(root: Path) -> dict[str, str]:
    """sha256 snapshot of every file under ``root`` (relative path -> digest)."""
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Hermetic native-channel env: data root + mundo dir + dedicated profile.

    The probe gate is OPEN (``_PROBE_PASSED=True``) by default so the toolset
    reconcile is exercisable; the byte-identical default-OFF tests flip it
    back to the production-closed default. The dedicated profile config lives
    under a temp ``HERMES_HOME`` — the personal ``~/.hermes`` is never
    resolved or written in these tests (P0-8 / REQ-NC-3).
    """
    project_root = tmp_path / "proyecto"
    (project_root / "mundos" / WORLD).mkdir(parents=True)
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    monkeypatch.setattr(api_server, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(api_server, "MUNDOS_DIR", project_root / "mundos")
    monkeypatch.setattr(api_server, "_active_world", lambda: WORLD)
    library = _StubLibrary(
        published=[_published("guia", foundational=False)],
        activations={WORLD: _activation(WORLD, "guia", "1.0.0")},
    )
    monkeypatch.setattr(api_server, "_methodology_library", lambda: library)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", None)
    monkeypatch.setattr(api_server, "_PROBE_PASSED", True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    api_server._NATIVE_HEALTH_MEMO.clear()
    ns = SimpleNamespace(
        project_root=project_root,
        library=library,
        profile_config=hermes_home / "config.yaml",
        hermes_home=hermes_home,
    )
    yield ns
    api_server._NATIVE_HEALTH_MEMO.clear()


def _write_profile(env, tools=("file",)):
    """Write the dedicated profile config with the given api_server tools."""
    env.profile_config.parent.mkdir(parents=True, exist_ok=True)
    lines = ["platform_toolsets:", "  api_server:"] + [f"    - {t}" for t in tools]
    env.profile_config.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_current_revision(env, marker: bytes = b"rev-1\n"):
    """Promote a current revision: live folder exists and live == staging."""
    live = resolve_skills_dir(env.project_root)
    live.mkdir(parents=True, exist_ok=True)
    (live / ".gitkeep").write_bytes(b"")
    (live / ".demiurgos-revision").write_bytes(marker)
    staging = revision_marker_path(env.project_root)
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_bytes(marker)


def _make_healthy(env):
    """Flag ON + toolset present + live folder present + promotion current."""
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file", "skills"))
    _make_current_revision(env)


def _companions(env):
    return [SimpleNamespace(skill_id="guia", version="1.0.0", world=WORLD)]


def _carries_no_methodology(payload) -> bool:
    """True when a payload carries no legacy-methodology content/marker."""
    text = yaml.safe_dump(payload) if isinstance(payload, dict) else str(payload)
    return _COMPANION_MARKER not in text and "compiled_contract" not in text


# -- channel_health conditions (3.2.2/3.2.4, REQ-NC-6) ------------------------


def test_channel_health_all_true_is_healthy(env):
    """Spec scenario 'Healthy channel': all three conditions true ⇒ healthy."""
    _make_healthy(env)
    assert api_server.channel_health(WORLD) is True


def test_channel_health_toolset_absent_is_unhealthy(env):
    """Condition 1 false ⇒ unhealthy (design §5.2 row 3)."""
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file",))  # no ``skills``
    _make_current_revision(env)
    assert api_server.channel_health(WORLD) is False


def test_channel_health_live_folder_missing_is_unhealthy(env):
    """Condition 2 false ⇒ unhealthy (design §5.2 row 4)."""
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file", "skills"))
    # live folder never promoted into existence
    assert api_server.channel_health(WORLD) is False


def test_channel_health_stale_revision_is_unhealthy(env):
    """Condition 3 false (live rev != staging rev) ⇒ unhealthy (row 5)."""
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file", "skills"))
    live = resolve_skills_dir(env.project_root)
    live.mkdir(parents=True, exist_ok=True)
    (live / ".gitkeep").write_bytes(b"")
    (live / ".demiurgos-revision").write_bytes(b"rev-1\n")
    staging = revision_marker_path(env.project_root)
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_bytes(b"rev-2\n")  # staging advanced, promotion stale
    assert api_server.channel_health(WORLD) is False


def test_channel_health_missing_live_marker_is_unhealthy(env):
    """Condition 3 false (live marker missing) ⇒ unhealthy (row 5)."""
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file", "skills"))
    live = resolve_skills_dir(env.project_root)
    live.mkdir(parents=True, exist_ok=True)
    (live / ".gitkeep").write_bytes(b"")
    staging = revision_marker_path(env.project_root)
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_bytes(b"rev-1\n")
    assert api_server.channel_health(WORLD) is False


def test_channel_health_missing_profile_config_is_unhealthy(env):
    """A missing dedicated profile config ⇒ toolset absent ⇒ unhealthy."""
    env.library.set_native_channel(WORLD, True)
    _make_current_revision(env)
    assert api_server.channel_health(WORLD) is False


# -- health memo (3.2.5, REQ-NC-6 per-turn) -----------------------------------


def test_health_memo_key_carries_every_input(env):
    """The memo key is ``(config mtime/size, marker signatures, flag)``: a
    live/staging/config change lands a new key (memo invalidation)."""
    _make_healthy(env)
    key = api_server._health_memo_key(WORLD)
    assert key[-1] is True  # flag in the key
    assert key[0] != (0, 0)  # config stat populated
    assert key[1] != (0, 0, "")  # live marker signature populated
    assert key[2] != (0, 0, "")  # staging marker signature populated

    staging = revision_marker_path(env.project_root)
    staging.write_bytes(b"rev-2\n")
    assert api_server._health_memo_key(WORLD) != key


def test_health_memo_invalidates_on_marker_change(env):
    """A promotion that advances the staging marker flips a memoized healthy
    world to unhealthy on the next evaluation (no stale cache)."""
    _make_healthy(env)
    assert api_server.channel_health(WORLD) is True  # memoized fast path
    staging = revision_marker_path(env.project_root)
    staging.write_bytes(b"rev-2\n")  # live rev-1 now stale
    assert api_server.channel_health(WORLD) is False


def test_health_memo_invalidates_on_config_change(env):
    """Removing ``skills`` from the dedicated profile flips health on the next
    evaluation without a process restart."""
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file", "skills"))
    _make_current_revision(env)
    assert api_server.channel_health(WORLD) is True
    _write_profile(env, ("file",))  # toolset removed externally
    assert api_server.channel_health(WORLD) is False


# -- _active_channel_state tri-state (3.2.3) ----------------------------------


def test_state_legacy_when_flag_off(env):
    """Flag OFF ⇒ ``legacy`` — regardless of native health."""
    _make_current_revision(env)  # native side healthy on disk
    _write_profile(env, ("file", "skills"))
    assert api_server._native_channel_enabled(WORLD) is False
    assert api_server._active_channel_state() == "legacy"


def test_state_native_when_flag_on_and_healthy(env):
    _make_healthy(env)
    assert api_server._active_channel_state() == "native"


def test_state_unhealthy_when_flag_on_and_health_fails(env):
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file",))
    _make_current_revision(env)
    assert api_server._active_channel_state() == "unhealthy"


# -- toolset reconcile (3.2.6/3.2.7, REQ-NC-3) --------------------------------


def test_sync_adds_skills_when_native(env):
    """Flag ON healthy ⇒ ``skills`` added to the dedicated profile; siblings
    preserved (REQ-NC-3 scenario 1)."""
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file",))
    _make_current_revision(env)
    assert api_server._sync_native_channel(WORLD) is True
    data = yaml.safe_load(env.profile_config.read_text(encoding="utf-8"))
    assert data["platform_toolsets"]["api_server"] == ["file", "skills"]


def test_sync_removes_skills_when_legacy(env):
    """Flag OFF ⇒ desired state is ``enabled=False``: only ``skills`` is
    removed, sibling tools and blocks preserved."""
    env.library.set_native_channel(WORLD, False)
    _write_profile(env, ("file", "skills"))
    assert api_server._sync_native_channel(WORLD) is True
    data = yaml.safe_load(env.profile_config.read_text(encoding="utf-8"))
    assert data["platform_toolsets"]["api_server"] == ["file"]


def test_zero_on_config_byte_identical(env):
    """Zero worlds opted in + ``skills`` never present ⇒ the writer returns
    False and the dedicated profile stays byte-identical (REQ-NC-3 scenario 3)."""
    _write_profile(env, ("file",))
    before = env.profile_config.read_bytes()
    assert api_server._sync_native_channel(WORLD) is False
    assert env.profile_config.read_bytes() == before


def test_sync_probe_closed_is_noop_byte_identical(env, monkeypatch):
    """REQ-NC-1: with the probe gate CLOSED (production default) nothing
    enables — even a flag-ON healthy world leaves the profile untouched."""
    _make_healthy(env)
    monkeypatch.setattr(api_server, "_PROBE_PASSED", False)
    before = env.profile_config.read_bytes()
    assert api_server._sync_native_channel(WORLD) is False
    assert env.profile_config.read_bytes() == before


def test_personal_profile_never_created_or_modified(env, monkeypatch):
    """REQ-NC-3 scenario 2 / P0-8: no file under a personal-like
    ``~/.hermes`` is created or modified. The reconcile resolves only the
    dedicated product ``HERMES_HOME``; with the probe closed it short-circuits
    before any path resolution, and with the flag OFF an absent ``skills``
    writes nothing (``ensure_skills_toolset`` is a no-op)."""
    personal = env.hermes_home.parent / "personal-home"
    personal.mkdir()
    before = _snapshot_tree(personal)

    # Probe closed (production default): the reconcile never resolves/writes.
    _make_healthy(env)
    monkeypatch.setattr(api_server, "_PROBE_PASSED", False)
    assert api_server._sync_native_channel(WORLD) is False
    assert _snapshot_tree(personal) == before

    # Probe open + flag OFF + HERMES_HOME at the personal-like root: with
    # ``skills`` absent the writer returns False and creates nothing.
    monkeypatch.setattr(api_server, "_PROBE_PASSED", True)
    env.library.set_native_channel(WORLD, False)
    monkeypatch.setenv("HERMES_HOME", str(personal))
    assert api_server._sync_native_channel(WORLD) is False
    assert _snapshot_tree(personal) == before
    assert not (personal / "config.yaml").exists()


# -- path a: _route_skill suppression (3.2.9/3.2.10, REQ-NC-4) -----------------


def test_route_skill_suppressed_when_native(env, monkeypatch):
    _make_healthy(env)
    fake = _FakeRouter()
    monkeypatch.setattr(api_server, "_SKILL_ROUTER", fake)
    assert asyncio.run(api_server._route_skill("Hola", WORLD, None)) is None
    assert fake.calls == []  # the legacy router is never even reached


def test_route_skill_suppressed_when_unhealthy(env, monkeypatch):
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file",))
    _make_current_revision(env)
    fake = _FakeRouter()
    monkeypatch.setattr(api_server, "_SKILL_ROUTER", fake)
    assert api_server._active_channel_state() == "unhealthy"
    assert asyncio.run(api_server._route_skill("Hola", WORLD, None)) is None
    assert fake.calls == []


def test_route_skill_flag_off_control(env, monkeypatch):
    """Flag OFF control: the legacy routing side effect is byte-identical —
    the router runs and its skill_id is returned (REQ-NC-4 scenario 5)."""
    fake = _FakeRouter("narrative-draft")
    monkeypatch.setattr(api_server, "_SKILL_ROUTER", fake)
    result = asyncio.run(api_server._route_skill("Hola", WORLD, None))
    assert result == "narrative-draft"
    assert fake.calls == [("Hola", WORLD, None)]


# -- path b: _companion_contract_for suppression (3.2.11/3.2.12) --------------


def test_companion_contract_suppressed_when_native(env):
    _make_healthy(env)
    assert api_server._companion_contract_for("guia", _companions(env), WORLD) is None


def test_companion_contract_suppressed_when_unhealthy(env):
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file",))
    _make_current_revision(env)
    assert api_server._active_channel_state() == "unhealthy"
    assert api_server._companion_contract_for("guia", _companions(env), WORLD) is None


def test_companion_contract_flag_off_control(env):
    """Flag OFF control: the companion marker is produced exactly as at
    baseline — and it never starts with the suppressed marker when ON."""
    marker = api_server._companion_contract_for("guia", _companions(env), WORLD)
    assert marker is not None
    assert marker.startswith(_COMPANION_MARKER)


# -- path c: /api/chat _semantic_gate no-injection guard (3.2.13, REQ-NC-4) ---


def test_chat_gate_injects_no_legacy_content_when_native(env):
    """The mandatory ``_semantic_gate`` (and its bounded context) carries NO
    legacy methodology content for a flag-ON world — the no-injection invariant
    guard (design §2 Q7 row c)."""
    _make_healthy(env)
    payload = asyncio.run(api_server._semantic_gate(WORLD, "Hola")).as_dict()
    assert _carries_no_methodology(payload)
    context, _reference, _name, _unavailable = api_server._semantic_context(WORLD, "Hola")
    assert _carries_no_methodology(context.__dict__)


def test_chat_gate_envelope_identical_flag_off(env):
    """Flag OFF control: the gate envelope is byte-identical to the flag-ON
    shape (the gate never carried methodology content on either side)."""
    _write_profile(env, ("file", "skills"))
    _make_current_revision(env)

    env.library.set_native_channel(WORLD, True)
    on_payload = asyncio.run(
        api_server._semantic_gate(WORLD, "Hola", request_id="r-fixed")
    ).as_dict()
    env.library.set_native_channel(WORLD, False)
    off_payload = asyncio.run(
        api_server._semantic_gate(WORLD, "Hola", request_id="r-fixed")
    ).as_dict()

    assert on_payload == off_payload
    assert _carries_no_methodology(on_payload)


# -- path d: guided resolvers suppression (3.2.14/3.2.15, REQ-NC-4/REQ-GF-1) ---


def test_compiled_contract_suppressed_when_native(env):
    """Flag ON healthy: ``_compiled_contract_markdown`` returns None even
    though the legacy path WOULD resolve the world's activation to Markdown."""
    _make_healthy(env)
    assert env.library.active_for(WORLD) is not None  # activation present
    assert api_server._compiled_contract_markdown(WORLD) is None


def test_compiled_contract_flag_off_control(env):
    """Flag OFF control: the compiled contract resolves to Markdown exactly as
    at baseline."""
    markdown = api_server._compiled_contract_markdown(WORLD)
    assert markdown is not None
    assert markdown == project_contract_markdown(
        env.library.get_published("guia", "1.0.0")
    )


def test_specimen_suppressed_before_any_resolution(env, monkeypatch):
    """Flag ON: ``_convergence_specimen_markdown`` returns None BEFORE the
    legacy resolution machinery is reached (the suppression is the guard)."""
    _make_healthy(env)

    def boom(*_args, **_kwargs):  # the legacy path would call this
        raise AssertionError("legacy specimen machinery reached with flag ON")

    monkeypatch.setattr(api_server, "candidate_minimum_complete", boom)
    assert api_server._convergence_specimen_markdown(WORLD, FLOW, object()) is None


def test_specimen_flag_off_control(env, monkeypatch):
    """Flag OFF control: the legacy specimen machinery behaves byte-identically
    (a ``None`` state still resolves to ``None`` without suppression)."""

    def boom(*_args, **_kwargs):
        raise AssertionError("specimen machinery must not run for state=None")

    monkeypatch.setattr(api_server, "candidate_minimum_complete", boom)
    assert api_server._convergence_specimen_markdown(WORLD, FLOW, None) is None


def test_guided_resolvers_suppressed_when_unhealthy(env):
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file",))
    _make_current_revision(env)
    assert api_server._active_channel_state() == "unhealthy"
    assert api_server._compiled_contract_markdown(WORLD) is None
    assert api_server._convergence_specimen_markdown(WORLD, FLOW, None) is None


# -- _channel_session_id health gate (D4 refinement) --------------------------


def test_channel_session_id_suffixed_only_when_native(env):
    """The D4 run-path suffix applies only for a healthy ``native`` channel:
    unhealthy (flag ON, health fails) keeps the base id — fail-closed, no
    native session pinning."""
    _make_healthy(env)
    assert api_server._active_channel_state() == "native"
    assert api_server._channel_session_id("sess-1") == "sess-1"  # no epoch stored

    from skill_session_epochs import SessionEpochRegistry, resolve_session_store_path

    SessionEpochRegistry(resolve_session_store_path(env.project_root)).observe(
        WORLD, "rev-1"
    )
    suffixed = api_server._channel_session_id("sess-1")
    assert suffixed.startswith("sess-1.")

    # Unhealthy: base id unchanged even with an epoch present.
    _write_profile(env, ("file",))  # toolset removed -> unhealthy
    assert api_server._active_channel_state() == "unhealthy"
    assert api_server._channel_session_id("sess-1") == "sess-1"


def test_channel_session_id_flag_off_unchanged(env):
    _make_current_revision(env)
    _write_profile(env, ("file", "skills"))
    assert api_server._active_channel_state() == "legacy"
    assert api_server._channel_session_id("sess-1") == "sess-1"


# -- fail-closed matrix (3.2.16, REQ-NC-5) ------------------------------------


def _assert_fail_closed(env, caplog, monkeypatch):
    assert api_server._active_channel_state() == "unhealthy"
    assert any(record.levelname == "WARNING" for record in caplog.records)

    fake = _FakeRouter()
    monkeypatch.setattr(api_server, "_SKILL_ROUTER", fake)
    assert asyncio.run(api_server._route_skill("Hola", WORLD, None)) is None
    assert api_server._companion_contract_for("guia", _companions(env), WORLD) is None
    assert api_server._compiled_contract_markdown(WORLD) is None
    assert api_server._convergence_specimen_markdown(WORLD, FLOW, None) is None
    assert _carries_no_methodology(
        asyncio.run(api_server._semantic_gate(WORLD, "Hola")).as_dict()
    )


def test_fail_closed_toolset_absent(env, caplog, monkeypatch):
    """Row 3: flag ON + ``skills`` absent ⇒ unhealthy; zero guidance on every
    seam, no legacy fallback, warning emitted."""
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file",))
    _make_current_revision(env)
    _assert_fail_closed(env, caplog, monkeypatch)


def test_fail_closed_live_folder_missing(env, caplog, monkeypatch):
    """Row 4: flag ON + live folder missing ⇒ unhealthy; zero guidance."""
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file", "skills"))
    _assert_fail_closed(env, caplog, monkeypatch)


def test_fail_closed_promote_stale(env, caplog, monkeypatch):
    """Row 5: flag ON + live rev ≠ staging rev ⇒ unhealthy; zero guidance."""
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file", "skills"))
    _make_current_revision(env, marker=b"rev-1\n")
    revision_marker_path(env.project_root).write_bytes(b"rev-2\n")
    _assert_fail_closed(env, caplog, monkeypatch)


# -- flag OFF unaffected by health (3.2.17, REQ-NC-5 scenario 5) --------------


def test_flag_off_unaffected_by_native_health(env, monkeypatch):
    """Flag OFF: native health is irrelevant — the world still receives the
    legacy projection (byte-identical controls on every seam)."""
    _write_profile(env, ("file",))  # toolset unhealthy
    assert api_server._active_channel_state() == "legacy"
    fake = _FakeRouter("narrative-draft")
    monkeypatch.setattr(api_server, "_SKILL_ROUTER", fake)
    assert asyncio.run(api_server._route_skill("Hola", WORLD, None)) == "narrative-draft"
    assert api_server._companion_contract_for("guia", _companions(env), WORLD) is not None
    assert api_server._compiled_contract_markdown(WORLD) is not None
    assert api_server._channel_session_id("sess-1") == "sess-1"


# -- default-OFF byte-identical guard (cross-cutting D1) ----------------------


def test_default_off_is_byte_identical(env, monkeypatch):
    """Production default (flag OFF + probe CLOSED): every seam behaves
    exactly as at baseline — suppression never fires, the toolset reconcile is
    a no-op, and the dedicated profile config stays byte-identical."""
    env.library.set_native_channel(WORLD, False)
    _write_profile(env, ("file",))
    before = env.profile_config.read_bytes()
    monkeypatch.setattr(api_server, "_PROBE_PASSED", False)

    assert api_server._active_channel_state() == "legacy"
    assert api_server._sync_native_channel(WORLD) is False
    assert env.profile_config.read_bytes() == before

    fake = _FakeRouter("narrative-draft")
    monkeypatch.setattr(api_server, "_SKILL_ROUTER", fake)
    assert asyncio.run(api_server._route_skill("Hola", WORLD, None)) == "narrative-draft"
    assert api_server._companion_contract_for("guia", _companions(env), WORLD) is not None
    assert api_server._compiled_contract_markdown(WORLD) is not None
    assert api_server._convergence_specimen_markdown(WORLD, FLOW, None) is None
    assert api_server._channel_session_id("sess-1") == "sess-1"


# -- flag route (3.2.18/3.2.19) -----------------------------------------------


def test_native_channel_route_unauthenticated_401(env, monkeypatch):
    """Unauthenticated ⇒ 401 fail-closed; the flag is never touched."""
    monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: None)
    from fastapi.testclient import TestClient

    resp = TestClient(api_server.app).post(
        f"/api/{WORLD}/methodologies/native-channel", json={"enabled": True}
    )
    assert resp.status_code == 401
    assert env.library.native_channel_enabled(WORLD) is False


def test_native_channel_route_unknown_world_404(env, monkeypatch):
    monkeypatch.setattr(
        api_server, "_resolve_principal",
        lambda _request: api_server.EditPrincipal("tester"),
    )
    from fastapi.testclient import TestClient

    resp = TestClient(api_server.app).post(
        "/api/unknown-world/methodologies/native-channel", json={"enabled": True}
    )
    assert resp.status_code == 404


def test_native_channel_route_authenticated_sets_flag_and_reconciles(env, monkeypatch):
    """Authenticated ⇒ flag set/unset persists and the toolset reconciles
    (skills added on enable, removed on disable)."""
    monkeypatch.setattr(
        api_server, "_resolve_principal",
        lambda _request: api_server.EditPrincipal("tester"),
    )
    _make_current_revision(env)
    _write_profile(env, ("file",))
    from fastapi.testclient import TestClient

    client = TestClient(api_server.app)

    resp = client.post(f"/api/{WORLD}/methodologies/native-channel", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["native_channel"] is True
    assert env.library.native_channel_enabled(WORLD) is True
    data = yaml.safe_load(env.profile_config.read_text(encoding="utf-8"))
    assert data["platform_toolsets"]["api_server"] == ["file", "skills"]

    resp = client.post(f"/api/{WORLD}/methodologies/native-channel", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["native_channel"] is False
    assert env.library.native_channel_enabled(WORLD) is False
    data = yaml.safe_load(env.profile_config.read_text(encoding="utf-8"))
    assert data["platform_toolsets"]["api_server"] == ["file"]


# -- E2E harness (3.2.20; deterministic half + opt-in live half) --------------


def test_e2e_flag_on_single_channel_and_fail_closed_removal(env):
    """(3.2.20 deterministic half) flag ON ⇒ exactly ONE channel enabled in the
    dedicated profile; removing ``skills`` ⇒ fail-closed: nothing enabled and
    no legacy fallback content on any seam."""
    env.library.set_native_channel(WORLD, True)
    _write_profile(env, ("file",))
    _make_current_revision(env)
    assert api_server._sync_native_channel(WORLD) is True

    data = yaml.safe_load(env.profile_config.read_text(encoding="utf-8"))
    assert data["platform_toolsets"]["api_server"] == ["file", "skills"]

    # Simulate the toolset being removed (operator / drift / rollback).
    from hermes_profile_config import ensure_skills_toolset

    ensure_skills_toolset(env.profile_config, enabled=False)
    data = yaml.safe_load(env.profile_config.read_text(encoding="utf-8"))
    assert data["platform_toolsets"]["api_server"] == ["file"]

    # Fail-closed: unhealthy, zero guidance on every seam, no legacy fallback.
    assert api_server._active_channel_state() == "unhealthy"
    assert api_server._compiled_contract_markdown(WORLD) is None
    assert api_server._companion_contract_for("guia", _companions(env), WORLD) is None


def test_live_native_channel_e2e_gateway():
    """(3.2.20 live half) Boot the real Hermes gateway on a dedicated TEST
    profile and assert the channel wiring comes up. Explicitly opt-in
    (``DEMIURGOS_PROBE_LIVE=1``) and requires a provisioned dedicated profile
    (``DEMIURGOS_HERMES_HOME``/``HERMES_HOME``, never the personal profile);
    otherwise SKIPPED with the exact reason — runs with the shared WU-2 harness
    (REQ-LPH-5). A failing run here FAILS loudly, never silently passes."""
    if not probe_support.live_probe_enabled():
        pytest.skip(
            "live gateway E2E disabled (DEMIURGOS_PROBE_LIVE=1 required); "
            "deterministic unit/integration half executed instead"
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

    try:
        result = probe_support.boot_and_probe_gateway(hermes_bin, home)
    except probe_support.ProbeLogDriftError as exc:
        pytest.skip(str(exc))  # log-path drift is an honest skip, never a pass

    assert result.booted, (
        "gateway did not come up with hook evidence; "
        f"returncode={result.returncode}"
    )
    assert any("pre_tool_call" in line.lower() for line in result.hook_evidence), (
        "no pre_tool_call registration evidence in the gateway log"
    )