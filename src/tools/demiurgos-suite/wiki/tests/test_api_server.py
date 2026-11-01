# -*- coding: utf-8 -*-
"""API server tests — tree contract, save, and diff endpoints.

These endpoints were rebuilt in api_server.py and previously had no test
coverage, which is how the is_dir contract regression survived unnoticed.
"""

import base64
import asyncio
import hashlib
import io
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import types
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import requests
import yaml
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
_SUITE = _WIKI.parent
for _p in (str(_WIKI), str(_SUITE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import api_server  # noqa: E402
from state_root_support import state_file  # noqa: E402
from assistant_activity import assess_hermes_capabilities  # noqa: E402
import guided_session_store  # noqa: E402
from guided_character_persistence import ReindexCoordinator, ReindexResult  # noqa: E402
from guided_session_store import GuidedSessionStore as DurableGuidedSessionStore  # noqa: E402
from guided_session_store import SESSION_TTL  # noqa: E402
import idea_capture_ui  # noqa: E402
from methodology_compiler import compile_methodology  # noqa: E402
from methodology_library import MethodologyLibrary  # noqa: E402
from methodology_seed import install_seeds, load_seed_catalog  # noqa: E402
from methodology_trust import build_package, inspect_package  # noqa: E402
import telegram_settings  # noqa: E402
from wiki import migration as migration_module  # noqa: E402
from wiki.graph_indexer import EntityGraphIndex  # noqa: E402
from wiki.world_authority import _is_case_insensitive_fs  # noqa: E402
from migration_settings import create_migration_settings_router  # noqa: E402

REPO_ROOT = _WIKI.parents[3]
SEED_ROOT = REPO_ROOT / "data" / "methodology" / "seeds"


def _fs_case_insensitive() -> bool:
    """True when the sandbox filesystem is case-insensitive (macOS/Windows CI).

    On a case-insensitive FS ``Lore`` and ``lore`` are the same physical
    directory: fixtures that create both spellings, rollback injection, and
    "legacy absence" assertions are skipped/adjusted there (R-CIM-07).
    """
    with tempfile.TemporaryDirectory() as tmp:
        if _is_case_insensitive_fs(Path(tmp)):
            return True
    # Physical probe can miss NTFS on some setups; CI runners (APFS/NTFS) are
    # always case-insensitive, so fall back to platform (test-only heuristic).
    return sys.platform in ("darwin", "win32")


def _activity_capability():
    return assess_hermes_capabilities(
        {
            "object": "hermes.api_server.capabilities",
            "platform": "hermes-agent",
            "features": {
                "run_submission": True,
                "run_status": True,
                "run_events_sse": True,
                "run_stop": True,
                "tool_progress_events": True,
            },
        }
    )


def _parse_sse(text: str) -> list[dict]:
    """Parse ``event: <kind>`` / ``data: <json>`` records in stream order."""
    records = []
    event_name: str | None = None
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("event: "):
            event_name = line[len("event: "):]
        elif line.startswith("data: "):
            data_lines.append(line[len("data: "):])
        elif line == "" and event_name is not None:
            records.append(json.loads("\n".join(data_lines)))
            event_name = None
            data_lines = []
    return records


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a temp mundos dir and a sample world."""
    mundos = tmp_path / "mundos"
    world = mundos / "test_mundo"
    lore = world / "lore"
    (lore / "subdir").mkdir(parents=True)
    (lore / "00_inicio.md").write_text("---\ntype: criatura\ntitle: Inicio\n---\n# Inicio\n", encoding="utf-8")
    (lore / "subdir" / "detalle.md").write_text("# Detalle\n", encoding="utf-8")

    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    # Hermes-first contract: unwired semantic provider fails closed. Tests that
    # exercise /ai/ask or /api/chat wire a fake provider explicitly.
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", None)
    api_server._graph_indices.clear()
    api_server._confirmation_store.clear()
    api_server._GUIDED_PENDING_PROPOSALS.clear()
    api_server._MATERIALIZE_PENDING_PROPOSALS.clear()
    api_server._GUIDED_CONSENT_TOKENS.clear()
    api_server._GUIDED_INDEX_REQUESTS.clear()
    api_server._METHODOLOGY_LIBRARY = None
    api_server._METHODOLOGY_QUARANTINE = None
    with api_server._local_session_lock:
        api_server._local_sessions.clear()
    api_server._target_locks.clear()
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.mark.parametrize("language,expected", [
    ("es", "es"),
    ("es-ar", "es"),
    ("es-es", "es"),
    ("en", "en"),
])
def test_config_endpoint_exposes_normalized_language(client: TestClient, monkeypatch, language, expected):
    monkeypatch.setenv("DEMIURGOS_LANGUAGE", language)
    # Pin the runtime version so the response shape is deterministic: env wins
    # over the layout/dev fallback chain (runtime-version-reporting spec).
    monkeypatch.setenv("DEMIURGOS_APP_VERSION", "9.9.9")
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json() == {"language": expected, "app_version": "9.9.9"}


def test_config_endpoint_reads_project_env_file_with_safe_fallback(client: TestClient, monkeypatch, tmp_path):
    monkeypatch.delenv("DEMIURGOS_LANGUAGE", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("DEMIURGOS_LANGUAGE=en\n", encoding="utf-8")
    response = client.get("/api/config")
    body = response.json()
    assert body["language"] == "en"
    # The new app_version field is always present and never empty.
    assert isinstance(body["app_version"], str) and body["app_version"]

    env_file.write_text("SOME_SECRET=top-secret\n", encoding="utf-8")
    response = client.get("/api/config")
    body = response.json()
    assert body["language"] == "es"
    assert isinstance(body["app_version"], str) and body["app_version"]


# --- Runtime version resolution (runtime-version-reporting spec) -------------


def _make_current_layout(tmp_path: Path) -> Path:
    """Create ``<tmp>/app/0.2.0`` plus a ``current`` symlink to it.

    Mirrors the installed layout ``<install_root>/current -> app/<version>``.
    Returns the ``current`` link, which is what the code root resolves to in
    an installed deployment. Skipped on platforms that cannot create links.
    """
    app_version_dir = tmp_path / "app" / "0.2.0"
    app_version_dir.mkdir(parents=True)
    current = tmp_path / "current"
    try:
        current.symlink_to(app_version_dir, target_is_directory=True)
    except OSError as exc:  # pragma: no cover - platform-dependent
        pytest.skip(f"cannot create a directory symlink here: {exc}")
    return current


def test_app_version_env_wins_over_layout(monkeypatch, tmp_path):
    """Spec: env `DEMIURGOS_APP_VERSION` beats an existing install layout."""
    monkeypatch.setenv("DEMIURGOS_APP_VERSION", "9.9.9")
    monkeypatch.setattr(api_server, "_CODE_ROOT", _make_current_layout(tmp_path))
    assert api_server._app_version() == "9.9.9"


def test_app_version_layout_basename_used_when_env_absent(monkeypatch, tmp_path):
    """Spec: layout used when env is absent — basename of `current` target."""
    monkeypatch.delenv("DEMIURGOS_APP_VERSION", raising=False)
    monkeypatch.setattr(api_server, "_CODE_ROOT", _make_current_layout(tmp_path))
    assert api_server._app_version() == "0.2.0"


def test_app_version_dev_literal_when_nothing_usable(monkeypatch, tmp_path):
    """Spec: absolute fallback `0.0.0-dev` when no env/layout/dev source."""
    monkeypatch.delenv("DEMIURGOS_APP_VERSION", raising=False)
    plain = tmp_path / "plain-checkout"
    plain.mkdir()
    monkeypatch.setattr(api_server, "_CODE_ROOT", plain)
    assert api_server._app_version() == "0.0.0-dev"


def test_app_version_never_raises_and_always_nonempty(monkeypatch, tmp_path):
    """Hard constraint: resolver never raises and never returns empty."""
    monkeypatch.delenv("DEMIURGOS_APP_VERSION", raising=False)
    # A deleted, non-git code root: no package.json, `git -C` cannot resolve,
    # no env, no layout — must still land on the literal fallback.
    monkeypatch.setattr(api_server, "_CODE_ROOT", tmp_path / "missing")
    assert api_server._app_version() == "0.0.0-dev"
    # Layout present: resolves even though the symlink was created after mkdir.
    monkeypatch.setattr(api_server, "_CODE_ROOT", _make_current_layout(tmp_path))
    assert bool(api_server._app_version())


def test_install_root_detects_current_layout(monkeypatch, tmp_path):
    """`_install_root()` returns <install_root> only under the `current` layout."""
    monkeypatch.setattr(api_server, "_CODE_ROOT", _make_current_layout(tmp_path))
    assert api_server._install_root() == tmp_path
    monkeypatch.setattr(api_server, "_CODE_ROOT", tmp_path / "plain-checkout")
    assert api_server._install_root() is None


def test_config_endpoint_includes_nonempty_app_version(client: TestClient, monkeypatch):
    """Spec: GET /api/config includes a non-empty app_version string."""
    monkeypatch.setenv("DEMIURGOS_APP_VERSION", "9.9.9")
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json()["app_version"] == "9.9.9"


@pytest.fixture()
def jpeg_bytes() -> bytes:
    """Minimal valid JPEG payload (survives PIL round-trip in uploads)."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture()
def client_sorted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a world whose tree exercises ordering rules.

    Top level mixes dirs and files with case variations so that only a
    dirs-first, case-insensitive sort yields the expected order:
    `alpha/`, `Zeta/`, `Beta.md`, `gamma.md`.
    """
    mundos = tmp_path / "mundos"
    world = mundos / "test_mundo"
    lore = world / "lore"
    (lore / "Zeta").mkdir(parents=True)
    (lore / "Zeta" / "zeta_inner.md").write_text("# Z\n", encoding="utf-8")
    (lore / "alpha").mkdir()
    (lore / "alpha" / "aleph").mkdir()
    (lore / "alpha" / "aleph" / "a1.md").write_text("# A1\n", encoding="utf-8")
    (lore / "alpha" / "Beta").mkdir()
    (lore / "alpha" / "Beta" / "b1.md").write_text("# B1\n", encoding="utf-8")
    (lore / "alpha" / "gamma.md").write_text("# G\n", encoding="utf-8")
    (lore / "alpha" / "Delta.md").write_text("# D\n", encoding="utf-8")
    (lore / "Beta.md").write_text("# B\n", encoding="utf-8")
    (lore / "gamma.md").write_text("# G\n", encoding="utf-8")

    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    api_server._graph_indices.clear()
    return TestClient(api_server.app)


def _principal(monkeypatch: pytest.MonkeyPatch, pid: str = "tester") -> None:
    monkeypatch.setattr(api_server, "_resolve_principal", lambda request: api_server.EditPrincipal(pid))


def _confirm(client: TestClient, path: str, content: str,
             edit_id: str = "e1") -> tuple[dict, str]:
    full = api_server.MUNDOS_DIR / "test_mundo" / "lore" / path
    base_rev = hashlib.sha256(full.read_bytes()).hexdigest()
    resp = client.post(
        f"/api/test_mundo/lore/edit-confirmation?path={path}",
        json={"edit_id": edit_id, "base_revision": base_rev, "proposed_content": content},
    )
    assert resp.status_code == 200, resp.text
    return resp.json(), base_rev


def _gated_write(client: TestClient, path: str, content: str,
                 conf: dict, base_rev: str, edit_id: str = "e1"):
    return client.post(f"/api/test_mundo/lore/save?path={path}",
                       json={"content": content, "edit_id": edit_id,
                             "proposed_digest": conf["proposed_digest"],
                             "token": conf["token"], "base_revision": base_rev})


def _confirm_new(client: TestClient, path: str, content: str,
                 edit_id: str = "n1") -> dict:
    resp = client.post(
        f"/api/test_mundo/lore/edit-confirmation?path={path}",
        json={"edit_id": edit_id, "proposed_content": content, "kind": "new"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _gated_create(client: TestClient, path: str, content: str, conf: dict,
                  edit_id: str = "n1"):
    return client.post(f"/api/test_mundo/lore/create?path={path}",
                       json={"content": content, "edit_id": edit_id,
                             "proposed_digest": conf["proposed_digest"],
                             "token": conf["token"]})


# ---------------------------------------------------------------------------
# Materialize preview/confirm helpers (PR5, tasks 4.4-4.6)
# ---------------------------------------------------------------------------


class _FakeMaterializeGraph:
    """EntityGraphIndex seam for a fixed entity list (mirrors _GuidedGraphReader).

    ``_GuidedGraphReader`` wraps every result with ``vars()``
    (api_server.py:5269-5274) and reads through ``get_entity``, so this fake
    returns SimpleNamespace objects (they have ``__dict__``) and exposes the
    index-level ``search``/``get_entity``/``get_links`` API.
    """

    def __init__(self, entities: list[dict]) -> None:
        self._entities = {e["path"]: e for e in entities}

    def search(self, query: str) -> list[dict]:
        return [types.SimpleNamespace(path=p) for p in sorted(self._entities)]

    def get_entity(self, path: str) -> object | None:
        entity = self._entities.get(path)
        return types.SimpleNamespace(**entity) if entity is not None else None

    def get_links(self, entity_path: str, kind: str) -> list[dict]:
        return []


class _FakeMaterializeProvider:
    """Route-level fake for api_server._MATERIALIZE_PROVIDER.

    ``result`` is a fixed object (returned as-is) or a callable
    ``(request, cancellation) -> object``; every MaterializationRequest is
    recorded for assertions.
    """

    def __init__(self, result):
        self.result = result
        self.requests = []

    async def invoke(self, request, cancellation):
        self.requests.append(request)
        if callable(self.result):
            return self.result(request, cancellation)
        return self.result


def _materialize_delta(request, *, body: str = "# Cuerpo del arquero\n",
                       relations: list | None = None) -> dict:
    """A valid idea-materialization-v1 delta envelope echoing request identity."""
    return {
        "protocol_version": request.protocol_version,
        "request_id": request.request_id,
        "session_id": request.session_id,
        "outcome": "delta",
        "delta": {"body": body, "relations": relations or []},
    }


def _materialize_entity(path: str, *, id: str, title: str = "",
                        type: str = "concepto", description: str = "") -> dict:
    return {"path": path, "id": id, "title": title, "type": type, "description": description}


def _wire_materialize(monkeypatch, provider_result, entities: list[dict] | None = None):
    """Wire a fake _MATERIALIZE_PROVIDER (+ optional fake _get_graph) and principal.

    ``provider_result`` is returned as-is when not callable, or invoked as
    ``(request, cancellation)`` when callable.
    """
    _principal(monkeypatch)
    # IdeasBank resolves the data root through ITS OWN _project_root (data_root
    # resolver), not api_server.PROJECT_ROOT — point it at the hermetic root so
    # the preview handler's IdeasBank().read(slug) sees the fixture ideas.
    monkeypatch.setattr("ideas_bank._project_root", lambda: api_server.PROJECT_ROOT)
    fake = _FakeMaterializeProvider(provider_result)
    monkeypatch.setattr(api_server, "_MATERIALIZE_PROVIDER", fake)
    if entities is not None:
        monkeypatch.setattr(api_server, "_get_graph", lambda _world: _FakeMaterializeGraph(entities))
    return fake


def _materialize_preview(client: TestClient, slug: str = "arquero-ciego", **overrides):
    payload = {"world": "test_mundo", "section": "lore", "folder": "subdir"}
    payload.update(overrides)
    return client.post(f"/api/ideas/{slug}/materialize-preview", json=payload)


def _materialize_target(client: TestClient, slug: str = "arquero-ciego", **overrides):
    payload = {"world": "test_mundo", "section": "lore", "folder": "subdir"}
    payload.update(overrides)
    return client.post(f"/api/ideas/{slug}/materialize-target", json=payload)


def _world_listing() -> list[str]:
    """Sorted world-relative paths under the fixture world (zero-writes checks)."""
    world = api_server.MUNDOS_DIR / "test_mundo"
    return sorted(str(p.relative_to(world)) for p in world.rglob("*"))


class TestTreeContract:
    def test_tree_marks_directories_with_is_dir(self, client: TestClient):
        """Directories must carry is_dir=True so the frontend can expand them."""
        tree = client.get("/api/test_mundo/lore/tree").json()
        by_name = {node["name"]: node for node in tree}
        assert by_name["subdir"]["is_dir"] is True
        assert "children" in by_name["subdir"]
        assert by_name["00_inicio.md"]["is_dir"] is False
        # No node may carry the old broken 'type' field as the discriminator.
        for node in tree:
            assert "is_dir" in node

    def test_tree_includes_markdown_files(self, client: TestClient):
        tree = client.get("/api/test_mundo/lore/tree").json()
        names = [node["name"] for node in tree]
        assert "00_inicio.md" in names


class TestTreeOrdering:
    def test_dirs_before_files_case_insensitive(self, client_sorted: TestClient):
        """Directories come first; each group is sorted case-insensitively."""
        tree = client_sorted.get("/api/test_mundo/lore/tree").json()
        names = [node["name"] for node in tree]
        assert names == ["alpha", "Zeta", "Beta.md", "gamma.md"]

    def test_order_applies_recursively(self, client_sorted: TestClient):
        """Nested directories follow the same dirs-first, case-insensitive rule."""
        tree = client_sorted.get("/api/test_mundo/lore/tree").json()
        by_name = {node["name"]: node for node in tree}
        alpha = by_name["alpha"]
        inner_names = [node["name"] for node in alpha["children"]]
        assert inner_names == ["aleph", "Beta", "Delta.md", "gamma.md"]

    def test_empty_dirs_are_listed(self, client_sorted: TestClient):
        """Empty dirs are surfaced so the OC8 lore skeleton (empty folders)
        stays visible after world creation instead of being pruned."""
        (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "vacio").mkdir()
        tree = client_sorted.get("/api/test_mundo/lore/tree").json()
        names = [node["name"] for node in tree]
        assert "vacio" in names


class TestTreeManifestOrdering:
    """PR 1: /tree honors the section's _order.json manifest (import order).

    Listed nodes keep their manifest index; unlisted nodes sort after them,
    folders before files within an index group, then alphabetically.
    """

    def test_tree_orders_by_manifest(self, client: TestClient):
        base = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        for name in ("intro.md", "chapter-2.md", "chapter-1.md"):
            (base / name).write_text(f"# {name}\n", encoding="utf-8")
        (base / "_order.json").write_text(
            json.dumps(["intro.md", "chapter-1.md", "chapter-2.md"]), encoding="utf-8"
        )
        names = [node["name"] for node in client.get("/api/test_mundo/lore/tree").json()]
        # Manifest order beats alphabetical; unlisted 00_inicio.md lands last.
        assert names == ["subdir", "intro.md", "chapter-1.md", "chapter-2.md", "00_inicio.md"]

    def test_tree_fallback_alphabetical(self, client: TestClient):
        base = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        (base / "intro.md").write_text("# I\n", encoding="utf-8")
        (base / "beta.md").write_text("# B\n", encoding="utf-8")
        (base / "alpha.md").write_text("# A\n", encoding="utf-8")
        (base / "_order.json").write_text(json.dumps(["intro.md"]), encoding="utf-8")
        names = [node["name"] for node in client.get("/api/test_mundo/lore/tree").json()]
        # intro.md is listed (index 0); unlisted files fall back to
        # case-insensitive alphabetical order after it.
        assert names == ["subdir", "intro.md", "00_inicio.md", "alpha.md", "beta.md"]

    def test_tree_folders_before_files(self, client: TestClient):
        base = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        (base / "chapter-1").mkdir()
        (base / "chapter-1" / "a.md").write_text("# A\n", encoding="utf-8")
        (base / "chapter-1.md").write_text("# C\n", encoding="utf-8")
        (base / "_order.json").write_text(
            json.dumps(["chapter-1", "chapter-1.md"]), encoding="utf-8"
        )
        names = [node["name"] for node in client.get("/api/test_mundo/lore/tree").json()]
        # Same-index group: the folder (is_file=0) sorts before the file (1).
        assert names.index("chapter-1") < names.index("chapter-1.md")

    def test_tree_no_manifest(self, client: TestClient):
        base = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        (base / "Beta.md").write_text("# B\n", encoding="utf-8")
        (base / "alpha.md").write_text("# A\n", encoding="utf-8")
        names = [node["name"] for node in client.get("/api/test_mundo/lore/tree").json()]
        # Historical behavior preserved: dirs first, files alphabetical.
        assert names == ["subdir", "00_inicio.md", "alpha.md", "Beta.md"]

    def test_delete_removes_from_manifest(self, client: TestClient):
        base = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        for name in ("intro.md", "chapter-1.md", "chapter-2.md"):
            (base / name).write_text(f"# {name}\n", encoding="utf-8")
        (base / "_order.json").write_text(
            json.dumps(["intro.md", "chapter-1.md", "chapter-2.md"]), encoding="utf-8"
        )
        resp = client.delete("/api/test_mundo/lore/file?path=chapter-1.md")
        assert resp.status_code == 200
        manifest = json.loads((base / "_order.json").read_text(encoding="utf-8"))
        # Deleted path removed, remaining entries keep their relative order.
        assert manifest == ["intro.md", "chapter-2.md"]

    def test_tree_hides_order_manifest(self, client: TestClient):
        """REQ-5 S9: _order.json never appears as a node in /tree.

        The existing ``_``-prefix filter in ``_build_tree`` already excludes
        the manifest from sibling iteration; this test pins that behavior so
        the manifest stays invisible to the tree contract.
        """
        base = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        (base / "intro.md").write_text("# Intro\n", encoding="utf-8")
        (base / "_order.json").write_text(
            json.dumps(["intro.md"]), encoding="utf-8"
        )
        tree = client.get("/api/test_mundo/lore/tree").json()

        def _walk_names(nodes: list[dict]) -> list[str]:
            out: list[str] = []
            for node in nodes:
                out.append(node["name"])
                out.extend(_walk_names(node.get("children", [])))
            return out

        all_names = _walk_names(tree)
        assert "intro.md" in all_names
        assert "_order.json" not in all_names

    def test_tree_orders_folders_by_manifest(self, client: TestClient):
        """Folders sort at the manifest index of their first listed child.

        The manifest stores FILE paths (``a/b.md``), never bare folders; a
        folder must inherit the position of the document that created it
        instead of falling into the unlisted alphabetical bucket.
        """
        base = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        for folder in (
            "el-origen-breve-historia",
            "ayagars-reptiles-vibrantes",
            "sistema-stal-poderes-vibrantes",
        ):
            (base / folder).mkdir()
            (base / folder / f"{folder}.md").write_text(f"# {folder}\n", encoding="utf-8")
        (base / "_order.json").write_text(
            json.dumps([
                "el-origen-breve-historia/el-origen-breve-historia.md",
                "ayagars-reptiles-vibrantes/ayagars-reptiles-vibrantes.md",
                "sistema-stal-poderes-vibrantes/sistema-stal-poderes-vibrantes.md",
            ]),
            encoding="utf-8",
        )
        names = [node["name"] for node in client.get("/api/test_mundo/lore/tree").json()]
        # Manifest order, not alphabetical (ayagars < el-origen < sistema-stal).
        assert names == [
            "el-origen-breve-historia",
            "ayagars-reptiles-vibrantes",
            "sistema-stal-poderes-vibrantes",
            "subdir",
            "00_inicio.md",
        ]

    def test_tree_folders_fallback_when_unlisted(self, client: TestClient):
        """Folders with no manifest entry (nor listed descendants) fall back
        to the alphabetical bucket, after every listed folder."""
        base = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        for folder in ("b-folder", "a-folder", "zeta-unlisted", "alpha-unlisted"):
            (base / folder).mkdir()
            (base / folder / f"{folder}.md").write_text("# F\n", encoding="utf-8")
        (base / "_order.json").write_text(
            json.dumps([
                "b-folder/b-folder.md",
                "a-folder/a-folder.md",
            ]),
            encoding="utf-8",
        )
        names = [node["name"] for node in client.get("/api/test_mundo/lore/tree").json()]
        # Listed folders keep manifest order; unlisted ones sort alphabetically
        # after them (len(order) fallback).
        assert names == [
            "b-folder",
            "a-folder",
            "alpha-unlisted",
            "subdir",
            "zeta-unlisted",
            "00_inicio.md",
        ]

    def test_tree_mixed_folders_and_plain_files(self, client: TestClient):
        """Root-level plain files keep their direct manifest index while
        folders interleave via their first listed child."""
        base = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        (base / "z-folder").mkdir()
        (base / "z-folder" / "z-file.md").write_text("# Z\n", encoding="utf-8")
        (base / "chapter-1.md").write_text("# C1\n", encoding="utf-8")
        (base / "intro.md").write_text("# Intro\n", encoding="utf-8")
        (base / "_order.json").write_text(
            json.dumps([
                "intro.md",
                "z-folder/z-file.md",
                "chapter-1.md",
            ]),
            encoding="utf-8",
        )
        names = [node["name"] for node in client.get("/api/test_mundo/lore/tree").json()]
        # intro.md (index 0) keeps its direct entry ahead of chapter-1.md
        # (index 2) — not alphabetical; z-folder sorts via its child (index 1).
        assert names == [
            "z-folder",
            "subdir",
            "intro.md",
            "chapter-1.md",
            "00_inicio.md",
        ]


class TestSaveEndpoint:
    def test_save_writes_content(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        conf, base_rev = _confirm(client, "00_inicio.md", "# Editado\n")
        resp = _gated_write(client, "00_inicio.md", "# Editado\n", conf, base_rev)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        saved = (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").read_text(encoding="utf-8")
        assert saved == "# Editado\n"

    def test_save_blocks_path_traversal(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo/lore/save?path=../../secrets.txt",
                           json={"content": "x"})
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()


class TestRelationsAfterSave:
    """P1: a save grows relations from the body, deterministically."""

    def _add_target(self) -> Path:
        world = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        (world / "beta.md").write_text(
            "---\ntype: personaje\nid: lore::beta\ntitle: Beta\n---\nBeta.\n",
            encoding="utf-8",
        )
        api_server._graph_indices.clear()
        return world

    def test_save_links_a_body_mention(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        world = self._add_target()
        content = "---\ntype: criatura\ntitle: Inicio\n---\nBeta arrives.\n"
        conf, base_rev = _confirm(client, "00_inicio.md", content)

        resp = _gated_write(client, "00_inicio.md", content, conf, base_rev)

        assert resp.status_code == 200, resp.text
        saved = (world / "00_inicio.md").read_text(encoding="utf-8")
        assert "relaciones:" in saved
        assert saved.count("lore::beta") == 1

    def test_resaving_does_not_duplicate_the_relation(
        self, client: TestClient, monkeypatch
    ):
        _principal(monkeypatch)
        world = self._add_target()
        content = "---\ntype: criatura\ntitle: Inicio\n---\nBeta arrives.\n"
        conf, base_rev = _confirm(client, "00_inicio.md", content)
        assert _gated_write(client, "00_inicio.md", content, conf, base_rev).status_code == 200
        saved = (world / "00_inicio.md").read_text(encoding="utf-8")

        conf2, base_rev2 = _confirm(client, "00_inicio.md", saved, edit_id="e2")
        resp = _gated_write(client, "00_inicio.md", saved, conf2, base_rev2, edit_id="e2")

        assert resp.status_code == 200, resp.text
        resaved = (world / "00_inicio.md").read_text(encoding="utf-8")
        assert resaved.count("lore::beta") == 1
        assert resaved == saved

    def test_reverse_pass_links_an_existing_mention(
        self, client: TestClient, monkeypatch
    ):
        _principal(monkeypatch)
        world = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        (world / "delta.md").write_text(
            "---\ntype: personaje\nid: lore::delta\ntitle: Delta\n---\n"
            "Delta mentions Gamma.\n",
            encoding="utf-8",
        )
        api_server._graph_indices.clear()
        content = "---\ntype: personaje\nid: lore::gamma\ntitle: Gamma\n---\nGamma is new.\n"
        conf, base_rev = _confirm(client, "00_inicio.md", content)

        resp = _gated_write(client, "00_inicio.md", content, conf, base_rev)

        assert resp.status_code == 200, resp.text
        delta = (world / "delta.md").read_text(encoding="utf-8")
        assert delta.count("lore::gamma") == 1


class TestDiffEndpoint:
    def test_diff_marks_added_removed_same(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/lore/diff?path=00_inicio.md",
            json={"content": "# Inicio\n\nNueva línea\n"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["original_path"] == "00_inicio.md"
        types = [line["type"] for line in body["diff"]]
        assert "same" in types
        assert "added" in types
        for line in body["diff"]:
            assert line["type"] in ("same", "added", "removed")
            assert "text" in line

    def test_diff_identical_content_all_same(self, client: TestClient):
        content = (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").read_text(encoding="utf-8")
        resp = client.post(
            "/api/test_mundo/lore/diff?path=00_inicio.md",
            json={"content": content},
        )
        body = resp.json()
        assert len(body["diff"]) > 0
        assert all(line["type"] == "same" for line in body["diff"])


class TestTrashDelete:
    """S24-S27: delete_file moves to .papelera, never unlinks.

    v2 contract: every deleted item lives under
    ``.papelera/{section}/{entry_id12}/`` with a ``meta.json`` next to the
    original basename (file or directory tree) — no more ``{ts}_path`` names.
    """

    def _papelera_lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / ".papelera" / "lore"

    def _entry_dir(self, entry_id: str) -> Path:
        return self._papelera_lore() / entry_id

    def test_file_moves_to_papelera(self, client: TestClient):
        resp = client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert re.fullmatch(r"[0-9a-f]{12}", body["entry_id"])
        entry_dir = self._entry_dir(body["entry_id"])
        # entry_dir named as 12-hex id, holding meta.json + the original file
        assert entry_dir.name == body["entry_id"]
        assert entry_dir.is_dir()
        assert re.fullmatch(r"[0-9a-f]{12}", entry_dir.name)
        assert (entry_dir / "meta.json").is_file()
        assert (entry_dir / "00_inicio.md").read_text(encoding="utf-8").startswith("---")
        meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["entry_id"] == body["entry_id"]
        assert meta["original_path"] == "00_inicio.md"
        assert meta["kind"] == "file"
        assert meta["deleted_at"].endswith("Z")
        assert isinstance(meta["size"], int) and meta["size"] > 0
        # Original gone
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").exists()

    def test_dir_moves_recursively(self, client: TestClient):
        ciudades = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "ciudades"
        ciudades.mkdir()
        (ciudades / "alfa.md").write_text("# Alfa\n", encoding="utf-8")
        (ciudades / "beta.md").write_text("# Beta\n", encoding="utf-8")

        resp = client.delete("/api/test_mundo/lore/file?path=ciudades")
        assert resp.status_code == 200
        entry_dir = self._entry_dir(resp.json()["entry_id"])
        assert entry_dir.is_dir()
        # Directory content kept under the moved dir's basename inside entry_dir
        assert (entry_dir / "ciudades" / "alfa.md").read_text(encoding="utf-8") == "# Alfa\n"
        assert (entry_dir / "ciudades" / "beta.md").read_text(encoding="utf-8") == "# Beta\n"
        meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["kind"] == "dir"
        assert meta["original_path"] == "ciudades"
        assert not ciudades.exists()

    def test_subfolders_preserved(self, client: TestClient):
        planos = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "ciudades" / "planos"
        planos.mkdir(parents=True)
        (planos / "x.md").write_text("# X\n", encoding="utf-8")

        resp = client.delete("/api/test_mundo/lore/file?path=ciudades")
        assert resp.status_code == 200
        entry_dir = self._entry_dir(resp.json()["entry_id"])
        # Nested subfolders survive the move under entry_dir/{basename}/...
        assert (entry_dir / "ciudades" / "planos" / "x.md").read_text(encoding="utf-8") == "# X\n"
        assert (entry_dir / "meta.json").is_file()

    def test_rapid_deletes_get_distinct_entry_ids(self, client: TestClient):
        base = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        (base / "a.md").write_text("# A\n", encoding="utf-8")
        (base / "b.md").write_text("# B\n", encoding="utf-8")

        r1 = client.delete("/api/test_mundo/lore/file?path=a.md")
        r2 = client.delete("/api/test_mundo/lore/file?path=b.md")
        assert r1.status_code == 200
        assert r2.status_code == 200
        e1, e2 = r1.json()["entry_id"], r2.json()["entry_id"]
        assert e1 != e2
        assert re.fullmatch(r"[0-9a-f]{12}", e1)
        assert re.fullmatch(r"[0-9a-f]{12}", e2)
        for eid in (e1, e2):
            assert (self._entry_dir(eid) / "meta.json").is_file()
            assert (self._entry_dir(eid) / "a.md").exists() or (self._entry_dir(eid) / "b.md").exists()
        # Exactly two entry dirs, each with a valid 12-hex name
        names = sorted(p.name for p in self._papelera_lore().iterdir())
        assert names == sorted([e1, e2])

    def test_tree_no_longer_lists_trashed_file(self, client: TestClient):
        client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert "00_inicio.md" not in [n["name"] for n in tree]

    def test_papelera_never_appears_in_tree(self, client: TestClient):
        client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        tree = client.get("/api/test_mundo/lore/tree").json()

        def walk(nodes):
            for node in nodes:
                assert ".papelera" not in node["path"]
                if node["is_dir"]:
                    walk(node["children"])

        walk(tree)

    def test_graph_search_excludes_trashed_entity(self, client: TestClient):
        before = client.get("/api/test_mundo/graph/search?q=inicio").json()
        assert any(h["path"] == "lore/00_inicio.md" for h in before)
        assert "test_mundo" in api_server._graph_indices

        assert client.delete("/api/test_mundo/lore/file?path=00_inicio.md").status_code == 200
        assert "test_mundo" not in api_server._graph_indices  # cache popped

        after = client.get("/api/test_mundo/graph/search?q=inicio").json()
        assert after == []
        assert all(h["path"] != "lore/00_inicio.md" for h in after)

    def test_missing_returns_404(self, client: TestClient):
        resp = client.delete("/api/test_mundo/lore/file?path=no_existe.md")
        assert resp.status_code == 404
        assert "no encontrado" in resp.json()["detail"].lower()

    def test_empty_path_returns_400(self, client: TestClient):
        resp = client.delete("/api/test_mundo/lore/file?path=")
        assert resp.status_code == 400


class TestErrorUpgrades:
    """D8/S35: create_file/save_file raise HTTPException with real statuses;
    slice 1B gates writes behind a trusted principal (seam fails closed)."""

    def test_create_existing_returns_409(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo/lore/create?path=00_inicio.md", json={"content": "x"})
        assert resp.status_code == 409
        assert "ya existe" in resp.json()["detail"].lower()

    def test_create_invalid_section_returns_400(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo/wiki/create?path=a.md", json={"content": "x"})
        assert resp.status_code == 400
        assert resp.json()["detail"]

    def test_create_missing_mundo_returns_404(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo_fantasma/lore/create?path=a.md", json={"content": "x"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_create_traversal_returns_400(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo/lore/create?path=../../x.md", json={"content": "x"})
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()

    def test_save_invalid_section_returns_400(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo/wiki/save?path=a.md", json={"content": "x"})
        assert resp.status_code == 400

    def test_save_missing_mundo_returns_404(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo_fantasma/lore/save?path=a.md", json={"content": "x"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_save_traversal_returns_400(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post("/api/test_mundo/lore/save?path=../../x.md", json={"content": "x"})
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()


class TestMoveEndpoint:
    """S15-S20: POST /api/{mundo}/move with independent path validation."""

    def test_rename_same_dir(self, client: TestClient):
        resp = client.post("/api/test_mundo/move", json={"from": "lore/00_inicio.md", "to": "lore/inicio.md"})
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "path": "lore/inicio.md"}
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "inicio.md").exists()
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").exists()

    def test_cross_section_recursive(self, client: TestClient):
        ciudades = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "ciudades"
        ciudades.mkdir()
        (ciudades / "planos").mkdir()
        (ciudades / "planos" / "x.md").write_text("# X\n", encoding="utf-8")

        resp = client.post("/api/test_mundo/move", json={"from": "lore/ciudades", "to": "personajes/ciudades"})
        assert resp.status_code == 200
        moved = api_server.MUNDOS_DIR / "test_mundo" / "personajes" / "ciudades"
        assert (moved / "planos" / "x.md").read_text(encoding="utf-8") == "# X\n"
        assert not ciudades.exists()

    def test_into_itself_400(self, client: TestClient):
        (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "c").mkdir()
        resp = client.post("/api/test_mundo/move", json={"from": "lore/c", "to": "lore/c/sub"})
        assert resp.status_code == 400
        assert "sí misma" in resp.json()["detail"]
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "c").is_dir()

    def test_to_exists_409(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/move",
            json={"from": "lore/00_inicio.md", "to": "lore/subdir/detalle.md"},
        )
        assert resp.status_code == 409
        assert "ya existe" in resp.json()["detail"].lower()
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").exists()

    def test_from_missing_404(self, client: TestClient):
        resp = client.post("/api/test_mundo/move", json={"from": "lore/no_existe.md", "to": "lore/x.md"})
        assert resp.status_code == 404

    def test_traversal_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/move", json={"from": "../secret.md", "to": "lore/x.md"})
        assert resp.status_code == 400
        resp2 = client.post("/api/test_mundo/move", json={"from": "lore/00_inicio.md", "to": "../fuera.md"})
        assert resp2.status_code == 400

    def test_invalid_section_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/move", json={"from": "lore/00_inicio.md", "to": "wiki/x.md"})
        assert resp.status_code == 400

    def test_deep_target_mkdir(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/move",
            json={"from": "lore/00_inicio.md", "to": "personajes/carpetas/nueva/x.md"},
        )
        assert resp.status_code == 200
        assert (api_server.MUNDOS_DIR / "test_mundo" / "personajes" / "carpetas" / "nueva" / "x.md").exists()

    def test_destination_referencias_200(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/move",
            json={"from": "lore/00_inicio.md", "to": "referencias/notas/x.md"},
        )
        assert resp.status_code == 200
        assert (api_server.MUNDOS_DIR / "test_mundo" / "referencias" / "notas" / "x.md").exists()

    def test_unicode_and_spaces(self, client: TestClient):
        bosque = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "El Bosque Oscuro"
        bosque.mkdir()
        (bosque / "Ñandú.md").write_text("# Ñ\n", encoding="utf-8")
        resp = client.post(
            "/api/test_mundo/move",
            json={"from": "lore/El Bosque Oscuro/Ñandú.md", "to": "lore/El Bosque Oscuro/Renombrado.md"},
        )
        assert resp.status_code == 200
        assert (bosque / "Renombrado.md").exists()
        assert not (bosque / "Ñandú.md").exists()

    def test_graph_cache_popped(self, client: TestClient):
        client.get("/api/test_mundo/graph/search?q=inicio")
        assert "test_mundo" in api_server._graph_indices
        resp = client.post("/api/test_mundo/move", json={"from": "lore/00_inicio.md", "to": "lore/inicio.md"})
        assert resp.status_code == 200
        assert "test_mundo" not in api_server._graph_indices

    def test_missing_fields_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/move", json={"from": "lore/00_inicio.md"})
        assert resp.status_code == 400


class TestDuplicateEndpoint:
    """S21-S23: POST /api/{mundo}/duplicate with server-side collision
    resolution and byte-identical copies."""

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def test_happy_creates_copia_with_identical_bytes(self, client: TestClient):
        content = "---\ntype: criatura\ntitle: Inicio\n---\n# Inicio\n"
        (self._lore() / "a.md").write_text(content, encoding="utf-8")
        resp = client.post("/api/test_mundo/duplicate", json={"from": "lore/a.md"})
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "path": "lore/a-copia.md"}
        # Byte-identical to the source (S23)
        assert (self._lore() / "a-copia.md").read_bytes() == (self._lore() / "a.md").read_bytes()

    def test_collision_one_uses_suffix_2(self, client: TestClient):
        content = "# A\n"
        (self._lore() / "a.md").write_text(content, encoding="utf-8")
        (self._lore() / "a-copia.md").write_text("exists", encoding="utf-8")
        resp = client.post("/api/test_mundo/duplicate", json={"from": "lore/a.md"})
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "path": "lore/a-2.md"}
        assert (self._lore() / "a-2.md").read_bytes() == (self._lore() / "a.md").read_bytes()

    def test_collision_two_uses_suffix_3(self, client: TestClient):
        content = "# A\n"
        (self._lore() / "a.md").write_text(content, encoding="utf-8")
        (self._lore() / "a-copia.md").write_text("1", encoding="utf-8")
        (self._lore() / "a-2.md").write_text("2", encoding="utf-8")
        resp = client.post("/api/test_mundo/duplicate", json={"from": "lore/a.md"})
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "path": "lore/a-3.md"}

    def test_directory_returns_422(self, client: TestClient):
        (self._lore() / "carpeta").mkdir()
        resp = client.post("/api/test_mundo/duplicate", json={"from": "lore/carpeta"})
        assert resp.status_code == 422
        assert "solo se pueden duplicar archivos" in resp.json()["detail"].lower()

    def test_missing_returns_404(self, client: TestClient):
        resp = client.post("/api/test_mundo/duplicate", json={"from": "lore/no_existe.md"})
        assert resp.status_code == 404

    def test_traversal_returns_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/duplicate", json={"from": "../secret.md"})
        assert resp.status_code == 400

    def test_graph_cache_popped(self, client: TestClient):
        client.get("/api/test_mundo/graph/search?q=inicio")
        assert "test_mundo" in api_server._graph_indices
        resp = client.post("/api/test_mundo/duplicate", json={"from": "lore/00_inicio.md"})
        assert resp.status_code == 200
        assert resp.json()["path"] == "lore/00_inicio-copia.md"
        assert "test_mundo" not in api_server._graph_indices


class TestCovers:
    """S29-S31: ?covers=true adds portada to file nodes; dirs null; field
    absent without the param; frontmatter value with body-image fallback."""

    def _world(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo"

    def _setup_media(self) -> Path:
        media = self._world() / "wiki" / "media"
        media.mkdir(parents=True)
        (media / "foto.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
        return media

    def test_valid_portada(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "a.md").write_text(
            "---\ntype: ficha\nportada: wiki/media/foto.jpg\n---\n# A\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = next(n for n in tree if n["name"] == "a.md")
        assert node["portada"] == "wiki/media/foto.jpg"

    def test_quoted_portada_value(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "f.md").write_text(
            '---\nportada: "wiki/media/foto.jpg"\n---\n# F\n', encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = next(n for n in tree if n["name"] == "f.md")
        assert node["portada"] == "wiki/media/foto.jpg"

    def test_portada_missing_falls_back_to_body_image(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "b.md").write_text(
            "---\nportada: wiki/media/inexistente.jpg\n---\n# B\n\n![alt](wiki/media/foto.jpg)\n",
            encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = next(n for n in tree if n["name"] == "b.md")
        assert node["portada"] == "wiki/media/foto.jpg"

    def test_body_image_without_portada(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "c.md").write_text(
            "# C\n\n![descripción](wiki/media/foto.jpg)\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = next(n for n in tree if n["name"] == "c.md")
        assert node["portada"] == "wiki/media/foto.jpg"

    def test_body_image_strips_fragment_suffix(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "d.md").write_text(
            "# D\n\n![x](wiki/media/foto.jpg#grande)\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = next(n for n in tree if n["name"] == "d.md")
        assert node["portada"] == "wiki/media/foto.jpg"

    def test_no_images_returns_null(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "e.md").write_text("# E\n\nSin imágenes\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = next(n for n in tree if n["name"] == "e.md")
        assert node["portada"] is None

    def test_directory_returns_null(self, client: TestClient):
        self._setup_media()
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        subdir = next(n for n in tree if n["is_dir"])
        assert subdir["portada"] is None

    def test_covers_false_field_absent(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "a.md").write_text(
            "---\nportada: wiki/media/foto.jpg\n---\n# A\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        node = next(n for n in tree if n["name"] == "a.md")
        assert "portada" not in node

    def test_covers_in_nested_files(self, client: TestClient):
        self._setup_media()
        (self._world() / "lore" / "subdir" / "g.md").write_text(
            "# G\n\n![x](wiki/media/foto.jpg)\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        subdir = next(n for n in tree if n["is_dir"])
        node = next(n for n in subdir["children"] if n["name"] == "g.md")
        assert node["portada"] == "wiki/media/foto.jpg"


class TestTreeStatus:
    """Item 14 follow-up: tree nodes expose the OKF frontmatter ``status``
    (draft|stable) — only known values, only for files, only from the
    leading frontmatter block (legacy body blocks never count)."""

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def _node(self, tree: list, name: str) -> dict:
        return next(n for n in tree if n["name"] == name)

    def test_file_with_draft_status(self, client: TestClient):
        (self._lore() / "d.md").write_text(
            "---\ntype: ficha\nstatus: draft\n---\n# D\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert self._node(tree, "d.md")["status"] == "draft"

    def test_file_with_stable_status(self, client: TestClient):
        (self._lore() / "s.md").write_text(
            "---\nstatus: stable\n---\n# S\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert self._node(tree, "s.md")["status"] == "stable"

    def test_quoted_status_value(self, client: TestClient):
        (self._lore() / "q.md").write_text(
            '---\nstatus: "draft"\n---\n# Q\n', encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert self._node(tree, "q.md")["status"] == "draft"

    def test_crlf_frontmatter_status(self, client: TestClient):
        (self._lore() / "crlf.md").write_bytes(
            "---\r\nstatus: draft\r\n---\r\n# CRLF\r\n".encode("utf-8"))
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert self._node(tree, "crlf.md")["status"] == "draft"

    def test_missing_status_field_absent(self, client: TestClient):
        (self._lore() / "plain.md").write_text("# Sin frontmatter\n", encoding="utf-8")
        (self._lore() / "fm.md").write_text(
            "---\ntype: ficha\n---\n# FM\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        for name in ("plain.md", "fm.md"):
            assert "status" not in self._node(tree, name)

    def test_unknown_status_field_absent(self, client: TestClient):
        (self._lore() / "synced.md").write_text(
            '---\nstatus: "synced"\n---\n# SY\n', encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert "status" not in self._node(tree, "synced.md")

    def test_legacy_body_blocks_are_ignored(self, client: TestClient):
        (self._lore() / "pert.md").write_text(
            "# Titulo\n\n---\nstatus: stable\n---\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree").json()
        assert "status" not in self._node(tree, "pert.md")

    def test_directories_never_carry_status(self, client: TestClient):
        tree = client.get("/api/test_mundo/lore/tree").json()
        for node in tree:
            if node["is_dir"]:
                assert "status" not in node

    def test_status_survives_covers_param(self, client: TestClient):
        (self._lore() / "c.md").write_text(
            "---\nstatus: stable\n---\n# C\n", encoding="utf-8")
        tree = client.get("/api/test_mundo/lore/tree?covers=true").json()
        node = self._node(tree, "c.md")
        assert node["status"] == "stable"
        assert "portada" in node


class TestStatusEndpoint:
    """Item 14: POST /api/{mundo}/{section}/status rewrites ONLY the
    frontmatter `status:` line — CRLF-safe, never touching legacy body
    blocks (Pert.md regression)."""

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def test_updates_status_and_preserves_crlf_bytes(self, client: TestClient):
        content = "---\r\ntype: Personaje\r\ntitle: X\r\nstatus: draft\r\n---\r\n# Cuerpo\r\n"
        (self._lore() / "ficha.md").write_bytes(content.encode("utf-8"))
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "ficha.md", "status": "stable"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "path": "lore/ficha.md", "status": "stable"}
        # CRLF preserved byte-for-byte except the status line value
        expected = content.replace("status: draft\r\n", "status: stable\r\n")
        assert (self._lore() / "ficha.md").read_bytes() == expected.encode("utf-8")

    def test_legacy_body_block_untouched(self, client: TestClient):
        """Pert.md shape: `status` in the frontmatter AND a legacy
        `---\nstatus: draft\n---` block in the body — only the first block
        is rewritten."""
        content = (
            "---\ntype: Personaje\ntitle: Pert\nstatus: stable\n---\n\n"
            "---\nstatus: draft\n---\n\nCuerpo\n"
        )
        (self._lore() / "pert.md").write_text(content, encoding="utf-8")
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "pert.md", "status": "draft"},
        )
        assert resp.status_code == 200
        saved = (self._lore() / "pert.md").read_text(encoding="utf-8")
        # Frontmatter updated, legacy body block untouched
        assert saved == content.replace("status: stable\n", "status: draft\n", 1)
        assert saved.count("status: draft") == 2

    def test_legacy_body_block_untouched_crlf(self, client: TestClient):
        content = (
            "---\r\ntype: Personaje\r\ntitle: Pert\r\nstatus: stable\r\n---\r\n\r\n"
            "---\r\nstatus: draft\r\n---\r\n\r\nCuerpo\r\n"
        )
        (self._lore() / "pert.md").write_bytes(content.encode("utf-8"))
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "pert.md", "status": "stable"},
        )
        assert resp.status_code == 200
        saved = (self._lore() / "pert.md").read_bytes()
        assert saved.count(b"status: stable") == 1
        assert saved.count(b"status: draft") == 1  # legacy block untouched
        assert b"\r\n" in saved

    def test_inserts_status_line_when_field_missing(self, client: TestClient):
        content = "---\ntype: Nota\ntitle: X\n---\nCuerpo"
        (self._lore() / "nota.md").write_text(content, encoding="utf-8")
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "nota.md", "status": "draft"},
        )
        assert resp.status_code == 200
        saved = (self._lore() / "nota.md").read_text(encoding="utf-8")
        assert saved == "---\ntype: Nota\ntitle: X\nstatus: draft\n---\nCuerpo"

    def test_no_frontmatter_inserts_leading_block(self, client: TestClient):
        (self._lore() / "plain.md").write_text("# Plain\n", encoding="utf-8")
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "plain.md", "status": "draft"},
        )
        assert resp.status_code == 200
        saved = (self._lore() / "plain.md").read_text(encoding="utf-8")
        assert saved == "---\nstatus: draft\n---\n# Plain\n"

    def test_invalid_status_returns_422(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "00_inicio.md", "status": "published"},
        )
        assert resp.status_code == 422
        assert "estado inválido" in resp.json()["detail"].lower()
        # File untouched
        saved = (self._lore() / "00_inicio.md").read_text(encoding="utf-8")
        assert "status:" not in saved

    def test_missing_file_returns_404(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "no_existe.md", "status": "draft"},
        )
        assert resp.status_code == 404
        assert "no encontrado" in resp.json()["detail"].lower()

    def test_missing_mundo_returns_404(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo_fantasma/lore/status",
            json={"path": "a.md", "status": "draft"},
        )
        assert resp.status_code == 404

    def test_traversal_returns_400(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"path": "../../secrets.md", "status": "draft"},
        )
        assert resp.status_code == 400

    def test_missing_path_field_returns_400(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/lore/status",
            json={"status": "draft"},
        )
        assert resp.status_code == 400


class TestSetFrontmatterRelaciones:
    """Unit tests for api_server._set_frontmatter_relaciones — the CRLF-safe,
    YAML-validated rewrite of the frontmatter `relaciones:` list."""

    @staticmethod
    def _set(content: str, action: str, target_id: str) -> str:
        return api_server._set_frontmatter_relaciones(content, action, target_id)

    def test_create_adds_entry_when_field_absent(self):
        content = "---\ntype: Personaje\ntitle: Rhyz\n---\n# Cuerpo\n"
        out = self._set(content, "create", "Stal::Vael")
        assert out == (
            "---\ntype: Personaje\ntitle: Rhyz\nrelaciones:\n  - Stal::Vael\n---\n# Cuerpo\n"
        )

    def test_create_appends_to_existing_block(self):
        content = "---\ntype: Personaje\ntitle: Rhyz\nrelaciones:\n  - Stal::Otro\n---\n# Cuerpo\n"
        out = self._set(content, "create", "Stal::Vael")
        assert out == (
            "---\ntype: Personaje\ntitle: Rhyz\nrelaciones:\n  - Stal::Otro\n  - Stal::Vael\n---\n# Cuerpo\n"
        )

    def test_break_removes_entry_and_keeps_others(self):
        content = "---\ntype: Personaje\ntitle: Rhyz\nrelaciones:\n  - Stal::Vael\n  - Stal::Otro\n---\n# Cuerpo\n"
        out = self._set(content, "break", "Stal::Vael")
        assert out == (
            "---\ntype: Personaje\ntitle: Rhyz\nrelaciones:\n  - Stal::Otro\n---\n# Cuerpo\n"
        )

    def test_break_removes_now_empty_block(self):
        content = "---\ntype: Personaje\ntitle: Rhyz\nrelaciones:\n  - Stal::Vael\n---\n# Cuerpo\n"
        out = self._set(content, "break", "Stal::Vael")
        assert out == "---\ntype: Personaje\ntitle: Rhyz\n---\n# Cuerpo\n"

    def test_crlf_preserved_byte_for_byte(self):
        content = "---\r\ntype: Personaje\r\ntitle: Rhyz\r\n---\r\n# Cuerpo\r\n"
        out = self._set(content, "create", "Stal::Vael")
        assert out == (
            "---\r\ntype: Personaje\r\ntitle: Rhyz\r\nrelaciones:\r\n  - Stal::Vael\r\n---\r\n# Cuerpo\r\n"
        )

    def test_no_frontmatter_prepends_block(self):
        content = "# Plain\n"
        out = self._set(content, "create", "Stal::Vael")
        assert out == "---\nrelaciones:\n  - Stal::Vael\n---\n# Plain\n"

    def test_an_id_with_a_colon_round_trips_as_a_string(self):
        """Regression: a bare ``Eneatipo 8: El Desafiante`` parsed as a MAPPING.

        The sync then never converged: every run re-planned the same addition,
        wrote nothing and reported zero applied files.
        """
        content = "---\ntype: concepto\ntitle: Canon\n---\n# Cuerpo\n"
        out = self._set(content, "create", "Eneatipo 8: El Desafiante")

        assert '  - "Eneatipo 8: El Desafiante"' in out
        frontmatter = out.split("---")[1]
        assert api_server.yaml.safe_load(frontmatter)["relaciones"] == [
            "Eneatipo 8: El Desafiante"
        ]
        # Idempotent: the second create is a conflict, not a silent duplicate.
        with pytest.raises(api_server.RelationConflict):
            self._set(out, "create", "Eneatipo 8: El Desafiante")

    def test_a_plain_id_keeps_its_existing_bytes(self):
        """Only values that would not round-trip get quoted (no diff churn)."""
        content = "---\ntype: Personaje\ntitle: Rhyz\n---\n"
        out = self._set(content, "create", "Stal::Vael")
        assert "  - Stal::Vael" in out
        assert '"' not in out

    def test_duplicate_create_raises_conflict(self):
        content = "---\ntype: Personaje\ntitle: Rhyz\nrelaciones:\n  - Stal::Vael\n---\n"
        with pytest.raises(api_server.RelationConflict):
            self._set(content, "create", "Stal::Vael")

    def test_break_missing_raises_conflict(self):
        content = "---\ntype: Personaje\ntitle: Rhyz\n---\n"
        with pytest.raises(api_server.RelationConflict):
            self._set(content, "break", "Stal::Vael")

    def test_flow_form_normalized_on_create(self):
        content = "---\ntype: Personaje\ntitle: Rhyz\nrelaciones: [Stal::Otro]\n---\n"
        out = self._set(content, "create", "Stal::Vael")
        assert out == (
            "---\ntype: Personaje\ntitle: Rhyz\nrelaciones:\n  - Stal::Otro\n  - Stal::Vael\n---\n"
        )

    def test_break_matches_wikilink_wrapped_entry(self):
        content = '---\ntype: Personaje\ntitle: Rhyz\nrelaciones:\n  - "[[Stal::Vael]]"\n---\n'
        out = self._set(content, "break", "Stal::Vael")
        assert out == "---\ntype: Personaje\ntitle: Rhyz\n---\n"

    def test_invalid_action_raises_value_error(self):
        with pytest.raises(ValueError):
            self._set("---\ntype: X\n---\n", "rename", "Stal::Vael")


class TestGraphRelationEndpoint:
    """POST /api/{mundo}/graph/relation — create/break a graph connection by
    rewriting the source ficha's frontmatter `relaciones:` list."""

    @staticmethod
    def _personajes() -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "personajes"

    def _seed(self) -> None:
        """Two indexed fichas with canonical ids: Rhyz (source) + Vael (target)."""
        personajes = self._personajes()
        personajes.mkdir(parents=True, exist_ok=True)
        (personajes / "Rhyz.md").write_text(
            "---\ntype: Personaje\ntitle: Rhyz\nid: Rhyz::Vael\n---\n# Rhyz\n",
            encoding="utf-8",
        )
        (personajes / "Vael.md").write_text(
            "---\ntype: Personaje\ntitle: Vael\nid: Stal::Vael\n---\n# Vael\n",
            encoding="utf-8",
        )

    def _seed_with_relation(self) -> None:
        self._seed()
        (self._personajes() / "Rhyz.md").write_text(
            "---\ntype: Personaje\ntitle: Rhyz\nid: Rhyz::Vael\n"
            "relaciones:\n  - Stal::Vael\n---\n# Rhyz\n",
            encoding="utf-8",
        )

    def test_create_relation_returns_200(self, client: TestClient):
        self._seed()
        resp = client.post(
            "/api/test_mundo/graph/relation",
            json={"action": "create", "source_path": "personajes/Rhyz.md", "target_id": "Stal::Vael"},
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "success": True,
            "path": "personajes/Rhyz.md",
            "action": "create",
            "target_id": "Stal::Vael",
        }
        saved = (self._personajes() / "Rhyz.md").read_text(encoding="utf-8")
        assert "relaciones:\n  - Stal::Vael" in saved
        # Graph cache invalidated so the watcher reindexes on next read.
        assert "test_mundo" not in api_server._graph_indices

    def test_break_relation_returns_200(self, client: TestClient):
        self._seed_with_relation()
        resp = client.post(
            "/api/test_mundo/graph/relation",
            json={"action": "break", "source_path": "personajes/Rhyz.md", "target_id": "Stal::Vael"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        saved = (self._personajes() / "Rhyz.md").read_text(encoding="utf-8")
        assert "relaciones:" not in saved
        assert "test_mundo" not in api_server._graph_indices

    def test_source_not_found_returns_404(self, client: TestClient):
        self._seed()
        resp = client.post(
            "/api/test_mundo/graph/relation",
            json={"action": "create", "source_path": "personajes/NoExiste.md", "target_id": "Stal::Vael"},
        )
        assert resp.status_code == 404
        assert "origen" in resp.json()["detail"].lower()

    def test_target_not_found_returns_404(self, client: TestClient):
        self._seed()
        resp = client.post(
            "/api/test_mundo/graph/relation",
            json={"action": "create", "source_path": "personajes/Rhyz.md", "target_id": "Stal::Fantasmal"},
        )
        assert resp.status_code == 404
        assert "destino" in resp.json()["detail"].lower()

    def test_duplicate_relation_returns_409(self, client: TestClient):
        self._seed_with_relation()
        resp = client.post(
            "/api/test_mundo/graph/relation",
            json={"action": "create", "source_path": "personajes/Rhyz.md", "target_id": "Stal::Vael"},
        )
        assert resp.status_code == 409

    def test_break_non_existent_returns_409(self, client: TestClient):
        self._seed()
        resp = client.post(
            "/api/test_mundo/graph/relation",
            json={"action": "break", "source_path": "personajes/Rhyz.md", "target_id": "Stal::Vael"},
        )
        assert resp.status_code == 409

    def test_path_traversal_returns_400(self, client: TestClient):
        self._seed()
        resp = client.post(
            "/api/test_mundo/graph/relation",
            json={"action": "create", "source_path": "../../secrets.md", "target_id": "Stal::Vael"},
        )
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()

    def test_missing_fields_returns_400(self, client: TestClient):
        self._seed()
        assert client.post(
            "/api/test_mundo/graph/relation", json={}
        ).status_code == 400
        assert client.post(
            "/api/test_mundo/graph/relation",
            json={"action": "create", "target_id": "Stal::Vael"},
        ).status_code == 400
        assert client.post(
            "/api/test_mundo/graph/relation",
            json={"action": "create", "source_path": "personajes/Rhyz.md"},
        ).status_code == 400

    def test_invalid_action_returns_400(self, client: TestClient):
        self._seed()
        resp = client.post(
            "/api/test_mundo/graph/relation",
            json={"action": "rename", "source_path": "personajes/Rhyz.md", "target_id": "Stal::Vael"},
        )
        assert resp.status_code == 400


class TestAiAsk:
    def test_natural_character_message_handoffs_to_guided_session(self, client: TestClient, monkeypatch):
        """Hermes-first: a natural character message becomes a guarded guided
        session only through a validated require_confirmation decision."""
        _principal(monkeypatch)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(api_server, "_named_reference_context", lambda _m, _p: ("", False, None))
        runs = _SemanticRuns(_continuation_semantic_payload("require_confirmation"))
        _wire_semantic_provider(monkeypatch, runs)

        response = client.post(
            "/api/test_mundo/ai/ask",
            json={"prompt": "Un guerrero de las sombras", "session_id": "chat-1"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["state"] == "require_confirmation"
        assert payload["guided_session_id"].startswith("guided-")
        assert payload["guided_revision"] == 1
        assert payload["guided_state"]["phase"] == "confirmation"
        assert payload["guided_state"]["session_id"] == payload["guided_session_id"]
        assert runs.starts == 1

    def test_subsequent_guided_turn_keeps_session_and_revision(self, client: TestClient, monkeypatch):
        _principal(monkeypatch, "author-1")
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(api_server, "_named_reference_context", lambda _m, _p: ("", False, None))
        runs = _SemanticRuns(
            _continuation_semantic_payload("require_confirmation"),
            _semantic_payload("allow"),
        )
        _wire_semantic_provider(monkeypatch, runs)
        first = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Quiero crear un personaje", "session_id": "chat-1",
        }).json()

        second = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Busca la libertad", "session_id": "chat-1",
            "guided_session_id": first["guided_session_id"],
            "guided_revision": first["guided_revision"],
        })

        assert second.status_code == 200
        assert second.json()["guided_session_id"] == first["guided_session_id"]
        assert second.json()["guided_revision"] == first["guided_revision"] + 1
        assert runs.starts == 2

    def test_guided_turn_receives_bounded_active_ficha_context(self, client: TestClient, monkeypatch):
        """The authorized open ficha reaches Hermes as bounded context."""
        target = api_server.MUNDOS_DIR / "test_mundo" / "personajes" / "rhyz.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("---\ntitle: Rhyz\n---\nRhyz is a patient tactician.\n", encoding="utf-8")
        runs = _SemanticRuns(_continuation_semantic_payload("require_confirmation"))
        _wire_semantic_provider(monkeypatch, runs)
        _principal(monkeypatch)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(api_server, "_named_reference_context", lambda _m, _p: ("", False, None))

        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Me gustaria crear un nuevo personaje",
            "section": "personajes", "file_path": "rhyz.md",
        })

        assert response.status_code == 200
        prompt = runs.requests[0].prompt
        assert "Rhyz is a patient tactician." in prompt
        assert "personajes/rhyz.md" not in prompt
        assert runs.starts == 1

    def test_folder_character_reference_uses_canonical_graph_evidence(self, client: TestClient, monkeypatch):
        class Graph:
            def __init__(self):
                self.calls = []

            def search(self, query):
                self.calls.append(("search", query))
                return [{"name": "Rhyz", "path": "personajes/rhyz.md"}]

            def read(self, path):
                self.calls.append(("read", path))
                return {"name": "Rhyz", "type": "Personaje", "content": "Patient tactician."}

            def links(self, path, kind):
                self.calls.append(("links", kind))
                return []

        graph = Graph()
        seen = []

        async def provider(request, _token):
            seen.append(request.reference_context)
            return {
                "protocol_version": request.protocol_version,
                "request_id": request.request_id,
                "session_id": request.session_id,
                "outcome": "question",
                "question": "What makes this sibling distinct?",
            }

        _principal(monkeypatch)
        monkeypatch.setattr(api_server, "_get_graph", lambda _world: graph)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", api_server.Capabilities(
            "guided-character-v1", True, True, True, 30000,
        ))
        runs = _SemanticRuns(
            _continuation_semantic_payload("require_confirmation"),
            _semantic_payload("allow"),
        )
        _wire_semantic_provider(monkeypatch, runs)
        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "quiero crear un hermano de Rhyz",
            "section": "personajes",
        })

        assert response.status_code == 200
        payload = response.json()
        # Hermes decides require_confirmation; the canonical graph evidence is
        # gathered ONCE server-side and bound to the guarded session.
        assert payload["state"] == "require_confirmation"
        assert payload["guided_state"]["phase"] == "confirmation"
        assert payload["guided_revision"] == 1
        assert payload["guided_state"]["candidate"]["proposals"] == {}
        assert payload["guided_state"]["candidate"]["accepted_canon"] == {}
        assert seen == []
        # The canonical graph evidence is gathered at routing time and bound to
        # the session, but only reaches the provider after explicit confirmation.
        assert graph.calls == [("search", "Rhyz"), ("read", "personajes/rhyz.md"), ("links", "forward"), ("links", "backlinks")]
        state = api_server._GUIDED_SESSIONS.recover(payload["guided_session_id"], "tester")
        assert state is not None
        assert state.reference_name == "Rhyz"
        assert "Patient tactician." in state.reference_context

        confirmed = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "sí",
            "session_id": "chat-1",
            "guided_session_id": payload["guided_session_id"],
            "guided_revision": payload["guided_revision"],
        })

        assert confirmed.status_code == 200
        confirmed_payload = confirmed.json()
        assert confirmed_payload["guided_state"]["phase"] == "conversation"
        assert confirmed_payload["guided_revision"] == payload["guided_revision"] + 2
        assert len(seen) == 1
        assert "Patient tactician." in seen[0]
        assert "personajes/rhyz.md" not in seen[0]

    def test_folder_reference_factual_turn_preserves_guided_state(self, client: TestClient, monkeypatch):
        class Graph:
            def search(self, query):
                assert query == "Rhyz"
                return [{"name": "Rhyz", "path": "personajes/rhyz.md"}]

            def read(self, path):
                assert path == "personajes/rhyz.md"
                return {"name": "Rhyz", "type": "Personaje", "content": "Patient tactician."}

            def links(self, _path, _kind):
                return []

        guided_calls = []

        async def provider(request, _token):
            guided_calls.append(request)
            return {
                "protocol_version": request.protocol_version,
                "request_id": request.request_id,
                "session_id": request.session_id,
                "outcome": "question",
                "question": f"Guided question {request.base_revision + 1}",
            }

        _principal(monkeypatch, "author-1")
        monkeypatch.setattr(api_server, "_get_graph", lambda _world: Graph())
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", api_server.Capabilities(
            "guided-character-v1", True, True, True, 30000,
        ))
        runs = _SemanticRuns(
            _continuation_semantic_payload("require_confirmation"),
            _semantic_payload("allow"),
            _semantic_payload("allow"),
            _semantic_payload("allow"),
        )
        _wire_semantic_provider(monkeypatch, runs)

        first = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "quiero crear al hermano de Rhyz",
            "section": "personajes",
            "session_id": "chat-1",
        }).json()
        assert first["guided_state"]["phase"] == "confirmation"
        assert first["guided_revision"] == 1
        assert guided_calls == []

        # The factual shortcut is gone: a non-confirmation message during the
        # confirmation phase is interpreted by Hermes first, then the guarded
        # confirmation simply re-prompts without running the guided provider or
        # a plain-chat call, so the guided state stays safe.
        factual = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "me puedes indicar cual es el papel que cumple Rhyz?",
            "section": "personajes",
            "session_id": "chat-1",
            "guided_session_id": first["guided_session_id"],
            "guided_revision": first["guided_revision"],
        })

        assert factual.status_code == 200
        factual_payload = factual.json()
        assert factual_payload["guided_session_id"] == first["guided_session_id"]
        assert factual_payload["guided_state"]["phase"] == "confirmation"
        assert guided_calls == []
        assert runs.starts == 2

        confirmed = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "sí",
            "section": "personajes",
            "session_id": "chat-1",
            "guided_session_id": first["guided_session_id"],
            "guided_revision": factual_payload["guided_revision"],
        })

        assert confirmed.status_code == 200
        confirmed_payload = confirmed.json()
        # Only after explicit confirmation does the guided provider run, carrying
        # the canonical reference revision-bound into the conversation.
        assert confirmed_payload["guided_state"]["phase"] == "conversation"
        assert len(guided_calls) == 1
        assert guided_calls[0].base_revision == factual_payload["guided_revision"] + 1
        assert guided_calls[0].reference_name == "Rhyz"
        assert "Patient tactician." in guided_calls[0].reference_context

        resumed = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Su deseo es proteger a su hermana",
            "section": "personajes",
            "session_id": "chat-1",
            "guided_session_id": first["guided_session_id"],
            "guided_revision": confirmed_payload["guided_revision"],
        })

        assert resumed.status_code == 200
        assert resumed.json()["guided_session_id"] == first["guided_session_id"]
        assert resumed.json()["guided_revision"] == confirmed_payload["guided_revision"] + 1
        assert len(guided_calls) == 2
        assert guided_calls[1].base_revision == confirmed_payload["guided_revision"]

    def test_missing_or_ambiguous_folder_reference_stays_uncertain(self, client: TestClient, monkeypatch):
        class Graph:
            def __init__(self, matches):
                self.matches = matches

            def search(self, _query):
                return self.matches

            def read(self, _path):
                raise AssertionError("ambiguous or missing references must not be read")

            def links(self, _path, _kind):
                raise AssertionError("ambiguous or missing references must not explore links")

        seen = []

        async def provider(request, _token):
            seen.append(request.reference_context)
            return {
                "protocol_version": request.protocol_version,
                "request_id": request.request_id,
                "session_id": request.session_id,
                "outcome": "question",
                "question": "Which existing character do you mean?",
            }

        _principal(monkeypatch)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", api_server.Capabilities(
            "guided-character-v1", True, True, True, 30000,
        ))
        runs = _SemanticRuns(
            _continuation_semantic_payload("require_confirmation"),
            _semantic_payload("allow"),
            _continuation_semantic_payload("require_confirmation"),
            _semantic_payload("allow"),
        )
        _wire_semantic_provider(monkeypatch, runs)
        for matches, expected in (
            ([], "was not found"),
            ([{"name": "Rhyz", "path": "personajes/a.md"}, {"name": "Rhyz", "path": "personajes/b.md"}], "multiple graph matches"),
        ):
            monkeypatch.setattr(api_server, "_get_graph", lambda _world, matches=matches: Graph(matches))
            before = len(seen)
            response = client.post("/api/test_mundo/ai/ask", json={
                "prompt": "quiero crear un hermano de Rhyz",
                "section": "personajes",
            })
            assert response.status_code == 200
            payload = response.json()
            # Confirmation-first: the unresolved/ambiguous reference enters
            # confirmation and the provider does not run before explicit
            # confirmation, so no facts are invented prematurely.
            assert payload["state"] == "require_confirmation"
            assert payload["guided_state"]["phase"] == "confirmation"
            assert payload["guided_revision"] == 1
            assert len(seen) == before
            # The uncertainty is retained in the session (never read/linked) and
            # reaches the provider only after confirmation to ask for clarification.
            state = api_server._GUIDED_SESSIONS.recover(payload["guided_session_id"], "tester")
            assert state is not None
            assert expected in state.reference_context
            assert "personajes/" not in state.reference_context

            confirmed = client.post("/api/test_mundo/ai/ask", json={
                "prompt": "sí",
                "guided_session_id": payload["guided_session_id"],
                "guided_revision": payload["guided_revision"],
            })
            assert confirmed.status_code == 200
            assert len(seen) == before + 1
            assert expected in seen[-1]
            assert "personajes/" not in seen[-1]

    def test_named_reference_graph_failure_fails_closed_without_session_mutation(self, client: TestClient, monkeypatch):
        async def provider(_request, _token):
            raise AssertionError("provider must not run when the graph is unavailable")

        _principal(monkeypatch)
        sessions = api_server.GuidedSessionStore()
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", api_server.Capabilities(
            "guided-character-v1", True, True, True, 30000,
        ))
        monkeypatch.setattr(api_server, "_get_graph", lambda _world: (_ for _ in ()).throw(RuntimeError("index unavailable")))
        runs = _SemanticRuns(_continuation_semantic_payload("require_confirmation"))
        _wire_semantic_provider(monkeypatch, runs)

        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "quiero crear un hermano de Rhyz",
            "section": "personajes",
        })

        # Hermes decided require_confirmation, but the guarded continuation
        # cannot be backed without graph evidence: fail closed to blocked with
        # zero session mutation.
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "blocked"
        assert envelope["action"] == "blocked_explanation"
        assert "proposal" not in envelope and "digest" not in envelope
        assert not sessions._sessions

class TestGuidedSessionDurability:
    """Phase 2 (2.4): durable resume, pending-proposal revalidation,
    methodology change → new session, and legacy in-memory fail-closed."""

    def _delta_provider(self):
        async def provider(request, _token):
            return {
                "protocol_version": "guided-character-v1",
                "request_id": request.request_id,
                "session_id": request.session_id,
                "outcome": "delta",
                "delta": {"name": "Pert", "desire": "freedom"},
            }

        return provider

    def _wire(self, monkeypatch, store, provider=None, semantic_payloads=()):
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", store)
        if provider is not None:
            monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
            monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", api_server.Capabilities(
                "guided-character-v1", True, True, True, 30000,
            ))
        if semantic_payloads:
            _wire_semantic_provider(monkeypatch, _SemanticRuns(*semantic_payloads))

    def test_resume_under_30_days_survives_durable_restart(self, client: TestClient, monkeypatch, tmp_path):
        assert SESSION_TTL.days == 30
        db = tmp_path / "guided.sqlite3"
        provider = self._delta_provider()
        self._wire(monkeypatch, DurableGuidedSessionStore(db), provider=provider,
                   semantic_payloads=[_semantic_payload("allow"), _semantic_payload("allow")])
        _principal(monkeypatch, "author-1")

        started = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Pert",
        })
        assert started.status_code == 200
        payload = started.json()
        sid, revision = payload["session_id"], payload["revision"]
        assert payload["candidate"]["proposals"]

        # Durable restart: a fresh store over the same file has no
        # in-process state, yet the session is recoverable.
        DurableGuidedSessionStore(db).close()
        self._wire(monkeypatch, DurableGuidedSessionStore(db))
        resumed = client.get(f"/api/test_mundo/guided-character/session/{sid}")
        assert resumed.status_code == 200
        assert resumed.json()["session_id"] == sid
        assert resumed.json()["revision"] == revision

    def test_pending_proposal_requires_revalidation_after_restart(self, client: TestClient, monkeypatch, tmp_path):
        db = tmp_path / "guided.sqlite3"
        provider = self._delta_provider()
        self._wire(monkeypatch, DurableGuidedSessionStore(db), provider=provider,
                   semantic_payloads=[_semantic_payload("allow"), _semantic_payload("allow")])
        _principal(monkeypatch, "author-1")

        started = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Pert",
        }).json()
        sid, revision = started["session_id"], started["revision"]

        before = client.post("/api/test_mundo/guided-character/proposal/serialize", json={
            "session_id": sid, "base_revision": revision,
        })
        assert before.status_code == 200

        DurableGuidedSessionStore(db).close()
        self._wire(monkeypatch, DurableGuidedSessionStore(db), provider=provider,
                   semantic_payloads=[_semantic_payload("allow")])
        resumed = client.get(f"/api/test_mundo/guided-character/session/{sid}")
        assert resumed.status_code == 200

        # The recovered pending proposal is NOT inherited: serialization is
        # refused until a fresh turn revalidates it.
        blocked = client.post("/api/test_mundo/guided-character/proposal/serialize", json={
            "session_id": sid, "base_revision": revision,
        })
        assert blocked.status_code == 422
        assert "revalidation" in blocked.json()["message"]

        revalidated = client.post("/api/test_mundo/guided-character/turn", json={
            "session_id": sid, "base_revision": revision,
            "author_input": "Su deseo es la libertad",
        })
        assert revalidated.status_code == 200
        fresh_revision = revalidated.json()["revision"]

        fresh = client.post("/api/test_mundo/guided-character/proposal/serialize", json={
            "session_id": sid, "base_revision": fresh_revision,
        })
        assert fresh.status_code == 200
        assert fresh.json()["proposal_id"].startswith("guided-proposal-")

    def test_factory_version_change_keeps_existing_session(self, client: TestClient, monkeypatch, tmp_path):
        """S6/S7: the method is per-session. A new factory version never
        invalidates an existing session; only new sessions pin it."""
        db = tmp_path / "guided.sqlite3"
        store = DurableGuidedSessionStore(db)
        provider = self._delta_provider()
        self._wire(monkeypatch, store, provider=provider,
                   semantic_payloads=[_semantic_payload("allow"), _semantic_payload("allow"),
                                      _semantic_payload("allow")])
        _principal(monkeypatch, "author-1")

        started = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Pert",
        }).json()
        sid, revision = started["session_id"], started["revision"]

        monkeypatch.setattr(api_server, "_ACTIVE_METHODOLOGY_VERSION", "custom-v2")
        resumed = client.get(f"/api/test_mundo/guided-character/session/{sid}")
        assert resumed.status_code == 200

        turned = client.post("/api/test_mundo/guided-character/turn", json={
            "session_id": sid, "base_revision": revision,
            "author_input": "Su deseo es la libertad",
        })
        assert turned.status_code == 200

        # A brand-new session under the new factory version pins it.
        fresh = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Mar",
        })
        assert fresh.status_code == 200
        snapshot = store.methodology_snapshot(fresh.json()["session_id"], "author-1")
        assert snapshot is not None
        assert snapshot.skill_version == "custom-v2"
        assert snapshot.flow_type == "guided-character"

    def test_legacy_in_memory_sessions_fail_closed_without_migration(self, client: TestClient, monkeypatch, tmp_path):
        _principal(monkeypatch, "author-1")
        legacy = api_server.GuidedSessionStore()
        legacy.create("guided-legacy-1", "test_mundo", "author-1")

        durable = DurableGuidedSessionStore(tmp_path / "fresh.sqlite3")
        self._wire(monkeypatch, durable)
        response = client.get("/api/test_mundo/guided-character/session/guided-legacy-1")
        assert response.status_code == 401
        assert response.json()["code"] == "unauthorized"
        assert durable.recover("guided-legacy-1", "author-1") is None
        assert durable.discard_expired() == 0

    def test_default_configuration_recovers_after_durable_restart(self, client: TestClient, monkeypatch, tmp_path):
        """The default configuration (no ``db_path``, no env var) is durable:
        two stores wired over the same resolved default file recover the
        session after a restart, and the resolved path is the repo-local
        ``data/guided-sessions.sqlite3`` default, not ``:memory:``."""
        default = tmp_path / "data" / "guided-sessions.sqlite3"
        monkeypatch.setattr(guided_session_store, "default_db_path", lambda: default)
        provider = self._delta_provider()

        store = DurableGuidedSessionStore()
        assert store._db_path == str(default)  # noqa: SLF001
        assert default.exists()
        self._wire(monkeypatch, store, provider=provider,
                   semantic_payloads=[_semantic_payload("allow"), _semantic_payload("allow")])
        _principal(monkeypatch, "author-1")

        started = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Pert",
        })
        assert started.status_code == 200
        payload = started.json()
        sid, revision = payload["session_id"], payload["revision"]
        assert payload["candidate"]["proposals"]

        store.close()
        self._wire(monkeypatch, DurableGuidedSessionStore())
        resumed = client.get(f"/api/test_mundo/guided-character/session/{sid}")
        assert resumed.status_code == 200
        assert resumed.json()["session_id"] == sid
        assert resumed.json()["revision"] == revision

    def test_factual_ficha_question_answers_via_hermes_without_factual_shortcut(self, client: TestClient, monkeypatch):
        target = api_server.MUNDOS_DIR / "test_mundo" / "personajes" / "rhyz.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("---\ntitle: Rhyz\n---\nRhyz is patient.\n", encoding="utf-8")
        calls = []

        async def provider(request, _token):
            calls.append(request.author_input)
            return {
                "protocol_version": request.protocol_version,
                "request_id": request.request_id,
                "session_id": request.session_id,
                "outcome": "question",
                "question": f"Guided question {request.base_revision + 1}",
            }

        _principal(monkeypatch, "author-1")
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", api_server.Capabilities(
            "guided-character-v1", True, True, True, 30000,
        ))
        monkeypatch.setattr(api_server, "_named_reference_context", lambda _m, _p: ("", False, None))
        runs = _SemanticRuns(
            _continuation_semantic_payload("require_confirmation"),
            _semantic_payload("allow"),
            _semantic_payload("allow"),
            _semantic_payload("allow"),
        )
        _wire_semantic_provider(monkeypatch, runs)
        context = {"section": "personajes", "file_path": "rhyz.md", "session_id": "chat-1"}
        first = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Quiero crear un personaje", **context,
        }).json()
        with patch("api_server._run_hermes", new=AsyncMock()) as normal:
            factual = client.post("/api/test_mundo/ai/ask", json={
                "prompt": "Recuérdame cómo es Rhyz", **context,
                "guided_session_id": first["guided_session_id"],
                "guided_revision": first["guided_revision"],
            })
        assert factual.status_code == 200
        # Hermes interpreted the factual message; the guarded confirmation just
        # re-prompts (no factual shortcut, no plain-chat fallback).
        assert factual.json()["guided_session_id"] == first["guided_session_id"]
        assert factual.json()["guided_revision"] == first["guided_revision"] + 1
        normal.assert_not_awaited()

        confirmed = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "sí", **context,
            "guided_session_id": first["guided_session_id"],
            "guided_revision": factual.json()["guided_revision"],
        })
        assert confirmed.status_code == 200
        assert confirmed.json()["guided_state"]["phase"] == "conversation"
        assert confirmed.json()["guided_revision"] == factual.json()["guided_revision"] + 2
        assert calls == ["Quiero crear un personaje"]

        resumed = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Su deseo es proteger a su hermana", **context,
            "guided_session_id": first["guided_session_id"],
            "guided_revision": confirmed.json()["guided_revision"],
        })
        assert resumed.status_code == 200
        assert resumed.json()["guided_session_id"] == first["guided_session_id"]
        assert resumed.json()["guided_revision"] == confirmed.json()["guided_revision"] + 1
        assert calls == ["Quiero crear un personaje", "Su deseo es proteger a su hermana"]

    def test_factual_question_with_missing_ficha_context_stays_safe_without_mutation(
        self, client: TestClient, monkeypatch,
    ):
        calls = []

        async def provider(request, _token):
            calls.append(request.author_input)
            return {
                "protocol_version": request.protocol_version,
                "request_id": request.request_id,
                "session_id": request.session_id,
                "outcome": "question",
                "question": "What drives them?",
            }

        _principal(monkeypatch, "author-1")
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", api_server.Capabilities(
            "guided-character-v1", True, True, True, 30000,
        ))
        monkeypatch.setattr(api_server, "_named_reference_context", lambda _m, _p: ("", False, None))
        runs = _SemanticRuns(
            _continuation_semantic_payload("require_confirmation"),
            _semantic_payload("allow"),
        )
        _wire_semantic_provider(monkeypatch, runs)
        first = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Quiero crear un personaje", "session_id": "chat-1",
        }).json()

        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Recuérdame cómo es Rhyz", "session_id": "chat-1",
            "section": "personajes", "file_path": "missing.md",
            "guided_session_id": first["guided_session_id"],
            "guided_revision": first["guided_revision"],
        })

        # No factual shortcut exists: the message is interpreted by Hermes and
        # the guarded confirmation re-prompts. Zero provider calls, no mutation.
        assert response.status_code == 200
        assert response.json()["guided_session_id"] == first["guided_session_id"]
        assert response.json()["guided_revision"] == first["guided_revision"] + 1
        state = api_server._GUIDED_SESSIONS.recover(first["guided_session_id"], "author-1")
        assert state is not None
        assert calls == []

    def test_guided_turn_requires_authentication_without_mutation(self, client: TestClient, monkeypatch):
        sessions = api_server.GuidedSessionStore()
        state = sessions.create("guided-auth", "test_mundo", "author-1")
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)
        monkeypatch.setattr(api_server, "_resolve_principal", lambda _request: None)

        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Continúa", "guided_session_id": state.session_id,
            "guided_revision": state.revision,
        })

        assert response.status_code == 401
        recovered = sessions.recover(state.session_id, "author-1")
        assert recovered is not None
        assert recovered.revision == 0

    def test_explicit_edit_request_stays_outside_guided_handoff(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        with patch("api_server._run_hermes", new=AsyncMock(return_value="ordinary edit answer")) as mock_run:
            response = client.post(
                "/api/test_mundo/ai/ask",
                json={"prompt": "Editar el personaje Aria"},
            )

        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "allow"
        assert envelope["response"] == "Hermes semantic answer."
        assert runs.starts == 1
        mock_run.assert_not_awaited()

    def test_ai_ask_includes_file_context(self, client: TestClient, monkeypatch):
        """The bounded open-ficha content reaches the semantic decision input."""
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        target.write_text("---\ntitle: Inicio\n---\nCuerpo\n", encoding="utf-8")
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        with patch("api_server._run_hermes", new=AsyncMock(return_value="Hola desde Hermes")) as mock_run:
            resp = client.post(
                "/api/test_mundo/ai/ask",
                json={"prompt": "Hola", "section": "lore", "file_path": "00_inicio.md"},
            )
        assert resp.status_code == 200
        sent = runs.requests[0].prompt
        assert "Cuerpo" in sent
        assert "lore/00_inicio.md" not in sent
        assert resp.json()["state"] == "allow"
        mock_run.assert_not_awaited()

    def test_ai_ask_without_file_context(self, client: TestClient, monkeypatch):
        """Without a file_path no ficha context reaches Hermes."""
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        with patch("api_server._run_hermes", new=AsyncMock(return_value="ok")) as mock_run:
            resp = client.post(
                "/api/test_mundo/ai/ask",
                json={"prompt": "Hola"},
            )
        assert resp.status_code == 200
        sent = runs.requests[0].prompt
        assert '"ficha"' not in sent
        assert "test_mundo" in sent
        mock_run.assert_not_awaited()

    def test_activity_route_returns_sanitized_correlated_sse(self, client: TestClient, monkeypatch):
        class FakeAdapter:
            available = True
            capability = _activity_capability()

            def __init__(self):
                self.cancelled = []
                self.request_id = ""

            def start(self, request):
                assert request.request_id
                # The identity override replaces the legacy "[Mundo: ...]" prefix
                # (commit 82c7a8c): the prompt now opens with the Demiurgos
                # assistant identity prompt naming the world.
                assert request.prompt.startswith("[SYSTEM OVERRIDE — IDENTITY]")
                assert "test_mundo" in request.prompt
                assert "with markdown when it adds structure" in request.prompt
                assert request.prompt.endswith("\n\nHola")
                self.request_id = request.request_id
                return "run-1"

            async def events(self, run_id):
                assert run_id == "run-1"
                yield {
                    "event": "tool.started", "run_id": run_id, "tool": "graph_read",
                }
                yield {
                    "event": "tool.completed", "run_id": run_id, "tool": "graph_read",
                    "error": False,
                }
                yield {
                    "event": "run.completed", "run_id": run_id, "output": "safe answer",
                }

            def cancel(self, run_id):
                self.cancelled.append(run_id)

        adapter = FakeAdapter()
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)
        response = client.post("/api/test_mundo/ai/ask/activity", json={"prompt": "Hola"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(response.text)
        kinds = [event["kind"] for event in events]
        assert kinds[0] == "semantic_decision"
        assert events[0]["state"] == "allow"
        assert events[0]["action"] == "answer"
        assert events[0]["unavailable"] is False
        assert "activity" in kinds
        assert kinds[-1] == "terminal"
        assert "event: activity" in response.text
        assert '"response": "safe answer"' in response.text
        assert '"request_id": "activity-' in response.text
        assert '"path"' not in response.text
        assert "run-1" not in response.text
        assert runs.starts == 1

    def test_activity_route_unavailable_is_neutral_fallback(
        self, client: TestClient, monkeypatch
    ):
        """Unavailable (unwired) Hermes fails closed: HTTP 200 with the ordered
        blocked semantic stream, safe copy, and zero classifier/action/write."""
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", None)
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/test_mundo/ai/ask/activity", json={"prompt": "Hola"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(response.text)
        kinds = [event["kind"] for event in events]
        assert kinds[0] == "semantic_decision"
        assert kinds[-1] == "terminal"
        decision = events[0]
        assert decision["state"] == "blocked"
        assert decision["action"] == "blocked_explanation"
        assert decision["unavailable"] is True
        answer = next(event for event in events if event["kind"] == "answer")
        assert answer["response"].startswith("El Asistente IA no pudo")
        terminal = events[-1]
        assert terminal["status"] == "failed"
        legacy.assert_not_awaited()
        lowered = response.text.lower()
        for term in ("hermes", "provider", "gateway", "http", "timeout", "quota",
                     "credits", "credential", "model", "error:"):
            assert term not in lowered

    def test_activity_pre_acceptance_failure_does_not_leak_provider_error(
        self, client: TestClient, monkeypatch
    ):
        class FailingAdapter:
            available = True
            capability = _activity_capability()

            def start(self, request):
                raise RuntimeError("credential=secret /absolute/provider/path")

        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", FailingAdapter())
        response = client.post("/api/test_mundo/ai/ask/activity", json={"prompt": "Hola"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(response.text)
        kinds = [event["kind"] for event in events]
        assert kinds[0] == "semantic_decision"
        assert events[0]["state"] == "allow"
        assert kinds[-1] == "terminal"
        assert events[-1]["status"] == "failed"
        assert "credential=secret" not in response.text
        assert "/absolute/provider/path" not in response.text
        assert runs.starts == 1

    def test_activity_partial_failure_preserves_answer_and_cancels_on_timeout(
        self, client: TestClient, monkeypatch
    ):
        class PartialAdapter:
            available = True
            capability = _activity_capability()

            def __init__(self):
                self.cancelled = []
                self.request_id = ""

            def start(self, request):
                self.request_id = request.request_id
                return "run-1"

            async def events(self, run_id):
                yield {
                    "event": "message.delta", "run_id": run_id,
                    "delta": "preserve this answer",
                }
                await asyncio.sleep(0.05)
                yield {"event": "run.completed", "run_id": run_id, "output": "preserve this answer"}

            def cancel(self, run_id):
                self.cancelled.append(run_id)

        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        adapter = PartialAdapter()
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)
        monkeypatch.setattr(api_server, "ACTIVITY_EVENT_TIMEOUT_SECONDS", 0.01)
        response = client.post("/api/test_mundo/ai/ask/activity", json={"prompt": "Hola"})

        assert response.status_code == 200
        events = _parse_sse(response.text)
        kinds = [event["kind"] for event in events]
        assert kinds[0] == "semantic_decision"
        assert kinds[-1] == "terminal"
        assert '"response": "preserve this answer"' in response.text
        assert '"status": "unknown"' in response.text
        assert adapter.cancelled == ["run-1"]
        assert runs.starts == 1

    def test_unwired_ai_ask_fails_closed_without_legacy_chat(self, client: TestClient):
        with patch("api_server._run_hermes", new=AsyncMock(return_value="legacy answer")):
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": "Hola"})

        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "blocked"
        assert envelope["unavailable"] is True
        assert envelope["response"] != "legacy answer"
        assert envelope["response"].startswith("El Asistente IA no pudo")


class _SemanticRuns:
    """Minimal runs adapter shape consumed by SemanticIntentProvider."""

    def __init__(self, *payloads):
        self._payloads = list(payloads)
        self.starts = 0
        self.requests = []

    async def start(self, request):
        self.starts += 1
        self.requests.append(request)
        return f"run-{self.starts}"

    async def events(self, run_id):
        if self._payloads:
            payload = self._payloads.pop(0)
        else:
            payload = None
        yield {"event": "run.completed", "run_id": run_id, "output": payload}


def _semantic_payload(state="allow", **overrides):
    payload = {
        "state": state,
        "response": "Hermes semantic answer.",
        "request_id": "request-1",
        "session_id": "chat-1",
        "guided": True,
    }
    payload.update(overrides)
    return payload


def _continuation_semantic_payload(state="proposal_ready", **overrides):
    """Single-run envelope: semantic decision + typed guided continuation.

    Defaults to ``imperative`` so the legacy auto-open machinery assertions
    stay valid; musing/consent tests override ``guided_explicitness``.
    """
    payload = {
        "state": state,
        "response": "Hermes semantic answer.",
        "request_id": "request-1",
        "session_id": "chat-1",
        "guided": True,
        "guided_explicitness": "imperative",
        "continuation": {
            "outcome": "question" if state == "require_confirmation" else "delta",
            "question": "¿Creo este personaje?" if state == "require_confirmation" else None,
            "delta": None if state == "require_confirmation" else {"name": "Rhyz's Wife", "desire": "freedom"},
        },
    }
    payload.update(overrides)
    return payload


def _wire_semantic_provider(monkeypatch, runs, **provider_kwargs):
    provider = api_server.SemanticIntentProvider(runs, **provider_kwargs)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", provider)
    return provider


def _approve_draft_trigger(
    client: TestClient, draft_id: str, description: str = "Approved test trigger",
) -> dict:
    """Etapa 2: record the explicit trigger approval a real Author grants on the
    review surface before publishing (REQ ``skill-trigger-approval``)."""
    response = client.post(
        f"/api/methodologies/drafts/{draft_id}/trigger/approve",
        json={"description": description},
    )
    assert response.status_code == 200, response.text
    return response.json()["trigger_approval"]


def _approve_library_trigger(
    library: MethodologyLibrary, draft_id: str,
    description: str = "Approved test trigger",
) -> None:
    """Library-boundary twin of ``_approve_draft_trigger`` for helpers that
    seed the store directly (no HTTP route)."""
    library.approve_trigger(draft_id, description, "author-1")


class TestMethodologyApi:
    """Phase 3 (3.5): publish/activate wiring — only NEW sessions use the
    change; existing sessions pinned to a different version fail closed."""

    def _draft_payload(self):
        return {
            "skill_id": "guided-character-v1",
            "version": "1.2.0",
            "name": "Guided character methodology",
            "source": "## Construcción segura\n\nHaz preguntas de a una.\n",
        }

    def _publish_and_activate(self, client: TestClient):
        draft = client.post("/api/methodologies/drafts", json=self._draft_payload())
        assert draft.status_code == 200, draft.text
        draft_id = draft.json()["draft_id"]
        _approve_draft_trigger(client, draft_id)
        published = client.post(f"/api/methodologies/drafts/{draft_id}/publish")
        assert published.status_code == 200, published.text
        assert published.json()["digest"]
        activated = client.post("/api/methodologies/activate", json={
            "world": "test_mundo", "skill_id": "guided-character-v1", "version": "1.2.0",
        })
        assert activated.status_code == 200, activated.text
        return activated.json()

    def test_status_lists_published_and_activations(self, client: TestClient, monkeypatch):
        _principal(monkeypatch, "author-1")
        self._publish_and_activate(client)
        status = client.get("/api/methodologies/status")
        assert status.status_code == 200
        payload = status.json()
        assert len(payload["published"]) == 1
        assert payload["published"][0]["version"] == "1.2.0"
        assert payload["activations"]["test_mundo"]["version"] == "1.2.0"

    def test_new_session_after_activation_pins_library_version(self, client: TestClient, monkeypatch, tmp_path):
        """Activating a published version makes NEW sessions pin it."""
        db = tmp_path / "guided.sqlite3"
        store = DurableGuidedSessionStore(db)
        provider = _delta_guided_provider()
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", store)
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", api_server.Capabilities(
            "guided-character-v1", True, True, True, 30000,
        ))
        _wire_semantic_provider(monkeypatch, _SemanticRuns(
            _semantic_payload("allow"), _semantic_payload("allow"), _semantic_payload("allow"),
        ))
        _principal(monkeypatch, "author-1")

        self._publish_and_activate(client)
        started = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Pert",
        })
        assert started.status_code == 200
        snapshot = store.methodology_snapshot(started.json()["session_id"], "author-1")
        assert snapshot is not None
        assert snapshot.skill_version == "1.2.0"
        assert snapshot.compiled_contract_digest is not None
        assert snapshot.flow_type == "guided-character"

    def test_existing_session_keeps_method_after_activation(self, client: TestClient, monkeypatch, tmp_path):
        """S6/S7: activating a world default later never invalidates a session
        that already pinned the factory method; new sessions pin the default."""
        db = tmp_path / "guided.sqlite3"
        store = DurableGuidedSessionStore(db)
        provider = _delta_guided_provider()
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", store)
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", api_server.Capabilities(
            "guided-character-v1", True, True, True, 30000,
        ))
        _wire_semantic_provider(monkeypatch, _SemanticRuns(
            _semantic_payload("allow"), _semantic_payload("allow"), _semantic_payload("allow"),
        ))
        _principal(monkeypatch, "author-1")

        # Session pinned to the builtin contract before any activation.
        started = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Pert",
        })
        assert started.status_code == 200
        sid, revision = started.json()["session_id"], started.json()["revision"]
        builtin = store.methodology_snapshot(sid, "author-1")
        assert builtin.skill_version == "builtin"
        assert builtin.flow_type == "guided-character"

        self._publish_and_activate(client)
        resumed = client.get(f"/api/test_mundo/guided-character/session/{sid}")
        assert resumed.status_code == 200
        turned = client.post("/api/test_mundo/guided-character/turn", json={
            "session_id": sid, "base_revision": revision,
            "author_input": "Su deseo es la libertad",
        })
        assert turned.status_code == 200

        fresh = client.post("/api/test_mundo/guided-character/session", json={
            "author_input": "Crear un personaje nuevo llamado Mar",
        })
        assert fresh.status_code == 200
        snapshot = store.methodology_snapshot(fresh.json()["session_id"], "author-1")
        assert snapshot is not None
        assert snapshot.skill_version == "1.2.0"

    def test_authority_claiming_draft_fails_compile_on_publish(self, client: TestClient, monkeypatch):
        _principal(monkeypatch, "author-1")
        draft = client.post("/api/methodologies/drafts", json={
            "skill_id": "guided-character-v1",
            "version": "1.0.0",
            "name": "Unsafe",
            "source": "## Malo\n\n#!demiurgos-authority\n",
        })
        assert draft.status_code == 200
        draft_id = draft.json()["draft_id"]
        published = client.post(f"/api/methodologies/drafts/{draft_id}/publish")
        assert published.status_code == 422
        assert published.json()["code"] == "validation_error"

    # ------------------------------------------------------------------ #
    # Server-authoritative trust (S7/S8): client trust claims are rejected
    # with 400; omission/null/[] stay valid; a clean draft publishes as
    # Personalizadas with no trust attributes (local-author, G14).
    # ------------------------------------------------------------------ #

    def test_draft_claims_clasificacion_rejected_400(self, client: TestClient, monkeypatch):
        _principal(monkeypatch, "author-1")
        claimed = client.post("/api/methodologies/drafts", json={
            "skill_id": "guided-character-v1",
            "version": "1.0.0",
            "name": "Forge",
            "source": "## Intento\n\nTexto.\n",
            "clasificacion": "Oficiales",
        })
        assert claimed.status_code == 400
        assert claimed.json()["code"] == "client_trust_claim_not_allowed"
        # No draft was created.
        assert api_server._methodology_library().list_drafts() == []

    def test_draft_claims_trust_attributes_rejected_400(self, client: TestClient, monkeypatch):
        _principal(monkeypatch, "author-1")
        claimed = client.post("/api/methodologies/drafts", json={
            "skill_id": "guided-character-v1",
            "version": "1.0.0",
            "name": "Forge",
            "source": "## Intento\n\nTexto.\n",
            "trust_attributes": ["fundacional"],
        })
        assert claimed.status_code == 400
        assert claimed.json()["code"] == "client_trust_claim_not_allowed"
        assert api_server._methodology_library().list_drafts() == []

    def test_draft_null_and_empty_trust_fields_stay_valid(self, client: TestClient, monkeypatch):
        """S8: explicit null/[] claims are omission — accepted."""
        _principal(monkeypatch, "author-1")
        clean = client.post("/api/methodologies/drafts", json={
            "skill_id": "guided-character-v1",
            "version": "1.0.0",
            "name": "Clean",
            "source": "## Limpio\n\nTexto.\n",
            "clasificacion": None,
            "trust_attributes": [],
        })
        assert clean.status_code == 200, clean.text
        assert clean.json()["clasificacion"] is None
        assert clean.json()["trust_attributes"] == []

    def test_clean_draft_publishes_personalizadas_with_no_trust(self, client: TestClient, monkeypatch):
        """AC: a normal draft->publish record lands Personalizadas + []."""
        _principal(monkeypatch, "author-1")
        draft = client.post("/api/methodologies/drafts", json=self._draft_payload())
        assert draft.status_code == 200, draft.text
        _approve_draft_trigger(client, draft.json()["draft_id"])
        published = client.post(f"/api/methodologies/drafts/{draft.json()['draft_id']}/publish")
        assert published.status_code == 200, published.text
        record = api_server._methodology_library().get_published("guided-character-v1", "1.2.0")
        assert record is not None
        assert record.clasificacion == "Personalizadas"
        assert record.trust_attributes == ()

    def test_publish_attachment_overflow_returns_422_and_never_mutates(
        self, client: TestClient, monkeypatch,
    ):
        """S4/R2: an adjuntos overflow at publish returns 422 with code
        ``attachment_limit_reached`` and ZERO mutation — no record is written."""
        _principal(monkeypatch, "author-1")
        overflow = [
            {
                "path": f"ejemplos/e{i}.md",
                "sha256": f"{i:064x}",
                "bytes": 1024,
                "nivel": "1º",
            }
            for i in range(9)
        ]
        draft = client.post("/api/methodologies/drafts", json={
            "skill_id": "guided-character-v1",
            "version": "1.2.0",
            "name": "Guided character methodology",
            "source": "## Construcción segura\n\nHaz preguntas de a una.\n",
            "adjuntos": overflow,
        })
        assert draft.status_code == 200, draft.text
        published = client.post(f"/api/methodologies/drafts/{draft.json()['draft_id']}/publish")
        assert published.status_code == 422
        assert published.json()["code"] == "attachment_limit_reached"
        # Zero mutation: nothing published, the draft remains editable.
        assert api_server._methodology_library().published_versions_for("guided-character-v1") == []
        assert api_server._methodology_library().get_draft(draft.json()["draft_id"]) is not None

    def test_publish_echoes_adjuntos_only_when_present(self, client: TestClient, monkeypatch):
        """4.2: the publish response gains ``adjuntos`` only when entries exist —
        today's (pre-PR③) payloads stay byte-identical."""
        _principal(monkeypatch, "author-1")
        draft = client.post("/api/methodologies/drafts", json=self._draft_payload())
        assert draft.status_code == 200, draft.text
        _approve_draft_trigger(client, draft.json()["draft_id"])
        published = client.post(f"/api/methodologies/drafts/{draft.json()['draft_id']}/publish")
        assert published.status_code == 200, published.text
        assert "adjuntos" not in published.json()
        # The approved trigger rides along; nothing else is added.
        assert set(published.json()) == {
            "skill_id", "version", "name", "description", "trigger", "digest",
            "published_at",
        }
        assert published.json()["trigger"] == "Approved test trigger"

    def test_activate_requires_published_version(self, client: TestClient, monkeypatch):
        _principal(monkeypatch, "author-1")
        activated = client.post("/api/methodologies/activate", json={
            "world": "test_mundo", "skill_id": "guided-character-v1", "version": "9.9.9",
        })
        assert activated.status_code == 422
        assert activated.json()["code"] == "not_published"

    def test_mutations_require_authentication(self, client: TestClient):
        unauthenticated = client.post("/api/methodologies/drafts", json=self._draft_payload())
        assert unauthenticated.status_code == 401

    # ------------------------------------------------------------------ #
    # Taller de Herramientas Fase 1: inventory endpoint (TW7) + status
    # payload extension. The store is seeded directly (the draft POST body
    # does not expose inventory fields in Fase 1).
    # ------------------------------------------------------------------ #

    def _seed_inventory_library(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> MethodologyLibrary:
        library = MethodologyLibrary(tmp_path / "data" / "methodology" / "library.json")
        oficial = library.create_draft(
            skill_id="guided-character-v1", version="1.2.0",
            name="Guided character methodology",
            source="## Construcción segura\n\nHaz preguntas de a una.\n",
            taller="Creación",
            talleres_compatibles=("Investigación", "Diseño"),
            categoria_funcional="Análisis",
            etiquetas=("lore", "npc"),
            clasificacion="Oficiales",
            trust_attributes=("verified",),
        )
        _approve_library_trigger(library, oficial)
        library.publish(oficial)
        community = library.create_draft(
            skill_id="community-skill", version="0.1.0",
            name="Community skill", source="## Comunitario\n\nTexto.\n",
            taller="Investigación",
            categoria_funcional="Investigación",
            etiquetas=("lore",),
            clasificacion="Comunitarias",
            trust_attributes=(),
        )
        _approve_library_trigger(library, community)
        library.publish(community)
        monkeypatch.setattr(api_server, "_METHODOLOGY_LIBRARY", library)
        return library

    def test_inventory_lists_all_published_activated_or_not(self, client, monkeypatch, tmp_path):
        library = self._seed_inventory_library(monkeypatch, tmp_path)
        library.activate("test_mundo", "guided-character-v1", "1.2.0")
        response = client.get("/api/methodologies/inventory")
        assert response.status_code == 200
        items = response.json()["items"]
        assert {item["skill_id"] for item in items} == {
            "guided-character-v1", "community-skill",
        }

    def test_inventory_filters_by_clasificacion(self, client, monkeypatch, tmp_path):
        self._seed_inventory_library(monkeypatch, tmp_path)
        response = client.get(
            "/api/methodologies/inventory", params={"clasificacion": "Oficiales"},
        )
        assert response.status_code == 200
        assert [item["skill_id"] for item in response.json()["items"]] == [
            "guided-character-v1",
        ]

    def test_inventory_filters_by_categoria_funcional(self, client, monkeypatch, tmp_path):
        self._seed_inventory_library(monkeypatch, tmp_path)
        response = client.get(
            "/api/methodologies/inventory",
            params={"categoria_funcional": "Investigación"},
        )
        assert response.status_code == 200
        assert [item["skill_id"] for item in response.json()["items"]] == [
            "community-skill",
        ]

    def test_inventory_filters_taller_and_etiquetas_conjunctively(self, client, monkeypatch, tmp_path):
        self._seed_inventory_library(monkeypatch, tmp_path)
        response = client.get(
            "/api/methodologies/inventory",
            params={"taller": "Creación", "etiquetas": "lore"},
        )
        assert response.status_code == 200
        assert [item["skill_id"] for item in response.json()["items"]] == [
            "guided-character-v1",
        ]
        # Etiquetas are AND-matching: a tag absent everywhere yields no items.
        response = client.get(
            "/api/methodologies/inventory",
            params={"taller": "Creación", "etiquetas": "lore,extra"},
        )
        assert response.status_code == 200
        assert response.json()["items"] == []

    def test_inventory_etiquetas_match_case_insensitive_substring(self, client, monkeypatch, tmp_path):
        self._seed_inventory_library(monkeypatch, tmp_path)
        # Partial input: "lor" is a substring of the stored "lore" tag, so both
        # published skills match (no taller filter narrows them here).
        response = client.get(
            "/api/methodologies/inventory", params={"etiquetas": "lor"},
        )
        assert response.status_code == 200
        assert {item["skill_id"] for item in response.json()["items"]} == {
            "guided-character-v1", "community-skill",
        }
        # Case-insensitive: uppercase input still matches the stored tag.
        response = client.get(
            "/api/methodologies/inventory", params={"etiquetas": "LOR"},
        )
        assert response.status_code == 200
        assert {item["skill_id"] for item in response.json()["items"]} == {
            "guided-character-v1", "community-skill",
        }

    def test_inventory_categoria_funcional_matches_case_insensitive_substring(self, client, monkeypatch, tmp_path):
        self._seed_inventory_library(monkeypatch, tmp_path)
        # "investig" is a case-insensitive substring of "Investigación".
        response = client.get(
            "/api/methodologies/inventory",
            params={"categoria_funcional": "investig"},
        )
        assert response.status_code == 200
        assert [item["skill_id"] for item in response.json()["items"]] == [
            "community-skill",
        ]

    def test_inventory_no_matches_returns_empty_list(self, client, monkeypatch, tmp_path):
        self._seed_inventory_library(monkeypatch, tmp_path)
        response = client.get(
            "/api/methodologies/inventory", params={"clasificacion": "Personalizadas"},
        )
        assert response.status_code == 200
        assert response.json() == {"items": []}

    def test_inventory_filters_by_fundacional(self, client, monkeypatch, tmp_path):
        library = self._seed_inventory_library(monkeypatch, tmp_path)
        # G14 invariant: fundacional trust only accompanies Oficiales.
        fundacional = library.create_draft(
            skill_id="fundacional-skill", version="1.0.0",
            name="Fundacional skill", source="## Fundacional\n\nTexto.\n",
            taller="Creación",
            categoria_funcional="Creación",
            etiquetas=(),
            clasificacion="Oficiales",
            trust_attributes=("fundacional",),
        )
        _approve_library_trigger(library, fundacional)
        library.publish(fundacional)

        # `fundacional=true` restricts to server-seeded foundational skills
        # (trust attribute), regardless of their origin classification.
        response = client.get(
            "/api/methodologies/inventory", params={"fundacional": "true"},
        )
        assert response.status_code == 200
        assert [item["skill_id"] for item in response.json()["items"]] == [
            "fundacional-skill",
        ]

        # Without the param the whole catalog is still returned.
        response = client.get("/api/methodologies/inventory")
        assert response.status_code == 200
        assert {item["skill_id"] for item in response.json()["items"]} == {
            "guided-character-v1", "community-skill", "fundacional-skill",
        }

        # Conjunctive with another facet: Oficiales keeps it, Personalizadas drops it.
        response = client.get(
            "/api/methodologies/inventory",
            params={"fundacional": "true", "clasificacion": "Oficiales"},
        )
        assert response.status_code == 200
        assert [item["skill_id"] for item in response.json()["items"]] == [
            "fundacional-skill",
        ]
        response = client.get(
            "/api/methodologies/inventory",
            params={"fundacional": "true", "clasificacion": "Personalizadas"},
        )
        assert response.status_code == 200
        assert response.json()["items"] == []

    def test_inventory_get_has_no_side_effects(self, client, monkeypatch, tmp_path):
        self._seed_inventory_library(monkeypatch, tmp_path)
        _principal(monkeypatch, "author-1")
        before = client.get("/api/methodologies/status").json()
        response = client.get("/api/methodologies/inventory")
        assert response.status_code == 200
        assert client.get("/api/methodologies/status").json() == before

    def test_inventory_unauthenticated_get_returns_200(self, client, monkeypatch, tmp_path):
        """Read-only catalog: no auth gate (public-read policy)."""
        self._seed_inventory_library(monkeypatch, tmp_path)
        response = client.get("/api/methodologies/inventory")
        assert response.status_code == 200
        assert response.json()["items"]

    def test_status_payload_includes_inventory_fields(self, client, monkeypatch, tmp_path):
        self._seed_inventory_library(monkeypatch, tmp_path)
        _principal(monkeypatch, "author-1")
        status = client.get("/api/methodologies/status")
        assert status.status_code == 200
        entry = status.json()["published"][0]
        assert entry["taller"] == "Creación"
        assert entry["talleres_compatibles"] == ["Investigación", "Diseño"]
        assert entry["categoria_funcional"] == "Análisis"
        assert entry["etiquetas"] == ["lore", "npc"]
        assert entry["clasificacion"] == "Oficiales"
        assert entry["trust_attributes"] == ["verified"]

    # ------------------------------------------------------------------ #
    # Fase 5b (PR 2): skill import/export/quarantine/trust + reserved-id
    # guard (REQ-IMP-1..6).
    # ------------------------------------------------------------------ #

    def _import_package(self, manifest=None) -> bytes:
        return build_package(
            manifest or {
                "skill_id": "guided-character-v1",
                "version": "1.2.0",
                "name": "Guided character methodology",
                "description": "A safe construction methodology.",
                "phases": ["conversation", "review", "complete"],
                "language": "es",
            },
            "## Construcción segura\n\nHaz preguntas de a una.\n",
        )

    def _upload(self, client: TestClient, package: bytes, filename: str = "skill.zip"):
        return client.post(
            "/api/methodologies/import",
            files={"file": (filename, package, "application/zip")},
        )

    def test_export_builds_valid_zip(self, client: TestClient, monkeypatch):
        """REQ-IMP-1: the exported .zip contains manifest, source and the
        integrity checksum, and re-inspects clean (round-trip safe)."""
        _principal(monkeypatch, "author-1")
        draft = client.post("/api/methodologies/drafts", json=self._draft_payload())
        assert draft.status_code == 200, draft.text
        draft_id = draft.json()["draft_id"]
        _approve_draft_trigger(client, draft_id)
        published = client.post(f"/api/methodologies/drafts/{draft_id}/publish")
        assert published.status_code == 200, published.text
        exported = client.post("/api/methodologies/published/guided-character-v1/1.2.0/export")
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-type"] == "application/zip"
        archive = zipfile.ZipFile(io.BytesIO(exported.content))
        assert set(archive.namelist()) == {"manifest.yaml", "source.md", "checksums.json"}
        verdict = inspect_package(exported.content)
        assert verdict.ok, verdict.issues

    def test_export_requires_auth_and_known_version(self, client: TestClient, monkeypatch):
        unauthenticated = client.post("/api/methodologies/published/x/1.0.0/export")
        assert unauthenticated.status_code == 401
        _principal(monkeypatch, "author-1")
        missing = client.post("/api/methodologies/published/ghost/9.9.9/export")
        assert missing.status_code == 404

    # ------------------------------------------------------------------ #
    # PR ⑤a (SR4/SR5): published/status expose additive adjuntos metadata
    # (R14/R15) and export embeds pinned carriers / fails closed (R16/R17).
    # ------------------------------------------------------------------ #

    def _publish_with_adjuntos(
        self, client: TestClient, tmp_path: Path, *,
        drift: bool = False, omit_carrier: bool = False,
        carrier_root: str = "seeds",
    ) -> dict:
        """Publish the draft with one pinned carrier written under ``carrier_root``.

        ``tmp_path`` is the patched PROJECT_ROOT, so the directory the export
        route resolves is the one this helper populates. ``carrier_root`` is
        ``seeds`` for bundled skills (whose dir exists → resolver returns it)
        and ``attachments`` for author skills (no seed dir → fallback).
        """
        path = "adjunto-nivel-1.md"
        data = "# Principal\n\nContenido.\n".encode("utf-8")
        entry = {
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "nivel": "1º",
        }
        root_dir = tmp_path / "data" / "methodology" / carrier_root / "guided-character-v1"
        root_dir.mkdir(parents=True, exist_ok=True)
        if not omit_carrier:
            (root_dir / path).write_bytes(b"# Drifted\n" if drift else data)
        draft = client.post("/api/methodologies/drafts", json={
            **self._draft_payload(),
            "adjuntos": [entry],
        })
        assert draft.status_code == 200, draft.text
        _approve_draft_trigger(client, draft.json()["draft_id"])
        published = client.post(
            f"/api/methodologies/drafts/{draft.json()['draft_id']}/publish",
        )
        assert published.status_code == 200, published.text
        return entry

    def _publish_plain(self, client: TestClient) -> None:
        draft = client.post("/api/methodologies/drafts", json=self._draft_payload())
        assert draft.status_code == 200, draft.text
        _approve_draft_trigger(client, draft.json()["draft_id"])
        published = client.post(
            f"/api/methodologies/drafts/{draft.json()['draft_id']}/publish",
        )
        assert published.status_code == 200, published.text

    def test_published_detail_exposes_adjuntos_metadata(
        self, client: TestClient, monkeypatch, tmp_path,
    ):
        """R14 scenario "pinned detail": metadata-only pins, no bytes."""
        _principal(monkeypatch, "author-1")
        entry = self._publish_with_adjuntos(client, tmp_path)
        detail = client.get("/api/methodologies/published/guided-character-v1/1.2.0")
        assert detail.status_code == 200
        body = detail.json()
        assert body["adjuntos"] == [entry]
        # Byte content is never exposed on this surface.
        assert set(body["adjuntos"][0]) == {"path", "sha256", "bytes", "nivel"}

    def test_published_detail_adjuntos_empty_when_absent(self, client: TestClient, monkeypatch):
        """R14 scenario "empty adjuntos": absent pins project to ``[]``."""
        _principal(monkeypatch, "author-1")
        self._publish_plain(client)
        detail = client.get("/api/methodologies/published/guided-character-v1/1.2.0")
        assert detail.json()["adjuntos"] == []

    def test_status_exposes_adjuntos_metadata(self, client: TestClient, monkeypatch, tmp_path):
        """R15: each published item carries the additive metadata."""
        _principal(monkeypatch, "author-1")
        entry = self._publish_with_adjuntos(client, tmp_path)
        status = client.get("/api/methodologies/status")
        assert status.status_code == 200
        assert status.json()["published"][0]["adjuntos"] == [entry]

    def test_status_adjuntos_empty_when_absent(self, client: TestClient, monkeypatch):
        _principal(monkeypatch, "author-1")
        self._publish_plain(client)
        status = client.get("/api/methodologies/status")
        assert status.json()["published"][0]["adjuntos"] == []

    def test_export_embeds_adjuntos_and_round_trips(
        self, client: TestClient, monkeypatch, tmp_path,
    ):
        """R16 scenario "round-trip fidelity": carriers ship at their path,
        checksums bind them, inspection succeeds and the pins are reproduced."""
        _principal(monkeypatch, "author-1")
        entry = self._publish_with_adjuntos(client, tmp_path)
        exported = client.post(
            "/api/methodologies/published/guided-character-v1/1.2.0/export",
        )
        assert exported.status_code == 200, exported.text
        archive = zipfile.ZipFile(io.BytesIO(exported.content))
        assert set(archive.namelist()) == {
            "manifest.yaml", "source.md", "checksums.json", "adjunto-nivel-1.md",
        }
        verdict = inspect_package(exported.content)
        assert verdict.ok, verdict.issues
        assert verdict.compiled is not None
        assert [e.as_dict() for e in verdict.compiled.adjuntos] == [entry]
        # The exported package re-imports and verifies (never self-rejecting).
        uploaded = self._upload(client, exported.content, filename="roundtrip.zip")
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["verdict"]["ok"] is True

    def test_export_without_adjuntos_omits_manifest_key_and_carriers(
        self, client: TestClient, monkeypatch,
    ):
        """R21: a zero-attachment export stays byte-shape compatible with the
        pre-PR⑤ package (base entries only, no ``adjuntos`` key)."""
        _principal(monkeypatch, "author-1")
        self._publish_plain(client)
        exported = client.post(
            "/api/methodologies/published/guided-character-v1/1.2.0/export",
        )
        assert exported.status_code == 200, exported.text
        archive = zipfile.ZipFile(io.BytesIO(exported.content))
        assert set(archive.namelist()) == {"manifest.yaml", "source.md", "checksums.json"}
        manifest = yaml.safe_load(archive.read("manifest.yaml"))
        assert "adjuntos" not in manifest

    def test_export_missing_carrier_is_422(self, client: TestClient, monkeypatch, tmp_path):
        """R17 scenario "missing carrier": fail closed, no partial package."""
        _principal(monkeypatch, "author-1")
        self._publish_with_adjuntos(client, tmp_path, omit_carrier=True)
        exported = client.post(
            "/api/methodologies/published/guided-character-v1/1.2.0/export",
        )
        assert exported.status_code == 422
        assert exported.json()["code"] == "attachment_unavailable"
        # Non-leaking: the carrier path is never surfaced.
        assert "adjunto-nivel-1.md" not in exported.text

    def test_export_drifted_carrier_is_422(self, client: TestClient, monkeypatch, tmp_path):
        """R17 scenario "drifted carrier": fail closed with no package."""
        _principal(monkeypatch, "author-1")
        self._publish_with_adjuntos(client, tmp_path, drift=True)
        exported = client.post(
            "/api/methodologies/published/guided-character-v1/1.2.0/export",
        )
        assert exported.status_code == 422
        assert exported.json()["code"] == "attachment_unavailable"

    # ------------------------------------------------------------------ #
    # S1 — author carrier root: the resolver picks seeds/ when it exists,
    # else attachments/ (R9/R24). Seed export stays byte-identical.
    # ------------------------------------------------------------------ #

    def test_export_author_carriers_embed_from_attachments_root(
        self, client: TestClient, monkeypatch, tmp_path,
    ):
        """R24 scenario "author export embeds carriers": a skill with no seed
        dir resolves to ``attachments/`` and its verified carriers ship."""
        _principal(monkeypatch, "author-1")
        entry = self._publish_with_adjuntos(client, tmp_path, carrier_root="attachments")
        exported = client.post(
            "/api/methodologies/published/guided-character-v1/1.2.0/export",
        )
        assert exported.status_code == 200, exported.text
        archive = zipfile.ZipFile(io.BytesIO(exported.content))
        assert "adjunto-nivel-1.md" in archive.namelist()
        assert archive.read("adjunto-nivel-1.md") == "# Principal\n\nContenido.\n".encode("utf-8")
        verdict = inspect_package(exported.content)
        assert verdict.ok, verdict.issues
        assert verdict.compiled is not None
        assert [e.as_dict() for e in verdict.compiled.adjuntos] == [entry]
        # The exported package re-imports and verifies (never self-rejecting).
        uploaded = self._upload(client, exported.content, filename="author.zip")
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["verdict"]["ok"] is True

    def test_export_missing_author_carrier_is_422(
        self, client: TestClient, monkeypatch, tmp_path,
    ):
        """R24 scenario "missing author carrier fails closed": absent bytes
        under ``attachments/`` yield 422 and no partial package."""
        _principal(monkeypatch, "author-1")
        self._publish_with_adjuntos(
            client, tmp_path, carrier_root="attachments", omit_carrier=True,
        )
        exported = client.post(
            "/api/methodologies/published/guided-character-v1/1.2.0/export",
        )
        assert exported.status_code == 422
        assert exported.json()["code"] == "attachment_unavailable"
        assert "adjunto-nivel-1.md" not in exported.text

    def test_export_drifted_author_carrier_is_422(
        self, client: TestClient, monkeypatch, tmp_path,
    ):
        """R24: bytes changed under ``attachments/`` fail closed too."""
        _principal(monkeypatch, "author-1")
        self._publish_with_adjuntos(
            client, tmp_path, carrier_root="attachments", drift=True,
        )
        exported = client.post(
            "/api/methodologies/published/guided-character-v1/1.2.0/export",
        )
        assert exported.status_code == 422
        assert exported.json()["code"] == "attachment_unavailable"

    def test_seed_carrier_wins_when_author_dir_also_exists(
        self, client: TestClient, monkeypatch, tmp_path,
    ):
        """R24 scenario "seed export unchanged": an existing seed dir keeps
        winning even if an author dir of the same name exists, so the bundled
        bytes — not the author bytes — are embedded (byte-identical export)."""
        _principal(monkeypatch, "author-1")
        path = "adjunto-nivel-1.md"
        seed_data = "# Seed\n\nContenido semilla.\n".encode("utf-8")
        author_data = "# Author\n\nContenido autor.\n".encode("utf-8")
        entry = {
            "path": path,
            "sha256": hashlib.sha256(seed_data).hexdigest(),
            "bytes": len(seed_data),
            "nivel": "1º",
        }
        seed_dir = tmp_path / "data" / "methodology" / "seeds" / "guided-character-v1"
        seed_dir.mkdir(parents=True, exist_ok=True)
        (seed_dir / path).write_bytes(seed_data)
        author_dir = tmp_path / "data" / "methodology" / "attachments" / "guided-character-v1"
        author_dir.mkdir(parents=True, exist_ok=True)
        (author_dir / path).write_bytes(author_data)
        draft = client.post("/api/methodologies/drafts", json={
            **self._draft_payload(),
            "adjuntos": [entry],
        })
        assert draft.status_code == 200, draft.text
        _approve_draft_trigger(client, draft.json()["draft_id"])
        published = client.post(
            f"/api/methodologies/drafts/{draft.json()['draft_id']}/publish",
        )
        assert published.status_code == 200, published.text
        exported = client.post(
            "/api/methodologies/published/guided-character-v1/1.2.0/export",
        )
        assert exported.status_code == 200, exported.text
        archive = zipfile.ZipFile(io.BytesIO(exported.content))
        assert archive.read(path) == seed_data
        assert archive.read(path) != author_data

    def test_import_quarantines_and_does_not_mutate_library(self, client: TestClient, monkeypatch):
        """REQ-IMP-2/3: import isolates the package; the library stays intact."""
        _principal(monkeypatch, "author-1")
        imported = self._upload(client, self._import_package())
        assert imported.status_code == 200, imported.text
        record = imported.json()
        assert record["package_id"]
        assert record["verdict"]["ok"] is True
        assert record["verdict"]["issues"] == []
        assert record["verdict"]["checksum_valid"] is True
        assert record["clasificacion"] == "Comunitarias"
        assert record["trusted"] is False
        entries = client.get("/api/methodologies/quarantine").json()["entries"]
        assert [entry["package_id"] for entry in entries] == [record["package_id"]]
        status = client.get("/api/methodologies/status").json()
        assert status["drafts"] == []
        assert status["published"] == []

    def test_import_malformed_zip_quarantines_failed_verdict(self, client: TestClient, monkeypatch):
        """REQ-IMP-3: malformed packages fail closed but stay quarantined."""
        _principal(monkeypatch, "author-1")
        imported = self._upload(client, b"not-a-zip", filename="broken.zip")
        assert imported.status_code == 200
        record = imported.json()
        assert record["verdict"]["ok"] is False
        assert record["verdict"]["checksum_valid"] is False
        assert record["verdict"]["issues"]

    def test_import_quarantine_trust_round_trip_creates_draft(self, client: TestClient, monkeypatch):
        """REQ-IMP-4: trust promotes a quarantined package to an editable
        draft with system-derived clasificacion/trust_attributes."""
        _principal(monkeypatch, "author-1")
        imported = self._upload(client, self._import_package()).json()
        trusted = client.post(f"/api/methodologies/quarantine/{imported['package_id']}/trust")
        assert trusted.status_code == 200, trusted.text
        payload = trusted.json()
        assert payload["package_id"] == imported["package_id"]
        assert payload["trusted"] is True
        assert payload["draft_id"]
        assert payload["clasificacion"] == "Comunitarias"
        assert payload["trust_attributes"] == []
        status = client.get("/api/methodologies/status").json()
        assert [draft["skill_id"] for draft in status["drafts"]] == ["guided-character-v1"]
        entries = client.get("/api/methodologies/quarantine").json()["entries"]
        trusted_entry = next(
            entry for entry in entries
            if entry["package_id"] == imported["package_id"]
        )
        assert trusted_entry["trusted"] is True
        assert trusted_entry["draft_id"] == payload["draft_id"]

    def test_trust_fails_closed_for_failed_verdict(self, client: TestClient, monkeypatch):
        """REQ-IMP-4: trust is blocked when the package does not re-validate."""
        _principal(monkeypatch, "author-1")
        imported = self._upload(client, b"not-a-zip", filename="broken.zip").json()
        trusted = client.post(f"/api/methodologies/quarantine/{imported['package_id']}/trust")
        assert trusted.status_code == 422
        assert trusted.json()["code"] == "trust_rejected"
        assert client.get("/api/methodologies/status").json()["drafts"] == []

    def test_trust_unknown_package_is_404(self, client: TestClient, monkeypatch):
        _principal(monkeypatch, "author-1")
        response = client.post("/api/methodologies/quarantine/ghost/trust")
        assert response.status_code == 404

    # ------------------------------------------------------------------ #
    # S5 — trust-time carrier extraction: the trust route materializes the
    # verified zip carriers under attachments/{skill_id}/ so the exported
    # package round-trips instead of failing closed 422 (AE-4).
    # ------------------------------------------------------------------ #

    def test_trust_extracts_carriers_and_export_round_trips(
        self, client: TestClient, monkeypatch, tmp_path,
    ):
        """AE-4 scenario "trusted import round-trips": after trusting a package
        with carriers, its export embeds them (no ``attachment_unavailable``)."""
        _principal(monkeypatch, "author-1")
        path = "adjunto-nivel-1.md"
        data = "# Principal\n\nContenido.\n".encode("utf-8")
        entry = {
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "nivel": "1º",
        }
        package = build_package(
            {
                "skill_id": "guided-character-v1",
                "version": "1.2.0",
                "name": "Guided character methodology",
                "description": "A safe construction methodology.",
                "phases": ["conversation", "review", "complete"],
                "language": "es",
                "adjuntos": [entry],
            },
            "## Construcción segura\n\nHaz preguntas de a una.\n",
            attachments={path: data},
        )
        imported = self._upload(client, package, filename="with-carrier.zip").json()
        assert imported["verdict"]["ok"] is True, imported["verdict"]["issues"]

        trusted = client.post(
            f"/api/methodologies/quarantine/{imported['package_id']}/trust",
        )
        assert trusted.status_code == 200, trusted.text

        # The verified carrier landed under the patched PROJECT_ROOT.
        extracted = (
            tmp_path / "data" / "methodology" / "attachments" / "guided-character-v1" / path
        )
        assert extracted.read_bytes() == data

        # Publish the trusted draft, then export: the carriers ship.
        draft_id = trusted.json()["draft_id"]
        _approve_draft_trigger(client, draft_id)
        published = client.post(f"/api/methodologies/drafts/{draft_id}/publish")
        assert published.status_code == 200, published.text
        exported = client.post(
            "/api/methodologies/published/guided-character-v1/1.2.0/export",
        )
        assert exported.status_code == 200, exported.text
        archive = zipfile.ZipFile(io.BytesIO(exported.content))
        assert archive.read(path) == data
        verdict = inspect_package(exported.content)
        assert verdict.ok, verdict.issues

    def test_publish_before_trust_extraction_would_fail_closed(
        self, client: TestClient, monkeypatch, tmp_path,
    ):
        """The pre-existing broken round-trip: without a trusted extraction the
        author export fails closed 422 (the bug S5 fixes)."""
        _principal(monkeypatch, "author-1")
        path = "adjunto-nivel-1.md"
        data = "# Principal\n\nContenido.\n".encode("utf-8")
        entry = {
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "nivel": "1º",
        }
        package = build_package(
            {
                "skill_id": "guided-character-v1",
                "version": "1.2.0",
                "name": "Guided character methodology",
                "description": "A safe construction methodology.",
                "phases": ["conversation", "review", "complete"],
                "language": "es",
                "adjuntos": [entry],
            },
            "## Construcción segura\n\nHaz preguntas de a una.\n",
            attachments={path: data},
        )
        imported = self._upload(client, package, filename="with-carrier.zip").json()
        assert imported["verdict"]["ok"] is True, imported["verdict"]["issues"]
        # Publish the imported draft WITHOUT trusting (the buggy path): no bytes
        # are materialized, so export fails closed.
        record = api_server._methodology_quarantine().get(imported["package_id"])
        assert record is not None
        draft_id = api_server._methodology_library().create_draft(
            skill_id=record.verdict.compiled.skill_id,
            version=record.verdict.compiled.version,
            name=record.verdict.compiled.name,
            source=record.verdict.compiled.source,
            description=record.verdict.compiled.description,
            phases=tuple(record.verdict.compiled.phases),
            language=record.verdict.compiled.language,
            adjuntos=tuple(record.verdict.compiled.adjuntos),
        )
        _approve_draft_trigger(client, draft_id)
        published = client.post(f"/api/methodologies/drafts/{draft_id}/publish")
        assert published.status_code == 200, published.text
        exported = client.post(
            "/api/methodologies/published/guided-character-v1/1.2.0/export",
        )
        assert exported.status_code == 422
        assert exported.json()["code"] == "attachment_unavailable"

    def test_reserved_skill_id_rejected_at_trust(self, client: TestClient, monkeypatch):
        """REQ-IMP-6 scenario: trusting a package with the foundational
        character-skill id is rejected with 409 and no draft is created."""
        _principal(monkeypatch, "author-1")
        foundational = build_package({
            "skill_id": "narrative-character-creation",
            "version": "1.0.0",
            "name": "Skill Madre",
            "description": "La skill madre del taller.",
            "phases": ["conversation", "review", "complete"],
            "language": "es",
        }, "## Skill Madre\n\nTexto.\n")
        imported = self._upload(client, foundational, filename="madre.zip").json()
        assert imported["verdict"]["ok"] is True
        trusted = client.post(f"/api/methodologies/quarantine/{imported['package_id']}/trust")
        assert trusted.status_code == 409
        assert trusted.json()["code"] == "reserved_skill_id"
        assert client.get("/api/methodologies/status").json()["drafts"] == []

    def test_system_skill_id_rejected_at_trust(self, client: TestClient, monkeypatch):
        """WU-3 quarantine-trust coverage: the reserved foundational Sistema id
        is rejected with 409 reserved_skill_id and no draft is created — the
        system skill is reserved exactly like the character skill."""
        _principal(monkeypatch, "author-1")
        foundational = build_package({
            "skill_id": "narrative-system-creation",
            "version": "1.0",
            "name": "Creación de Sistemas",
            "description": "La skill fundacional de sistemas.",
            "phases": ["conversation", "review", "complete"],
            "language": "es",
        }, "## Sistema\n\nTexto.\n")
        imported = self._upload(client, foundational, filename="sistema.zip").json()
        assert imported["verdict"]["ok"] is True
        trusted = client.post(f"/api/methodologies/quarantine/{imported['package_id']}/trust")
        assert trusted.status_code == 409
        assert trusted.json()["code"] == "reserved_skill_id"
        assert client.get("/api/methodologies/status").json()["drafts"] == []

    def test_reserved_skill_id_rejected_at_publish(self, client: TestClient, monkeypatch):
        """REQ-IMP-6 scenario: an import-derived foundational character-skill
        draft can never be published (409 reserved_skill_id)."""
        _principal(monkeypatch, "author-1")
        draft = client.post("/api/methodologies/drafts", json={
            "skill_id": "narrative-character-creation",
            "version": "1.0.0",
            "name": "Skill Madre",
            "source": "## Skill Madre\n\nTexto.\n",
        })
        assert draft.status_code == 200, draft.text
        draft_id = draft.json()["draft_id"]
        # Import-derived drafts carry server-injected parent_skill_id; simulate
        # that state (white-box) and assert publish fails closed.
        library = api_server._methodology_library()
        with library._lock:
            library._drafts[draft_id]["parent_skill_id"] = "narrative-character-creation"
        published = client.post(f"/api/methodologies/drafts/{draft_id}/publish")
        assert published.status_code == 409
        assert published.json()["code"] == "reserved_skill_id"

    def test_reserved_foundational_author_publish_is_allowed(self, client: TestClient, monkeypatch):
        """The guard only blocks import-derived publishes: the foundational
        character skill authored directly in the workshop still publishes normally."""
        _principal(monkeypatch, "author-1")
        draft = client.post("/api/methodologies/drafts", json={
            "skill_id": "narrative-character-creation",
            "version": "1.0.0",
            "name": "Skill Madre",
            "source": "## Skill Madre\n\nTexto.\n",
        })
        assert draft.status_code == 200, draft.text
        _approve_draft_trigger(client, draft.json()["draft_id"])
        published = client.post(f"/api/methodologies/drafts/{draft.json()['draft_id']}/publish")
        assert published.status_code == 200, published.text
        assert published.json()["skill_id"] == "narrative-character-creation"

    # ------------------------------------------------------------------ #
    # Companion routes (WU2): activate/deactivate + additive status key.
    # ------------------------------------------------------------------ #

    def _seed_companion_library(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> MethodologyLibrary:
        library = MethodologyLibrary(tmp_path / "data" / "methodology" / "library.json")
        draft_id = library.create_draft(
            skill_id="companion-skill", version="1.0.0",
            name="Companion skill",
            source="## Compañera\n\nTexto.\n",
            description="Metodología compañera de prueba.",
        )
        _approve_library_trigger(library, draft_id, "Metodología compañera de prueba.")
        library.publish(draft_id)
        monkeypatch.setattr(api_server, "_METHODOLOGY_LIBRARY", library)
        return library

    def test_activate_companion_happy_path(self, client: TestClient, monkeypatch, tmp_path):
        _principal(monkeypatch, "author-1")
        library = self._seed_companion_library(monkeypatch, tmp_path)
        published = library.get_published("companion-skill", "1.0.0")
        resp = client.post("/api/methodologies/companions/activate", json={
            "world": "test_mundo", "skill_id": "companion-skill", "version": "1.0.0",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["world"] == "test_mundo"
        assert resp.json()["companion"] == {
            "world": "test_mundo",
            "skill_id": "companion-skill",
            "version": "1.0.0",
            "description": published.description,
            "activated_at": library.list_companions("test_mundo")[0].activated_at,
        }
        assert [c.skill_id for c in library.list_companions("test_mundo")] == ["companion-skill"]

    def test_companion_routes_auth_and_unknown_world(self, client: TestClient, monkeypatch, tmp_path):
        self._seed_companion_library(monkeypatch, tmp_path)
        activate = {"world": "test_mundo", "skill_id": "companion-skill", "version": "1.0.0"}
        deactivate = {"world": "test_mundo", "skill_id": "companion-skill"}
        # No principal -> 401 on both routes.
        assert client.post("/api/methodologies/companions/activate", json=activate).status_code == 401
        assert client.post("/api/methodologies/companions/deactivate", json=deactivate).status_code == 401
        # Unknown world -> 404 on both routes.
        _principal(monkeypatch, "author-1")
        assert client.post(
            "/api/methodologies/companions/activate",
            json={"world": "ghost", "skill_id": "companion-skill", "version": "1.0.0"},
        ).status_code == 404
        assert client.post(
            "/api/methodologies/companions/deactivate",
            json={"world": "ghost", "skill_id": "companion-skill"},
        ).status_code == 404

    def test_deactivate_companion_idempotent(self, client: TestClient, monkeypatch, tmp_path):
        _principal(monkeypatch, "author-1")
        library = self._seed_companion_library(monkeypatch, tmp_path)
        client.post("/api/methodologies/companions/activate", json={
            "world": "test_mundo", "skill_id": "companion-skill", "version": "1.0.0",
        })
        removed = client.post("/api/methodologies/companions/deactivate", json={
            "world": "test_mundo", "skill_id": "companion-skill",
        })
        assert removed.status_code == 200, removed.text
        assert removed.json() == {"world": "test_mundo", "removed": True}
        assert library.list_companions("test_mundo") == []
        again = client.post("/api/methodologies/companions/deactivate", json={
            "world": "test_mundo", "skill_id": "companion-skill",
        })
        assert again.json() == {"world": "test_mundo", "removed": False}

    def test_status_companions_additive_and_stable(self, client: TestClient, monkeypatch, tmp_path):
        _principal(monkeypatch, "author-1")
        library = self._seed_companion_library(monkeypatch, tmp_path)
        baseline = client.get("/api/methodologies/status").json()
        client.post("/api/methodologies/companions/activate", json={
            "world": "test_mundo", "skill_id": "companion-skill", "version": "1.0.0",
        })
        after = client.get("/api/methodologies/status").json()
        # Every pre-existing key is byte-stable vs the no-companion baseline.
        for key in ("published", "activations", "drafts"):
            assert after[key] == baseline[key]
        companion = library.list_companions("test_mundo")[0]
        assert after["companions"] == {
            "test_mundo": [{
                "world": "test_mundo",
                "skill_id": "companion-skill",
                "version": "1.0.0",
                "description": "Metodología compañera de prueba.",
                "activated_at": companion.activated_at,
            }],
        }

    def test_status_includes_ideas_global_only_when_present(self, client: TestClient, monkeypatch, tmp_path):
        """D-GLOBAL regression (C3): ideas-global is not a real world, so the
        companion routes 404 it and it never appears in the status map."""
        _principal(monkeypatch, "author-1")
        self._seed_companion_library(monkeypatch, tmp_path)
        resp = client.post("/api/methodologies/companions/activate", json={
            "world": "ideas-global", "skill_id": "companion-skill", "version": "1.0.0",
        })
        assert resp.status_code == 404
        status = client.get("/api/methodologies/status").json()
        assert "ideas-global" not in status["companions"]

    def test_guided_flow_ignores_companions(self, client: TestClient, monkeypatch, tmp_path):
        """R-GUIDED-INVARIANT anchor: a companion-rich world with an EMPTY slot
        yields the exact same guided contract projection as a companion-free
        world — ``_compiled_contract_markdown`` reads only ``active_for``."""
        _principal(monkeypatch, "author-1")
        library = self._seed_companion_library(monkeypatch, tmp_path)
        assert api_server._compiled_contract_markdown("test_mundo") is None
        library.add_companion("test_mundo", "companion-skill", "1.0.0")
        assert library.active_for("test_mundo") is None
        assert api_server._compiled_contract_markdown("test_mundo") is None


class TestSeedFirstBoot:
    """PR3: first-boot seeding through the API (S2, S3-boot, S4).

    Seeding runs on lazy init of ``_methodology_library()``; the seed root is
    resolved from PROJECT_ROOT at call time, so these tests copy the REAL
    bundled seeds into the tmp project root the ``client`` fixture patches —
    the repo store is never written by tests.
    """

    @staticmethod
    def _write_seed_entry(
        root: Path, skill_id: str, *, source: str,
    ) -> None:
        """Write a seed entry whose checksums match its own bytes (integrity
        passes) but whose content may fail compilation."""
        entry_dir = root / skill_id
        entry_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "skill_id": skill_id,
            "version": "1.0",
            "name": "Skill de prueba",
            "description": "Metodología de prueba para el catálogo de seeds.",
            "phases": ["fase uno", "fase dos"],
            "language": "es",
        }
        manifest_bytes = yaml.safe_dump(
            manifest, sort_keys=False, allow_unicode=True,
        ).encode("utf-8")
        source_bytes = source.encode("utf-8")
        (entry_dir / "manifest.yaml").write_bytes(manifest_bytes)
        (entry_dir / "source.md").write_bytes(source_bytes)
        (entry_dir / "checksums.json").write_text(
            json.dumps({
                "manifest.yaml": hashlib.sha256(manifest_bytes).hexdigest(),
                "source.md": hashlib.sha256(source_bytes).hexdigest(),
            }, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def test_fresh_boot_seeds_foundational_skill(
        self, client: TestClient, monkeypatch, tmp_path: Path,
    ) -> None:
        """S2: with the real seeds copied into the tmp PROJECT_ROOT, lazy init
        publishes the skill as Oficiales + fundacional with the digest pinned
        to the compiled bundled bytes; inventory and status expose it."""
        shutil.copytree(SEED_ROOT, tmp_path / "data" / "methodology" / "seeds")
        response = client.get("/api/methodologies/inventory")
        assert response.status_code == 200
        items = response.json()["items"]
        assert [item["skill_id"] for item in items] == [
            "narrative-character-creation", "narrative-chronology-creation",
            "narrative-entity-creation", "narrative-system-creation",
        ]
        item = items[0]
        assert item["version"] == "1.3"
        assert item["clasificacion"] == "Oficiales"
        assert item["trust_attributes"] == ["fundacional"]
        entry = load_seed_catalog(SEED_ROOT)[0]
        compiled = compile_methodology(entry.manifest, entry.source)
        assert compiled.ok
        assert item["digest"] == compiled.compiled.digest
        _principal(monkeypatch, "author-1")
        status = client.get("/api/methodologies/status").json()
        published = status["published"]
        assert [p["skill_id"] for p in published] == [
            "narrative-character-creation", "narrative-chronology-creation",
            "narrative-entity-creation", "narrative-system-creation",
        ]
        assert published[0]["clasificacion"] == "Oficiales"
        assert published[0]["trust_attributes"] == ["fundacional"]

    def test_compiler_invalid_seed_fails_closed_and_routes_serve(
        self, client: TestClient, monkeypatch, tmp_path: Path,
    ) -> None:
        """S3-boot: a seed whose bytes are intact (checksums match) but whose
        source claims authority aborts the install — ZERO records inserted,
        the lazy-init never raises, and the routes still serve."""
        seed_root = tmp_path / "data" / "methodology" / "seeds"
        seed_root.mkdir(parents=True)
        self._write_seed_entry(
            seed_root, "broken-skill",
            source="## Rota\n\n#!demiurgos-authority\nContenido que reclama autoridad.\n",
        )
        response = client.get("/api/methodologies/inventory")
        assert response.status_code == 200
        assert response.json() == {"items": []}
        assert not (tmp_path / "data" / "methodology" / "library.json").exists()

    def test_concurrent_first_boot_installs_one_copy(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """S4: two threads racing ``_methodology_library()`` yield ONE
        published copy and a valid, reloadable store."""
        monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
        api_server._METHODOLOGY_LIBRARY = None
        shutil.copytree(SEED_ROOT, tmp_path / "data" / "methodology" / "seeds")
        barrier = threading.Barrier(2)
        seen = []

        def _init() -> None:
            barrier.wait()
            seen.append(api_server._methodology_library())

        threads = [threading.Thread(target=_init) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        # Double-checked init: both racers resolve the same instance.
        assert seen[0] is seen[1]
        versions = api_server._methodology_library().published_versions_for(
            "narrative-character-creation",
        )
        assert len(versions) == 1
        reloaded = MethodologyLibrary(tmp_path / "data" / "methodology" / "library.json")
        assert [v["version"] for v in
                reloaded.published_versions_for("narrative-character-creation")] == ["1.3"]
        # Leave the module global clean for later tests.
        api_server._METHODOLOGY_LIBRARY = None


# ------------------------------------------------------------------ #
# Companion-gated awaited routing bridge (WU3b): injection + fallback.
# ------------------------------------------------------------------ #


class _RecordingActivityAdapter:
    """Records every submitted prompt and cancellation (leak/call assertions)."""

    available = True
    capability = _activity_capability()

    def __init__(self):
        self.prompts = []
        self.cancelled = []
        self._n = 0

    def start(self, request):
        self.prompts.append(request.prompt)
        self._n += 1
        return f"bridge-run-{self._n}"

    async def events(self, run_id):
        yield {"event": "run.completed", "run_id": run_id, "output": "bridge answer"}

    def cancel(self, run_id):
        self.cancelled.append(run_id)


class _BridgeRouter:
    """Scripted skill router: yields pre-set winners in order; records calls."""

    def __init__(self, *winners):
        self._winners = list(winners)
        self.calls = []

    async def route(self, prompt, mundo, distilled_state=None):
        self.calls.append((prompt, mundo))
        winner = self._winners.pop(0) if self._winners else None
        return api_server.SkillRouteResult(
            skill_id=winner, confidence=0.9 if winner else 0.0,
            source="llm" if winner else "fallback", routed=winner is not None,
        )


class _SlowRouter:
    """Router that sleeps past the routing budget (timeout fallback test)."""

    async def route(self, prompt, mundo, distilled_state=None):
        await asyncio.sleep(0.2)
        return api_server.SkillRouteResult(
            skill_id="companion-skill", confidence=0.9, source="llm", routed=True,
        )


class TestCompanionActivityBridge:
    """WU3b bridge: companion-gated awaited routing + bounded injection.

    R-BRIDGE scenarios: a companion winner injects the projected methodology
    (content, not name-only); a routing timeout falls back to today's prompt
    with persistence intact; a zero-companion baseline stays byte-identical
    with no double routing; injection is per-turn only (no sticky state); and
    the marker leaks no digest or internal path.
    """

    def _wire(self, monkeypatch, tmp_path, router, payloads=1, *, companions=True):
        library = MethodologyLibrary(tmp_path / "data" / "methodology" / "library.json")
        draft_id = library.create_draft(
            skill_id="companion-skill", version="1.0.0",
            name="Companion skill",
            source="## Compañera\n\nMetodología compañera.\n",
            description="Metodología compañera de prueba.",
        )
        _approve_library_trigger(library, draft_id, "Metodología compañera de prueba.")
        library.publish(draft_id)
        if companions:
            library.add_companion("test_mundo", "companion-skill", "1.0.0")
        monkeypatch.setattr(api_server, "_METHODOLOGY_LIBRARY", library)
        monkeypatch.setattr(
            api_server, "_CONVERSATION_MEMORY", api_server.ConversationMemoryStore(":memory:")
        )
        monkeypatch.setattr(api_server, "_SKILL_ROUTER", router)
        runs = _SemanticRuns(*([_semantic_payload("allow")] * payloads))
        _wire_semantic_provider(monkeypatch, runs)
        adapter = _RecordingActivityAdapter()
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)
        return library, runs, adapter

    def test_activity_companion_winner_injects_contract(self, client, monkeypatch, tmp_path):
        """A companion winner's projected methodology is injected as CONTENT."""
        library, runs, adapter = self._wire(
            monkeypatch, tmp_path, _BridgeRouter("companion-skill")
        )
        response = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "Hola", "session_id": "bridge-1",
        })
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        published = library.get_published("companion-skill", "1.0.0")
        assert f"[Companion methodology: {published.name}]\n" in adapter.prompts[0]
        # Projected markdown content rides in the marker (not name-only).
        assert "Metodología compañera de prueba." in adapter.prompts[0]
        assert adapter.prompts[0].endswith("\n\nHola")
        # Exactly one semantic provider run — the gate; routing adds none.
        assert runs.starts == 1

    def test_activity_timeout_falls_back_and_persists(self, client, monkeypatch, tmp_path):
        """A routing timeout keeps today's prompt AND persistence intact."""
        library, runs, adapter = self._wire(monkeypatch, tmp_path, _SlowRouter())
        monkeypatch.setattr(api_server, "ROUTING_AWAIT_TIMEOUT_SECONDS", 0.01)
        response = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "Hola", "session_id": "bridge-timeout",
        })
        assert response.status_code == 200
        prompt = adapter.prompts[0]
        assert "[Companion methodology:" not in prompt
        assert prompt.endswith("\n\nHola")
        # The shielded task resolved at close: the user turn persisted with the
        # companion winner recorded for analytics while the prompt stayed clean.
        turns = api_server._CONVERSATION_MEMORY.get_recent_turns("bridge-timeout")
        assert [turn.role for turn in turns] == ["user", "assistant"]
        assert turns[0].skill_id == "companion-skill"

    def test_activity_nonmatching_prompt_identical_baseline(self, client, monkeypatch, tmp_path):
        """Zero-companion no-winner == companion-no-winner prompt; one routing
        decision per turn (no double routing).

        WU-3: companion-free worlds with a real session now AWAIT routing, so a
        zero-companion no-winner turn still yields today's byte-identical
        no-skill prompt (no marker injected) with exactly one routing decision.
        """
        router = _BridgeRouter()
        library, runs, adapter = self._wire(
            monkeypatch, tmp_path, router, payloads=2, companions=False,
        )
        baseline = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "Hola", "session_id": "bridge-baseline",
        })
        assert baseline.status_code == 200
        baseline_prompt = adapter.prompts[0]
        # The companion-free no-winner turn injects nothing (byte-identical).
        assert "[Companion methodology:" not in baseline_prompt
        assert "[Foundational methodology:" not in baseline_prompt
        # The same world now gains a companion but classification yields no
        # winner: the prompt must be byte-identical to the no-skill prompt.
        library.add_companion("test_mundo", "companion-skill", "1.0.0")
        no_winner = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "Hola", "session_id": "bridge-nowinner",
        })
        assert no_winner.status_code == 200
        assert adapter.prompts[1] == baseline_prompt
        # One routing decision per turn: the awaited early task is reused at
        # close (never re-spawned), so exactly 2 total for 2 turns.
        assert len(router.calls) == 2

    def test_activity_no_stickiness_next_turn(self, client, monkeypatch, tmp_path):
        """Injection is per-turn only: a later non-matching turn has no marker."""
        router = _BridgeRouter("companion-skill")
        library, runs, adapter = self._wire(monkeypatch, tmp_path, router, payloads=2)
        first = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "Hola", "session_id": "bridge-sticky",
        })
        assert first.status_code == 200
        assert "[Companion methodology:" in adapter.prompts[0]
        second = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "Chau", "session_id": "bridge-sticky",
        })
        assert second.status_code == 200
        assert "[Companion methodology:" not in adapter.prompts[1]

    def test_injection_marker_no_digest_no_path(self, client, monkeypatch, tmp_path):
        """The marker is bounded: name + projected markdown only — no digest,
        no library file, no methodology dir, no absolute path."""
        library, runs, adapter = self._wire(
            monkeypatch, tmp_path, _BridgeRouter("companion-skill")
        )
        response = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "Hola", "session_id": "bridge-leak",
        })
        assert response.status_code == 200
        prompt = adapter.prompts[0]
        assert "[Companion methodology:" in prompt
        for forbidden in (
            "sha256:", "digest", "library.json", "data/methodology",
            "/mnt/", "tmp/", "CompiledMethodology",
        ):
            assert forbidden not in prompt


class TestTransversalActivityConsumption:
    """WU-3 consume bridge: a routed transversal winner injects the bounded
    method on the legacy channel for a companion-FREE world.

    Mirrors ``TestCompanionActivityBridge`` for the generic transversal seam:
    the world has NO companion and the router returns a foundational winner
    (``narrative-system-creation``), yet the method content is injected; a
    routing timeout falls back to today's prompt with persistence intact; and a
    companion-free no-winner turn stays byte-identical to the baseline.
    """

    def _wire(self, monkeypatch, tmp_path, router, payloads=1):
        library = MethodologyLibrary(tmp_path / "data" / "methodology" / "library.json")
        draft_id = library.create_draft(
            skill_id="narrative-system-creation", version="1.0",
            name="Creación de Sistemas",
            source="## Sistema\n\nMetodología fundacional de sistemas.\n",
            description="Metodología fundacional para co-crear un sistema.",
        )
        _approve_library_trigger(
            library, draft_id, "Metodología fundacional para co-crear un sistema."
        )
        library.publish(draft_id)
        # No companion is registered: the world is companion-free (WU-3 change).
        monkeypatch.setattr(api_server, "_METHODOLOGY_LIBRARY", library)
        monkeypatch.setattr(
            api_server, "_CONVERSATION_MEMORY", api_server.ConversationMemoryStore(":memory:")
        )
        monkeypatch.setattr(api_server, "_SKILL_ROUTER", router)
        runs = _SemanticRuns(*([_semantic_payload("allow")] * payloads))
        _wire_semantic_provider(monkeypatch, runs)
        adapter = _RecordingActivityAdapter()
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)
        return library, runs, adapter

    def test_companion_free_transversal_winner_injects_contract(self, client, monkeypatch, tmp_path):
        """A routed transversal winner's projected method is injected as CONTENT."""
        library, runs, adapter = self._wire(
            monkeypatch, tmp_path, _BridgeRouter("narrative-system-creation")
        )
        response = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "Hola", "session_id": "transversal-1",
        })
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        published = library.get_published("narrative-system-creation", "1.0")
        assert f"[Foundational methodology: {published.name}]\n" in adapter.prompts[0]
        # Projected markdown content rides in the marker (not name-only).
        assert "Metodología fundacional para co-crear un sistema." in adapter.prompts[0]
        assert adapter.prompts[0].endswith("\n\nHola")
        # Exactly one semantic provider run — the gate; routing adds none.
        assert runs.starts == 1

    def test_real_seed_injects_full_system_method_contract(self, client, monkeypatch, tmp_path):
        """WARNING-1 regression: the REAL repo seed's method — not the synthetic
        stand-in the E2E tests publish — is what the transversal seam injects.
        Installing the real seed catalog and routing its skill yields a
        projection carrying all nine question markers, the five origin classes,
        the ``Rieles 40%`` completeness rail, and the Cronología boundary, within
        the default token bound. This locks the seed's ``description`` contract
        against future byte-edits."""
        library = MethodologyLibrary(tmp_path / "data" / "methodology" / "library.json")
        report = install_seeds(library, SEED_ROOT)
        assert report.installed == 4 and report.conflict == 0
        monkeypatch.setattr(api_server, "_METHODOLOGY_LIBRARY", library)

        contract = api_server._transversal_contract_for(
            "narrative-system-creation", "test_mundo"
        )

        assert contract is not None
        assert contract.startswith("[Foundational methodology: Creación de Sistemas]\n")
        for marker in (f"({n})" for n in range(1, 10)):
            assert marker in contract, f"missing question marker {marker}"
        for clase in (
            "material/construido", "innato/biológico", "otorgado/divino",
            "natural/cósmico", "social/convencional",
        ):
            assert clase in contract, f"missing origin class {clase}"
        assert "Rieles 40%" in contract
        assert "Cronología" in contract
        # Default projection bound (≤1000 tokens, ~4 chars/token).
        projected = contract.split("\n", 1)[1]
        assert len(projected) <= 1000 * 4

    def test_transversal_marker_no_digest_no_path(self, client, monkeypatch, tmp_path):
        """The transversal marker is bounded: name + projected markdown only."""
        library, runs, adapter = self._wire(
            monkeypatch, tmp_path, _BridgeRouter("narrative-system-creation")
        )
        response = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "Hola", "session_id": "transversal-leak",
        })
        assert response.status_code == 200
        prompt = adapter.prompts[0]
        assert "[Foundational methodology:" in prompt
        for forbidden in (
            "sha256:", "digest", "library.json", "data/methodology",
            "/mnt/", "tmp/", "CompiledMethodology",
        ):
            assert forbidden not in prompt

    def test_transversal_routing_timeout_falls_back_and_persists(
        self, client, monkeypatch, tmp_path
    ):
        """A routing timeout keeps today's prompt AND persistence intact."""
        library, runs, adapter = self._wire(monkeypatch, tmp_path, _SlowRouter())
        monkeypatch.setattr(api_server, "ROUTING_AWAIT_TIMEOUT_SECONDS", 0.01)
        response = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "Hola", "session_id": "transversal-timeout",
        })
        assert response.status_code == 200
        prompt = adapter.prompts[0]
        assert "[Foundational methodology:" not in prompt
        assert prompt.endswith("\n\nHola")
        # The shielded task resolved at close: the user turn persisted with the
        # routed winner recorded while the prompt stayed clean.
        turns = api_server._CONVERSATION_MEMORY.get_recent_turns("transversal-timeout")
        assert [turn.role for turn in turns] == ["user", "assistant"]
        assert turns[0].skill_id == "companion-skill"


def _delta_guided_provider():
    async def provider(request, _token):
        return {
            "protocol_version": "guided-character-v1",
            "request_id": request.request_id,
            "session_id": request.session_id,
            "outcome": "delta",
            "delta": {"name": "Pert", "desire": "freedom"},
        }

    return provider


class TestSemanticRouting:
    """PR 2 (Hermes-first): the mandatory semantic gate runs BEFORE any
    Demiurgos classifier or action on every assistant surface.

    No lexical-first path and no plain-chat fallback exist: unwired,
    unavailable, invalid, or exhausted Hermes fails closed with the localized
    safe blocked envelope and zero action, session, proposal, or write.
    """

    def test_unwired_provider_fails_closed_without_legacy_path(self, client: TestClient):
        assert api_server._SEMANTIC_PROVIDER is None
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": "Hola"})
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "blocked"
        assert envelope["unavailable"] is True
        assert envelope["action"] == "blocked_explanation"
        assert envelope["response"].startswith("El Asistente IA no pudo")
        legacy.assert_not_awaited()

    def test_allow_returns_server_envelope_without_second_run(self, client: TestClient, monkeypatch):
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        with patch("api_server._run_hermes", new=AsyncMock(return_value="unused")) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": "Hola"})
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "allow"
        assert envelope["action"] == "answer"
        assert envelope["response"] == "Hermes semantic answer."
        assert envelope["attempts"] == 1
        assert envelope["guided"] is True
        assert "fallback" not in envelope
        legacy.assert_not_awaited()
        assert runs.starts == 1

    def test_self_contained_states_route_through_the_seam(self, client: TestClient, monkeypatch):
        for state in ("clarify", "blocked"):
            runs = _SemanticRuns(_semantic_payload(state))
            _wire_semantic_provider(monkeypatch, runs)
            with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
                response = client.post("/api/test_mundo/ai/ask", json={"prompt": "Hola"})
            assert response.status_code == 200
            envelope = response.json()
            assert envelope["state"] == state
            assert envelope["response"] == "Hermes semantic answer."
            legacy.assert_not_awaited()

    def test_guided_proposal_states_fail_closed_blocked(self, client: TestClient, monkeypatch):
        """require_confirmation/proposal_ready are NOT emitted hollow: without a
        typed continuation the guarded machinery cannot back a server-owned
        session/proposal, so the envelope fails closed to blocked."""
        for state in ("require_confirmation", "proposal_ready"):
            runs = _SemanticRuns(_semantic_payload(state))
            _wire_semantic_provider(monkeypatch, runs)
            with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
                response = client.post("/api/test_mundo/ai/ask", json={"prompt": "Hola"})
            assert response.status_code == 200
            envelope = response.json()
            assert envelope["state"] == "blocked"
            assert envelope["action"] == "blocked_explanation"
            assert envelope["attempts"] == 1
            assert "proposal" not in envelope and "digest" not in envelope
            legacy.assert_not_awaited()

    def test_exhausted_provider_fails_closed_blocked_no_write(self, client: TestClient, monkeypatch, tmp_path):
        canon_dir = api_server.MUNDOS_DIR / "test_mundo" / "lore"
        before = {p.name: p.read_bytes() for p in canon_dir.iterdir() if p.is_file()}
        runs = _SemanticRuns(
            {"state": "approve", "response": "go"},
            {"state": "execute", "response": "go"},
            {"state": "write", "response": "go"},
        )
        _wire_semantic_provider(monkeypatch, runs)
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": "Vuelca esto al canon"})
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "blocked"
        assert envelope["action"] == "blocked_explanation"
        assert envelope["attempts"] == 3
        assert envelope["unavailable"] is True
        legacy.assert_not_awaited()
        after = {p.name: p.read_bytes() for p in canon_dir.iterdir() if p.is_file()}
        assert after == before

    def test_canon_mutation_request_never_touches_canon(self, client: TestClient, monkeypatch):
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        original = target.read_bytes()
        runs = _SemanticRuns(_semantic_payload("proposal_ready", response="I will rewrite the canon."))
        _wire_semantic_provider(monkeypatch, runs)
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": "Modifica el canon"})
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "blocked"
        assert "proposal" not in envelope and "digest" not in envelope
        assert target.read_bytes() == original
        legacy.assert_not_awaited()

    def test_invalid_exhausted_provider_never_falls_back_to_lexical_chat(self, client: TestClient, monkeypatch):
        runs = _SemanticRuns(
            {"state": "approve", "response": "go"},
            {"state": "approve", "response": "go"},
            {"state": "approve", "response": "go"},
        )
        _wire_semantic_provider(monkeypatch, runs)
        with patch("api_server._run_hermes", new=AsyncMock(return_value="lexical answer")) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": "Hola"})
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "blocked"
        assert envelope["unavailable"] is True
        assert envelope["response"] != "lexical answer"
        legacy.assert_not_awaited()
        assert runs.starts == 3

    def test_semantic_decide_completes_before_any_classifier_on_ai_ask(self, client: TestClient, monkeypatch):
        """Hermes interprets before route_new_character_intent or any successor
        classifier. A lexical new-character prompt with an ``allow`` decision
        answers conversationally and never starts a guided handoff."""
        order = []
        runs = _SemanticRuns(_semantic_payload("allow"))
        provider = _wire_semantic_provider(monkeypatch, runs)
        original_decide = provider.decide

        async def recorded_decide(*args, **kwargs):
            order.append("semantic.decide")
            return await original_decide(*args, **kwargs)

        provider.decide = recorded_decide
        real_route = api_server.route_new_character_intent

        def recorded_route(*args, **kwargs):
            order.append("route_new_character_intent")
            return real_route(*args, **kwargs)

        monkeypatch.setattr(api_server, "route_new_character_intent", recorded_route)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        response = client.post(
            "/api/test_mundo/ai/ask",
            json={"prompt": "Un guerrero de las sombras", "session_id": "chat-1"},
        )
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "allow"
        assert envelope["response"] == "Hermes semantic answer."
        assert order == ["semantic.decide"]
        assert runs.starts == 1

    def test_ai_ask_authorized_context_reaches_hermes_before_decide(self, client: TestClient, monkeypatch):
        """Bounded authorized context {mundo,ficha,...} reaches decide(), never
        credentials, filesystem/write authority, or raw secrets."""
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        target.write_text("---\ntitle: Inicio\n---\nCuerpo del ficha\n", encoding="utf-8")
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={
                "prompt": "Hola", "section": "lore", "file_path": "00_inicio.md",
            })
        assert response.status_code == 200
        prompt = runs.requests[0].prompt
        assert "test_mundo" in prompt
        assert "Cuerpo del ficha" in prompt
        for forbidden in ("api_key", "sk-secret", "auth-token", "/etc/passwd",
                          '"digest"', '"authority"', '"path"'):
            assert forbidden not in prompt
        legacy.assert_not_awaited()
        assert runs.starts == 1

    def test_chat_valid_decision_preserves_compatibility_content(self, client: TestClient, monkeypatch):
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/chat", json={
                "messages": [{"role": "user", "content": "Hola"}],
                "mundo": "test_mundo",
            })
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "allow"
        assert body["content"] == "Hermes semantic answer."
        assert body["response"] == "Hermes semantic answer."
        assert body["action"] == "answer"
        assert body["unavailable"] is False
        legacy.assert_not_awaited()
        assert runs.starts == 1

    def test_chat_unwired_provider_fails_closed_without_leakage(self, client: TestClient):
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Hola"}]})
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "blocked"
        assert body["unavailable"] is True
        assert "content" not in body
        lowered = f"{body['response']} {body['action']}".lower()
        for term in ("hermes", "provider", "gateway", "http", "timeout", "quota",
                     "credits", "credential", "model", "error:"):
            assert term not in lowered
        legacy.assert_not_awaited()

    def test_chat_exhausted_hermes_blocks_with_zero_classifier(self, client: TestClient, monkeypatch):
        order = []
        runs = _SemanticRuns(
            {"state": "approve", "response": "go"},
            {"state": "approve", "response": "go"},
            {"state": "approve", "response": "go"},
        )
        provider = _wire_semantic_provider(monkeypatch, runs)
        original_decide = provider.decide

        async def recorded_decide(*args, **kwargs):
            order.append("semantic.decide")
            return await original_decide(*args, **kwargs)

        provider.decide = recorded_decide
        monkeypatch.setattr(
            api_server, "route_new_character_intent",
            lambda *a, **k: order.append("classifier") or None,
        )
        response = client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "Crea un personaje"}],
        })
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "blocked"
        assert body["attempts"] == 3
        assert body["unavailable"] is True
        assert order == ["semantic.decide"]
        assert runs.starts == 3


class TestSemanticActivitySSE:
    """PR 3 (task 3.1): the activity SSE boundary is Hermes-first and emits the
    authoritative ``semantic_decision`` event before compatible ``answer`` and
    final ``terminal`` events. Unavailable Hermes fails closed over HTTP 200
    with the ordered blocked semantic stream, zero action/session/proposal/
    write, and no provider/internal leakage. Guided decisions hand off (503)
    without any lexical classifier."""

    def test_activity_semantic_decision_precedes_answer_and_terminal(self, client, monkeypatch):
        class FakeAdapter:
            available = True
            capability = _activity_capability()

            def __init__(self):
                self.cancelled = []

            def start(self, request):
                return "run-1"

            async def events(self, run_id):
                yield {"event": "message.delta", "run_id": run_id, "delta": "safe answer"}
                yield {"event": "run.completed", "run_id": run_id, "output": "safe answer"}

            def cancel(self, run_id):
                self.cancelled.append(run_id)

        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        adapter = FakeAdapter()
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)
        response = client.post("/api/test_mundo/ai/ask/activity", json={"prompt": "Hola"})

        assert response.status_code == 200
        events = _parse_sse(response.text)
        kinds = [event["kind"] for event in events]
        assert kinds[0] == "semantic_decision"
        assert kinds.index("semantic_decision") < kinds.index("answer")
        assert kinds.index("semantic_decision") < kinds.index("terminal")
        assert kinds[-1] == "terminal"
        decision = events[0]
        assert decision["request_id"].startswith("activity-")
        assert decision["state"] == "allow"
        assert decision["action"] == "answer"
        assert decision["unavailable"] is False
        assert decision["continuation"] is None
        answer = next(event for event in events if event["kind"] == "answer")
        assert answer["response"] == "safe answer"
        assert adapter.cancelled == []
        assert runs.starts == 1

    def test_activity_unavailable_fails_closed_with_ordered_blocked_stream(self, client):
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/test_mundo/ai/ask/activity", json={"prompt": "Hola"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(response.text)
        kinds = [event["kind"] for event in events]
        assert kinds[0] == "semantic_decision"
        assert kinds[-1] == "terminal"
        decision = events[0]
        assert decision["state"] == "blocked"
        assert decision["action"] == "blocked_explanation"
        assert decision["unavailable"] is True
        assert decision["continuation"] is None
        answer = next(event for event in events if event["kind"] == "answer")
        assert answer["response"].startswith("El Asistente IA no pudo")
        terminal = events[-1]
        assert terminal["status"] == "failed"
        legacy.assert_not_awaited()
        lowered = response.text.lower()
        for term in ("hermes", "provider", "gateway", "http", "timeout", "quota",
                     "credits", "credential", "model", "error:"):
            assert term not in lowered

    def test_activity_guided_semantic_decision_hands_off_without_lexical_shortcut(
        self, client, monkeypatch
    ):
        order = []
        runs = _SemanticRuns(_continuation_semantic_payload("require_confirmation"))
        provider = _wire_semantic_provider(monkeypatch, runs)
        original_decide = provider.decide

        async def recorded_decide(*args, **kwargs):
            order.append("semantic.decide")
            return await original_decide(*args, **kwargs)

        provider.decide = recorded_decide
        monkeypatch.setattr(
            api_server, "route_new_character_intent",
            lambda *a, **k: order.append("route_new_character_intent") or None,
        )
        response = client.post(
            "/api/test_mundo/ai/ask/activity",
            json={"prompt": "Quiero crear un personaje"},
        )

        assert response.status_code == 503
        assert response.json()["code"] == "guided_handoff"
        assert order == ["semantic.decide"]
        assert runs.starts == 1


class TestSemanticSingleRunContinuation:
    """PR 2 continuation (task 2.3): one Hermes run backs guided/proposal states.

    require_confirmation and proposal_ready are REAL only when the same run
    supplies a typed continuation that the server routes through the existing
    guarded session / diskless proposal machinery. No second Hermes run is
    started; any missing backing, auth, world, graph, or validation failure
    fails the envelope closed to blocked with zero writes.
    """

    _NON_GUIDED_PROMPT = "Define el perfil de un ser que lo protege"
    _CONFIRM_PROMPT = "Quisiera que me propongas un compañero para ese mundo"

    def _wire_continuation(self, client, monkeypatch, *payloads):
        runs = _SemanticRuns(*payloads)
        _wire_semantic_provider(monkeypatch, runs)
        _principal(monkeypatch)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(api_server, "_GUIDED_PENDING_PROPOSALS", {})
        monkeypatch.setattr(
            api_server, "_named_reference_context",
            lambda _mundo, _prompt: ("", False, None),
        )
        return runs

    def test_proposal_ready_single_run_creates_diskless_proposal(self, client: TestClient, monkeypatch):
        runs = self._wire_continuation(client, monkeypatch, _continuation_semantic_payload("proposal_ready"))
        with patch("api_server._run_hermes", new=AsyncMock(return_value="unused")) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": self._NON_GUIDED_PROMPT})
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "proposal_ready"
        assert envelope["action"] == "show_proposal"
        assert envelope["guided"] is True
        assert envelope["guided_session_id"].startswith("guided-")
        assert envelope["guided_revision"] == 1
        assert envelope["target"] == "personajes/rhyz-s-wife.md"
        assert envelope["is_new_file"] is True
        assert re.fullmatch(r"[0-9a-f]{64}", envelope["proposed_digest"])
        assert hashlib.sha256(envelope["proposed_content"].encode("utf-8")).hexdigest() == envelope["proposed_digest"]
        assert envelope["proposal_id"].startswith("guided-proposal-")
        assert runs.starts == 1
        legacy.assert_not_awaited()
        pending = api_server._GUIDED_PENDING_PROPOSALS[envelope["proposal_id"]]
        assert pending["target"] == envelope["target"]
        assert pending["digest"] == envelope["proposed_digest"]
        assert pending["principal_id"] == "tester"
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "personajes").exists()

    def test_require_confirmation_single_run_begins_guarded_confirmation(self, client: TestClient, monkeypatch):
        runs = self._wire_continuation(client, monkeypatch, _continuation_semantic_payload("require_confirmation"))
        with patch("api_server._run_hermes", new=AsyncMock(return_value="unused")) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": self._CONFIRM_PROMPT})
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "require_confirmation"
        assert envelope["action"] == "request_confirmation"
        assert envelope["response"] == "¿Creo este personaje?"
        assert envelope["guided_session_id"].startswith("guided-")
        assert envelope["guided_revision"] == 1
        assert envelope["guided_state"]["phase"] == "confirmation"
        assert envelope["guided_state"]["pending_question"] == "¿Creo este personaje?"
        assert "proposal_id" not in envelope and "proposed_digest" not in envelope
        assert runs.starts == 1
        legacy.assert_not_awaited()
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "personajes").exists()

    def test_confirmation_state_answers_flow_through_guarded_machinery(self, client: TestClient, monkeypatch):
        runs = self._wire_continuation(
            client, monkeypatch,
            _continuation_semantic_payload("require_confirmation"),
            _semantic_payload("allow"),
        )
        started = client.post("/api/test_mundo/ai/ask", json={"prompt": self._CONFIRM_PROMPT}).json()
        sid, revision = started["guided_session_id"], started["guided_revision"]

        guided_calls = []

        async def provider(request, _token):
            guided_calls.append(request)
            return {
                "protocol_version": request.protocol_version,
                "request_id": request.request_id,
                "session_id": request.session_id,
                "outcome": "question",
                "question": "What drives them?",
            }

        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", provider)
        monkeypatch.setattr(api_server, "_GUIDED_CAPABILITIES", api_server.Capabilities(
            "guided-character-v1", True, True, True, 30000,
        ))
        with patch("api_server._run_hermes", new=AsyncMock(return_value="unused")) as legacy:
            confirmed = client.post("/api/test_mundo/ai/ask", json={
                "prompt": "sí", "session_id": "chat-1",
                "guided_session_id": sid, "guided_revision": revision,
            })
        assert confirmed.status_code == 200
        assert confirmed.json()["guided_state"]["phase"] == "conversation"
        assert len(guided_calls) == 1
        assert runs.starts == 2
        legacy.assert_not_awaited()

    def test_semantic_decide_precedes_typed_confirmation_parsing(self, client: TestClient, monkeypatch):
        """Typed confirmation is parsed as policy ONLY after a validated Hermes
        interpretation: confirmation_decision never decides whether Hermes runs."""
        order = []
        runs = _SemanticRuns(_semantic_payload("allow"))
        provider = _wire_semantic_provider(monkeypatch, runs)
        original_decide = provider.decide

        async def recorded_decide(*args, **kwargs):
            order.append("semantic.decide")
            return await original_decide(*args, **kwargs)

        provider.decide = recorded_decide
        _principal(monkeypatch)
        sessions = api_server.GuidedSessionStore()
        state = sessions.create("guided-confirm", "test_mundo", "tester")
        confirming = sessions.begin_confirmation(
            "guided-confirm", "tester", "Crea un personaje", "¿Sí o no?",
        )
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)
        monkeypatch.setattr(
            api_server, "_named_reference_context",
            lambda _mundo, _prompt: ("", False, None),
        )
        def recorded_confirmation(*args, **kwargs):
            order.append("confirmation_decision")
            # Return None (ambiguous) so the guarded confirmation re-prompts
            # without invoking the guided provider: the ordering proof only
            # needs confirmation_decision to run strictly after decide().
            return None

        monkeypatch.setattr(api_server, "confirmation_decision", recorded_confirmation)
        monkeypatch.setattr(api_server, "_GUIDED_PROVIDER", None)
        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "sí", "session_id": "chat-1",
            "guided_session_id": state.session_id,
            "guided_revision": confirming.revision,
        })
        assert response.status_code == 200
        assert order == ["semantic.decide", "confirmation_decision"]
        assert runs.starts == 1

    def test_semantic_guided_continuation_requires_auth(self, client: TestClient, monkeypatch):
        runs = _SemanticRuns(_continuation_semantic_payload("proposal_ready"))
        _wire_semantic_provider(monkeypatch, runs)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": self._NON_GUIDED_PROMPT})
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "blocked"
        assert envelope["action"] == "blocked_explanation"
        assert "proposal" not in envelope and "digest" not in envelope
        assert legacy.assert_not_awaited() or runs.starts == 1

    def test_malformed_continuation_fails_closed_no_write(self, client: TestClient, monkeypatch):
        runs = self._wire_continuation(client, monkeypatch, {
            "state": "proposal_ready",
            "response": "I will rewrite the canon.",
            "request_id": "request-1",
            "session_id": "chat-1",
            "guided": True,
            "continuation": {"outcome": "delta", "delta": {"target": "lore/00_inicio.md", "name": "X"}},
        })
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        original = target.read_bytes()
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": self._NON_GUIDED_PROMPT})
        envelope = response.json()
        assert envelope["state"] == "blocked"
        assert envelope["action"] == "blocked_explanation"
        assert envelope["attempts"] == 3
        assert "proposal" not in envelope and "digest" not in envelope
        assert target.read_bytes() == original
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "personajes").exists()
        assert api_server._GUIDED_PENDING_PROPOSALS == {}
        assert legacy.assert_not_awaited() or runs.starts == 3

    def test_continuation_fails_closed_when_graph_evidence_unavailable(self, client: TestClient, monkeypatch):
        runs = _SemanticRuns(_continuation_semantic_payload("proposal_ready"))
        _wire_semantic_provider(monkeypatch, runs)
        _principal(monkeypatch)
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", api_server.GuidedSessionStore())
        monkeypatch.setattr(api_server, "_named_reference_context", lambda _mundo, _prompt: ("", True, None))
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            response = client.post("/api/test_mundo/ai/ask", json={"prompt": self._NON_GUIDED_PROMPT})
        envelope = response.json()
        assert envelope["state"] == "blocked"
        assert envelope["action"] == "blocked_explanation"
        assert "proposal" not in envelope and "digest" not in envelope
        assert api_server._GUIDED_PENDING_PROPOSALS == {}
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "personajes").exists()
        legacy.assert_not_awaited()

    def test_semantic_proposal_stale_revision_is_rejected(self, client: TestClient, monkeypatch):
        self._wire_continuation(client, monkeypatch, _continuation_semantic_payload("proposal_ready"))
        created = client.post("/api/test_mundo/ai/ask", json={"prompt": self._NON_GUIDED_PROMPT}).json()
        sid = created["guided_session_id"]
        with patch("api_server._run_hermes", new=AsyncMock()) as legacy:
            stale = client.post("/api/test_mundo/ai/ask", json={
                "prompt": "un turno", "session_id": "chat-1",
                "guided_session_id": sid, "guided_revision": 0,
            })
        assert stale.status_code == 409
        assert stale.json()["code"] == "revision_conflict"
        legacy.assert_not_awaited()

    def test_semantic_proposal_accepts_through_existing_guarded_endpoint(self, client: TestClient, monkeypatch):
        self._wire_continuation(client, monkeypatch, _continuation_semantic_payload("proposal_ready"))
        created = client.post("/api/test_mundo/ai/ask", json={"prompt": self._NON_GUIDED_PROMPT}).json()
        sid, revision = created["guided_session_id"], created["guided_revision"]
        accepted = client.post("/api/test_mundo/guided-character/proposal/accept", json={
            "session_id": sid, "base_revision": revision, "key": "desire",
        })
        assert accepted.status_code == 200
        assert accepted.json()["candidate"]["accepted_canon"]["desire"]["certainty"] == "accepted"
        assert accepted.json()["revision"] == 2
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "personajes").exists()

    def test_semantic_created_session_inherits_guided_handoff(self, client: TestClient, monkeypatch):
        runs = self._wire_continuation(client, monkeypatch, _continuation_semantic_payload("proposal_ready"))
        created = client.post("/api/test_mundo/ai/ask", json={"prompt": self._NON_GUIDED_PROMPT}).json()
        handoff = client.post("/api/test_mundo/ai/ask/activity", json={
            "prompt": "x", "session_id": "chat-1",
            "guided_session_id": created["guided_session_id"],
            "guided_revision": created["guided_revision"],
        })
        assert handoff.status_code == 503
        assert handoff.json()["code"] == "guided_handoff"
        assert runs.starts == 1

    def test_musing_guided_intent_suggests_without_creating_session(self, client: TestClient, monkeypatch):
        """REQ-GFC-03: musing/absent intent yields a token-bound suggestion and
        creates no session; the single Hermes run is not repeated."""
        memory = api_server.ConversationMemoryStore(":memory:")
        monkeypatch.setattr(api_server, "_CONVERSATION_MEMORY", memory)
        sessions = api_server.GuidedSessionStore()
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)
        monkeypatch.setattr(api_server, "_GUIDED_PENDING_PROPOSALS", {})
        monkeypatch.setattr(api_server, "_named_reference_context", lambda _m, _p: ("", False, None))
        _principal(monkeypatch)
        runs = _SemanticRuns(
            _continuation_semantic_payload("require_confirmation", guided_explicitness="musing"),
        )
        _wire_semantic_provider(monkeypatch, runs)

        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": self._CONFIRM_PROMPT, "session_id": "consent-1",
        })
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["state"] == "require_confirmation"
        assert envelope["consent"] == "required"
        assert envelope["consent_token"].startswith("ct-")
        assert envelope["guided_explicitness"] == "musing"
        assert envelope["response"] == api_server.GUIDED_CONSENT_SUGGESTION_TEXT
        assert "guided_session_id" not in envelope
        assert "guided_revision" not in envelope
        assert "guided_state" not in envelope
        assert "proposal_id" not in envelope and "proposed_digest" not in envelope
        assert runs.starts == 1
        assert sessions._sessions == {}
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "personajes").exists()

    def test_imperative_guided_intent_carries_explicitness_and_auto_opens(self, client: TestClient, monkeypatch):
        """REQ-GFC-02: an explicit imperative keeps today's auto-open and the
        envelope carries the server-derived explicitness."""
        runs = self._wire_continuation(
            client, monkeypatch,
            _continuation_semantic_payload("require_confirmation", guided_explicitness="imperative"),
        )
        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": self._CONFIRM_PROMPT, "session_id": "chat-1",
        })
        assert response.status_code == 200
        envelope = response.json()
        assert envelope["guided_explicitness"] == "imperative"
        assert envelope["guided_session_id"].startswith("guided-")
        assert envelope["guided_state"]["phase"] == "confirmation"
        assert "consent" not in envelope
        assert runs.starts == 1

    def test_keeps_chatting_after_suggestion_declines_and_suppresses_repeat(self, client: TestClient, monkeypatch):
        """REQ-GFC-06: a suggestion left unaccepted is a session decline; later
        musing turns neither re-suggest nor open a session."""
        memory = api_server.ConversationMemoryStore(":memory:")
        monkeypatch.setattr(api_server, "_CONVERSATION_MEMORY", memory)
        sessions = api_server.GuidedSessionStore()
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", sessions)
        monkeypatch.setattr(api_server, "_GUIDED_PENDING_PROPOSALS", {})
        monkeypatch.setattr(api_server, "_named_reference_context", lambda _m, _p: ("", False, None))
        _principal(monkeypatch)
        runs = _SemanticRuns(
            _continuation_semantic_payload("require_confirmation", guided_explicitness="musing"),
            _semantic_payload("allow"),
            _continuation_semantic_payload("require_confirmation", guided_explicitness="musing"),
        )
        _wire_semantic_provider(monkeypatch, runs)

        first = client.post("/api/test_mundo/ai/ask", json={
            "prompt": self._CONFIRM_PROMPT, "session_id": "consent-2",
        }).json()
        assert first["consent"] == "required"
        assert memory.guided_consent_declined("consent-2", "test_mundo") is False

        # Keeps chatting: the next same-session turn is not an accept.
        second = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "gracias", "session_id": "consent-2",
        }).json()
        assert second["state"] == "allow"
        assert memory.guided_consent_declined("consent-2", "test_mundo") is True

        third = client.post("/api/test_mundo/ai/ask", json={
            "prompt": self._CONFIRM_PROMPT, "session_id": "consent-2",
        }).json()
        assert third["state"] == "allow"
        assert "consent" not in third and "consent_token" not in third
        assert "guided_session_id" not in third and "guided_state" not in third
        assert runs.starts == 3
        assert sessions._sessions == {}


class TestMundoValidation:
    """Audit 07-30 (item 13): every endpoint taking {mundo} must reject
    worlds that do not exist and block mundo-level traversal.

    ``%2e%2e`` is URL-encoded ``..`` — plain ``/api/../...`` is normalized
    away by clients, but encoded dots reach the endpoint verbatim, so the
    server must validate the mundo param itself. Established patterns:
    mutations raise 404 "Mundo no encontrado"; GET/list endpoints keep
    their soft-empty contract.
    """

    ENC_DOTS = "%2e%2e"

    def _tmp_root(self) -> Path:
        return api_server.MUNDOS_DIR.parent

    # -- world existence: GET/list keep their soft contract ------------------

    def test_tree_missing_mundo_returns_empty(self, client: TestClient):
        assert client.get("/api/mundo_fantasma/lore/tree").json() == []

    def test_get_file_missing_mundo_soft_error(self, client: TestClient):
        resp = client.get("/api/mundo_fantasma/lore/file?path=a.md")
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_list_media_missing_mundo_empty(self, client: TestClient):
        resp = client.get("/api/mundo_fantasma/media/list")
        assert resp.json() == {"images": [], "total": 0}

    def test_graph_search_missing_mundo_empty(self, client: TestClient):
        assert client.get("/api/mundo_fantasma/graph/search?q=a").json() == []

    def test_graph_status_missing_mundo_zeroed(self, client: TestClient):
        assert client.get("/api/mundo_fantasma/graph/status").json() == {
            "node_count": 0,
            "link_count": 0,
            "indexed": False,
        }

    # -- world existence: mutations raise 404 --------------------------------

    def test_diff_missing_mundo_404(self, client: TestClient):
        resp = client.post("/api/mundo_fantasma/lore/diff?path=a.md", json={"content": "x"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_diff_invalid_section_400(self, client: TestClient):
        resp = client.post("/api/test_mundo/wiki/diff?path=a.md", json={"content": "x"})
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Sección inválida"

    def test_delete_missing_mundo_404(self, client: TestClient):
        resp = client.delete("/api/mundo_fantasma/lore/file?path=a.md")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_move_missing_mundo_404(self, client: TestClient):
        resp = client.post("/api/mundo_fantasma/move", json={"from": "lore/a.md", "to": "lore/b.md"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_duplicate_missing_mundo_404(self, client: TestClient):
        resp = client.post("/api/mundo_fantasma/duplicate", json={"from": "lore/a.md"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    def test_upload_missing_mundo_404_never_creates_world(
        self, client: TestClient, jpeg_bytes: bytes
    ):
        resp = client.post(
            "/api/mundo_fantasma/media/upload",
            files={"file": ("x.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"
        assert not (api_server.MUNDOS_DIR / "mundo_fantasma").exists()

    def test_delete_media_missing_mundo_404(self, client: TestClient):
        resp = client.delete("/api/mundo_fantasma/media?path=wiki/media/x.jpg")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Mundo no encontrado"

    # -- mundo-level traversal (%2e%2e = '..') --------------------------------

    def test_tree_mundo_traversal_empty_never_leaks(self, client: TestClient):
        outside = self._tmp_root() / "lore"
        outside.mkdir(exist_ok=True)
        (outside / "secreto.md").write_text("# SECRETO\n", encoding="utf-8")
        resp = client.get(f"/api/{self.ENC_DOTS}/lore/tree")
        assert resp.status_code == 200
        assert all(n["name"] != "secreto.md" for n in resp.json())

    def test_save_mundo_traversal_404_never_writes(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        outside = self._tmp_root() / "lore"
        outside.mkdir(exist_ok=True)
        resp = client.post(
            f"/api/{self.ENC_DOTS}/lore/save?path=pwned.md", json={"content": "x"}
        )
        assert resp.status_code == 404
        assert not (outside / "pwned.md").exists()

    def test_create_mundo_traversal_404_never_writes(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = client.post(
            f"/api/{self.ENC_DOTS}/lore/create?path=pwned.md", json={"content": "x"}
        )
        assert resp.status_code == 404
        assert not (self._tmp_root() / "lore" / "pwned.md").exists()

    def test_status_mundo_traversal_404_never_rewrites(self, client: TestClient):
        outside = self._tmp_root() / "lore"
        outside.mkdir(exist_ok=True)
        (outside / "secreto.md").write_text("# SECRETO\n", encoding="utf-8")
        resp = client.post(
            f"/api/{self.ENC_DOTS}/lore/status",
            json={"path": "secreto.md", "status": "stable"},
        )
        assert resp.status_code == 404
        saved = (outside / "secreto.md").read_text(encoding="utf-8")
        assert "status:" not in saved

    def test_delete_mundo_traversal_404_never_moves(self, client: TestClient):
        outside = self._tmp_root() / "lore"
        outside.mkdir(exist_ok=True)
        (outside / "secreto.md").write_text("# SECRETO\n", encoding="utf-8")
        resp = client.delete(f"/api/{self.ENC_DOTS}/lore/file?path=secreto.md")
        assert resp.status_code == 404
        assert (outside / "secreto.md").exists()

    def test_upload_mundo_traversal_404_never_writes(
        self, client: TestClient, jpeg_bytes: bytes
    ):
        resp = client.post(
            f"/api/{self.ENC_DOTS}/media/upload",
            files={"file": ("y.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert resp.status_code == 404
        assert not (self._tmp_root() / "wiki" / "media" / "y.jpg").exists()

    def test_delete_media_mundo_traversal_404_never_deletes(
        self, client: TestClient, jpeg_bytes: bytes
    ):
        outside = self._tmp_root() / "wiki" / "media"
        outside.mkdir(parents=True, exist_ok=True)
        (outside / "z.jpg").write_bytes(jpeg_bytes)
        resp = client.delete(f"/api/{self.ENC_DOTS}/media?path=wiki/media/z.jpg")
        assert resp.status_code == 404
        assert (outside / "z.jpg").exists()

    def test_get_media_mundo_traversal_400(self, client: TestClient):
        resp = client.get(f"/api/{self.ENC_DOTS}/media?path=wiki/media/foto.jpg")
        assert resp.status_code == 400

    def test_graph_search_mundo_traversal_empty(self, client: TestClient):
        assert client.get(f"/api/{self.ENC_DOTS}/graph/search?q=a").json() == []

    def test_graph_entity_mundo_traversal_error(self, client: TestClient):
        resp = client.get(f"/api/{self.ENC_DOTS}/graph/entity?name=X")
        assert "error" in resp.json()


class TestTrashList:
    """GET /api/{mundo}/papelera — list trash entries across all sections."""

    def _papelera(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / ".papelera"

    def test_list_empty_returns_empty(self, client: TestClient):
        resp = client.get("/api/test_mundo/papelera")
        assert resp.status_code == 200
        assert resp.json() == {"entries": []}

    def test_list_after_delete_shows_entry(self, client: TestClient):
        client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        entries = client.get("/api/test_mundo/papelera").json()["entries"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["original_path"] == "00_inicio.md"
        assert entry["kind"] == "file"
        assert entry["deleted_at"].endswith("Z")

    def test_list_includes_section_and_entry_id(self, client: TestClient):
        client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        personajes = api_server.MUNDOS_DIR / "test_mundo" / "personajes"
        personajes.mkdir(parents=True)
        (personajes / "p.md").write_text("# P\n", encoding="utf-8")
        client.delete("/api/test_mundo/personajes/file?path=p.md")

        entries = client.get("/api/test_mundo/papelera").json()["entries"]
        by_section = {e["section"]: e for e in entries}
        assert set(by_section) == {"lore", "personajes"}
        for eid in (by_section["lore"]["entry_id"], by_section["personajes"]["entry_id"]):
            assert re.fullmatch(r"[0-9a-f]{12}", eid)

    def test_list_excludes_corrupt_meta(self, client: TestClient):
        client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        # Entry dir whose meta.json is not valid JSON must be skipped by the list
        bogus = self._papelera() / "lore" / "deadbeefdead"
        bogus.mkdir(parents=True)
        (bogus / "meta.json").write_text("{not json", encoding="utf-8")

        entries = client.get("/api/test_mundo/papelera").json()["entries"]
        ids = [e["entry_id"] for e in entries]
        assert "deadbeefdead" not in ids
        assert len(entries) == 1


class TestTrashRestore:
    """POST /api/{mundo}/papelera/restore — move an entry back to its path."""

    def _papelera(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / ".papelera"

    def test_restore_roundtrip_restores_file(self, client: TestClient):
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        resp = client.post(
            "/api/test_mundo/papelera/restore",
            json={"entry_id": entry_id, "section": "lore"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"restored_to": "lore/00_inicio.md", "entry_id": entry_id}
        # File back with original content, entry dir gone
        restored = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        assert restored.read_text(encoding="utf-8").startswith("---")
        assert not (self._papelera() / "lore" / entry_id).exists()

    def test_restore_to_dest_collision_dedups(self, client: TestClient):
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        # Original path reoccupied with different content -> restore dedups
        (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").write_text(
            "nuevo contenido\n", encoding="utf-8")

        resp = client.post(
            "/api/test_mundo/papelera/restore",
            json={"entry_id": entry_id, "section": "lore"},
        )
        assert resp.status_code == 200
        assert resp.json()["restored_to"] == "lore/00_inicio-copia.md"
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio-copia.md").read_text(
            encoding="utf-8").startswith("---")
        # Occupier untouched
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").read_text(
            encoding="utf-8") == "nuevo contenido\n"

    def test_restore_missing_entry_404(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/papelera/restore",
            json={"entry_id": "000000000000", "section": "lore"},
        )
        assert resp.status_code == 404
        assert "no encontrada" in resp.json()["detail"].lower()

    def test_restore_missing_section_400(self, client: TestClient):
        resp = client.post(
            "/api/test_mundo/papelera/restore",
            json={"entry_id": "000000000000", "section": "wiki"},
        )
        assert resp.status_code == 400
        assert "sección requerida" in resp.json()["detail"].lower()

    def test_restore_dir_roundtrip(self, client: TestClient):
        ciudades = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "ciudades"
        ciudades.mkdir()
        (ciudades / "planos").mkdir()
        (ciudades / "planos" / "x.md").write_text("# X\n", encoding="utf-8")
        (ciudades / "alfa.md").write_text("# Alfa\n", encoding="utf-8")
        entry_id = client.delete("/api/test_mundo/lore/file?path=ciudades").json()["entry_id"]

        resp = client.post(
            "/api/test_mundo/papelera/restore",
            json={"entry_id": entry_id, "section": "lore"},
        )
        assert resp.status_code == 200
        assert resp.json()["restored_to"] == "lore/ciudades"
        restored = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "ciudades"
        assert (restored / "planos" / "x.md").read_text(encoding="utf-8") == "# X\n"
        assert (restored / "alfa.md").read_text(encoding="utf-8") == "# Alfa\n"
        assert not (self._papelera() / "lore" / entry_id).exists()


class TestTrashPurge:
    """DELETE /api/{mundo}/papelera — remove one entry or empty the whole bin."""

    def _papelera(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / ".papelera"

    def test_purge_individual_removes_entry(self, client: TestClient):
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        resp = client.delete(f"/api/test_mundo/papelera?entry_id={entry_id}&section=lore")
        assert resp.status_code == 200
        assert resp.json() == {"purged": entry_id}
        assert not (self._papelera() / "lore" / entry_id).exists()
        assert client.get("/api/test_mundo/papelera").json() == {"entries": []}

    def test_purge_missing_entry_404(self, client: TestClient):
        resp = client.delete("/api/test_mundo/papelera?entry_id=000000000000&section=lore")
        assert resp.status_code == 404
        assert "no encontrada" in resp.json()["detail"].lower()

    def test_purge_all_empties_bin(self, client: TestClient):
        client.delete("/api/test_mundo/lore/file?path=00_inicio.md")
        client.delete("/api/test_mundo/lore/file?path=subdir/detalle.md")
        resp = client.delete("/api/test_mundo/papelera")
        assert resp.status_code == 200
        assert resp.json() == {"purged": "all", "entries": 2}
        assert not self._papelera().exists()
        assert client.get("/api/test_mundo/papelera").json() == {"entries": []}

    def test_purge_all_when_empty_returns_zero(self, client: TestClient):
        resp = client.delete("/api/test_mundo/papelera")
        assert resp.status_code == 200
        assert resp.json() == {"purged": "all", "entries": 0}


class TestTrashTTL:
    """Item 8 Phase 1: lazy TTL purge (30 days) triggered by GET /papelera.

    Boundary: an entry is expired when ``deleted_at < now - 30d`` (strictly
    less). Equal to the threshold → kept. Malformed/missing meta.json is
    skipped, never crashes the purge nor the list.
    """

    def _papelera(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / ".papelera"

    def _patch_deleted_at(self, entry_dir: Path, deleted_at: datetime) -> None:
        """Rewrite meta.json's deleted_at as ISO-8601 UTC ending in 'Z'."""
        meta_path = entry_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["deleted_at"] = deleted_at.isoformat().replace("+00:00", "Z")
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    def test_ttl_purges_expired_on_list(self, client: TestClient):
        """deleted_at 31 days ago → purged before the list is returned."""
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        entry_dir = self._papelera() / "lore" / entry_id
        self._patch_deleted_at(entry_dir, datetime.now(timezone.utc) - timedelta(days=31))

        resp = client.get("/api/test_mundo/papelera")
        ids = [e["entry_id"] for e in resp.json()["entries"]]
        assert entry_id not in ids
        assert not entry_dir.exists()
        assert resp.json().get("purged") == 1

    def test_ttl_preserves_fresh_on_list(self, client: TestClient):
        """deleted_at = now (default delete flow) → kept."""
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        entry_dir = self._papelera() / "lore" / entry_id

        resp = client.get("/api/test_mundo/papelera")
        ids = [e["entry_id"] for e in resp.json()["entries"]]
        assert entry_id in ids
        assert entry_dir.exists()
        assert resp.json().get("purged") is None

    def test_ttl_boundary_exactly_30_days(self, client: TestClient, monkeypatch: pytest.MonkeyPatch):
        """Boundary (MANDATORY): deleted_at == now - 30d exactly is KEPT.

        Expired means ``deleted_at < threshold`` (strictly). At exactly 30
        days the entry survives; at 30 days + 1 second it is purged. Time
        is frozen so the purge threshold matches the written value exactly,
        making the equality branch deterministic.
        """
        frozen = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        class _FrozenDateTime(api_server.datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen

        monkeypatch.setattr(api_server, "datetime", _FrozenDateTime)

        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        entry_dir = self._papelera() / "lore" / entry_id
        self._patch_deleted_at(entry_dir, frozen - timedelta(days=30))

        resp = client.get("/api/test_mundo/papelera")
        ids = [e["entry_id"] for e in resp.json()["entries"]]
        assert entry_id in ids
        assert entry_dir.exists()
        assert resp.json().get("purged") is None

    def test_ttl_malformed_meta_skipped(self, client: TestClient):
        """Unreadable meta.json → entry skipped (kept), no crash, nothing purged."""
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        entry_dir = self._papelera() / "lore" / entry_id
        (entry_dir / "meta.json").write_text("{not json", encoding="utf-8")

        resp = client.get("/api/test_mundo/papelera")
        assert resp.status_code == 200
        assert entry_dir.exists()
        assert resp.json().get("purged") is None

    def test_ttl_missing_meta_skipped(self, client: TestClient):
        """Entry dir with NO meta.json → skipped (kept), no crash."""
        entry_id = client.delete("/api/test_mundo/lore/file?path=00_inicio.md").json()["entry_id"]
        entry_dir = self._papelera() / "lore" / entry_id
        (entry_dir / "meta.json").unlink()

        resp = client.get("/api/test_mundo/papelera")
        assert resp.status_code == 200
        assert entry_dir.exists()
        assert resp.json().get("purged") is None


class TestFileRevision:
    """Slice 1A (task 1.1): GET /api/{mundo}/{section}/file returns
    ``revision`` = SHA-256 of the file's exact bytes on disk.

    The revision fingerprints raw bytes — never the newline-normalized text
    returned as ``content`` — so a future editor can detect stale bases
    before confirming a write.
    """

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def test_get_file_returns_sha256_revision(self, client: TestClient):
        resp = client.get("/api/test_mundo/lore/file?path=00_inicio.md")
        assert resp.status_code == 200
        body = resp.json()
        assert "revision" in body
        assert len(body["revision"]) == 64
        expected = hashlib.sha256((self._lore() / "00_inicio.md").read_bytes()).hexdigest()
        assert body["revision"] == expected
        assert body["content"].startswith("---")
        assert isinstance(body["size"], int) and body["size"] > 0

    def test_revision_tracks_content_change(self, client: TestClient):
        target = self._lore() / "00_inicio.md"
        r1 = client.get("/api/test_mundo/lore/file?path=00_inicio.md").json()["revision"]
        target.write_text("# Cambiado\n", encoding="utf-8")
        r2 = client.get("/api/test_mundo/lore/file?path=00_inicio.md").json()["revision"]
        assert r1 != r2
        # Hash of the exact on-disk bytes (text writes may translate newlines).
        assert r2 == hashlib.sha256(target.read_bytes()).hexdigest()

    def test_revision_hashes_exact_bytes_not_normalized_text(self, client: TestClient):
        """CRLF file: read_text() normalizes line endings, but the revision
        must fingerprint the exact bytes on disk."""
        target = self._lore() / "crlf.md"
        target.write_bytes(b"# CRLF\r\nsegunda\r\n")
        body = client.get("/api/test_mundo/lore/file?path=crlf.md").json()
        assert body["revision"] == hashlib.sha256(b"# CRLF\r\nsegunda\r\n").hexdigest()
        # Sanity: the text layer normalizes, the revision layer must not.
        assert "\r" not in body["content"]

    def test_missing_file_keeps_soft_error_contract(self, client: TestClient):
        resp = client.get("/api/test_mundo/lore/file?path=no_existe.md")
        assert resp.status_code == 200
        assert "error" in resp.json()
        assert "revision" not in resp.json()


class TestReadPathAuthorization:
    """Slice 1A (tasks 1.3-1.4): centralized world/section/path authorization
    on read and proposal-adjacent boundaries.

    Traversal, sibling-world prefix collisions, symlink escapes, invalid
    sections, and internal ``.papelera``/``.history`` targets are all denied
    through the shared resolver — with zero disclosure and zero mutation.
    """

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def _assert_soft_denial(self, resp, marker: str) -> None:
        """get_file denies through its soft-error envelope (no disclosure)."""
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body
        assert marker not in json.dumps(body)

    def test_traversal_read_denied_with_zero_mutation(self, client: TestClient, tmp_path):
        escape = tmp_path / "mundos" / "secrets.txt"
        escape.write_text("TOP SECRET\n", encoding="utf-8")
        resp = client.get("/api/test_mundo/lore/file?path=../../secrets.txt")
        self._assert_soft_denial(resp, "TOP SECRET")
        # Zero mutation: the escape target is untouched and no file appeared
        # inside the world.
        assert escape.read_text(encoding="utf-8") == "TOP SECRET\n"
        assert not (self._lore() / "secrets.txt").exists()

    def test_sibling_world_prefix_collision_denied(self, client: TestClient):
        """The old weak ``startswith(root)`` check treats
        ``mundos/test_mundo2/...`` as a child of ``mundos/test_mundo``
        (string prefix). The centralized resolver must reject the sibling."""
        sibling = api_server.MUNDOS_DIR / "test_mundo2" / "lore"
        sibling.mkdir(parents=True)
        (sibling / "x.md").write_text("SIBLING SECRET\n", encoding="utf-8")
        resp = client.get("/api/test_mundo/lore/file?path=../../test_mundo2/lore/x.md")
        self._assert_soft_denial(resp, "SIBLING SECRET")
        # Zero mutation: sibling untouched.
        assert (sibling / "x.md").read_text(encoding="utf-8") == "SIBLING SECRET\n"

    def test_symlink_escape_read_denied(self, client: TestClient, tmp_path):
        outside = tmp_path / "outside.md"
        outside.write_text("OUTSIDE SECRET\n", encoding="utf-8")
        link = self._lore() / "escape.md"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("symlinks not permitted on this platform")
        try:
            resp = client.get("/api/test_mundo/lore/file?path=escape.md")
            self._assert_soft_denial(resp, "OUTSIDE SECRET")
            assert outside.read_text(encoding="utf-8") == "OUTSIDE SECRET\n"
        finally:
            if link.is_symlink():
                link.unlink()

    def test_papelera_target_denied(self, client: TestClient):
        trashed = api_server.MUNDOS_DIR / "test_mundo" / ".papelera" / "lore" / "x.md"
        trashed.parent.mkdir(parents=True)
        trashed.write_text("TRASHED SECRET\n", encoding="utf-8")
        for p in ("../.papelera/lore/x.md", ".papelera/lore/x.md"):
            resp = client.get(f"/api/test_mundo/lore/file?path={p}")
            self._assert_soft_denial(resp, "TRASHED SECRET")

    def test_history_target_denied(self, client: TestClient):
        snap = api_server.MUNDOS_DIR / "test_mundo" / ".history" / "lore" / "x.md"
        snap.parent.mkdir(parents=True)
        snap.write_text("SNAPSHOT SECRET\n", encoding="utf-8")
        for p in ("../.history/lore/x.md", ".history/lore/x.md"):
            resp = client.get(f"/api/test_mundo/lore/file?path={p}")
            self._assert_soft_denial(resp, "SNAPSHOT SECRET")

    def test_invalid_section_denied(self, client: TestClient):
        resp = client.get("/api/test_mundo/wiki/file?path=x.md")
        assert resp.status_code == 200
        body = resp.json()
        # Denied via the soft-error envelope: no content, no revision —
        # only the client's own requested path may be echoed back.
        assert "error" in body
        assert "revision" not in body
        assert "content" not in body

    def test_mundo_traversal_read_denied_never_leaks(self, client: TestClient, tmp_path):
        outside = tmp_path / "lore"
        outside.mkdir(exist_ok=True)
        (outside / "secreto.md").write_text("# SECRETO\n", encoding="utf-8")
        resp = client.get("/api/%2e%2e/lore/file?path=secreto.md")
        self._assert_soft_denial(resp, "SECRETO")

    def test_ai_ask_traversal_never_leaks_content(self, client: TestClient, tmp_path, monkeypatch):
        """Proposal-adjacent read: ai/ask must not inject the content of an
        escaped target into the Hermes semantic prompt."""
        escape = tmp_path / "mundos" / "secrets.md"
        escape.write_text("AI LEAK SECRET\n", encoding="utf-8")
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        with patch("api_server._run_hermes", new=AsyncMock(return_value="ok")) as mock_run:
            resp = client.post(
                "/api/test_mundo/ai/ask",
                json={"prompt": "Hola", "section": "lore", "file_path": "../../secrets.md"},
            )
        assert resp.status_code == 200
        sent = runs.requests[0].prompt
        assert "AI LEAK SECRET" not in sent
        assert escape.read_text(encoding="utf-8") == "AI LEAK SECRET\n"
        mock_run.assert_not_awaited()


class TestEditPrincipalSeam:
    """Slice 1A (task 1.2): trusted EditPrincipal seam.

    Fails closed until a deployment supplies trusted auth/session middleware,
    and never promotes caller-supplied identity (headers/body) to a principal.
    """

    def test_resolve_principal_fails_closed_by_default(self):
        assert api_server._resolve_principal(None) is None

    def test_resolve_principal_ignores_client_supplied_identity(self):
        class _FakeRequest:
            def __init__(self, headers: dict):
                self.headers = headers

        req = _FakeRequest({
            "x-edit-principal": "admin",
            "x-user": "alice",
            "authorization": "Bearer forged-token",
        })
        assert api_server._resolve_principal(req) is None

    def test_edit_principal_requires_id(self):
        with pytest.raises(ValueError):
            api_server.EditPrincipal("")
        with pytest.raises(ValueError):
            api_server.EditPrincipal("   ")
        p = api_server.EditPrincipal("session-42")
        assert p.id == "session-42"
        assert p.label == ""

    def test_seam_pluggable_for_deployment_middleware(self, monkeypatch: pytest.MonkeyPatch):
        """Once a deployment wires trusted middleware, the seam returns an
        EditPrincipal — proving the plug contract for the confirmation gate
        (slice 1B) and for fail-closed callers."""
        def fake_middleware(request):
            return api_server.EditPrincipal("session-42", label="deployment-user")

        monkeypatch.setattr(api_server, "_resolve_principal", fake_middleware)
        principal = api_server._resolve_principal(object())
        assert isinstance(principal, api_server.EditPrincipal)
        assert principal.id == "session-42"
        assert principal.label == "deployment-user"


class TestLocalDevelopmentAuth:
    """Explicit loopback-only session provider for local editing tests."""

    def test_disabled_mode_is_visible_and_remains_fail_closed(self, client: TestClient):
        status = client.get("/api/auth/local-dev/session")
        assert status.status_code == 200
        assert status.json() == {
            "mode": "disabled",
            "enabled": False,
            "authenticated": False,
            "label": None,
        }
        assert client.post("/api/auth/local-dev/session").status_code == 403
        assert client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={"edit_id": "e1", "base_revision": "0" * 64, "proposed_content": "x"},
        ).status_code == 401
        assert client.post(
            "/api/test_mundo/lore/save?path=00_inicio.md",
            json={"content": "x"},
        ).status_code == 401

    def test_loopback_start_status_logout_and_cookie_contract(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")

        started = client.post(
            "/api/auth/local-dev/session",
            json={"principal_id": "caller-controlled"},
        )
        assert started.status_code == 200
        assert started.json() == {
            "mode": "local-dev",
            "enabled": True,
            "authenticated": True,
            "label": "Local development user",
        }
        assert "token" not in started.json()
        assert "principal_id" not in started.json()
        cookie = started.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=lax" in cookie

        assert client.get("/api/auth/local-dev/session").json()["authenticated"] is True
        confirmation, base_revision = _confirm(client, "00_inicio.md", "# Local edit\n")
        assert confirmation["token"]
        saved = _gated_write(client, "00_inicio.md", "# Local edit\n", confirmation, base_revision)
        assert saved.status_code == 200

        history = client.get("/api/test_mundo/history?path=lore/00_inicio.md")
        assert history.status_code == 200
        entry = history.json()["entries"][0]
        current_revision = hashlib.sha256(
            (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").read_bytes()
        ).hexdigest()
        restore_confirmation = client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={
                "edit_id": "restore-1",
                "kind": "restore",
                "base_revision": current_revision,
                "snapshot_id": entry["snapshot_id"],
                "proposed_content": entry["content"],
            },
        )
        assert restore_confirmation.status_code == 200
        restored = client.post(
            "/api/test_mundo/history/restore",
            json={
                "path": "lore/00_inicio.md",
                "snapshot_id": entry["snapshot_id"],
                "edit_id": "restore-1",
                "base_revision": current_revision,
                "content": entry["content"],
                "proposed_digest": restore_confirmation.json()["proposed_digest"],
                "token": restore_confirmation.json()["token"],
            },
        )
        assert restored.status_code == 200

        logged_out = client.delete("/api/auth/local-dev/session")
        assert logged_out.status_code == 200
        assert logged_out.json()["authenticated"] is False
        assert client.get("/api/auth/local-dev/session").json()["authenticated"] is False
        assert client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={"edit_id": "e2", "base_revision": "0" * 64, "proposed_content": "x"},
        ).status_code == 401

    def test_non_loopback_clients_cannot_start_use_or_logout(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
        non_loopback = TestClient(api_server.app, client=("192.0.2.10", 50001))

        assert non_loopback.post("/api/auth/local-dev/session").status_code == 403
        assert non_loopback.get("/api/auth/local-dev/session").status_code == 403
        assert non_loopback.delete("/api/auth/local-dev/session").status_code == 403
        assert client.get("/api/auth/local-dev/session").status_code == 200

    def test_confirmation_and_save_are_bound_to_the_issuing_session(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
        first = TestClient(api_server.app, client=("127.0.0.1", 50002))
        second = TestClient(api_server.app, client=("127.0.0.1", 50003))
        assert first.post("/api/auth/local-dev/session").status_code == 200
        assert second.post("/api/auth/local-dev/session").status_code == 200

        confirmation, base_revision = _confirm(first, "00_inicio.md", "# Bound edit\n")
        response = _gated_write(second, "00_inicio.md", "# Bound edit\n", confirmation, base_revision)
        assert response.status_code == 403
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md").read_text(
            encoding="utf-8"
        ).startswith("---")


class TestConfirmationStore:
    """Slice 1B (tasks 1.5 + 2.2): hashed, single-use, short-TTL confirmations."""

    def test_confirmation_requires_principal(self, client: TestClient):
        resp = client.post("/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
                           json={"edit_id": "e1", "base_revision": "0" * 64, "proposed_content": "x"})
        assert resp.status_code == 401

    def test_issue_returns_token_and_proposed_digest(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        conf, _ = _confirm(client, "00_inicio.md", "# Nuevo\n")
        assert conf["token"] and conf["expires_at"]
        assert conf["proposed_digest"] == hashlib.sha256("# Nuevo\n".encode()).hexdigest()
        # Stored hashed only: the raw token never appears as a store key.
        assert conf["token"] not in api_server._confirmation_store
        assert api_server._hash_token(conf["token"]) in api_server._confirmation_store

    def test_confirm_stale_base_409_zero_mutation(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        resp = client.post("/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
                           json={"edit_id": "e1", "base_revision": "0" * 64, "proposed_content": "x"})
        assert resp.status_code == 409
        assert target.read_text(encoding="utf-8").startswith("---")

    def test_expired_token_rejected(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        conf, base_rev = _confirm(client, "00_inicio.md", "# Vencido\n")
        api_server._confirmation_store[api_server._hash_token(conf["token"])][
            "expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        resp = _gated_write(client, "00_inicio.md", "# Vencido\n", conf, base_rev)
        assert resp.status_code == 403
        assert (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
                ).read_text(encoding="utf-8").startswith("---")

    def test_mismatched_edit_id_rejected(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        conf, base_rev = _confirm(client, "00_inicio.md", "# A\n", edit_id="eA")
        resp = _gated_write(client, "00_inicio.md", "# A\n", conf, base_rev, edit_id="eB")
        assert resp.status_code == 403

    def test_mismatched_principal_rejected(self, client: TestClient, monkeypatch):
        _principal(monkeypatch, pid="alice")
        conf, base_rev = _confirm(client, "00_inicio.md", "# A\n")
        _principal(monkeypatch, pid="bob")
        resp = _gated_write(client, "00_inicio.md", "# A\n", conf, base_rev)
        assert resp.status_code == 403


class TestGatedPersistence:
    """Slice 1B (task 2.1): save/create fail closed without valid proof."""

    def test_save_without_principal_401(self, client: TestClient):
        resp = client.post("/api/test_mundo/lore/save?path=00_inicio.md",
                           json={"content": "x", "edit_id": "e1", "token": "t",
                                 "proposed_digest": "0" * 64, "base_revision": "0" * 64})
        assert resp.status_code == 401

    def test_save_missing_token_400_zero_mutation(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        before = target.read_bytes()
        resp = client.post("/api/test_mundo/lore/save?path=00_inicio.md",
                           json={"content": "# HACKED\n", "edit_id": "e1",
                                 "base_revision": hashlib.sha256(before).hexdigest()})
        assert resp.status_code == 400
        assert target.read_bytes() == before

    def test_save_success_writes(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        conf, base_rev = _confirm(client, "00_inicio.md", "# Editado\n")
        resp = _gated_write(client, "00_inicio.md", "# Editado\n", conf, base_rev)
        assert resp.status_code == 200
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        assert target.read_text(encoding="utf-8") == "# Editado\n"

    def test_save_stale_base_409_zero_mutation(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        conf, base_rev = _confirm(client, "00_inicio.md", "# A\n")
        target.write_text("# Cambio externo\n", encoding="utf-8")
        resp = _gated_write(client, "00_inicio.md", "# A\n", conf, base_rev)
        assert resp.status_code == 409
        assert "base" in resp.json()["detail"].lower()
        assert target.read_text(encoding="utf-8") == "# Cambio externo\n"

    def test_save_replay_token_403_zero_mutation(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"
        conf, base_rev = _confirm(client, "00_inicio.md", "# A\n")
        assert _gated_write(client, "00_inicio.md", "# A\n", conf, base_rev).status_code == 200
        new_base = hashlib.sha256(target.read_bytes()).hexdigest()
        replay = _gated_write(client, "00_inicio.md", "# A\n", conf, new_base)
        assert replay.status_code == 403  # token consumed by the first save
        assert target.read_text(encoding="utf-8") == "# A\n"

    def test_create_without_token_400_zero_mutation(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "nuevo.md"
        resp = client.post("/api/test_mundo/lore/create?path=nuevo.md",
                           json={"content": "# N\n", "edit_id": "e1"})
        assert resp.status_code == 400
        assert not target.exists()


class TestAtomicReplace:
    """Slice 1C (task 2.3): atomic same-dir replace + per-target lock +
    snapshot seam, with no temp leftovers and zero mutation on failure."""

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def _no_temps(self) -> list[str]:
        return [p.name for p in self._lore().iterdir() if p.name.endswith(".tmp")]

    def test_success_replaces_content_and_leaves_no_temp(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        conf, base_rev = _confirm(client, "00_inicio.md", "# Editado\n")
        resp = _gated_write(client, "00_inicio.md", "# Editado\n", conf, base_rev)
        assert resp.status_code == 200
        target = self._lore() / "00_inicio.md"
        assert target.read_text(encoding="utf-8") == "# Editado\n"
        assert self._no_temps() == []

    def test_replace_failure_cleans_temp_target_intact(self, client: TestClient, monkeypatch):
        """A failed os.replace must remove the temp file and leave the
        original bytes untouched (500, not a torn write)."""
        _principal(monkeypatch)
        target = self._lore() / "00_inicio.md"
        before = target.read_bytes()

        def _boom(src, dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(os, "replace", _boom)
        conf, base_rev = _confirm(client, "00_inicio.md", "# Editado\n")
        resp = _gated_write(client, "00_inicio.md", "# Editado\n", conf, base_rev)
        assert resp.status_code == 500
        assert target.read_bytes() == before
        assert self._no_temps() == []

    def test_snapshot_seam_fires_before_successful_replace(self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        seen = []
        monkeypatch.setattr(api_server, "_snapshot_before_write",
                            lambda full: seen.append(str(full)))
        conf, base_rev = _confirm(client, "00_inicio.md", "# Editado\n")
        resp = _gated_write(client, "00_inicio.md", "# Editado\n", conf, base_rev)
        assert resp.status_code == 200
        assert seen == [str(self._lore() / "00_inicio.md")]

    def test_snapshot_seam_not_fired_on_rejected_write(self, client: TestClient, monkeypatch):
        """A stale-base rejection happens under the lock BEFORE the snapshot
        hook: the seam must not fire and the on-disk bytes must not change."""
        _principal(monkeypatch)
        seen = []
        monkeypatch.setattr(api_server, "_snapshot_before_write",
                            lambda full: seen.append(str(full)))
        target = self._lore() / "00_inicio.md"
        conf, base_rev = _confirm(client, "00_inicio.md", "# A\n")
        target.write_text("# Cambio externo\n", encoding="utf-8")
        resp = _gated_write(client, "00_inicio.md", "# A\n", conf, base_rev)
        assert resp.status_code == 409
        assert seen == []
        assert target.read_text(encoding="utf-8") == "# Cambio externo\n"

    def test_stale_second_confirmation_409(self, client: TestClient, monkeypatch):
        """A second confirmation bound to the SAME base as the first cannot
        write after the first write advanced the on-disk digest: valid token,
        stale base → 409, not 403, and no mutation of the first write."""
        _principal(monkeypatch)
        target = self._lore() / "00_inicio.md"
        conf1, base_rev = _confirm(client, "00_inicio.md", "# A\n")
        conf2, _ = _confirm(client, "00_inicio.md", "# B\n")  # same base still current
        assert _gated_write(client, "00_inicio.md", "# A\n", conf1, base_rev).status_code == 200
        resp = _gated_write(client, "00_inicio.md", "# B\n", conf2, base_rev)
        assert resp.status_code == 409
        assert "base" in resp.json()["detail"].lower()
        assert target.read_text(encoding="utf-8") == "# A\n"

    def test_concurrent_stale_writes_serialize(self, client: TestClient, monkeypatch):
        """Two writers with distinct valid tokens on the same base: the
        per-target lock serializes base recheck + replace, so exactly one
        write wins and the other 409s — the file is never torn."""
        _principal(monkeypatch)
        target = self._lore() / "00_inicio.md"
        conf_a, base_rev = _confirm(client, "00_inicio.md", "# A\n")
        conf_b, _ = _confirm(client, "00_inicio.md", "# B\n")
        outcomes = []

        def _writer(conf, content):
            try:
                outcomes.append(
                    _gated_write(client, "00_inicio.md", content, conf, base_rev).status_code)
            except Exception as exc:  # pragma: no cover - defensive
                outcomes.append(("exc", exc))

        t1 = threading.Thread(target=_writer, args=(conf_a, "# A\n"))
        t2 = threading.Thread(target=_writer, args=(conf_b, "# B\n"))
        t1.start(); t2.start(); t1.join(); t2.join()
        assert sorted(outcomes) == [200, 409]
        assert target.read_text(encoding="utf-8") in ("# A\n", "# B\n")


class TestNewFileParity:
    """Slice 1C (task 2.4): new files share the manual edit confirmation
    flow; every rejection leaves the target absent (zero mutation)."""

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def test_new_file_identical_confirmation_flow(self, client: TestClient, monkeypatch):
        """A new file uses the same confirm → token → gated-create flow as an
        existing-file edit; success persists the exact proposed content."""
        _principal(monkeypatch)
        conf = _confirm_new(client, "nuevo.md", "# Nuevo\n")
        resp = _gated_create(client, "nuevo.md", "# Nuevo\n", conf)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert (self._lore() / "nuevo.md").read_text(encoding="utf-8") == "# Nuevo\n"

    def test_edit_kind_token_cannot_authorize_creation(self, client: TestClient, monkeypatch):
        """A kind='edit' token bound to an existing file must never authorize
        creating a new file (kind and target binding in the store)."""
        _principal(monkeypatch)
        conf, _ = _confirm(client, "00_inicio.md", "# A\n")
        resp = _gated_create(client, "nuevo.md", "# A\n", conf)
        assert resp.status_code == 403
        assert not (self._lore() / "nuevo.md").exists()

    def test_new_kind_token_cannot_authorize_edit(self, client: TestClient, monkeypatch):
        """Parity is bidirectional: a kind='new' token must not save an edit."""
        _principal(monkeypatch)
        conf = _confirm_new(client, "nuevo.md", "# Nuevo\n")
        target = self._lore() / "00_inicio.md"
        before = target.read_bytes()
        base_rev = hashlib.sha256(before).hexdigest()
        resp = _gated_write(client, "00_inicio.md", "# Nuevo\n", conf, base_rev)
        assert resp.status_code == 403
        assert target.read_bytes() == before

    def test_rejections_leave_new_file_absent(self, client: TestClient, monkeypatch):
        """Digest mismatch, forged token, and mismatched edit_id each consume
        their own fresh confirmation and must leave no file behind."""
        _principal(monkeypatch)
        path = "nuevo.md"
        for overrides in (
            {"content": "# OTHER\n"},
            {"token": "forged"},
            {"edit_id": "eX"},
        ):
            conf = _confirm_new(client, path, "# Nuevo\n")
            payload = {"content": "# Nuevo\n", "edit_id": "n1",
                       "proposed_digest": conf["proposed_digest"],
                       "token": conf["token"]}
            payload.update(overrides)
            resp = client.post(f"/api/test_mundo/lore/create?path={path}", json=payload)
            assert resp.status_code == 403, (overrides, resp.text)
            assert not (self._lore() / path).exists(), overrides

    def test_create_without_principal_leaves_new_file_absent(self, client: TestClient):
        """No trusted principal (default seam) → 401 and no file created."""
        resp = client.post("/api/test_mundo/lore/create?path=nuevo.md",
                           json={"content": "# N\n", "edit_id": "n1"})
        assert resp.status_code == 401
        assert not (self._lore() / "nuevo.md").exists()


class TestHistoryRestore:
    """PR 3: bounded, integrity-checked history and safe restoration."""

    def _target(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore" / "00_inicio.md"

    def _write(self, client: TestClient, monkeypatch, content: str, edit_id: str):
        _principal(monkeypatch)
        target = self._target()
        base = hashlib.sha256(target.read_bytes()).hexdigest()
        conf, _ = _confirm(client, "00_inicio.md", content, edit_id=edit_id)
        response = _gated_write(client, "00_inicio.md", content, conf, base, edit_id=edit_id)
        assert response.status_code == 200, response.text

    def _entries(self, client: TestClient, monkeypatch) -> list[dict]:
        _principal(monkeypatch)
        response = client.get("/api/test_mundo/history?path=lore/00_inicio.md")
        assert response.status_code == 200, response.text
        return response.json()["entries"]

    def test_snapshot_before_write_and_new_file_has_no_snapshot(
            self, client: TestClient, monkeypatch):
        self._write(client, monkeypatch, "# First\n", "h1")
        entries = self._entries(client, monkeypatch)
        assert len(entries) == 1
        assert entries[0]["content"].startswith("---")
        assert entries[0]["target"] == "lore/00_inicio.md"

        _principal(monkeypatch)
        new_conf = _confirm_new(client, "new.md", "# New\n", edit_id="new-1")
        assert _gated_create(client, "new.md", "# New\n", new_conf,
                             edit_id="new-1").status_code == 200
        response = client.get("/api/test_mundo/history?path=lore/new.md")
        assert response.status_code == 200
        assert response.json()["entries"] == []

    def test_history_is_newest_first_and_scoped_to_target(
            self, client: TestClient, monkeypatch):
        self._write(client, monkeypatch, "# A\n", "h1")
        self._write(client, monkeypatch, "# B\n", "h2")
        other = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "other.md"
        other.write_text("# Other\n", encoding="utf-8")
        api_server._snapshot_before_write(other)

        entries = self._entries(client, monkeypatch)
        assert entries[0]["content"] == "# A\n"
        assert "title: Inicio" in entries[1]["content"]
        assert all(entry["target"] == "lore/00_inicio.md" for entry in entries)

    def test_history_record_preserves_exact_bytes_and_integrity_fields(
            self, client: TestClient, monkeypatch):
        target = self._target()
        original = b"# Exact bytes\r\nSecond line\r\n"
        target.write_bytes(original)
        api_server._snapshot_before_write(target)

        bucket, canonical_target = api_server._history_bucket(target)
        record_path = next(bucket.glob("*.json"))
        record = json.loads(record_path.read_text(encoding="utf-8"))

        assert set(record) == api_server._HISTORY_FIELDS
        assert record["version"] == api_server._HISTORY_VERSION
        assert record["snapshot_id"] == record_path.stem
        assert record["target"] == canonical_target == "lore/00_inicio.md"
        assert base64.b64decode(record["content_b64"], validate=True) == original
        assert record["content_digest"] == hashlib.sha256(original).hexdigest()
        assert record["size"] == len(original)
        assert api_server._parse_history_time(record["created_at"]) <= datetime.now(timezone.utc)

        entries = self._entries(client, monkeypatch)
        assert entries[0]["content"].encode("utf-8") == original
        assert entries[0]["revision"] == record["content_digest"]
        assert target.read_bytes() == original

    @pytest.mark.parametrize("mutation", [
        "extra_field", "missing_field", "target", "snapshot_id", "digest",
        "size", "encoding", "utf8", "future_timestamp",
    ])
    def test_history_record_integrity_rejects_each_invalid_field_without_mutation(
            self, client: TestClient, monkeypatch, mutation: str):
        self._write(client, monkeypatch, "# Current\n", f"integrity-{mutation}")
        target = self._target()
        bucket, _ = api_server._history_bucket(target)
        record_path = next(bucket.glob("*.json"))
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if mutation == "extra_field":
            record["unexpected"] = True
        elif mutation == "missing_field":
            del record["size"]
        elif mutation == "target":
            record["target"] = "lore/other.md"
        elif mutation == "snapshot_id":
            record["snapshot_id"] = "0" * 32
        elif mutation == "digest":
            record["content_digest"] = "0" * 64
        elif mutation == "size":
            record["size"] += 1
        elif mutation == "encoding":
            record["content_b64"] = "%%%"
        elif mutation == "utf8":
            record["content_b64"] = "/w=="
        else:
            record["created_at"] = (
                datetime.now(timezone.utc) + timedelta(days=1)
            ).isoformat().replace("+00:00", "Z")
        record_bytes = json.dumps(record, sort_keys=True).encode("utf-8")
        record_path.write_bytes(record_bytes)
        target_before = target.read_bytes()
        storage_before = sorted(path.name for path in bucket.iterdir())

        entries = self._entries(client, monkeypatch)
        assert entries == []
        _principal(monkeypatch)
        confirmation = client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={
                "kind": "restore", "snapshot_id": record_path.stem,
                "edit_id": f"restore-{mutation}",
                "base_revision": hashlib.sha256(target_before).hexdigest(),
            },
        )
        assert confirmation.status_code in (400, 404)
        assert target.read_bytes() == target_before
        assert sorted(path.name for path in bucket.iterdir()) == storage_before
        assert record_path.read_bytes() == record_bytes

    @pytest.mark.parametrize("storage", ["root", "bucket", "entry"])
    def test_symlinked_history_storage_is_rejected_without_mutation(
            self, client: TestClient, monkeypatch, tmp_path: Path, storage: str):
        target = self._target()
        target_before = target.read_bytes()
        world = api_server.MUNDOS_DIR / "test_mundo"
        history_root = world / ".history"
        bucket_id = hashlib.sha256("lore/00_inicio.md".encode("utf-8")).hexdigest()
        external = tmp_path / f"unsafe-{storage}"
        external.mkdir()
        try:
            if storage == "root":
                history_root.symlink_to(external, target_is_directory=True)
            else:
                history_root.mkdir()
                bucket = history_root / bucket_id
                if storage == "bucket":
                    bucket.symlink_to(external, target_is_directory=True)
                else:
                    bucket.mkdir()
                    external_record = external / "record.json"
                    external_record.write_text("must remain untouched", encoding="utf-8")
                    (bucket / ("a" * 32 + ".json")).symlink_to(external_record)
        except OSError as error:
            pytest.skip(f"symlink creation unavailable: {error}")

        external_before = sorted(
            (path.name, path.read_bytes()) for path in external.iterdir()
        )
        _principal(monkeypatch)
        response = client.get("/api/test_mundo/history?path=lore/00_inicio.md")
        if storage in ("root", "bucket"):
            assert response.status_code == 400
        else:
            assert response.status_code == 200
            assert response.json()["entries"] == []
        assert target.read_bytes() == target_before
        assert sorted(
            (path.name, path.read_bytes()) for path in external.iterdir()
        ) == external_before

    def test_history_retains_at_most_twenty_entries(
            self, client: TestClient, monkeypatch):
        for index in range(21):
            self._write(client, monkeypatch, f"# Version {index}\n", f"h-{index}")
        entries = self._entries(client, monkeypatch)
        assert len(entries) == api_server._HISTORY_MAX_SNAPSHOTS
        assert entries[0]["content"] == "# Version 19\n"
        assert entries[-1]["content"] == "# Version 0\n"

    def test_expired_entry_is_hidden_without_mutation(
            self, client: TestClient, monkeypatch):
        self._write(client, monkeypatch, "# Current\n", "ttl")
        target = self._target()
        bucket, _ = api_server._history_bucket(target)
        entry = next(bucket.glob("*.json"))
        metadata_before = entry.read_bytes()
        metadata = json.loads(metadata_before)
        metadata["created_at"] = (
            datetime.now(timezone.utc) - timedelta(days=31)
        ).isoformat().replace("+00:00", "Z")
        entry.write_text(json.dumps(metadata), encoding="utf-8")
        target_before = target.read_bytes()

        entries = self._entries(client, monkeypatch)
        assert entries == []
        assert target.read_bytes() == target_before
        assert entry.exists()

    @pytest.mark.parametrize("mutation", ["missing", "corrupt", "tampered", "incompatible"])
    def test_invalid_entry_is_rejected_without_mutation(
            self, client: TestClient, monkeypatch, mutation: str):
        self._write(client, monkeypatch, "# Current\n", f"invalid-{mutation}")
        target = self._target()
        entry_data = self._entries(client, monkeypatch)[0]
        bucket, _ = api_server._history_bucket(target)
        entry = bucket / f"{entry_data['snapshot_id']}.json"
        if mutation == "missing":
            entry.unlink()
        elif mutation == "corrupt":
            entry.write_text("not json", encoding="utf-8")
        else:
            metadata = json.loads(entry.read_text(encoding="utf-8"))
            if mutation == "tampered":
                metadata["content_b64"] = "YXR0YWNrZWQ="
            else:
                metadata["version"] = 999
            entry.write_text(json.dumps(metadata), encoding="utf-8")

        before = target.read_bytes()
        assert self._entries(client, monkeypatch) == []
        _principal(monkeypatch)
        base = hashlib.sha256(before).hexdigest()
        confirmation = client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={
                "kind": "restore", "snapshot_id": entry_data["snapshot_id"],
                "edit_id": "restore-invalid", "base_revision": base,
            },
        )
        assert confirmation.status_code in (400, 404)
        assert target.read_bytes() == before

    def test_unauthorized_and_traversal_history_requests_fail_closed(
            self, client: TestClient, monkeypatch, tmp_path: Path):
        target = self._target()
        before = target.read_bytes()
        unauthorized = client.get("/api/test_mundo/history?path=lore/00_inicio.md")
        assert unauthorized.status_code == 401
        restore_unauthorized = client.post(
            "/api/test_mundo/history/restore",
            json={"path": "lore/00_inicio.md", "snapshot_id": "0" * 32},
        )
        assert restore_unauthorized.status_code == 401

        _principal(monkeypatch)
        outside = tmp_path / "secret.md"
        outside.write_text("SECRET\n", encoding="utf-8")
        traversal = client.get("/api/test_mundo/history?path=../../secret.md")
        assert traversal.status_code == 400
        assert target.read_bytes() == before
        assert outside.read_text(encoding="utf-8") == "SECRET\n"

    def test_history_requires_section_prefixed_path(
            self, client: TestClient, monkeypatch):
        """Frontend boundary: a section-relative path (`00_inicio.md`) is
        rejected; only the canonical mundo-relative form (`lore/00_inicio.md`)
        is accepted."""
        _principal(monkeypatch)
        relative = client.get("/api/test_mundo/history?path=00_inicio.md")
        assert relative.status_code == 400
        assert relative.json()["detail"] == "Invalid history path"
        canonical = client.get("/api/test_mundo/history?path=lore/00_inicio.md")
        assert canonical.status_code == 200, canonical.text

    def test_restore_snapshots_current_content_before_replacement(
            self, client: TestClient, monkeypatch):
        self._write(client, monkeypatch, "# Current\n", "restore-source")
        entries = self._entries(client, monkeypatch)
        original = entries[0]
        target = self._target()
        current_base = hashlib.sha256(target.read_bytes()).hexdigest()
        _principal(monkeypatch)
        confirmation = client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={
                "kind": "restore", "snapshot_id": original["snapshot_id"],
                "edit_id": "restore-1", "base_revision": current_base,
                "proposed_content": original["content"],
            },
        )
        assert confirmation.status_code == 200, confirmation.text
        response = client.post(
            "/api/test_mundo/history/restore",
            json={
                "path": "lore/00_inicio.md",
                "snapshot_id": original["snapshot_id"],
                "edit_id": "restore-1", "base_revision": current_base,
                "content": original["content"],
                "token": confirmation.json()["token"],
                "proposed_digest": confirmation.json()["proposed_digest"],
            },
        )
        assert response.status_code == 200, response.text
        assert target.read_bytes().decode("utf-8") == original["content"]
        restored_entries = self._entries(client, monkeypatch)
        assert restored_entries[0]["content"] == "# Current\n"

    def test_restore_stale_base_rejects_before_safety_snapshot(
            self, client: TestClient, monkeypatch):
        self._write(client, monkeypatch, "# Current\n", "restore-stale")
        original = self._entries(client, monkeypatch)[0]
        target = self._target()
        base = hashlib.sha256(target.read_bytes()).hexdigest()
        _principal(monkeypatch)
        confirmation = client.post(
            "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
            json={"kind": "restore", "snapshot_id": original["snapshot_id"],
                  "edit_id": "restore-stale", "base_revision": base},
        )
        assert confirmation.status_code == 200
        before_count = len(self._entries(client, monkeypatch))
        target.write_text("# External\n", encoding="utf-8")
        response = client.post(
            "/api/test_mundo/history/restore",
            json={"path": "lore/00_inicio.md", "snapshot_id": original["snapshot_id"],
                  "edit_id": "restore-stale", "base_revision": base,
                  "token": confirmation.json()["token"],
                  "proposed_digest": confirmation.json()["proposed_digest"]},
        )
        assert response.status_code == 409
        assert target.read_text(encoding="utf-8") == "# External\n"
        assert len(self._entries(client, monkeypatch)) == before_count

    def test_snapshot_failure_rolls_back_without_replacing_target(
            self, client: TestClient, monkeypatch):
        _principal(monkeypatch)
        target = self._target()
        before = target.read_bytes()
        conf, base = _confirm(client, "00_inicio.md", "# New\n", edit_id="snapshot-fail")

        def fail_snapshot(*args):
            raise OSError("history unavailable")

        monkeypatch.setattr(api_server, "_snapshot_before_write", fail_snapshot)
        response = _gated_write(client, "00_inicio.md", "# New\n", conf, base,
                                edit_id="snapshot-fail")
        assert response.status_code == 500
        assert target.read_bytes() == before


class TestAIEditSuggest:
    """PR 2 (tasks 3.1-3.4): diskless validated Hermes proposals with a hard
    cap of exactly 3 total attempts and a safe, non-persisting fallback.

    Hermes is mocked via ``api_server._run_hermes``; every test asserts zero
    persistence (target bytes unchanged, no new file, no temp leftovers) and
    the observability test proves content never reaches the logs.
    """

    def _lore(self) -> Path:
        return api_server.MUNDOS_DIR / "test_mundo" / "lore"

    def _no_temps(self) -> list[str]:
        return [p.name for p in self._lore().iterdir() if p.name.endswith(".tmp")]

    def _valid_payload(self, content: str, new: bool = False) -> dict:
        base = "" if new else hashlib.sha256(
            (self._lore() / "00_inicio.md").read_bytes()).hexdigest()
        return {
            "proposal_id": "prop-1",
            "target": "lore/nuevo.md" if new else "lore/00_inicio.md",
            "base_revision": base,
            "content": content,
            "rationale": "test rationale",
            "is_new_file": new,
        }

    def _suggest(self, client: TestClient, path: str, **overrides) -> dict:
        body = {"section": "lore", "path": path, "prompt": "mejora este archivo"}
        body.update(overrides)
        return client.post("/api/test_mundo/ai/edit-suggest", json=body)

    def test_valid_existing_file_proposal(self, client: TestClient):
        """A contract-valid reply yields the full proposal and writes nothing."""
        target = self._lore() / "00_inicio.md"
        before = target.read_bytes()
        payload = self._valid_payload("# Propuesta\n")
        fenced = "```json\n" + json.dumps(payload) + "\n```"  # fence tolerance
        with patch("api_server._run_hermes",
                   new=AsyncMock(return_value=fenced)) as mock_run:
            resp = self._suggest(client, "00_inicio.md")
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "proposal" and body["attempts"] == 1
        prop = body["proposal"]
        assert prop["proposal_id"] == "prop-1"
        assert prop["target"] == "lore/00_inicio.md"
        assert prop["base_revision"] == hashlib.sha256(before).hexdigest()
        assert prop["content"] == "# Propuesta\n"
        assert prop["proposed_digest"] == hashlib.sha256("# Propuesta\n".encode()).hexdigest()
        assert prop["rationale"] and prop["is_new_file"] is False
        assert mock_run.await_count == 1
        # No-write invariant: proposal never touches the target on disk.
        assert target.read_bytes() == before
        assert self._no_temps() == []

    def test_valid_new_file_proposal(self, client: TestClient):
        """A new-target proposal is marked new with an empty base and stays
        unpersisted pending review."""
        payload = self._valid_payload("# Nuevo\n", new=True)
        with patch("api_server._run_hermes",
                   new=AsyncMock(return_value=json.dumps(payload))):
            resp = self._suggest(client, "nuevo.md")
        assert resp.status_code == 200
        prop = resp.json()["proposal"]
        assert prop["is_new_file"] is True
        assert prop["base_revision"] == ""
        assert prop["content"] == "# Nuevo\n"
        assert not (self._lore() / "nuevo.md").exists()  # still diskless

    def test_malformed_and_schema_invalid_exhaust_fallback(self, client: TestClient):
        """Unparseable, missing-field, and wrong-base replies each count as
        retryable attempts; after exactly 3 the user gets a safe fallback."""
        target = self._lore() / "00_inicio.md"
        before = target.read_bytes()
        replies = [
            "not json at all",
            json.dumps({"proposal_id": "p1"}),  # missing required fields
            json.dumps({"proposal_id": "p2", "target": "lore/00_inicio.md",
                        "base_revision": "0" * 64, "content": "x",
                        "rationale": "r", "is_new_file": False}),  # bad base
        ]
        with patch("api_server._run_hermes",
                   new=AsyncMock(side_effect=replies)) as mock_run:
            resp = self._suggest(client, "00_inicio.md")
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "fallback" and body["attempts"] == 3
        assert body["proposal"] is None
        assert body["fallback_action"] == "manual-edit-or-chat"
        assert mock_run.await_count == 3  # exactly 3, never more
        assert target.read_bytes() == before

    def test_transient_twice_then_success_attempts_three(self, client: TestClient):
        """Two transient gateway failures then a valid reply: attempts == 3
        and the proposal is returned (no fallback)."""
        payload = self._valid_payload("# Recuperado\n")
        replies = ["Error: timeout", "Error: HTTP 500", json.dumps(payload)]
        with patch("api_server._run_hermes",
                   new=AsyncMock(side_effect=replies)) as mock_run:
            resp = self._suggest(client, "00_inicio.md")
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "proposal" and body["attempts"] == 3
        assert body["proposal"]["content"] == "# Recuperado\n"
        assert body["proposal"]["base_revision"] == hashlib.sha256(
            (self._lore() / "00_inicio.md").read_bytes()).hexdigest()
        assert mock_run.await_count == 3

    def test_schema_invalid_target_mismatch_retries_then_success(self, client: TestClient):
        """Hermes must never select arbitrary targets: a mismatched target is
        schema-invalid (retryable) and a corrected reply succeeds on attempt 2."""
        wrong = self._valid_payload("# A\n")
        wrong["target"] = "lore/other.md"
        good = self._valid_payload("# B\n")
        with patch("api_server._run_hermes",
                   new=AsyncMock(side_effect=[json.dumps(wrong), json.dumps(good)])):
            resp = self._suggest(client, "00_inicio.md")
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "proposal" and body["attempts"] == 2
        assert body["proposal"]["content"] == "# B\n"
        assert body["proposal"]["target"] == "lore/00_inicio.md"

    def test_exhaustion_writes_nothing(self, client: TestClient):
        """On exhaustion the section tree is byte-identical: no edits, no new
        files, no temp leftovers."""
        target = self._lore() / "00_inicio.md"
        before = target.read_bytes()
        before_entries = sorted(p.name for p in self._lore().iterdir())
        with patch("api_server._run_hermes",
                   new=AsyncMock(return_value="garbage")):
            resp = self._suggest(client, "00_inicio.md")
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "fallback"
        assert target.read_bytes() == before
        assert sorted(p.name for p in self._lore().iterdir()) == before_entries
        assert self._no_temps() == []

    def test_traversal_and_internal_targets_rejected_without_gateway_call(
            self, client: TestClient, tmp_path):
        """Traversal and .history targets are rejected before any Hermes
        call, with zero mutation and zero disclosure."""
        escape = tmp_path / "mundos" / "secrets.md"
        escape.write_text("EDIT SUGGEST SECRET\n", encoding="utf-8")
        with patch("api_server._run_hermes",
                   new=AsyncMock(return_value="{}")) as mock_run:
            resp = self._suggest(client, "../../secrets.md")
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()
        assert mock_run.await_count == 0
        assert escape.read_text(encoding="utf-8") == "EDIT SUGGEST SECRET\n"

        snap = api_server.MUNDOS_DIR / "test_mundo" / ".history" / "lore" / "x.md"
        snap.parent.mkdir(parents=True)
        snap.write_text("SNAPSHOT\n", encoding="utf-8")
        with patch("api_server._run_hermes",
                   new=AsyncMock(return_value="{}")) as mock_run2:
            resp2 = self._suggest(client, "../.history/lore/x.md")
        assert resp2.status_code == 400
        assert mock_run2.await_count == 0
        assert snap.read_text(encoding="utf-8") == "SNAPSHOT\n"

    def test_observability_logs_metadata_only_not_content(self, client: TestClient,
                                                          monkeypatch, caplog):
        """Diagnostics record target/attempts/category/outcome/opaque principal
        but never proposal content or prompt secrets."""
        _principal(monkeypatch, pid="opaque-42")
        marker = "SUPER SECRET PROPOSAL CONTENT"
        payload = self._valid_payload(f"# Propuesta\n{marker}\n")
        with patch("api_server._run_hermes",
                   new=AsyncMock(return_value=json.dumps(payload))):
            with caplog.at_level(logging.INFO):
                resp = self._suggest(client, "00_inicio.md")
        assert resp.status_code == 200
        assert marker not in caplog.text
        assert "# Propuesta" not in caplog.text
        assert "ai/edit-suggest:" in caplog.text
        assert "lore/00_inicio.md" in caplog.text
        assert "attempts=1" in caplog.text and "outcome=proposal" in caplog.text
        assert "principal=opaque-42" in caplog.text


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ONB-1.1 / ONB-1.4 — Onboarding first-run gate, resume, offline, pending,
# unauthenticated access fails closed
# ---------------------------------------------------------------------------


@pytest.fixture()
def empty_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with an EMPTY mundos dir (no world) + fresh local registry."""
    mundos = tmp_path / "mundos"
    mundos.mkdir(parents=True)
    monkeypatch.setattr(api_server, "MUNDOS_DIR", mundos)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", tmp_path)
    # The telegram secret boundary (.env) must be hermetic too: the same
    # repo-root .env the idea-capture panel manages is redirected to the
    # sandbox so telegram tests never touch (or read) the real .env.
    monkeypatch.setattr(idea_capture_ui, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("DEMIURGOS_AUTH_MODE", raising=False)
    monkeypatch.setattr(api_server, "_SEMANTIC_PROVIDER", None)
    api_server._graph_indices.clear()
    api_server._confirmation_store.clear()
    api_server._GUIDED_PENDING_PROPOSALS.clear()
    api_server._GUIDED_CONSENT_TOKENS.clear()
    api_server._GUIDED_INDEX_REQUESTS.clear()
    api_server._LOCAL_STATE = None
    with api_server._local_session_lock:
        api_server._local_sessions.clear()
    api_server._target_locks.clear()
    yield TestClient(api_server.app, client=("127.0.0.1", 50000))
    api_server._LOCAL_STATE = None


def _state_path() -> Path:
    # Machine state lives in the state directory (2b), not under PROJECT_ROOT.
    return state_file("local-state.json")


def _post_step0(client: TestClient, **overrides):
    payload = {
        "ui": "es",
        "conversation": "es",
        "content": "es",
        "region": "AR",
        "region_explicit": True,
        "iana_timezone": "America/Argentina/Buenos_Aires",
    }
    payload.update(overrides)
    return client.post("/api/onboarding/step0", json=payload)


class TestOnboardingRoutes:
    def test_status_public_and_fresh_installation_reports_step0(
            self, empty_client: TestClient):
        resp = empty_client.get("/api/onboarding/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["completed"] is False
        assert body["current_step"] == "step0"
        assert body["completed_steps"] == []
        assert "ai" in body["remote_pending"]
        assert "telegram" in body["remote_pending"]

    def test_step0_write_allowed_without_principal_when_vault_off(
            self, empty_client: TestClient):
        """S-AC-02a — with the vault OFF (default fresh install) step0 needs
        no authentication."""
        resp = _post_step0(empty_client)
        assert resp.status_code == 200, resp.text

    def test_content_folder_step_is_offered_and_commits(
            self, empty_client: TestClient):
        """Step 4: after the account the folder step is offered, and committing
        it resumes at the world without storing a path (the pointer owns it)."""
        api_server._LOCAL_STATE = None
        assert _post_step0(empty_client).status_code == 200
        registry = api_server._local_state()
        registry.atomic_commit(
            api_server._commit_account_created(registry.snapshot())
        )
        offered = empty_client.get("/api/onboarding/status").json()
        assert offered["current_step"] == "content_folder"
        assert "content_folder" in offered["pending_steps"]

        committed = empty_client.post("/api/onboarding/content-folder")
        assert committed.status_code == 200, committed.text
        body = committed.json()
        assert "content_folder" in body["completed_steps"]
        assert body["current_step"] == "world"
        assert body["completed"] is False

    def test_step0_write_fails_closed_without_principal_when_vault_on(
            self, empty_client: TestClient):
        """S-AC-02b — with the vault ON (persisted flag) unauthenticated
        step0 fails closed (401)."""
        registry = api_server._local_state()
        state = registry.snapshot()
        state.setdefault("capabilities", {})["vault"] = {
            "enabled": True, "reauth_interval_d": 14}
        registry.atomic_commit(state)
        resp = _post_step0(empty_client)
        assert resp.status_code == 401

    def test_step0_write_requires_principal_and_persists_locale(
            self, empty_client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = _post_step0(empty_client)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "step0" in body["completed_steps"]
        assert body["current_step"] == "account"
        state = api_server._local_state().snapshot()
        assert state["locale"]["conversation"] == "es"
        assert state["locale"]["region"] == "AR"
        assert state["locale"]["iana_timezone"] == "America/Argentina/Buenos_Aires"

    def test_invalid_locale_is_rejected_without_mutation(
            self, empty_client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = _post_step0(empty_client, iana_timezone="GMT+3")
        assert resp.status_code == 422
        state = api_server._local_state().snapshot()
        assert state["locale"] is None

    def test_resume_after_restart_never_replays_step0(
            self, empty_client: TestClient, monkeypatch):
        _principal(monkeypatch)
        _post_step0(empty_client)
        # Simulate a process restart: a fresh LocalState reads the same file.
        from local_state import LocalState
        restarted = LocalState(_state_path())
        assert "step0" in restarted.snapshot()["onboarding"]["completed_steps"]
        # The endpoint agrees: step0 is not in pending_steps after reload.
        api_server._LOCAL_STATE = None
        resp = empty_client.get("/api/onboarding/status")
        assert "step0" not in resp.json()["pending_steps"]

    def test_step0_persists_and_round_trips_explicit_domain_flags(
            self, empty_client: TestClient, monkeypatch):
        """AD-7: step0 persists ``*_explicit`` and GET /api/locale returns them."""
        _principal(monkeypatch)
        resp = _post_step0(
            empty_client,
            ui="en", conversation="es", content="en",
            conversation_explicit=True, content_explicit=True,
        )
        assert resp.status_code == 200, resp.text
        body = empty_client.get("/api/locale").json()
        assert body["ui"] == "en"
        assert body["conversation"] == "es"
        assert body["content"] == "en"
        assert body["conversation_explicit"] is True
        assert body["content_explicit"] is True

    def test_config_endpoint_prefers_persisted_locale_over_env(
            self, empty_client: TestClient, monkeypatch):
        """LOC-REQ-1: /api/config is persisted-first, not env-only."""
        _principal(monkeypatch)
        monkeypatch.setenv("DEMIURGOS_LANGUAGE", "es")
        _post_step0(empty_client, ui="en", conversation="en", content="en")
        body = empty_client.get("/api/config").json()
        assert body["language"] == "en"
        # The app_version field rides along and stays non-empty.
        assert isinstance(body["app_version"], str) and body["app_version"]

    def test_ai_path_language_follows_persisted_locale_not_env(
            self, empty_client: TestClient, monkeypatch):
        """AD-6/AD-8: the conversation domain inherits the persisted UI locale.

        With no explicit conversation override, an ``en`` UI locale makes the
        server-owned guided copy English even while the env still says ``es``.
        """
        _principal(monkeypatch)
        monkeypatch.setenv("DEMIURGOS_LANGUAGE", "es")
        _post_step0(empty_client, ui="en", conversation="en", content="en")
        text = api_server._guided_confirmation_text("start")
        assert text.startswith("I can prepare a guided proposal")

    def test_ai_path_honors_explicit_conversation_override(
            self, empty_client: TestClient, monkeypatch):
        """AD-7: an explicit conversation override wins over the UI locale."""
        _principal(monkeypatch)
        monkeypatch.setenv("DEMIURGOS_LANGUAGE", "en")
        _post_step0(
            empty_client,
            ui="en", conversation="es", content="en",
            conversation_explicit=True,
        )
        text = api_server._guided_confirmation_text("start")
        assert text.startswith("Puedo preparar una propuesta guiada")

    def test_offline_bootstrap_keeps_local_work_pending_remote(
            self, empty_client: TestClient, monkeypatch):
        _principal(monkeypatch)
        _post_step0(empty_client)
        # No worlds and no connectivity: local steps stay actionable and
        # remote capabilities are visibly pending, never fabricated ready.
        resp = empty_client.get("/api/onboarding/status")
        body = resp.json()
        assert body["completed"] is False
        assert body["current_step"] == "account"
        assert set(body["remote_pending"]) == {"ai", "telegram", "backup_handoff"}


# ---------------------------------------------------------------------------
# ONB-1.2 / ONB-1.5 — World creation endpoint: naming, idempotency, collision
# ---------------------------------------------------------------------------


class TestWorldCreateEndpoint:
    def test_create_allowed_without_principal_when_auth_disabled(self, empty_client: TestClient):
        """When auth is disabled (default), world creation should work without authentication."""
        resp = empty_client.post("/api/worlds", json={"name": "mundo-x", "lore_skeleton": False})
        assert resp.status_code == 201, resp.text
        assert resp.json()["kind"] == "created"

    def test_create_fails_closed_without_principal_when_vault_on(
            self, empty_client: TestClient):
        """S-AC-02d — with the vault ON (persisted flag) world creation
        requires authentication."""
        registry = api_server._local_state()
        state = registry.snapshot()
        state.setdefault("capabilities", {})["vault"] = {
            "enabled": True, "reauth_interval_d": 14}
        registry.atomic_commit(state)
        resp = empty_client.post("/api/worlds", json={"name": "mundo-x", "lore_skeleton": False})
        assert resp.status_code == 401

    def test_create_valid_world_with_canonical_tree(
            self, empty_client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = empty_client.post("/api/worlds", json={"name": "mundo-x", "lore_skeleton": True})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["kind"] == "created"
        root = api_server.MUNDOS_DIR / "mundo-x"
        assert (root / "lore" / "reglas").is_dir()
        assert (root / "personajes").is_dir()
        assert not (root / "relaciones").exists()
        assert not (root / "_context").exists()
        # The empty OC8 skeleton folders must be visible in the section tree —
        # the checkbox promises "carpetas vacías" and the user must see them.
        tree = empty_client.get("/api/mundo-x/lore/tree").json()
        lore_names = [node["name"] for node in tree]
        for sub in ("reglas", "lugares", "culturas", "criaturas", "facciones",
                    "artefactos", "historia"):
            assert sub in lore_names, f"{sub} should be listed in the lore tree"

    def test_unsafe_name_returns_400_without_mutation(
            self, empty_client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = empty_client.post("/api/worlds", json={"name": "../escape", "lore_skeleton": False})
        assert resp.status_code == 400
        assert not (api_server.MUNDOS_DIR / "escape").exists()

    def test_collision_rejected_without_mutation(
            self, empty_client: TestClient, monkeypatch):
        _principal(monkeypatch)
        existing = api_server.MUNDOS_DIR / "test_mundo"
        (existing / "lore").mkdir(parents=True)
        (existing / "lore" / "00_inicio.md").write_text("# Inicio\n", encoding="utf-8")
        resp = empty_client.post("/api/worlds", json={"name": "test_mundo", "lore_skeleton": False})
        assert resp.status_code == 409
        assert (existing / "lore" / "00_inicio.md").exists()

    def test_repeat_creation_is_idempotent(
            self, empty_client: TestClient, monkeypatch):
        _principal(monkeypatch)
        first = empty_client.post("/api/worlds", json={"name": "nuevo", "lore_skeleton": False})
        assert first.status_code == 201
        second = empty_client.post("/api/worlds", json={"name": "nuevo", "lore_skeleton": False})
        assert second.status_code == 200
        assert second.json()["kind"] == "already_exists"

    def test_world_creation_marks_operational_step(
            self, empty_client: TestClient, monkeypatch):
        _principal(monkeypatch)
        # Full onboarding happy path: step0 -> account (R-AC-01 blocking) -> world.
        monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "credentials")
        _post_step0(empty_client)
        account = empty_client.post(
            "/api/auth/credentials/account",
            json={"username": "vault-user", "password": "secret-pass"},
        )
        assert account.status_code == 200
        created = empty_client.post("/api/worlds", json={"name": "final", "lore_skeleton": True})
        assert created.status_code == 201
        status = empty_client.get("/api/onboarding/status").json()
        assert status["completed"] is True
        assert status["current_step"] == "ready"

    def test_full_onboarding_flow_with_real_principal_without_stubbing(
            self, empty_client: TestClient):
        """The REAL onboarding happy path with the vault ON — no stubbing of
        ``_resolve_principal``: the account is created, the credentials login
        plants a real vault session, and step0 + world creation resolve the
        principal from that session (R-AC-01/R-AC-02, S-AC-02b/d)."""
        registry = api_server._local_state()
        state = registry.snapshot()
        state.setdefault("capabilities", {})["vault"] = {
            "enabled": True, "reauth_interval_d": 14}
        registry.atomic_commit(state)
        # Fail-closed while ON and unauthenticated (S-AC-02b).
        assert _post_step0(empty_client).status_code == 401
        # Account creation is allowed with the vault ON (S-AC-01a).
        account = empty_client.post(
            "/api/auth/credentials/account",
            json={"username": "real-user", "password": "secret-pass"},
        )
        assert account.status_code == 200, account.text
        assert account.json()["words"]
        # Real credentials login: the vault session cookie lands in the jar
        # (no env override -> the cookie is not Secure, so the http transport
        # keeps it).
        login = empty_client.post(
            "/api/auth/credentials/login", json={"password": "secret-pass"})
        assert login.status_code == 200, login.text
        assert login.json()["authenticated"] is True
        # step0 now resolves the real principal from the vault session. The
        # account step was already completed by the account creation above, so
        # the flow resumes at the content-folder step (step 4), before the world.
        step0 = _post_step0(empty_client)
        assert step0.status_code == 200, step0.text
        body = step0.json()
        assert "step0" in body["completed_steps"]
        assert "account" in body["completed_steps"]
        assert body["current_step"] == "content_folder"
        # World creation resolves the same real principal (S-AC-02d satisfied).
        created = empty_client.post(
            "/api/worlds", json={"name": "real-mundo", "lore_skeleton": True})
        assert created.status_code == 201, created.text
        assert created.json()["kind"] == "created"
        status = empty_client.get("/api/onboarding/status").json()
        assert status["completed"] is True
        assert status["current_step"] == "ready"


# ---------------------------------------------------------------------------
# ONB-4.1 / ONB-4.2 — read-only legacy detection: uppercase Lore/Personajes
# detected and surfaced via readiness; never mutated (approval/migration is
# ONB-4.3, a separate work unit).
# ---------------------------------------------------------------------------


class TestLegacyDetectionEndpoint:
    def test_readiness_reports_legacy_uppercase_folders_read_only(
            self, empty_client: TestClient):
        legacy = api_server.MUNDOS_DIR / "legacy-x"
        (legacy / "Lore").mkdir(parents=True)
        (legacy / "Personajes").mkdir()
        (legacy / "Lore" / "00_inicio.md").write_text("# X\n", encoding="utf-8")
        body = empty_client.get("/api/onboarding/readiness").json()
        finding = next((f for f in body["legacy"] if f["world"] == "legacy-x"), None)
        # Detection is scandir-name-based (ONB-4.2): a top-level dir literally
        # named `Lore`/`Personajes` is uppercase intent on EVERY filesystem —
        # Linux, macOS, and Windows all report it, so the expectation is
        # unconditional. (Previously this branched on
        # `(legacy / "lore").exists()` and asserted None on case-insensitive
        # FSes; the Windows CI runner proved that probe disagrees with the
        # detection loop's own probe — the test took the case-insensitive
        # branch while detection still fired — so detection no longer consults
        # filesystem case-sensitivity at all.)
        assert finding is not None
        assert set(finding["folders"]) == {"Lore", "Personajes"}
        # Detection is strictly read-only: the GET renamed nothing. On a
        # case-insensitive FS `lore` resolves to `Lore`, so assert the legacy
        # folder itself survived instead of the lowercased name.
        assert (legacy / "Lore").is_dir()
        assert (legacy / "Personajes").is_dir()
        assert (legacy / "Lore" / "00_inicio.md").exists()

    def test_readiness_does_not_report_canonical_worlds(
            self, empty_client: TestClient):
        good = api_server.MUNDOS_DIR / "bueno"
        for sub in ("lore", "personajes"):
            (good / sub).mkdir(parents=True)
        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["legacy"] == []
        assert all(f["world"] != "bueno" for f in body["legacy"])

    def test_readiness_legacy_is_empty_when_clean(
            self, empty_client: TestClient):
        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["legacy"] == []


# ---------------------------------------------------------------------------
# ONB-4.3 — Migration approval API (WU-4c1): explicit approval, fail-closed
# auth, machine-readable MigrationErrorKind -> HTTP mapping, and the
# completed/rolled_back/error response with transaction + evidence. The
# transactional engine lives in wiki.migration (WU-4b); these RED tests cover
# the backend routes/approval surface ONLY: no preview/history endpoints
# beyond readiness, no auto-rename, unapproved folders never touched.
# ---------------------------------------------------------------------------


class TestMigrationApprovalEndpoint:
    """ONB-4.3 — backend routes/approval API (WU-4c1)."""

    WORLD = "legacy-x"

    def _legacy_world(self, *, folders=("Lore", "Personajes")) -> Path:
        root = api_server.MUNDOS_DIR / self.WORLD
        for folder in folders:
            (root / folder).mkdir(parents=True)
        if (root / "Lore").is_dir():
            (root / "Lore" / "00_inicio.md").write_text("# X\n", encoding="utf-8")
        if (root / "Personajes").is_dir():
            (root / "Personajes" / "pc.md").write_text("# PC\n", encoding="utf-8")
        return root

    def _execute(self, client: TestClient, world: str = WORLD, folders=None):
        payload = {
            "world": world,
            "folders": folders if folders is not None else ["Lore", "Personajes"],
        }
        return client.post("/api/migration/execute", json=payload)

    def _evidence_file(self, transaction_id: str) -> Path:
        return (
            state_file("migration-evidence") / f"{transaction_id}.json"
        )

    def test_migration_execute_fails_closed_without_principal(
            self, empty_client: TestClient):
        root = self._legacy_world()
        resp = self._execute(empty_client)
        assert resp.status_code == 401
        # Fail-closed: nothing was planned or moved.
        assert (root / "Lore").is_dir()
        assert (root / "Personajes").is_dir()
        if not _fs_case_insensitive():
            assert not (root / "lore").exists()
            assert not (root / "personajes").exists()

    def test_migration_no_preview_or_history_endpoints_beyond_readiness(
            self, empty_client: TestClient, monkeypatch):
        """WU-4c1 scope: readiness already reports legacy; no extra GETs.

        The migration surface is exactly ONE explicit-approval POST endpoint:
        no preview, no history, no evidence-retrieval route (the engine
        persists evidence as files; retrieval is out of scope). The router
        exposes that single POST, and the app serves no migration GET.
        """
        _principal(monkeypatch)
        router = create_migration_settings_router(
            require_principal=lambda request: api_server.EditPrincipal("tester"),
            mundos_dir=lambda: api_server.MUNDOS_DIR,
            evidence_dir=lambda: api_server.PROJECT_ROOT / "data"
            / "migration-evidence",
        )
        routes = sorted(
            (r.path, sorted(getattr(r, "methods", []) or []))
            for r in router.routes
        )
        assert routes == [("/api/migration/execute", ["POST"])]
        assert empty_client.get("/api/migration/execute").status_code == 405
        assert empty_client.get("/api/migration/preview").status_code == 404

    def test_migration_empty_approval_rejected_without_mutation(
            self, empty_client: TestClient, monkeypatch):
        root = self._legacy_world()
        _principal(monkeypatch)
        resp = self._execute(empty_client, folders=[])
        assert resp.status_code == 400
        assert resp.json()["code"] == "empty_approval"
        assert (root / "Lore").is_dir()
        if not _fs_case_insensitive():
            assert not (root / "lore").exists()

    def test_migration_unknown_folder_rejected_without_mutation(
            self, empty_client: TestClient, monkeypatch):
        root = self._legacy_world(folders=("Lore",))
        _principal(monkeypatch)
        resp = self._execute(empty_client, folders=["Lore", "Sagas"])
        assert resp.status_code == 400
        assert resp.json()["code"] == "unknown_folder"
        assert (root / "Lore").is_dir()
        if not _fs_case_insensitive():
            assert not (root / "lore").exists()

    def test_migration_invalid_world_rejected_without_mutation(
            self, empty_client: TestClient, monkeypatch):
        _principal(monkeypatch)
        resp = self._execute(empty_client, world="no_such_world")
        assert resp.status_code == 404
        assert resp.json()["code"] == "invalid_world"

    def test_migration_world_symlink_escape_rejected_without_mutation(
            self, empty_client: TestClient, monkeypatch, tmp_path: Path):
        _principal(monkeypatch)
        outside = tmp_path / "outside-world"
        (outside / "Lore").mkdir(parents=True)
        (outside / "Lore" / "secret.md").write_text("# s\n", encoding="utf-8")
        link = api_server.MUNDOS_DIR / "link-x"
        link.symlink_to(outside, target_is_directory=True)
        resp = self._execute(empty_client, world="link-x")
        assert resp.status_code == 404
        assert resp.json()["code"] == "invalid_world"
        # The escape target is untouched: nothing moved or was renamed.
        assert (outside / "Lore" / "secret.md").exists()
        if not _fs_case_insensitive():
            assert not (outside / "lore").exists()

    def test_migration_destination_collision_rejected_without_mutation(
            self, empty_client: TestClient, monkeypatch):
        if _fs_case_insensitive():
            pytest.skip("Lore and lore are the same physical dir on "
                        "case-insensitive FS (natural noop, not a collision)")
        root = self._legacy_world()
        (root / "lore").mkdir()
        (root / "lore" / "exists.md").write_text("# y\n", encoding="utf-8")
        _principal(monkeypatch)
        resp = self._execute(empty_client)
        assert resp.status_code == 409
        assert resp.json()["code"] == "collision"
        assert (root / "Lore").is_dir()
        assert (root / "lore" / "exists.md").exists()

    def test_migration_approved_execution_completes_with_evidence(
            self, empty_client: TestClient, monkeypatch):
        root = self._legacy_world()
        _principal(monkeypatch)
        resp = self._execute(empty_client)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["transaction_id"].startswith("mig-")
        assert body["world"] == self.WORLD
        assert body["restore_verified"] is True
        assert body["error"] == ""
        assert {step["folder"] for step in body["steps"]} == {"Lore", "Personajes"}
        for step in body["steps"]:
            assert step["destination_hash"] == step["source_hash"]
        # Canonical-side content is reachable after the step (moved or noop).
        assert (root / "lore" / "00_inicio.md").exists()
        assert (root / "personajes" / "pc.md").exists()
        if _fs_case_insensitive():
            # Natural noop: the legacy-cased folders still resolve (same
            # physical dir); nothing was renamed (R-CIM-02).
            assert (root / "Lore").is_dir()
            assert (root / "Personajes").is_dir()
            assert all(step["is_noop"] for step in body["steps"])
        else:
            # Lowercase canonical tree replaced the legacy folders.
            assert not (root / "Lore").exists()
            assert not (root / "Personajes").exists()
        # Evidence persisted as JSON by the engine, keyed by the txn id.
        evidence_file = self._evidence_file(body["transaction_id"])
        assert evidence_file.is_file()
        persisted = json.loads(evidence_file.read_text(encoding="utf-8"))
        assert persisted["outcome"] == "completed"
        assert persisted["transaction_id"] == body["transaction_id"]
        assert "is_noop" in persisted["steps"][0]

    def test_migration_unapproved_folders_never_touched(
            self, empty_client: TestClient, monkeypatch):
        root = self._legacy_world()
        _principal(monkeypatch)
        resp = self._execute(empty_client, folders=["Lore"])
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert [step["folder"] for step in body["steps"]] == ["Lore"]
        assert (root / "lore").is_dir()
        if _fs_case_insensitive():
            # Natural noop: `Lore` still resolves (same physical dir).
            assert (root / "Lore").is_dir()
        else:
            assert not (root / "Lore").exists()
        # The unapproved legacy folder stays exactly as it was (no auto-rename).
        assert (root / "Personajes").is_dir()
        assert (root / "Personajes" / "pc.md").exists()
        if not _fs_case_insensitive():
            assert not (root / "personajes").exists()

    def test_migration_same_physical_directory_is_noop_not_409(
            self, empty_client: TestClient, monkeypatch):
        """R-CIM-04 — when source and destination are the same physical
        directory (simulated here on Linux; natural on case-insensitive FS),
        the endpoint returns 200 with a noop step instead of HTTP 409."""
        root = self._legacy_world()
        # Mirror the canonical tree so the noop evidence hash is computable on
        # case-sensitive Linux; on case-insensitive FS it already IS the same
        # physical directory.
        if not (root / "lore").exists():
            (root / "lore").mkdir()
            (root / "lore" / "00_inicio.md").write_text("# X\n", encoding="utf-8")
        if not (root / "personajes").exists():
            (root / "personajes").mkdir()
            (root / "personajes" / "pc.md").write_text("# PC\n", encoding="utf-8")
        _principal(monkeypatch)
        monkeypatch.setattr(
            migration_module, "_is_same_physical_directory", lambda _s, _d: True)
        resp = self._execute(empty_client)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert all(step["is_noop"] for step in body["steps"])
        # Nothing moved; legacy-cased folders still resolve.
        assert (root / "Lore").is_dir()
        assert (root / "Personajes").is_dir()

    def test_migration_mid_transaction_failure_rolls_back_with_evidence(
            self, empty_client: TestClient, monkeypatch):
        if _fs_case_insensitive():
            pytest.skip("rollback only applies to real moves, which never "
                        "happen for noop steps on case-insensitive FS")
        root = self._legacy_world()
        _principal(monkeypatch)
        real_move = migration_module._atomic_move
        calls = {"n": 0}

        def failing_move(source, destination):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("injected failure before second move")
            return real_move(source, destination)

        monkeypatch.setattr(migration_module, "_atomic_move", failing_move)
        resp = self._execute(empty_client)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rolled_back"
        assert body["restore_verified"] is True
        assert body["error"]
        # Originals restored; lowercase destinations absent.
        assert (root / "Lore" / "00_inicio.md").exists()
        assert (root / "Personajes" / "pc.md").exists()
        assert not (root / "lore").exists()
        assert not (root / "personajes").exists()
        evidence_file = self._evidence_file(body["transaction_id"])
        assert evidence_file.is_file()
        persisted = json.loads(evidence_file.read_text(encoding="utf-8"))
        assert persisted["outcome"] == "rolled_back"
        assert persisted["restore_verified"] is True

    def test_migration_evidence_write_failure_maps_to_io_error(
            self, empty_client: TestClient, monkeypatch):
        """Engine's IO_ERROR (evidence persist failure) maps to HTTP 500."""
        root = self._legacy_world()
        _principal(monkeypatch)

        def failing_evidence(evidence, evidence_dir):
            raise migration_module.MigrationError(
                migration_module.MigrationErrorKind.IO_ERROR,
                "evidence could not be persisted (injected)",
                evidence.transaction_id,
            )

        monkeypatch.setattr(
            migration_module, "_persist_evidence", failing_evidence)
        resp = self._execute(empty_client)
        assert resp.status_code == 500
        body = resp.json()
        assert body["code"] == "io_error"
        assert body["transaction_id"].startswith("mig-")


# ---------------------------------------------------------------------------
# ONB-1.9 — CORS: env-based origin allowlist; credentials never wildcard
# ---------------------------------------------------------------------------


class TestCorsPolicy:
    def test_default_config_allows_local_dev_origins_with_credentials(self, monkeypatch):
        monkeypatch.delenv("DEMIURGOS_CORS_ORIGINS", raising=False)
        cfg = api_server._cors_config()
        assert "http://localhost:5173" in cfg["origins"]
        assert cfg["allow_credentials"] is True
        assert "*" not in cfg["origins"]

    def test_env_allowlist_replaces_default(self, monkeypatch):
        monkeypatch.setenv("DEMIURGOS_CORS_ORIGINS", "https://app.example, https://beta.example")
        cfg = api_server._cors_config()
        assert cfg["origins"] == ["https://app.example", "https://beta.example"]
        assert cfg["allow_credentials"] is True

    def test_wildcard_never_grants_credentials(self, monkeypatch):
        monkeypatch.setenv("DEMIURGOS_CORS_ORIGINS", "*")
        cfg = api_server._cors_config()
        assert cfg["origins"] == ["*"]
        assert cfg["allow_credentials"] is False

    def test_preflight_allows_known_origin(self, client: TestClient):
        resp = client.options(
            "/api/onboarding/status",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code in (200, 400)
        if resp.status_code == 200:
            assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_preflight_rejects_unknown_origin(self, client: TestClient):
        resp = client.options(
            "/api/onboarding/status",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        if resp.status_code == 200:
            assert "access-control-allow-origin" not in resp.headers


# ---------------------------------------------------------------------------
# ONB-1.6 — Locale endpoint (G7/OC3 independent domains + IANA zone)
# ---------------------------------------------------------------------------


class TestLocaleEndpoint:
    def test_default_locale_is_safe(self, empty_client: TestClient):
        resp = empty_client.get("/api/locale")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ui"] == "es"
        assert body["conversation"] == "es"
        assert body["content"] == "es"
        assert body["iana_timezone"] == "UTC"

    def test_locale_reflects_persisted_step0(
            self, empty_client: TestClient, monkeypatch):
        _principal(monkeypatch)
        _post_step0(empty_client,
                    ui="en", conversation="es", content="es",
                    iana_timezone="Europe/Madrid")
        body = empty_client.get("/api/locale").json()
        assert body["ui"] == "en"
        assert body["conversation"] == "es"
        assert body["iana_timezone"] == "Europe/Madrid"


# ---------------------------------------------------------------------------
# ONB-1.8 — Readiness probe endpoint (local_editor essential badge)
# ---------------------------------------------------------------------------


class TestReadinessEndpoint:
    def test_local_editor_probe_round_trips(self, empty_client: TestClient):
        resp = empty_client.get("/api/onboarding/readiness")
        assert resp.status_code == 200
        body = resp.json()
        assert body["local_editor"]["ok"] is True
        assert body["cards"]["world"] == "pending"
        assert body["cards"]["identity"] == "pending"
        assert body["cards"]["telegram"] == "pending"


# ---------------------------------------------------------------------------
# ONB-3.1 — Readiness truthfulness: cloud cards never ready from local
# evidence; assistant pending without the three proofs (OC11/OC12/OC21).
# The projection must NOT trust registry claims for remote capabilities —
# only their dedicated contracts may mark them configured, and none exists
# for identity/telegram/backup in this slice.
# ---------------------------------------------------------------------------


class TestReadinessTruthfulness:
    def test_cloud_cards_never_configured_from_local_registry_claims(
            self, empty_client: TestClient):
        """A stale/buggy local registry entry claiming cloud capabilities
        configured must be downgraded: remote cards stay pending."""
        registry = api_server._local_state()
        state = registry.snapshot()
        state["capabilities"]["identity"] = "configured"
        state["capabilities"]["telegram"] = "configured"
        state["capabilities"]["backup"] = "configured"
        registry.atomic_commit(state)

        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["identity"] == "pending"
        assert body["cards"]["telegram"] == "pending"
        assert body["cards"]["backup"] == "pending"

    def test_assistant_pending_without_three_proofs(self, empty_client: TestClient):
        """A registry claim of a configured assistant is not proof: without
        the text+vision+runtime acceptance evidence the card stays pending."""
        registry = api_server._local_state()
        state = registry.snapshot()
        state["capabilities"]["assistant"] = "configured"
        registry.atomic_commit(state)

        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["assistant"] == "pending"

    def test_assistant_configured_only_with_all_three_proofs(
            self, empty_client: TestClient):
        """Only recorded text+vision+runtime acceptance evidence completes
        the assistant card; the claim alone never does."""
        registry = api_server._local_state()
        state = registry.snapshot()
        state["capabilities"]["assistant"] = "configured"
        state["assistant_acceptance"] = {
            "text": "passed",
            "vision": "passed",
            "runtime": "accepted",
        }
        registry.atomic_commit(state)

        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["assistant"] == "configured"

    def test_assistant_pending_when_any_proof_missing(self, empty_client: TestClient):
        """Partial evidence (e.g. only text+vision) must not configure."""
        registry = api_server._local_state()
        state = registry.snapshot()
        state["capabilities"]["assistant"] = "configured"
        state["assistant_acceptance"] = {"text": "passed", "vision": "passed"}
        registry.atomic_commit(state)

        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["assistant"] == "pending"

    def test_world_badge_derives_from_filesystem_truth(self, empty_client: TestClient):
        """The world badge follows filesystem truth: a real world dir turns
        the card configured; no world keeps it pending."""
        registry = api_server._local_state()
        state = registry.snapshot()
        state["capabilities"]["world"] = "configured"
        registry.atomic_commit(state)

        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["world"] == "pending"

        (api_server.MUNDOS_DIR / "real_world").mkdir()
        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["world"] == "configured"

    def test_locale_and_offline_derive_from_local_truth(self, empty_client: TestClient):
        """locale follows persisted step-0; offline follows the storage probe."""
        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["locale"] == "pending"
        assert body["cards"]["offline"] == "configured"

        registry = api_server._local_state()
        state = registry.snapshot()
        state["locale"] = {"ui": "es", "conversation": "es", "content": "es"}
        registry.atomic_commit(state)
        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["locale"] == "configured"


# ---------------------------------------------------------------------------
# assistant-activation-status (WU-2a) — the Telegram probe + token lifecycle
# moved onto the idea-capture path (the token owner). Additive slice: the
# legacy TestTelegramSettings class below stays green until retirement (WU-2b).
# ---------------------------------------------------------------------------


class _SpyRegistry:
    """LocalState-like spy capturing evidence commits for injection tests."""

    def __init__(self) -> None:
        self._state: dict = {}
        self.commits: list[dict] = []

    def snapshot(self) -> dict:
        return dict(self._state)

    def atomic_commit(self, next_state) -> int:
        self._state = dict(next_state)
        self.commits.append(dict(next_state))
        return len(self.commits)


class TestIdeaCaptureProbe:
    """WU-2a — POST /api/idea-capture/test-connection (probe relocated)."""

    SECRET = "123456789:AA-test-secret"

    def _authed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _principal(monkeypatch)

    def _save_token(self, client: TestClient, token: str | None = None):
        return client.post("/api/idea-capture/token",
                           json={"token": self.SECRET if token is None else token})

    def _probe(self, client: TestClient):
        return client.post("/api/idea-capture/test-connection")

    def _evidence(self) -> dict | None:
        return api_server._local_state().snapshot().get("telegram_evidence")

    def test_probe_fails_closed_without_principal(self, empty_client: TestClient):
        assert self._probe(empty_client).status_code == 401

    def test_probe_success_commits_configured_evidence(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        self._authed(monkeypatch)
        self._save_token(empty_client)

        seen_urls: list[str] = []

        class _Resp:
            status_code = 200

            def json(self):
                return {"ok": True, "result": {"id": 123, "username": "demo_bot"}}

        def _get(url, *args, **kwargs):
            seen_urls.append(url)
            return _Resp()

        monkeypatch.setattr(telegram_settings.requests, "get", _get)

        resp = self._probe(empty_client)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["state"] == "configured"
        assert body["has_token"] is True
        assert body["error_code"] == ""
        datetime.fromisoformat(body["tested_at"])
        assert self.SECRET not in resp.text

        # The pure helper ran against the STORED token (read server-side).
        assert seen_urls and self.SECRET in seen_urls[0]

        # Committed evidence reuses the EXACT {state, tested_at, error_code} shape.
        evidence = self._evidence()
        assert set(evidence) == {"state", "tested_at", "error_code"}
        assert evidence["state"] == "configured"
        assert evidence["error_code"] == ""
        datetime.fromisoformat(evidence["tested_at"])

        # The authoritative readiness projector agrees.
        cards = empty_client.get("/api/onboarding/readiness").json()["cards"]
        assert cards["telegram"] == "configured"

    def test_probe_offline_maps_to_requires_connection(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        self._authed(monkeypatch)
        self._save_token(empty_client)

        def _offline(*args, **kwargs):
            raise requests.ConnectionError("offline")

        monkeypatch.setattr(telegram_settings.requests, "get", _offline)
        resp = self._probe(empty_client)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["state"] == "requires_connection"
        assert body["error_code"] == "network"
        assert self._evidence()["state"] == "requires_connection"
        cards = empty_client.get("/api/onboarding/readiness").json()["cards"]
        assert cards["telegram"] == "requires_connection"

    def test_probe_invalid_token_maps_to_error(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        self._authed(monkeypatch)
        self._save_token(empty_client)

        class _Resp:
            status_code = 401

            def json(self):
                return {"ok": False, "error_code": 401, "description": "Unauthorized"}

        monkeypatch.setattr(telegram_settings.requests, "get",
                            lambda *a, **k: _Resp())
        resp = self._probe(empty_client)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["state"] == "error"
        assert body["error_code"] == "invalid_token"
        assert self._evidence()["state"] == "error"
        cards = empty_client.get("/api/onboarding/readiness").json()["cards"]
        assert cards["telegram"] == "error"

    def test_probe_without_token_returns_409_without_probe_or_evidence(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        self._authed(monkeypatch)
        calls = {"n": 0}

        def _boom(*args, **kwargs):
            calls["n"] += 1
            raise AssertionError("no Telegram call is allowed without a token")

        monkeypatch.setattr(telegram_settings.requests, "get", _boom)
        resp = self._probe(empty_client)
        assert resp.status_code == 409
        assert resp.json()["code"] == "no_token"
        assert calls["n"] == 0
        assert self._evidence() is None

    def test_injected_registry_receives_evidence_not_the_global(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        from fastapi import FastAPI

        self._authed(monkeypatch)
        self._save_token(empty_client)
        before = self._evidence()

        spy = _SpyRegistry()
        probe_app = FastAPI()
        probe_app.include_router(
            idea_capture_ui.create_idea_capture_router(
                require_principal=lambda request: api_server.EditPrincipal("tester"),
                registry=lambda: spy,
            )
        )

        class _Resp:
            status_code = 200

            def json(self):
                return {"ok": True, "result": {"id": 1}}

        monkeypatch.setattr(telegram_settings.requests, "get",
                            lambda *a, **k: _Resp())
        resp = TestClient(probe_app).post("/api/idea-capture/test-connection")
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == "configured"
        assert spy.commits, "the injected registry must receive the commit"
        assert spy.commits[-1]["telegram_evidence"]["state"] == "configured"
        # The module-global registry was NOT touched by the injected probe.
        assert self._evidence() == before

    def test_unwired_registry_fails_loudly(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        from fastapi import FastAPI

        self._authed(monkeypatch)
        self._save_token(empty_client)

        probe_app = FastAPI()
        probe_app.include_router(
            idea_capture_ui.create_idea_capture_router(
                require_principal=lambda request: api_server.EditPrincipal("tester"),
            )
        )

        class _Resp:
            status_code = 200

            def json(self):
                return {"ok": True, "result": {"id": 1}}

        monkeypatch.setattr(telegram_settings.requests, "get",
                            lambda *a, **k: _Resp())
        client = TestClient(probe_app, raise_server_exceptions=False)
        resp = client.post("/api/idea-capture/test-connection")
        assert resp.status_code == 500

    def test_evidence_survives_restart(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        self._authed(monkeypatch)
        self._save_token(empty_client)

        class _Resp:
            status_code = 200

            def json(self):
                return {"ok": True, "result": {"id": 123}}

        monkeypatch.setattr(telegram_settings.requests, "get",
                            lambda *a, **k: _Resp())
        self._probe(empty_client)

        # Simulate a process restart: a fresh LocalState reads the same file.
        api_server._LOCAL_STATE = None
        cards = empty_client.get("/api/onboarding/readiness").json()["cards"]
        assert cards["telegram"] == "configured"

    def test_probe_token_never_logged(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog):
        self._authed(monkeypatch)
        self._save_token(empty_client)

        class _Resp:
            status_code = 200

            def json(self):
                return {"ok": True, "result": {"id": 123}}

        monkeypatch.setattr(telegram_settings.requests, "get",
                            lambda *a, **k: _Resp())
        with caplog.at_level(logging.INFO):
            self._probe(empty_client)
        assert self.SECRET not in caplog.text


class TestIdeaCaptureTokenLifecycle:
    """WU-2a (corrective) — token save/delete own the evidence lifecycle."""

    SECRET = "123456789:AA-test-secret"

    def _authed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _principal(monkeypatch)

    def _save_token(self, client: TestClient, token: str | None = None):
        return client.post("/api/idea-capture/token",
                           json={"token": self.SECRET if token is None else token})

    def _delete_token(self, client: TestClient):
        return client.delete("/api/idea-capture/token")

    def _evidence(self) -> dict | None:
        return api_server._local_state().snapshot().get("telegram_evidence")

    def _card(self, client: TestClient) -> str:
        return client.get("/api/onboarding/readiness").json()["cards"]["telegram"]

    def test_save_commits_fresh_requires_connection_evidence(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        self._authed(monkeypatch)
        resp = self._save_token(empty_client)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"state": "requires_connection", "has_token": True}
        assert self.SECRET not in resp.text
        assert self._evidence() == {
            "state": "requires_connection", "tested_at": None, "error_code": "",
        }
        assert self._card(empty_client) == "requires_connection"

    def test_delete_pops_evidence_and_returns_pending(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        self._authed(monkeypatch)
        self._save_token(empty_client)
        resp = self._delete_token(empty_client)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"state": "pending", "has_token": False}
        env = (api_server.PROJECT_ROOT / ".env").read_text(encoding="utf-8")
        assert "TELEGRAM_BOT_TOKEN" not in env
        assert self._evidence() is None
        assert self._card(empty_client) == "pending"

    def test_invalid_token_rejected_without_mutation(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        self._authed(monkeypatch)
        for bad in ("", "   ", "abc def", "x" * 300):
            resp = self._save_token(empty_client, token=bad)
            assert resp.status_code == 400, resp.text
        env = api_server.PROJECT_ROOT / ".env"
        assert not env.exists() or "TELEGRAM_BOT_TOKEN" not in env.read_text(encoding="utf-8")
        assert self._evidence() is None

    def test_token_never_appears_in_responses_or_logs(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog):
        self._authed(monkeypatch)
        with caplog.at_level(logging.INFO):
            save = self._save_token(empty_client)
            delete = self._delete_token(empty_client)
        assert self.SECRET not in save.text
        assert self.SECRET not in delete.text
        assert self.SECRET not in caplog.text

    def test_stale_configured_cannot_survive_a_delete_and_resave(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        self._authed(monkeypatch)
        # Seed a token + stale configured evidence, as if an old probe succeeded.
        idea_capture_ui.write_env_var(idea_capture_ui._ENV_TOKEN_NAME, self.SECRET)
        registry = api_server._local_state()
        state = registry.snapshot()
        state["telegram_evidence"] = {
            "state": "configured",
            "tested_at": "2026-01-01T00:00:00+00:00",
            "error_code": "",
        }
        registry.atomic_commit(state)
        assert self._card(empty_client) == "configured"  # precondition

        # Save a fresh token → fresh untested evidence replaces the stale one.
        resp = self._save_token(empty_client)
        assert resp.json() == {"state": "requires_connection", "has_token": True}
        assert self._card(empty_client) == "requires_connection"
        assert self._card(empty_client) != "configured"

        # Delete → evidence popped, card pending.
        resp = self._delete_token(empty_client)
        assert resp.json() == {"state": "pending", "has_token": False}
        assert self._card(empty_client) == "pending"


class TestIdeaCaptureMigratedTelegramGuarantees:
    """WU-2a — parity port of the legacy TestTelegramSettings guarantees onto
    the idea-capture routes, asserted through the readiness projector and the
    save/delete/probe response bodies. Kept alongside TestTelegramSettings."""

    SECRET = "123456789:AA-test-secret"

    def _authed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _principal(monkeypatch)

    def test_relocated_routes_fail_closed_without_principal(self, empty_client: TestClient):
        assert empty_client.get("/api/idea-capture/status").status_code == 401
        assert empty_client.post("/api/idea-capture/token",
                                 json={"token": self.SECRET}).status_code == 401
        assert empty_client.delete("/api/idea-capture/token").status_code == 401
        assert empty_client.post("/api/idea-capture/test-connection").status_code == 401

    def test_status_and_readiness_pending_without_token(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        self._authed(monkeypatch)
        status = empty_client.get("/api/idea-capture/status")
        assert status.json()["has_token"] is False
        assert self.SECRET not in status.text
        cards = empty_client.get("/api/onboarding/readiness").json()["cards"]
        assert cards["telegram"] == "pending"

    def test_token_write_only_readiness_requires_connection(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        self._authed(monkeypatch)
        resp = empty_client.post("/api/idea-capture/token", json={"token": self.SECRET})
        assert resp.status_code == 200, resp.text
        assert self.SECRET not in resp.text
        env = (api_server.PROJECT_ROOT / ".env").read_text(encoding="utf-8")
        assert f"TELEGRAM_BOT_TOKEN={self.SECRET}" in env
        status = empty_client.get("/api/idea-capture/status")
        assert self.SECRET not in status.text
        assert status.json()["has_token"] is True
        cards = empty_client.get("/api/onboarding/readiness").json()["cards"]
        assert cards["telegram"] == "requires_connection"

    def test_probe_outcome_mapping_and_restart(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        self._authed(monkeypatch)
        empty_client.post("/api/idea-capture/token", json={"token": self.SECRET})

        class _Resp:
            status_code = 200

            def json(self):
                return {"ok": True, "result": {"id": 123}}

        monkeypatch.setattr(telegram_settings.requests, "get",
                            lambda *a, **k: _Resp())
        probe = empty_client.post("/api/idea-capture/test-connection")
        assert probe.status_code == 200, probe.text
        assert probe.json()["state"] == "configured"
        assert self.SECRET not in probe.text
        assert empty_client.get("/api/onboarding/readiness").json()["cards"]["telegram"] == "configured"

        # Offline remaps to requires_connection (retryable).
        def _offline(*args, **kwargs):
            raise requests.ConnectionError("offline")

        monkeypatch.setattr(telegram_settings.requests, "get", _offline)
        probe = empty_client.post("/api/idea-capture/test-connection")
        assert probe.json()["state"] == "requires_connection"
        assert probe.json()["error_code"] == "network"

        # Restart: a fresh LocalState reads the same file back.
        api_server._LOCAL_STATE = None
        cards = empty_client.get("/api/onboarding/readiness").json()["cards"]
        assert cards["telegram"] == "requires_connection"


# ---------------------------------------------------------------------------
# ONB-3.4 — offline continuation: readiness is public and independent of auth,
# the local core keeps working offline, and expired local sessions are never
# reused (OC5/OC19). The offline breakdown was removed from the payload
# (product-owner decision): the card map alone carries that state.
# ---------------------------------------------------------------------------


class TestOfflineContinuation:
    """ONB-3.4 — offline continuation (WU-3c)."""

    def test_readiness_no_longer_reports_the_offline_breakdown(
            self, empty_client: TestClient):
        """The readiness payload no longer carries an ``offline`` key; the
        card map keeps its shape and the local core stays configured."""
        body = empty_client.get("/api/onboarding/readiness").json()
        assert "offline" not in body
        assert body["cards"]["offline"] == "configured"

    def test_readiness_card_reports_error_when_probe_fails(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        """When the storage probe fails the offline card reports error and no
        offline breakdown is emitted."""
        monkeypatch.setattr(
            api_server,
            "probe_local_storage",
            lambda root: {"probe": "local_editor", "ok": False, "detail": "read-only"},
        )
        body = empty_client.get("/api/onboarding/readiness").json()
        assert "offline" not in body
        assert body["cards"]["offline"] == "error"

    def test_offline_readiness_is_public_without_auth(self, empty_client: TestClient):
        """The local core must not depend on authentication: readiness (local
        work available offline) reads fine without any principal."""
        resp = empty_client.get("/api/onboarding/readiness")
        assert resp.status_code == 200

    def test_expired_local_session_is_never_reused(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        """An expired local-dev session must not authorize gated writes: it is
        pruned on access and every write fails closed (OC1/OC5 — expired
        authorization is never reused). The vault flag is ON so the
        onboarding/world gates are active (S-AC-02b/d)."""
        monkeypatch.setenv("DEMIURGOS_AUTH_MODE", "local-dev")
        registry = api_server._local_state()
        state = registry.snapshot()
        state.setdefault("capabilities", {})["vault"] = {
            "enabled": True, "reauth_interval_d": 14}
        registry.atomic_commit(state)
        started = empty_client.post("/api/auth/local-dev/session")
        assert started.status_code == 200
        # Expire the stored session directly (simulates TTL passage).
        with api_server._local_session_lock:
            for record in api_server._local_sessions.values():
                record["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

        status = empty_client.get("/api/auth/local-dev/session").json()
        assert status["authenticated"] is False
        assert _post_step0(empty_client).status_code == 401
        assert empty_client.post("/api/worlds", json={"name": "x"}).status_code == 401


# ---------------------------------------------------------------------------
# ONB-3.5 — Import handoff card: entry/pending/error only, never configured.
# The importer stays a separate SDD; this change exposes no fake completion.
# ---------------------------------------------------------------------------


class TestImportHandoff:
    """ONB-3.5 — import handoff (WU-3c)."""

    def test_import_card_always_pending_never_configured(
            self, empty_client: TestClient):
        """The importer has no dedicated contract in this change: the card
        reports pending even when a stale registry claim says configured."""
        registry = api_server._local_state()
        state = registry.snapshot()
        state["capabilities"]["import"] = "configured"
        registry.atomic_commit(state)

        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["import"] == "pending"


# ---------------------------------------------------------------------------
# ONB-3.6 — Assistant badge evidence wiring: the three-proof acceptance is
# recorded in the registry so the badge may become configured ONLY when the
# runtime accepted the model; otherwise it stays pending/no-apto (OC19).
# ---------------------------------------------------------------------------


class TestAssistantEvidence:
    """ONB-3.6 — assistant acceptance evidence (WU-3c)."""

    def test_accepted_runtime_records_evidence_and_configures_badge(
            self, empty_client: TestClient):
        api_server._record_assistant_acceptance("accepted")
        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["assistant"] == "configured"

    def test_pending_reload_runtime_keeps_badge_pending(
            self, empty_client: TestClient):
        api_server._record_assistant_acceptance("pending-reload")
        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["assistant"] == "pending"

    def test_saved_not_active_runtime_keeps_badge_pending(
            self, empty_client: TestClient):
        api_server._record_assistant_acceptance("saved-not-active")
        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["assistant"] == "pending"

    def test_runtime_state_requires_live_gateway_and_matching_acceptance(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        class _Probe:
            def __init__(self, running: bool) -> None:
                self._running = running

            def is_running(self) -> bool:
                return self._running

        registry = api_server._local_state()
        state = registry.snapshot()
        state["assistant_acceptance"] = {
            "text": "passed", "vision": "passed", "runtime": "accepted", "revision": 3,
        }
        registry.atomic_commit(state)

        monkeypatch.setattr(api_server, "_assistant_gateway_probe", lambda: _Probe(True))
        assert api_server._resolve_assistant_runtime_state(3) == "active"
        # A different revision has no acceptance -> pending, never active.
        assert api_server._resolve_assistant_runtime_state(4) == "pending-reload"

        monkeypatch.setattr(api_server, "_assistant_gateway_probe", lambda: _Probe(False))
        assert api_server._resolve_assistant_runtime_state(3) == "saved-not-active"

    def test_down_save_never_resolves_active_after_gateway_returns(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        """F-2 regression: the resolver honours the recorded ``runtime`` field.

        A save while the gateway is down records ``runtime="saved-not-active"``
        for the persisted revision — exactly what ``_record_assistant_acceptance``
        writes, which is the real save path's recorder. When the gateway later
        comes up, the SAME evidence must not resolve to ``active``: the recorded
        acceptance is the arbiter, and the readiness projection requires
        ``runtime == "accepted"``. Flipping liveness from false to true must
        never manufacture ``active`` (the panel and the card stay in agreement).
        """
        class _Probe:
            def __init__(self, running: bool) -> None:
                self._running = running

            def is_running(self) -> bool:
                return self._running

        # The down-time save persisted this acceptance for revision 11.
        monkeypatch.setattr(
            api_server.assistant_settings, "current_config_revision", lambda: 11
        )
        api_server._record_assistant_acceptance("saved-not-active")
        evidence = api_server._local_state().snapshot()["assistant_acceptance"]
        assert evidence == {
            "text": "passed",
            "vision": "passed",
            "runtime": "saved-not-active",
            "revision": 11,
        }

        # Gateway still down: fail closed.
        monkeypatch.setattr(api_server, "_assistant_gateway_probe", lambda: _Probe(False))
        assert api_server._resolve_assistant_runtime_state(11) == "saved-not-active"

        # Gateway comes up later: the down-time acceptance stays non-active.
        monkeypatch.setattr(api_server, "_assistant_gateway_probe", lambda: _Probe(True))
        resumed = api_server._resolve_assistant_runtime_state(11)
        assert resumed == "pending-reload"
        assert resumed != "active"

        # The Configuration Center card reads the same evidence and agrees.
        body = empty_client.get("/api/onboarding/readiness").json()
        assert body["cards"]["assistant"] == "pending"

    def test_acceptance_records_the_current_revision(
            self, empty_client: TestClient, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(api_server.assistant_settings, "current_config_revision", lambda: 17)
        api_server._record_assistant_acceptance("active")
        evidence = api_server._local_state().snapshot()["assistant_acceptance"]
        assert evidence["revision"] == 17
        assert evidence["runtime"] == "accepted"


# ---------------------------------------------------------------------------
# BLOQUE 4 — GET /api/{mundo}/graph/entities (bulk entities + links)
# ---------------------------------------------------------------------------


class TestGraphEntitiesEndpoint:
    """GET /api/{mundo}/graph/entities — status field + status filter contract.

    Filter/link tests preload a REAL EntityGraphIndex with synthetic entity
    dicts so the endpoint exercises the actual ``_resolve_link`` resolution
    against the cache (ids/names) instead of a stub. Backward-compat and
    empty-world tests run against the natural fixture world (no stubbing).
    """

    @staticmethod
    def _index_with(entities: list[dict]) -> EntityGraphIndex:
        idx = EntityGraphIndex(mundos_path=Path("/nonexistent"))
        idx._cache["entities"] = {e["path"]: e for e in entities}
        return idx

    @staticmethod
    def _synthetic_world() -> list[dict]:
        """52 entities (26 stable, 26 draft) with same-parity ring links."""
        entities = []
        for i in range(52):
            name = f"Entidad {i:02d}"
            status = "stable" if i % 2 == 0 else "draft"
            entities.append({
                "name": name,
                "id": f"Catalogo::{name}",
                "type": "personaje" if i % 2 == 0 else "lugar",
                "path": f"personajes/{name}.md" if i % 2 == 0 else f"lore/{name}.md",
                "title": name,
                "description": f"Descripción de {name}",
                "tags": ["prueba"],
                "status": status,
                # Same-parity ring: every entity links to the next of its own
                # status class, so a single-status filter keeps exactly its
                # own subgraph edges (spec S2.5).
                "forward_links": [f"Entidad {(i + 2) % 52:02d}"],
                "backlinks": [],
                "content": "",
            })
        return entities

    def test_graph_entities_status_field(self, client: TestClient, monkeypatch):
        index = self._index_with(self._synthetic_world())
        monkeypatch.setattr(api_server, "_get_graph", lambda _world: index)
        resp = client.get("/api/test_mundo/graph/entities?status=all")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"entities", "links"}
        assert len(body["entities"]) == 52
        for ent in body["entities"]:
            assert set(ent.keys()) == {
                "id", "name", "type", "path", "status",
                "description", "tags", "forward_links", "backlinks",
                "content", "relaciones",
            }
        assert body["entities"][0]["status"] in ("draft", "stable")

    def test_graph_entities_content_and_relaciones(self, client: TestClient, monkeypatch):
        """The bulk payload ships content + relaciones per entity.

        Missing keys default to ``""`` / ``[]`` (never null or absent), and
        legacy entities (empty id) emit both fields alongside their
        path-based node key (REQ-BULK-1/BULK-3).
        """
        entities = [
            {
                "name": "Rhyz",
                "id": "Stal::Rhyz",
                "type": "personaje",
                "path": "personajes/Rhyz.md",
                "status": "stable",
                "forward_links": [],
                "backlinks": [],
                "content": "Rhyz es un cazador de la estepa.",
                "relaciones": ["Stal::Vael"],
            },
            {
                # No content/relaciones keys → empty defaults.
                "name": "Vael",
                "id": "Stal::Vael",
                "type": "personaje",
                "path": "personajes/Vael.md",
                "status": "draft",
                "forward_links": [],
                "backlinks": [],
            },
            {
                # Legacy entity: empty canonical id → path-based node key;
                # the new fields are still emitted.
                "name": "Dottua",
                "id": "",
                "type": "lugar",
                "path": "lore/Dottua.md",
                "status": "stable",
                "forward_links": [],
                "backlinks": [],
                "content": "Dottua es una región del sur.",
                "relaciones": [],
            },
        ]
        index = self._index_with(entities)
        monkeypatch.setattr(api_server, "_get_graph", lambda _world: index)
        body = client.get("/api/test_mundo/graph/entities?status=all").json()

        by_path = {e["path"]: e for e in body["entities"]}

        # Full content + relaciones round-trip untouched.
        rhyz = by_path["personajes/Rhyz.md"]
        assert rhyz["content"] == "Rhyz es un cazador de la estepa."
        assert rhyz["relaciones"] == ["Stal::Vael"]

        # Missing keys default to "" / [] — never null or absent.
        vael = by_path["personajes/Vael.md"]
        assert vael["content"] == ""
        assert vael["relaciones"] == []

        # Legacy entity (empty id) still emits both fields.
        dottua = by_path["lore/Dottua.md"]
        assert dottua["id"] == ""
        assert dottua["content"] == "Dottua es una región del sur."
        assert dottua["relaciones"] == []

    def test_graph_entities_filter_all(self, client: TestClient, monkeypatch):
        index = self._index_with(self._synthetic_world())
        monkeypatch.setattr(api_server, "_get_graph", lambda _world: index)
        body = client.get("/api/test_mundo/graph/entities?status=all").json()
        assert len(body["entities"]) == 52
        # Same-parity ring: 52 entities, each with one forward link → 52 links.
        assert len(body["links"]) == 52

    def test_graph_entities_filter_stable(self, client: TestClient, monkeypatch):
        index = self._index_with(self._synthetic_world())
        monkeypatch.setattr(api_server, "_get_graph", lambda _world: index)
        body = client.get("/api/test_mundo/graph/entities?status=stable").json()
        assert len(body["entities"]) == 26
        assert all(e["status"] == "stable" for e in body["entities"])
        assert len(body["links"]) == 26
        assert all(l["source"] != l["target"] for l in body["links"])

    def test_graph_entities_filter_draft(self, client: TestClient, monkeypatch):
        index = self._index_with(self._synthetic_world())
        monkeypatch.setattr(api_server, "_get_graph", lambda _world: index)
        body = client.get("/api/test_mundo/graph/entities?status=draft").json()
        assert len(body["entities"]) == 26
        assert all(e["status"] == "draft" for e in body["entities"])
        assert len(body["links"]) == 26

    def test_graph_entities_invalid_status_422(self, client: TestClient, monkeypatch):
        index = self._index_with(self._synthetic_world())
        monkeypatch.setattr(api_server, "_get_graph", lambda _world: index)
        resp = client.get("/api/test_mundo/graph/entities?status=banana")
        assert resp.status_code == 422

    def test_graph_entities_empty_world(self, client: TestClient):
        # Unknown mundo: _get_graph returns None → soft-empty contract
        # (same as /graph/search, spec S1.6).
        resp = client.get("/api/mundo_fantasma/graph/entities?status=all")
        assert resp.status_code == 200
        assert resp.json() == {"entities": [], "links": []}

    def test_graph_entities_backward_compat(self, client: TestClient):
        """Existing per-entity graph endpoints keep their contract unchanged.

        The fixture world has exactly one OKF ficha (lore/00_inicio.md, no
        status frontmatter → draft).
        """
        # /graph/search keeps the EntityHit shape (no status/id).
        search = client.get("/api/test_mundo/graph/search?q=inicio").json()
        assert search and "status" not in search[0] and "id" not in search[0]

        # /graph/entity keeps its detail shape (no status/id required there).
        detail = client.get("/api/test_mundo/graph/entity?name=Inicio").json()
        assert detail["path"] == "lore/00_inicio.md"
        assert "status" not in detail and "id" not in detail

        # /graph/links still responds for the entity.
        links = client.get("/api/test_mundo/graph/links?name=Inicio").json()
        assert isinstance(links, list)

        # /graph/status still reports node/link counts.
        status = client.get("/api/test_mundo/graph/status").json()
        assert status["node_count"] == 1

        # The new bulk endpoint reports the same single entity as draft.
        body = client.get("/api/test_mundo/graph/entities?status=all").json()
        assert len(body["entities"]) == 1
        assert body["entities"][0]["path"] == "lore/00_inicio.md"
        assert body["entities"][0]["status"] == "draft"

    def test_graph_entities_legacy_no_id_links_use_path(
            self, client: TestClient, monkeypatch):
        """Legacy entities (empty canonical id) emit links keyed by path.

        WARNING 1 (relaciones-canon-panel, BLOQUE 4 Slice A): worlds whose
        entities have no canonical ``id`` used to emit ``{source:"",target:""}``
        edges, which GraphView (nodeKey = id || path) filters out — legacy
        worlds rendered with zero edges despite having forward_links. The
        endpoint must fall back to the entity ``path`` so every edge references
        a node key the frontend matches.
        """
        entities = []
        for i in range(4):
            name = f"Legacy {i:02d}"
            entities.append({
                "name": name,
                "id": "",  # legacy world: no canonical id
                "type": "personaje",
                "path": f"lore/{name}.md",
                "title": name,
                "description": "",
                "tags": [],
                "status": "draft",
                "forward_links": [f"Legacy {(i + 1) % 4:02d}"],
                "backlinks": [],
                "content": "",
            })
        index = self._index_with(entities)
        monkeypatch.setattr(api_server, "_get_graph", lambda _world: index)
        body = client.get("/api/test_mundo/graph/entities?status=all").json()
        paths = {e["path"] for e in body["entities"]}
        assert len(body["entities"]) == 4
        assert len(body["links"]) == 4
        for link in body["links"]:
            # source/target reference node keys the frontend matches (paths).
            assert link["source"] in paths
            assert link["target"] in paths
            assert link["source"] != link["target"]


class TestGlobalAssistantContext:
    """GAP-A: the world-agnostic ``ideas-global`` assistant context.

    The Taller de Ideas assistant is world-agnostic and sends
    ``mundo == GLOBAL_ASSISTANT_CONTEXT`` to the AI assistant endpoints. The
    backend must accept that single literal context WITHOUT a world directory,
    keep per-world grounding intact, and never treat arbitrary names as worlds.
    """

    def test_global_ai_ask_answers_without_world_grounding(
        self, client: TestClient, monkeypatch,
    ):
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        response = client.post("/api/ideas-global/ai/ask", json={
            "prompt": "Ayudame a brainstormear una premisa",
            "session_id": "gap-global-1",
        })
        assert response.status_code == 200
        payload = response.json()
        assert payload["state"] == "allow"
        assert payload["unavailable"] is False
        assert payload["response"] == "Hermes semantic answer."
        # World-agnostic: the global context name never reaches the provider
        # and no world grounding is injected.
        prompt = runs.requests[0].prompt
        assert "ideas-global" not in prompt
        assert "Authorized context" not in prompt

    def test_global_ai_ask_activity_streams_usable_answer(
        self, client: TestClient, monkeypatch,
    ):
        class Adapter:
            available = True
            capability = _activity_capability()

            def __init__(self):
                self.request = None

            def start(self, request):
                self.request = request
                return "run-global"

            async def events(self, run_id):
                yield {"event": "message.delta", "run_id": run_id, "delta": "Idea enriquecida."}
                yield {"event": "run.completed", "run_id": run_id, "output": "Idea enriquecida."}

        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        adapter = Adapter()
        monkeypatch.setattr(api_server, "ACTIVITY_ADAPTER", adapter)
        response = client.post("/api/ideas-global/ai/ask/activity", json={
            "prompt": "Ayudame a brainstormear una premisa",
            "session_id": "gap-global-1",
        })
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(response.text)
        kinds = [event["kind"] for event in events]
        assert kinds[0] == "semantic_decision"
        assert events[0]["state"] == "allow"
        assert events[0]["unavailable"] is False
        assert kinds[-1] == "terminal"
        answers = [event["response"] for event in events if event["kind"] == "answer"]
        assert "Idea enriquecida." in answers
        # The adapter prompt is world-agnostic: global identity present, no
        # world name and no graph-tool grounding.
        assert "Taller de Ideas" in adapter.request.prompt
        assert "ideas-global" not in adapter.request.prompt

    def test_world_ai_ask_keeps_world_grounding(self, client: TestClient, monkeypatch):
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        response = client.post("/api/test_mundo/ai/ask", json={
            "prompt": "Quien es Rhyz", "session_id": "gap-chat-1",
        })
        assert response.status_code == 200
        assert response.json()["state"] == "allow"
        # Per-world behavior preserved: the real world name reaches the
        # provider as authorized context.
        assert '"mundo": "test_mundo"' in runs.requests[0].prompt

    def test_unknown_mundo_still_fails_closed(self, client: TestClient, monkeypatch):
        """An arbitrary name must never become a permissive world — even with a
        wired provider, ``nope`` fails closed on both assistant surfaces."""
        runs = _SemanticRuns(_semantic_payload("allow"))
        _wire_semantic_provider(monkeypatch, runs)
        ask = client.post("/api/nope/ai/ask", json={
            "prompt": "Hola", "session_id": "gap-nope-1",
        })
        assert ask.status_code == 200
        envelope = ask.json()
        assert envelope["state"] == "blocked"
        assert envelope["unavailable"] is True
        assert runs.starts == 0  # the provider was never consulted
        activity = client.post("/api/nope/ai/ask/activity", json={
            "prompt": "Hola", "session_id": "gap-nope-1",
        })
        assert activity.status_code == 503
        assert activity.json()["code"] == "activity_unavailable"


class TestPublishedAdjuntoRoute:
    """PR2: ``GET .../published/{skill}/{version}/adjunto/{path:path}`` serves a
    single pinned carrier as raw ``text/markdown`` (R14/R17; D1-D4)."""

    _BASE = "/api/methodologies/published/guided-character-v1/1.2.0/adjunto"

    def _publish_with_adjunto(
        self, client: TestClient, tmp_path: Path, *,
        path: str = "adjunto-nivel-1.md",
        data: bytes = b"# Principal\n\nContenido.\n",
        drift: bool = False,
        omit_carrier: bool = False,
        carrier_root: str = "seeds",
    ) -> dict:
        """Publish one pinned carrier written under ``carrier_root``.

        ``tmp_path`` is the patched ``PROJECT_ROOT``, so the directory the route
        resolves is the one this helper populates: ``seeds`` wins when its skill
        dir exists, otherwise the resolver falls back to ``attachments`` (R9/R24).
        The pin records ``data``; ``drift``/``omit_carrier`` make the bytes on
        disk diverge from (or disappear under) that pin.
        """
        entry = {
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "nivel": "1º",
        }
        root_dir = tmp_path / "data" / "methodology" / carrier_root / "guided-character-v1"
        carrier = root_dir / path
        carrier.parent.mkdir(parents=True, exist_ok=True)
        if not omit_carrier:
            carrier.write_bytes(b"# Drifted\n" if drift else data)
        draft = client.post("/api/methodologies/drafts", json={
            "skill_id": "guided-character-v1",
            "version": "1.2.0",
            "name": "Guided character methodology",
            "source": "## Construcción segura\n\nHaz preguntas de a una.\n",
            "adjuntos": [entry],
        })
        assert draft.status_code == 200, draft.text
        _approve_draft_trigger(client, draft.json()["draft_id"])
        published = client.post(
            f"/api/methodologies/drafts/{draft.json()['draft_id']}/publish",
        )
        assert published.status_code == 200, published.text
        return entry

    def test_serves_known_pin_as_raw_markdown(self, client: TestClient, monkeypatch, tmp_path):
        """R14 scenario "known pin": 200, markdown content type, inline
        disposition, and the exact pinned bytes."""
        _principal(monkeypatch, "author-1")
        data = b"# Principal\n\nContenido.\n"
        self._publish_with_adjunto(client, tmp_path, data=data)
        response = client.get(f"{self._BASE}/adjunto-nivel-1.md")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "text/markdown; charset=utf-8"
        assert response.headers["content-disposition"] == 'inline; filename="adjunto-nivel-1.md"'
        assert response.content == data

    def test_unauthenticated_is_401(self, client: TestClient):
        """R14 scenario "unauthenticated": the auth gate runs before existence."""
        response = client.get(f"{self._BASE}/adjunto-nivel-1.md")
        assert response.status_code == 401
        assert response.json() == {"detail": "Authentication required."}

    def test_unknown_pin_is_404(self, client: TestClient, monkeypatch, tmp_path):
        """R14 scenario "unknown target": an unlisted path is never resolved."""
        _principal(monkeypatch, "author-1")
        self._publish_with_adjunto(client, tmp_path)
        response = client.get(f"{self._BASE}/otro.md")
        assert response.status_code == 404
        assert response.json()["detail"] == "Adjunto no encontrado"

    def test_unpublished_skill_or_version_is_404(self, client: TestClient, monkeypatch):
        """R14 scenario "unknown target": unpublished skill/version 404s."""
        _principal(monkeypatch, "author-1")
        response = client.get(
            "/api/methodologies/published/ghost/9.9.9/adjunto/adjunto-nivel-1.md",
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Metodología no encontrada"

    def test_missing_carrier_is_422(self, client: TestClient, monkeypatch, tmp_path):
        """R17 scenario "unservable carrier": absent bytes fail closed."""
        _principal(monkeypatch, "author-1")
        self._publish_with_adjunto(client, tmp_path, omit_carrier=True)
        response = client.get(f"{self._BASE}/adjunto-nivel-1.md")
        assert response.status_code == 422
        assert response.json()["code"] == "attachment_unavailable"
        # Non-leaking: the carrier path is never surfaced.
        assert "adjunto-nivel-1.md" not in response.text

    def test_drifted_carrier_is_422(self, client: TestClient, monkeypatch, tmp_path):
        """R17 scenario "drifted carrier": SHA mismatch fails closed."""
        _principal(monkeypatch, "author-1")
        self._publish_with_adjunto(client, tmp_path, drift=True)
        response = client.get(f"{self._BASE}/adjunto-nivel-1.md")
        assert response.status_code == 422
        assert response.json()["code"] == "attachment_unavailable"

    def test_non_utf8_carrier_is_422(self, client: TestClient, monkeypatch, tmp_path):
        """R17: a byte-length/SHA-matching but non-UTF-8 carrier is unservable."""
        _principal(monkeypatch, "author-1")
        self._publish_with_adjunto(client, tmp_path, data=b"\xff\xfe\x00invalid")
        response = client.get(f"{self._BASE}/adjunto-nivel-1.md")
        assert response.status_code == 422
        assert response.json()["code"] == "attachment_unavailable"

    def test_traversal_path_is_404_without_reading_outside_root(
        self, client: TestClient, monkeypatch, tmp_path,
    ):
        """R14 scenario "traversal attempt": a `..` path that is not an exact
        pin 404s and never reads a file outside the carrier root.

        ``%2E%2E`` is used so the dot segments reach the route instead of being
        collapsed by client-side URL normalization; the route must still reject
        it as "not a recorded pin" rather than resolving the filesystem.
        """
        _principal(monkeypatch, "author-1")
        self._publish_with_adjunto(client, tmp_path)
        secret = tmp_path / "data" / "methodology" / "secret.md"
        secret.write_text("# SECRET-CANARY\n", encoding="utf-8")
        # Sanity: the route is live and the legitimate pin still serves.
        assert client.get(f"{self._BASE}/adjunto-nivel-1.md").status_code == 200
        response = client.get(f"{self._BASE}/%2E%2E/secret.md")
        assert response.status_code == 404
        assert response.json()["detail"] == "Adjunto no encontrado"
        assert "SECRET-CANARY" not in response.text

    def test_over_budget_carrier_is_served_untruncated(
        self, client: TestClient, monkeypatch, tmp_path,
    ):
        """R14 scenario "over-budget carrier": the 3072-token injection budget
        does NOT apply; the complete exemplar is returned.

        Publish caps carriers at ``MAX_ADJUNTO_BYTES`` (12288 B), which at the
        compiler's ~4 chars/token heuristic is itself the 3072-token boundary.
        An oversize exemplar therefore cannot enter through publish, so the
        record is injected at the library seam while the request still crosses
        the real HTTP boundary — proving the route ignores the budget.
        """
        from contract_projection import _estimate_tokens
        from methodology_compiler import AttachmentEntry
        from types import SimpleNamespace

        _principal(monkeypatch, "author-1")
        body = "# Exhaustivo\n\n" + ("palabra " * 3000) + "\n"
        data = body.encode("utf-8")
        assert _estimate_tokens(body) > 3072
        assert len(data) > 12288
        pin = AttachmentEntry(
            path="grande.md",
            sha256=hashlib.sha256(data).hexdigest(),
            bytes=len(data),
            nivel="1º",
        )
        carrier_root = tmp_path / "data" / "methodology" / "seeds" / "guided-character-v1"
        carrier_root.mkdir(parents=True, exist_ok=True)
        (carrier_root / "grande.md").write_bytes(data)

        class _StubLibrary:
            @staticmethod
            def get_published(skill_id: str, version: str):
                return SimpleNamespace(skill_id="guided-character-v1", adjuntos=(pin,))

        monkeypatch.setattr(api_server, "_methodology_library", lambda: _StubLibrary())
        response = client.get(f"{self._BASE}/grande.md")
        assert response.status_code == 200, response.text
        assert response.content == data
        assert len(response.content) > 12288

    def test_imported_subpath_pin_addressing_from_attachments_root(
        self, client: TestClient, monkeypatch, tmp_path,
    ):
        """R14/R24: a nested pin under the attachments root resolves through
        the ``:path`` route and serves its exact bytes."""
        _principal(monkeypatch, "author-1")
        data = "## Anexo importado\n\nTexto.\n".encode("utf-8")
        self._publish_with_adjunto(
            client, tmp_path, path="anexos/nivel-1.md", data=data,
            carrier_root="attachments",
        )
        response = client.get(f"{self._BASE}/anexos/nivel-1.md")
        assert response.status_code == 200, response.text
        assert response.content == data
        assert response.headers["content-disposition"] == 'inline; filename="nivel-1.md"'


# ---------------------------------------------------------------------------
# PR5 (task 4.4) — POST /api/ideas/{slug}/materialize-preview
# ---------------------------------------------------------------------------


def _write_idea(slug: str = "arquero-ciego", *, type: str = "personaje",
                title: str = "Arquero Ciego",
                body: str = "Un arquero que perdió la vista.",
                media_path: str | None = None) -> Path:
    """Write an idea file into the CURRENT hermetic ideas bank.

    Written directly (not via the /api/ideas router) because the router's
    ``IdeasBank`` instance is a process-lifetime singleton whose ``_ideas_root``
    is pinned to the FIRST test's tmp_path, while the preview handler resolves
    the current test's root — router-created ideas would 404 in later tests.
    """
    ideas_dir = api_server.PROJECT_ROOT / "ideas"
    ideas_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "---\n"
        f"id: idea-{slug}\n"
        f"slug: {slug}\n"
        f"type: {type}\n"
        "source: manual\n"
        f"status: fresh\n"
        f"title: {title}\n"
        + (f"media_path: {media_path}\n" if media_path is not None else "")
        + "tags: []\n"
        "used_in: []\n"
        "---\n\n"
        f"{body}\n"
    )
    path = ideas_dir / f"{slug}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _write_idea_media(name: str = "idea-foto.jpg",
                      data: bytes = b"\xff\xd8\xff\xe0fake-jpeg") -> Path:
    """Write a media file into the CURRENT hermetic ``ideas/media`` store."""
    media_dir = api_server.PROJECT_ROOT / "ideas" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    path = media_dir / name
    path.write_bytes(data)
    return path


class TestMaterializePreview:
    """Route-level matrix for the materialize preview endpoint (R-IM-01..09)."""

    def test_valid_picker_accepted_and_zero_writes(self, client: TestClient, monkeypatch):
        """R-IM-01/02/04: a valid picker resolves the target under
        mundos/{world}/{section}/, returns a server-built skeleton, stores a
        pending proposal — and touches no canon bytes."""
        _write_idea()
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        before = _world_listing()
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["proposal_id"].startswith("materialize-")
        assert payload["target"] == {
            "world": "test_mundo", "section": "lore", "folder": "subdir",
            "slug": "arquero-ciego", "path": "subdir/arquero-ciego.md",
        }
        assert payload["content"].startswith("---")
        assert "type: concepto" in payload["content"]
        assert "based_on: ideas/arquero-ciego" in payload["content"]
        assert payload["proposed_relations"] == []
        assert payload["discarded_relations"] == []
        assert len(provider.requests) == 1
        request = provider.requests[0]
        assert request.world == "test_mundo" and request.slug == "arquero-ciego"
        assert request.section == "lore" and request.folder == "subdir"
        assert request.request_id == request.session_id
        pending = api_server._MATERIALIZE_PENDING_PROPOSALS[payload["proposal_id"]]
        assert pending["target"] == "lore/subdir/arquero-ciego.md"
        assert pending["principal_id"] == "tester"
        assert pending["digest"] == hashlib.sha256(payload["content"].encode("utf-8")).hexdigest()
        assert pending["expires_at"] > pending["created_at"]
        # R-IM-04: preview alone leaves mundos/ byte-identical.
        assert _world_listing() == before
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "arquero-ciego.md").exists()

    # -----------------------------------------------------------------------
    # WU-6 (iteration 2) — the typed name drives the filename + frontmatter title
    # -----------------------------------------------------------------------

    def _frontmatter(self, content: str) -> dict:
        return yaml.safe_load(content.split("---\n", 2)[1])

    def test_title_drives_filename_frontmatter_and_h1(self, client: TestClient, monkeypatch):
        """FT-1: the server-owned ``title`` names the file, the frontmatter
        title AND the body H1, while ``based_on`` keeps the IDEA slug untouched."""
        _write_idea()  # slug=arquero-ciego, title="Arquero Ciego"
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client, title="El Arquero Ciego")
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["title"] == "El Arquero Ciego"
        assert payload["target"] == {
            "world": "test_mundo", "section": "lore", "folder": "subdir",
            "slug": "el-arquero-ciego", "path": "subdir/el-arquero-ciego.md",
        }
        fm = self._frontmatter(payload["content"])
        assert fm["title"] == "El Arquero Ciego"
        assert fm["based_on"] == "ideas/arquero-ciego"
        assert "\n# El Arquero Ciego\n" in payload["content"]
        pending = api_server._MATERIALIZE_PENDING_PROPOSALS[payload["proposal_id"]]
        assert pending["slug"] == "arquero-ciego"
        assert pending["file_slug"] == "el-arquero-ciego"
        assert pending["title"] == "El Arquero Ciego"
        assert pending["target"] == "lore/subdir/el-arquero-ciego.md"
        assert len(provider.requests) == 1

    def test_provider_request_keeps_idea_identity_unchanged(self, client: TestClient, monkeypatch):
        """WU-6 trap 4 + FT-1: the MaterializationRequest prompt inputs stay
        exactly today's — idea slug, idea title and the raw title_hint — even
        when a client title drives the visible ficha title."""
        _write_idea(title="Título De La Idea")
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client, title="Otro Titulo", title_hint="Hint Legado")
        assert resp.status_code == 200, resp.text
        assert len(provider.requests) == 1
        request = provider.requests[0]
        assert request.slug == "arquero-ciego"
        assert request.title == "Título De La Idea"
        assert request.title_hint == "Hint Legado"
        # The visible title follows the client title, not the request identity.
        assert resp.json()["title"] == "Otro Titulo"
        assert resp.json()["target"]["slug"] == "otro-titulo"

    def test_client_slug_overrides_file_name_only(self, client: TestClient, monkeypatch):
        """FT-1: a client ``slug`` overrides the FILE NAME only — the title and
        the body H1 keep following the resolved title."""
        _write_idea()
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = client.post("/api/ideas/arquero-ciego/materialize-preview", json={
            "world": "test_mundo", "section": "lore", "folder": "subdir",
            "title": "El Arquero Ciego", "slug": "Mi Nombre Raro!",
        })
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["target"]["slug"] == "mi-nombre-raro"
        assert payload["target"]["path"] == "subdir/mi-nombre-raro.md"
        assert payload["title"] == "El Arquero Ciego"
        assert self._frontmatter(payload["content"])["title"] == "El Arquero Ciego"
        assert "\n# El Arquero Ciego\n" in payload["content"]
        # The provider still sees the idea identity, never the client slug.
        assert provider.requests[0].slug == "arquero-ciego"

    def test_client_title_wins_over_idea_title_and_is_normalized(self, client: TestClient, monkeypatch):
        """FT-1: the client ``title`` wins over the idea title, internal
        whitespace collapses to one space, and the resolved title is returned."""
        _write_idea()  # idea title "Arquero Ciego"
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client, title="  El   Arquero   Ciego  ")
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["title"] == "El Arquero Ciego"
        assert payload["target"]["slug"] == "el-arquero-ciego"
        assert self._frontmatter(payload["content"])["title"] == "El Arquero Ciego"
        assert "\n# El Arquero Ciego\n" in payload["content"]

    def test_absent_title_and_slug_use_the_idea_title(self, client: TestClient, monkeypatch):
        """FT-1: with no client title/slug the idea title is the resolved title."""
        _write_idea()  # idea title "Arquero Ciego", slug "arquero-ciego"
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["title"] == "Arquero Ciego"
        assert payload["target"]["slug"] == "arquero-ciego"
        assert self._frontmatter(payload["content"])["title"] == "Arquero Ciego"
        assert "\n# Arquero Ciego\n" in payload["content"]

    def test_absent_title_and_slug_h1_owns_the_body(self, client: TestClient, monkeypatch):
        """FT-1: the AI body's own H1 is replaced even with no client title."""
        _write_idea()
        _wire_materialize(
            monkeypatch,
            lambda request, _c: _materialize_delta(request, body="# H1 inventado\n\nTexto.\n"),
        )
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        content = resp.json()["content"]
        assert "# H1 inventado" not in content
        assert content.endswith("---\n\n# Arquero Ciego\n\nTexto.\n")

    def test_client_title_preview_is_zero_write(self, client: TestClient, monkeypatch):
        """FT-1 keeps R-IM-04: a titled preview writes nothing to mundos/."""
        _write_idea()
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        before = _world_listing()
        resp = _materialize_preview(client, title="El Arquero Ciego")
        assert resp.status_code == 200, resp.text
        assert _world_listing() == before
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "el-arquero-ciego.md").exists()

    def test_empty_normalizing_client_slug_falls_back_to_derived(self, client: TestClient, monkeypatch):
        """FT-1: an empty/empty-normalizing client slug falls back to the title."""
        _write_idea()
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = client.post("/api/ideas/arquero-ciego/materialize-preview", json={
            "world": "test_mundo", "section": "lore", "folder": "subdir",
            "title": "El Arquero Ciego", "slug": "!!!",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["target"]["slug"] == "el-arquero-ciego"

    def test_untitled_idea_keeps_its_internal_slug_as_filename(self, client: TestClient, monkeypatch):
        """WU-6: an untitled idea (empty title) still derives from the idea slug."""
        _write_idea(title="")
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        assert resp.json()["target"]["slug"] == "arquero-ciego"

    def test_collision_on_derived_name_409_with_slug_2(self, client: TestClient, monkeypatch):
        """FT-1: a collision on the title-DERIVED filename yields 409 + ``-2``."""
        _write_idea()
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "el-arquero-ciego.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Ya existe\n", encoding="utf-8")
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client, title="El Arquero Ciego")
        assert resp.status_code == 409
        collision = resp.json()["collision"]
        assert collision["target"] == "lore/subdir/el-arquero-ciego.md"
        assert collision["suggested_slug"] == "el-arquero-ciego-2"
        assert collision["suggested_target"] == "lore/subdir/el-arquero-ciego-2.md"
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_preview_requires_auth(self, client: TestClient):
        _write_idea()
        resp = _materialize_preview(client)
        assert resp.status_code == 401
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_non_indexed_section_rejected(self, client: TestClient, monkeypatch):
        """R-IM-01: media is not ficha-eligible."""
        _write_idea()
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client, section="media")
        assert resp.status_code == 400
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_traversal_folder_rejected(self, client: TestClient, monkeypatch):
        """R-IM-01: a folder escaping the section is rejected."""
        _write_idea()
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client, folder="../personajes")
        assert resp.status_code == 400
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_unknown_world_rejected(self, client: TestClient, monkeypatch):
        """R-IM-01: an unknown world is 404 with no draft."""
        _write_idea()
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client, world="no-existe")
        assert resp.status_code == 404
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_suggested_section_from_idea_type_accepted(self, client: TestClient, monkeypatch):
        """The section SUGGESTION is frontend-owned (AD7); the backend contract
        is that the suggested graph-indexed section is accepted: personaje →
        personajes, concepto → lore."""
        _write_idea(type="personaje")
        _write_idea(slug="idea-concepto", type="concepto", title="Idea Concepto")
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        personajes = _materialize_preview(client, section="personajes", folder="")
        assert personajes.status_code == 200, personajes.text
        assert personajes.json()["target"]["path"] == "arquero-ciego.md"
        assert "type: Personaje" in personajes.json()["content"]
        lore = _materialize_preview(client, slug="idea-concepto", section="lore", folder="")
        assert lore.status_code == 200, lore.text
        assert lore.json()["target"]["path"] == "idea-concepto.md"
        assert len(provider.requests) == 2

    def test_provider_none_returns_503_zero_writes(self, client: TestClient, monkeypatch):
        """R-IM-09: an unwired provider fails closed with zero writes."""
        _write_idea()
        _principal(monkeypatch)
        monkeypatch.setattr("ideas_bank._project_root", lambda: api_server.PROJECT_ROOT)
        monkeypatch.setattr(api_server, "_MATERIALIZE_PROVIDER", None)
        before = _world_listing()
        resp = _materialize_preview(client)
        assert resp.status_code == 503
        assert resp.json() == {"status": "unavailable", "retryable": True}
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS
        assert _world_listing() == before

    @pytest.mark.parametrize("bad_result", [
        {"protocol_version": "idea-materialization-v9", "outcome": "delta",
         "delta": {"body": "# X\n", "relations": []}},
        "not-json-at-all",
        {},
        {"outcome": "delta", "delta": {"body": "# X\n", "relations": []}},
    ])
    def test_malformed_or_identity_mismatch_envelope_502(
            self, client: TestClient, monkeypatch, bad_result):
        """R-IM-09: malformed or identity-mismatched envelopes fail closed."""
        _write_idea()
        _wire_materialize(monkeypatch, bad_result)
        before = _world_listing()
        resp = _materialize_preview(client)
        assert resp.status_code == 502
        assert resp.json()["code"] == "malformed_output"
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS
        assert _world_listing() == before

    @pytest.mark.parametrize("bad_body", [
        "x" * 6001,                                      # R-IM-02 body bound
        "---\nid: injected\n---\n# Body\n",              # R-IM-08 frontmatter
    ])
    def test_oversized_or_frontmatter_body_502(self, client: TestClient, monkeypatch, bad_body):
        """Body bound and AI-frontmatter injection fail closed (502)."""
        _write_idea()
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request, body=bad_body))
        resp = _materialize_preview(client)
        assert resp.status_code == 502
        assert resp.json()["code"] == "malformed_output"
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_relations_over_cap_502(self, client: TestClient, monkeypatch):
        """AD1: more than MAX_RELATIONS rejects the whole envelope."""
        _write_idea()
        relations = [{"target_id": f"id-{i}", "rel_type": "aliado-de"} for i in range(13)]
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request, relations=relations))
        resp = _materialize_preview(client)
        assert resp.status_code == 502
        assert resp.json()["code"] == "malformed_output"
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_invented_target_dropped_and_reported(self, client: TestClient, monkeypatch):
        """R-IM-03: an invented target_id is dropped, reported and never written."""
        _write_idea()
        entities = [
            _materialize_entity("personajes/rhyz.md", id="Rhyz::Rhyz", title="Rhyz", type="Personaje"),
        ]

        def result(request, _cancellation):
            return _materialize_delta(request, relations=[
                {"target_id": "Rhyz::Rhyz", "rel_type": "aliado-de"},
                {"target_id": "Personaje::Inventado", "rel_type": "aliado-de"},
            ])

        _wire_materialize(monkeypatch, result, entities=entities)
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["proposed_relations"] == [
            {"target_id": "Rhyz::Rhyz", "title": "Rhyz", "rel_type": "aliado-de"}
        ]
        assert payload["discarded_relations"] == [
            {"target_id": "Personaje::Inventado", "reason": "target_not_found"}
        ]
        assert "[[Rhyz::Rhyz]]" in payload["content"]
        assert "Personaje::Inventado" not in payload["content"]

    def test_preview_grounds_candidates_from_the_graph(self, client: TestClient, monkeypatch):
        """Integration (materialize-graph-grounding): the handler advertises
        graph-grounded candidates on the provider request — the seed entity
        reaches the model instead of an arbitrary file-order slice."""
        _write_idea()
        entities = [
            _materialize_entity("personajes/rhyz.md", id="Rhyz::Rhyz", title="Rhyz", type="Personaje"),
        ]
        provider = _wire_materialize(
            monkeypatch, lambda request, _c: _materialize_delta(request), entities=entities,
        )
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        assert len(provider.requests) == 1
        assert [c["id"] for c in provider.requests[0].candidates] == ["Rhyz::Rhyz"]

    def test_out_of_vocab_rel_type_dropped_not_502(self, client: TestClient, monkeypatch):
        """Binding clarification: an out-of-vocabulary rel_type drops THAT
        relation into discarded_relations — never a whole-envelope failure."""
        _write_idea()
        entities = [
            _materialize_entity("personajes/rhyz.md", id="Rhyz::Rhyz", title="Rhyz", type="Personaje"),
        ]
        _wire_materialize(
            monkeypatch,
            lambda request, _c: _materialize_delta(request, relations=[
                {"target_id": "Rhyz::Rhyz", "rel_type": "hechizo-de"},
            ]),
            entities=entities,
        )
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["proposed_relations"] == []
        assert payload["discarded_relations"] == [
            {"target_id": "Rhyz::Rhyz", "reason": "rel_type_out_of_vocabulary"}
        ]

    def test_collision_409_with_slug_2_suggestion(self, client: TestClient, monkeypatch):
        """AD5: an existing target returns 409 with a -2 suggestion."""
        _write_idea()
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "arquero-ciego.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Ya existe\n", encoding="utf-8")
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client)
        assert resp.status_code == 409
        collision = resp.json()["collision"]
        assert collision["target"] == "lore/subdir/arquero-ciego.md"
        assert collision["suggested_slug"] == "arquero-ciego-2"
        assert collision["suggested_target"] == "lore/subdir/arquero-ciego-2.md"
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    # -----------------------------------------------------------------------
    # PR7 (task 6.1) — integration: preview is write-free (R-IM-04)
    # -----------------------------------------------------------------------

    def test_preview_is_write_free_by_mtime_snapshot(self, client: TestClient, monkeypatch):
        """R-IM-04 (SC2/AC1): a full preview round-trip leaves mundos/ byte-
        identical — same file set, same sizes, same mtimes/ctimes — and no
        pending ficha exists on disk. This is a stronger check than the listing
        equality in test_valid_picker_accepted_and_zero_writes: it also catches
        a write that modifies an existing file in place without adding one."""
        _write_idea()
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        world = api_server.MUNDOS_DIR / "test_mundo"

        def snapshot() -> dict[str, tuple[int, int, int]]:
            snap: dict[str, tuple[int, int, int]] = {}
            for path in sorted(world.rglob("*")):
                if not path.is_file():
                    continue
                stat = path.stat()
                snap[str(path.relative_to(world))] = (stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)
            return snap

        before = snapshot()
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert snapshot() == before
        # No pending ficha file on disk (the pending proposal is in-memory only).
        pending_target = world / payload["target"]["path"]
        assert not pending_target.exists()
        assert not list((world / "lore" / "subdir").glob("arquero-ciego*.md"))


# ---------------------------------------------------------------------------
# CI-1 (materialize-carry-idea-image) — preview resolves + injects the image
# ---------------------------------------------------------------------------


class TestMaterializePreviewImage:
    """Preview-side matrix for carrying an idea image (zero canon writes)."""

    def _media_preview(self, client: TestClient, monkeypatch: pytest.MonkeyPatch, *,
                       media_name: str = "idea-foto.jpg",
                       media_path: str | None = "media/idea-foto.jpg",
                       data: bytes = b"\xff\xd8\xff\xe0fake-jpeg",
                       **overrides):
        _write_idea(media_path=media_path)
        _write_idea_media(media_name, data)
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        return _materialize_preview(client, **overrides)

    def test_preview_injects_reference_and_media_block(self, client: TestClient, monkeypatch):
        """The assembled content carries the image and the response/pending
        both expose the src/dest (bare source + world-relative dest)."""
        resp = self._media_preview(client, monkeypatch)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["media"] == {
            "src": "/api/ideas/media/idea-foto.jpg",
            "dest": "media/arquero-ciego.jpg",
        }
        assert "# Arquero Ciego\n![Arquero Ciego](media/arquero-ciego.jpg)\n" in payload["content"]
        pending = api_server._MATERIALIZE_PENDING_PROPOSALS[payload["proposal_id"]]
        assert pending["media"] == {"source": "idea-foto.jpg", "dest": "media/arquero-ciego.jpg"}

    def test_preview_with_image_is_zero_write(self, client: TestClient, monkeypatch):
        """R-IM-04: a preview with an image never creates the world media dir."""
        world = api_server.MUNDOS_DIR / "test_mundo"
        assert not (world / "wiki").exists()
        before = _world_listing()
        resp = self._media_preview(client, monkeypatch)
        assert resp.status_code == 200, resp.text
        assert _world_listing() == before
        assert not (world / "wiki").exists()
        assert not (world / "wiki" / "media").exists()

    def test_preview_dest_dedupe_picks_next_free_name(self, client: TestClient, monkeypatch):
        """An existing dest file makes preview choose ``<name>-2.<ext>``."""
        existing = api_server.MUNDOS_DIR / "test_mundo" / "wiki" / "media" / "arquero-ciego.jpg"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"EXISTING")
        resp = self._media_preview(client, monkeypatch)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["media"]["dest"] == "media/arquero-ciego-2.jpg"
        assert "![Arquero Ciego](media/arquero-ciego-2.jpg)" in payload["content"]
        # The dedupe probe is read-only: the occupant is untouched.
        assert existing.read_bytes() == b"EXISTING"

    def test_preview_without_media_has_no_media_key(self, client: TestClient, monkeypatch):
        """An idea without media_path behaves exactly as today."""
        _write_idea()
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert "media" not in payload
        assert "![" not in payload["content"]
        pending = api_server._MATERIALIZE_PENDING_PROPOSALS[payload["proposal_id"]]
        assert "media" not in pending

    def test_preview_missing_media_file_degrades_to_no_image(self, client: TestClient, monkeypatch):
        """A media_path whose file is absent degrades without failing."""
        _write_idea(media_path="media/missing.jpg")  # file never written
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        assert "media" not in resp.json()
        assert "![" not in resp.json()["content"]

    def test_preview_non_allowlisted_extension_degrades_to_no_image(self, client: TestClient, monkeypatch):
        """A non-image extension degrades to no image even when the file exists."""
        _write_idea(media_path="media/notas.txt")
        _write_idea_media("notas.txt")
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        assert "media" not in resp.json()

    def test_preview_traversal_media_path_degrades_to_no_image(self, client: TestClient, monkeypatch):
        """A ``..`` segment in media_path degrades to no image."""
        _write_idea(media_path="media/../secreto.jpg")
        _write_idea_media("secreto.jpg")
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        assert "media" not in resp.json()


# ---------------------------------------------------------------------------
# CI-1 — confirm copies the image bytes before the first canon write
# ---------------------------------------------------------------------------


class TestMaterializeConfirmImage:
    """Confirm-side matrix for carrying an idea image (fail-closed copy)."""

    def _preview(self, client: TestClient, monkeypatch: pytest.MonkeyPatch, *,
                 media_name: str = "idea-foto.jpg",
                 media_path: str | None = "media/idea-foto.jpg",
                 data: bytes = b"\xff\xd8\xff\xe0fake-jpeg") -> dict:
        _write_idea(media_path=media_path)
        _write_idea_media(media_name, data)
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_preview(client)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def _confirm(self, client: TestClient, preview: dict):
        path = preview["target"]["path"]
        conf = client.post(
            f"/api/test_mundo/lore/edit-confirmation?path={path}",
            json={"edit_id": preview["proposal_id"], "kind": "new",
                  "proposed_content": preview["content"]},
        )
        assert conf.status_code == 200, conf.text
        conf = conf.json()
        return client.post(
            f"/api/test_mundo/lore/create?path={path}",
            json={"content": preview["content"], "edit_id": preview["proposal_id"],
                  "proposed_digest": conf["proposed_digest"], "token": conf["token"]},
        )

    def test_confirm_copies_bytes_and_reference_resolves(self, client: TestClient, monkeypatch):
        """The bytes land at the world dest, the ficha keeps the previewed
        content (digest verification still passes) and the reference resolves."""
        data = b"\xff\xd8\xff\xe0unique-jpeg-bytes"
        preview = self._preview(client, monkeypatch, data=data)
        resp = self._confirm(client, preview)
        assert resp.status_code == 200, resp.text
        world = api_server.MUNDOS_DIR / "test_mundo"
        dest = world / "wiki" / "media" / "arquero-ciego.jpg"
        assert dest.is_file()
        assert dest.read_bytes() == data
        ficha = world / "lore" / "subdir" / "arquero-ciego.md"
        assert ficha.is_file()
        assert ficha.read_text(encoding="utf-8") == preview["content"]
        assert "![Arquero Ciego](media/arquero-ciego.jpg)" in ficha.read_text(encoding="utf-8")
        resolved = api_server._resolve_media_path("test_mundo", "media/arquero-ciego.jpg")
        assert resolved is not None and resolved.is_file()
        assert resolved.read_bytes() == data
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_confirm_dest_race_fails_closed_with_no_write(self, client: TestClient, monkeypatch):
        """A destination created after preview -> 409, no ficha, proposal kept."""
        preview = self._preview(client, monkeypatch)
        dest = api_server.MUNDOS_DIR / "test_mundo" / "wiki" / "media" / "arquero-ciego.jpg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"RACE")
        resp = self._confirm(client, preview)
        assert resp.status_code == 409, resp.text
        assert "arquero-ciego.jpg" in resp.json()["detail"]
        ficha = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "arquero-ciego.md"
        assert not ficha.exists()
        assert dest.read_bytes() == b"RACE"
        assert preview["proposal_id"] in api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_confirm_missing_source_fails_closed(self, client: TestClient, monkeypatch):
        """The source disappearing after preview -> 409, no ficha, proposal kept."""
        preview = self._preview(client, monkeypatch)
        source = api_server.PROJECT_ROOT / "ideas" / "media" / "idea-foto.jpg"
        source.unlink()
        resp = self._confirm(client, preview)
        assert resp.status_code == 409, resp.text
        assert "idea-foto.jpg" in resp.json()["detail"]
        ficha = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "arquero-ciego.md"
        assert not ficha.exists()
        assert preview["proposal_id"] in api_server._MATERIALIZE_PENDING_PROPOSALS


# ---------------------------------------------------------------------------
# WU-2 — POST /api/ideas/{slug}/materialize-target (instant, provider-free)
# ---------------------------------------------------------------------------


class TestMaterializeTarget:
    """Route-level matrix for the destination-resolution endpoint (WU-2).

    It mirrors the preview validation order but must never start an AI run:
    the provider-recording seam is asserted untouched on every path.
    """

    def test_requires_auth(self, client: TestClient):
        _write_idea()
        resp = _materialize_target(client)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Autenticación requerida"
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_unknown_idea_404(self, client: TestClient, monkeypatch):
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_target(client, slug="no-existe")
        assert resp.status_code == 404
        assert provider.requests == []
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_unknown_world_404(self, client: TestClient, monkeypatch):
        _write_idea()
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_target(client, world="no-existe")
        assert resp.status_code == 404
        assert provider.requests == []
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_non_indexed_section_400(self, client: TestClient, monkeypatch):
        _write_idea()
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_target(client, section="media")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Sección no fichable"
        assert provider.requests == []
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_traversal_folder_400(self, client: TestClient, monkeypatch):
        _write_idea()
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_target(client, folder="../personajes")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Path traversal detectado"
        assert provider.requests == []
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_happy_path_resolves_path_without_provider(self, client: TestClient, monkeypatch):
        """200 returns the resolved target and starts no materialization run."""
        _write_idea()
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        before = _world_listing()
        resp = _materialize_target(client)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "title": "Arquero Ciego",
            "target": {
                "world": "test_mundo", "section": "lore", "folder": "subdir",
                "slug": "arquero-ciego", "path": "subdir/arquero-ciego.md",
            },
        }
        # WU-2: the provider seam is untouched and no proposal is stored.
        assert provider.requests == []
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS
        # Resolution is read-only: mundos/ stays byte-identical.
        assert _world_listing() == before

    def test_happy_path_section_root_path(self, client: TestClient, monkeypatch):
        """An empty folder resolves to ``{slug}.md`` at the section root."""
        _write_idea()
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_target(client, folder="")
        assert resp.status_code == 200, resp.text
        assert resp.json()["target"] == {
            "world": "test_mundo", "section": "lore", "folder": "",
            "slug": "arquero-ciego", "path": "arquero-ciego.md",
        }
        assert provider.requests == []

    def test_collision_409_with_slug_2_suggestion(self, client: TestClient, monkeypatch):
        """An existing target returns 409 + the shared collision shape."""
        _write_idea()
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "arquero-ciego.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Ya existe\n", encoding="utf-8")
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_target(client)
        assert resp.status_code == 409
        body = resp.json()
        assert body["detail"] == "El archivo ya existe"
        assert body["collision"] == {
            "target": "lore/subdir/arquero-ciego.md",
            "suggested_slug": "arquero-ciego-2",
            "suggested_target": "lore/subdir/arquero-ciego-2.md",
        }
        assert provider.requests == []
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_provider_seam_is_never_invoked(self, client: TestClient, monkeypatch):
        """WU-2: target resolution must not start a materialization run.

        A valid request resolves 200 while the recording provider seam stays
        empty — no invoke, no run, no pending proposal.
        """
        _write_idea()
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_target(client)
        assert resp.status_code == 200, resp.text
        assert provider.requests == []
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    # -----------------------------------------------------------------------
    # WU-6 (iteration 2) — the instant step resolves the title-derived name
    # -----------------------------------------------------------------------

    def test_accepts_title_and_returns_resolved_values(self, client: TestClient, monkeypatch):
        """FT-1: the target endpoint accepts ``title`` and returns
        ``{title, target}`` with both resolved (title normalized)."""
        _write_idea()  # slug=arquero-ciego, title="Arquero Ciego"
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_target(client, title="  El   Arquero Ciego  ")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "title": "El Arquero Ciego",
            "target": {
                "world": "test_mundo", "section": "lore", "folder": "subdir",
                "slug": "el-arquero-ciego", "path": "subdir/el-arquero-ciego.md",
            },
        }
        assert provider.requests == []

    def test_accepts_client_slug_normalized(self, client: TestClient, monkeypatch):
        """FT-1: a client ``slug`` overrides the file name and is normalized
        server-side, leaving the resolved title unchanged."""
        _write_idea()
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = client.post("/api/ideas/arquero-ciego/materialize-target", json={
            "world": "test_mundo", "section": "lore", "folder": "subdir",
            "title": "El Arquero Ciego", "slug": "Mi Nombre Raro!",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == "El Arquero Ciego"
        assert resp.json()["target"]["slug"] == "mi-nombre-raro"
        assert resp.json()["target"]["path"] == "subdir/mi-nombre-raro.md"
        assert provider.requests == []

    def test_untitled_idea_resolves_idea_slug(self, client: TestClient, monkeypatch):
        """WU-6: an untitled idea resolves its internal slug as filename."""
        _write_idea(title="")
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_target(client)
        assert resp.status_code == 200, resp.text
        assert resp.json()["target"]["slug"] == "arquero-ciego"

    def test_collision_on_derived_name_409_with_slug_2(self, client: TestClient, monkeypatch):
        """FT-1: a collision on the title-DERIVED name yields 409 + ``-2``."""
        _write_idea()
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "el-arquero-ciego.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Ya existe\n", encoding="utf-8")
        provider = _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        resp = _materialize_target(client, title="El Arquero Ciego")
        assert resp.status_code == 409
        body = resp.json()
        assert body["detail"] == "El archivo ya existe"
        assert body["collision"] == {
            "target": "lore/subdir/el-arquero-ciego.md",
            "suggested_slug": "el-arquero-ciego-2",
            "suggested_target": "lore/subdir/el-arquero-ciego-2.md",
        }
        assert provider.requests == []
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS


# ---------------------------------------------------------------------------
# PR5 (task 4.5) — confirm through the existing gated create route
# ---------------------------------------------------------------------------


class TestMaterializeConfirm:
    """Confirm flows through the existing confirmation-gated create pipeline
    with the materialize pending branch (AD3, R-IM-05/06)."""

    def _preview(self, client: TestClient, monkeypatch, slug: str = "arquero-ciego",
                 entities: list[dict] | None = None, **overrides) -> dict:
        _write_idea(slug)
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request), entities=entities)
        resp = _materialize_preview(client, slug=slug, **overrides)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def _confirm(self, client: TestClient, preview: dict, *,
                 mundo: str = "test_mundo", section: str = "lore", path: str | None = None):
        path = path or preview["target"]["path"]
        conf = client.post(
            f"/api/{mundo}/{section}/edit-confirmation?path={path}",
            json={"edit_id": preview["proposal_id"], "kind": "new",
                  "proposed_content": preview["content"]},
        )
        assert conf.status_code == 200, conf.text
        conf = conf.json()
        return client.post(
            f"/api/{mundo}/{section}/create?path={path}",
            json={"content": preview["content"], "edit_id": preview["proposal_id"],
                  "proposed_digest": conf["proposed_digest"], "token": conf["token"]},
        )

    def test_confirm_writes_exactly_one_file(self, client: TestClient, monkeypatch):
        """R-IM-05: confirm writes exactly one ficha at
        mundos/{world}/{section}/{folder}/{slug}.md and consumes the proposal."""
        preview = self._preview(client, monkeypatch)
        resp = self._confirm(client, preview)
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "arquero-ciego.md"
        assert target.is_file()
        assert target.read_text(encoding="utf-8") == preview["content"]
        matches = list((api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir").glob("arquero-ciego*.md"))
        assert matches == [target]
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_confirm_token_replay_rejected(self, client: TestClient, monkeypatch):
        """R-IM-05: the confirmation token is single-use; a replay is rejected.

        The written file is removed first so the replay exercises token
        single-use itself — against the still-existing file the collision 409
        fires before redemption (the proposal accepts 403/409 for replay).
        """
        preview = self._preview(client, monkeypatch)
        conf = client.post(
            "/api/test_mundo/lore/edit-confirmation?path=subdir/arquero-ciego.md",
            json={"edit_id": preview["proposal_id"], "kind": "new",
                  "proposed_content": preview["content"]},
        )
        assert conf.status_code == 200, conf.text
        conf = conf.json()
        url = "/api/test_mundo/lore/create?path=subdir/arquero-ciego.md"
        payload = {"content": preview["content"], "edit_id": preview["proposal_id"],
                   "proposed_digest": conf["proposed_digest"], "token": conf["token"]}
        first = client.post(url, json=payload)
        assert first.status_code == 200, first.text
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "arquero-ciego.md"
        assert target.is_file()
        target.unlink()
        replay = client.post(url, json=payload)
        assert replay.status_code == 403
        assert not target.exists()
        assert not api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_confirm_creates_missing_personajes_folder(self, client: TestClient, monkeypatch):
        """R-IM-05: a missing section folder is created as part of the write."""
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "personajes").exists()
        preview = self._preview(client, monkeypatch, section="personajes", folder="")
        resp = self._confirm(client, preview, section="personajes", path="arquero-ciego.md")
        assert resp.status_code == 200, resp.text
        target = api_server.MUNDOS_DIR / "test_mundo" / "personajes" / "arquero-ciego.md"
        assert target.is_file()
        content = target.read_text(encoding="utf-8")
        assert "type: Personaje" in content
        assert "schema_version: 1" in content

    def test_confirm_altered_content_rejected(self, client: TestClient, monkeypatch):
        """Task 4.5/AD3: the pending branch mirrors the guided branch
        (:4647-4650), so altered content fails the proposal check with 409 and
        no write occurs (the generic create pipeline's 403 digest protection
        is covered by TestNewFileParity)."""
        preview = self._preview(client, monkeypatch)
        conf = client.post(
            "/api/test_mundo/lore/edit-confirmation?path=subdir/arquero-ciego.md",
            json={"edit_id": preview["proposal_id"], "kind": "new",
                  "proposed_content": preview["content"]},
        )
        assert conf.status_code == 200, conf.text
        conf = conf.json()
        resp = client.post(
            "/api/test_mundo/lore/create?path=subdir/arquero-ciego.md",
            json={"content": "# ALTERED\n", "edit_id": preview["proposal_id"],
                  "proposed_digest": conf["proposed_digest"], "token": conf["token"]},
        )
        assert resp.status_code == 409
        assert not (api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "arquero-ciego.md").exists()
        # The proposal survives the failed confirm; the token is still redeemable.
        assert preview["proposal_id"] in api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_confirm_wrong_world_rejected_and_proposal_survives(self, client: TestClient, monkeypatch):
        """A preview generated for world A cannot be confirmed against world B.

        The request world must equal the world recorded on the proposal;
        otherwise 409 fires BEFORE the image copy and the canon write, so
        neither the ficha nor the media lands in world B, and the proposal is
        NOT consumed — a later confirm against the correct world A succeeds.
        """
        # A preview WITH an image proves the guard blocks the copy too.
        _write_idea(media_path="media/idea-foto.jpg")
        _write_idea_media("idea-foto.jpg", b"\xff\xd8\xff\xe0fake-jpeg")
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        preview_resp = _materialize_preview(client)
        assert preview_resp.status_code == 200, preview_resp.text
        preview = preview_resp.json()
        proposal_id = preview["proposal_id"]
        world_b = api_server.MUNDOS_DIR / "test_mundo_b"
        world_b.mkdir(parents=True, exist_ok=True)

        wrong = self._confirm(client, preview, mundo="test_mundo_b")
        assert wrong.status_code == 409, wrong.text
        assert wrong.json()["detail"] == "Materialize proposal is stale or altered"
        # Nothing was written or copied into world B.
        assert not (world_b / "lore" / "subdir" / "arquero-ciego.md").exists()
        assert not (world_b / "wiki" / "media" / "arquero-ciego.jpg").exists()
        assert not list(world_b.rglob("*.md"))
        # The proposal survived the mismatch.
        assert proposal_id in api_server._MATERIALIZE_PENDING_PROPOSALS

        # The correct world still confirms: ficha + carried image in world A.
        ok = self._confirm(client, preview, mundo="test_mundo")
        assert ok.status_code == 200, ok.text
        world_a = api_server.MUNDOS_DIR / "test_mundo"
        assert (world_a / "lore" / "subdir" / "arquero-ciego.md").is_file()
        assert (world_a / "wiki" / "media" / "arquero-ciego.jpg").is_file()
        assert proposal_id not in api_server._MATERIALIZE_PENDING_PROPOSALS

    def test_confirm_reports_index_status(self, client: TestClient, monkeypatch):
        """R-IM-06: the create response surfaces index_status/retryable/message."""
        preview = self._preview(client, monkeypatch)
        resp = self._confirm(client, preview)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["index_status"] in {"indexed", "pending", "dirty", "failed"}
        assert isinstance(body["retryable"], bool)
        assert "message" in body

    # -----------------------------------------------------------------------
    # PR7 (task 6.2) — confirm → reconcile → graph entities (R-IM-06, SC4/AC5)
    # -----------------------------------------------------------------------

    def test_confirm_new_entity_appears_in_graph_entities(self, client: TestClient, monkeypatch):
        """R-IM-06 (SC4): after a confirmed write the new entity is retrievable
        through GET /api/{mundo}/graph/entities with its server-built id/type.

        The coordinator is rebound per test to the hermetic mundos root: the
        production _GUIDED_REINDEX is a process-lifetime lazy binding that
        caches the FIRST test's root, so reconcile against a later tmp_path
        would report "not persisted" against the stale root (the same reason
        the PR5 confirm tests only assert index_status membership).
        """
        _write_idea()
        personajes = api_server.MUNDOS_DIR / "test_mundo" / "personajes"
        personajes.mkdir(parents=True, exist_ok=True)
        # A real grounding entity so the world index is non-trivial.
        (personajes / "rhyz.md").write_text(
            "---\nid: Rhyz::Rhyz\ntitle: Rhyz\ntype: Personaje\nstatus: stable\n"
            "schema_version: 1\nrelaciones: []\n---\n# Rhyz\n", encoding="utf-8")
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        monkeypatch.setattr(
            api_server, "_GUIDED_REINDEX",
            ReindexCoordinator(api_server._mundos_dir(), lambda world: api_server._get_graph(world)),
        )
        preview = _materialize_preview(client, section="personajes", folder="")
        assert preview.status_code == 200, preview.text
        resp = self._confirm(client, preview.json(), section="personajes", path="arquero-ciego.md")
        assert resp.status_code == 200, resp.text
        assert resp.json()["index_status"] == "indexed"
        graph = client.get("/api/test_mundo/graph/entities").json()
        by_path = {entity["path"]: entity for entity in graph["entities"]}
        entity = by_path.get("personajes/arquero-ciego.md")
        assert entity is not None, by_path.keys()
        assert entity["id"] == "arquero-ciego"
        assert entity["type"] == "personaje"
        assert entity["status"] == "stable"
        assert entity["relaciones"] == []

    @pytest.mark.parametrize("failed_status", ["dirty", "pending", "failed"])
    def test_confirm_reindex_failure_reports_status_and_keeps_ficha(
            self, client: TestClient, monkeypatch, failed_status):
        """R-IM-06 (SC4): a forced reconciliation failure returns
        index_status ∈ {dirty,pending,failed} with retryable:true and NEVER
        rolls back the durable ficha — it stays on disk byte-identical."""
        _write_idea()

        class _ForcedReindexFailure:
            def reconcile(self, **kwargs):
                return ReindexResult(
                    operation_id=kwargs["operation_id"],
                    content_digest=kwargs["content_digest"],
                    index_status=failed_status, retryable=True,
                    message="forced reindex failure for test",
                )

        monkeypatch.setattr(api_server, "_GUIDED_REINDEX", _ForcedReindexFailure())
        preview = self._preview(client, monkeypatch)
        resp = self._confirm(client, preview)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["index_status"] == failed_status
        assert body["retryable"] is True
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "arquero-ciego.md"
        assert target.is_file()
        assert target.read_text(encoding="utf-8") == preview["content"]

    # -----------------------------------------------------------------------
    # PR7 (task 6.3) — no-stub confirm + based_on link (R-IM-03/R-CG-04)
    # -----------------------------------------------------------------------

    def test_confirm_all_invented_relations_writes_empty_relaciones_no_stubs(
            self, client: TestClient, monkeypatch):
        """R-IM-03 (SC11/AC9): when every AI relation targets a non-existent
        entity the ficha is still written with empty/valid relaciones, the
        discards are reported, and none of the missing targets is created —
        no stub ficha ever lands on disk or in the graph."""
        _write_idea()
        invented = [
            {"target_id": "Rhyz::Rhyz", "rel_type": "aliado-de"},
            {"target_id": "Personaje::Inventado", "rel_type": "parentesco-de"},
        ]

        def result(request, _cancellation):
            return _materialize_delta(request, relations=invented)

        _wire_materialize(monkeypatch, result)  # entities=None → real index
        preview = _materialize_preview(client)
        assert preview.status_code == 200, preview.text
        payload = preview.json()
        assert payload["proposed_relations"] == []
        assert payload["discarded_relations"] == [
            {"target_id": "Rhyz::Rhyz", "reason": "target_not_found"},
            {"target_id": "Personaje::Inventado", "reason": "target_not_found"},
        ]
        assert "relaciones: []" in payload["content"]
        assert "Rhyz::Rhyz" not in payload["content"]
        assert "Personaje::Inventado" not in payload["content"]

        resp = self._confirm(client, payload)
        assert resp.status_code == 200, resp.text
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "arquero-ciego.md"
        assert target.is_file()
        assert target.read_text(encoding="utf-8") == payload["content"]
        # None of the invented targets was created anywhere under the world.
        world = api_server.MUNDOS_DIR / "test_mundo"
        for path in world.rglob("*.md"):
            assert "rhyz" not in path.name.lower() and "inventado" not in path.name.lower()
        graph = client.get("/api/test_mundo/graph/entities").json()
        invented_ids = {"Rhyz::Rhyz", "Personaje::Inventado"}
        assert not (invented_ids & {entity["id"] for entity in graph["entities"]})

    def test_confirm_ficha_carries_based_on_link(self, client: TestClient, monkeypatch):
        """R-CG-04: the NEW ficha written by the confirm flow carries
        based_on: ideas/{slug} in its frontmatter on disk."""
        preview = self._preview(client, monkeypatch)
        resp = self._confirm(client, preview)
        assert resp.status_code == 200, resp.text
        target = api_server.MUNDOS_DIR / "test_mundo" / "lore" / "subdir" / "arquero-ciego.md"
        assert target.is_file()
        content = target.read_text(encoding="utf-8")
        assert "based_on: ideas/arquero-ciego" in content

    # -----------------------------------------------------------------------
    # WU9 (BUG-B) — validated relations reach the graph (R-IM-03/06, SC4)
    # -----------------------------------------------------------------------

    def test_confirm_validated_relations_appear_in_graph_entities(
            self, client: TestClient, monkeypatch):
        """R-IM-06 (SC4): a validated AI relation against a REAL index entity
        survives the confirm and appears as a forward_link of the new entity
        in GET /api/{mundo}/graph/entities.

        Regression for BUG-B: grounding candidates and existing_ids must come
        from the real index enumeration (``entities()``), never from
        ``search("*")`` — which returns ``[]`` against the real index by
        design, so every AI relation used to be discarded as
        ``target_not_found`` and no validated relation ever reached the graph.
        """
        _write_idea()
        personajes = api_server.MUNDOS_DIR / "test_mundo" / "personajes"
        personajes.mkdir(parents=True, exist_ok=True)
        (personajes / "rhyz.md").write_text(
            "---\nid: Rhyz::Rhyz\ntitle: Rhyz\ntype: Personaje\nstatus: stable\n"
            "schema_version: 1\nrelaciones: []\n---\n# Rhyz\n", encoding="utf-8")
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(
            request, relations=[{"target_id": "Rhyz::Rhyz", "rel_type": "aliado-de"}]))
        monkeypatch.setattr(
            api_server, "_GUIDED_REINDEX",
            ReindexCoordinator(api_server._mundos_dir(), lambda w: api_server._get_graph(w)),
        )
        preview = _materialize_preview(client, section="personajes", folder="")
        assert preview.status_code == 200, preview.text
        assert preview.json()["proposed_relations"] == [
            {"target_id": "Rhyz::Rhyz", "title": "Rhyz", "rel_type": "aliado-de"},
        ]
        resp = self._confirm(client, preview.json(), section="personajes", path="arquero-ciego.md")
        assert resp.status_code == 200 and resp.json()["index_status"] == "indexed"
        graph = client.get("/api/test_mundo/graph/entities").json()
        by_path = {entity["path"]: entity for entity in graph["entities"]}
        assert by_path["personajes/arquero-ciego.md"]["forward_links"] == ["Rhyz::Rhyz"]

    # -----------------------------------------------------------------------
    # WU9 (BUG-A) — confirm marks the idea used (R-CG-04, SC5/AC7)
    # -----------------------------------------------------------------------

    def test_confirm_marks_idea_used_across_worlds(self, client: TestClient, monkeypatch):
        """R-CG-04 (SC5): confirming the ficha updates the idea — the world
        slug accumulates in used_in[] (deduped) and status becomes used.

        Regression for BUG-A: create_file's materialize branch never called
        IdeasBank.materialize, so after a successful preview→confirm the idea
        still showed used_in: [] and status: fresh.
        """
        _write_idea()
        (api_server.MUNDOS_DIR / "test_mundo_b" / "lore").mkdir(parents=True, exist_ok=True)
        _wire_materialize(monkeypatch, lambda request, _c: _materialize_delta(request))
        for world in ("test_mundo", "test_mundo_b"):
            preview = _materialize_preview(client, world=world)
            assert preview.status_code == 200, preview.text
            resp = self._confirm(client, preview.json(), mundo=world)
            assert resp.status_code == 200, resp.text
        idea = (api_server.PROJECT_ROOT / "ideas" / "arquero-ciego.md").read_text(encoding="utf-8")
        assert "used_in:" in idea and "test_mundo" in idea and "test_mundo_b" in idea
        assert "status: used" in idea


# ---------------------------------------------------------------------------
# Guided create branch — world pinning (same class of gap as the materialize
# branch: a proposal is bound to the world it was generated for)
# ---------------------------------------------------------------------------


class TestGuidedCreateWorldBinding:
    """The guided create branch pins the request world to the proposal's world.

    The guided pending record carries no ``world`` directly, but it carries its
    ``session_id`` and the guided session store is the authority on the world
    the proposal was serialized for. The create guard recovers that session and
    rejects a confirm whose URL world differs.
    """

    def _proposal(self, client: TestClient, monkeypatch, world: str) -> dict:
        _principal(monkeypatch, "tester")
        store = api_server.GuidedSessionStore()
        state = store.create("guided-world", world, "tester")
        state.candidate.proposals["desire"] = {"value": "freedom", "certainty": "proposed"}
        store._sessions["guided-world"] = state
        monkeypatch.setattr(api_server, "_GUIDED_SESSIONS", store)
        resp = client.post(
            f"/api/{world}/guided-character/proposal/serialize",
            json={"session_id": "guided-world", "base_revision": 0,
                  "slug": "aria", "title": "Aria"},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def _confirm(self, client: TestClient, preview: dict, mundo: str):
        section, path = preview["target"].split("/", 1)
        conf = client.post(
            f"/api/{mundo}/{section}/edit-confirmation?path={path}",
            json={"edit_id": preview["proposal_id"], "kind": "new",
                  "proposed_content": preview["proposed_content"]},
        )
        assert conf.status_code == 200, conf.text
        conf = conf.json()
        return client.post(
            f"/api/{mundo}/{section}/create?path={path}",
            json={"content": preview["proposed_content"], "edit_id": preview["proposal_id"],
                  "proposed_digest": conf["proposed_digest"], "token": conf["token"]},
        )

    def test_confirm_wrong_world_rejected_and_proposal_survives(
            self, client: TestClient, monkeypatch):
        preview = self._proposal(client, monkeypatch, "test_mundo")
        proposal_id = preview["proposal_id"]
        world_b = api_server.MUNDOS_DIR / "test_mundo_b"
        world_b.mkdir(parents=True, exist_ok=True)

        wrong = self._confirm(client, preview, "test_mundo_b")
        assert wrong.status_code == 409, wrong.text
        assert wrong.json()["detail"] == "Guided proposal is stale or altered"
        assert not (world_b / "personajes" / "aria.md").exists()
        assert proposal_id in api_server._GUIDED_PENDING_PROPOSALS

        ok = self._confirm(client, preview, "test_mundo")
        assert ok.status_code == 200, ok.text
        written = api_server.MUNDOS_DIR / "test_mundo" / "personajes" / "aria.md"
        assert written.is_file()
        assert written.read_text(encoding="utf-8") == preview["proposed_content"]


class TestTriggerApprovalApi:
    """Etapa 2 (WU 2.2): the draft publish gate refuses without an explicit
    trigger approval, and the approve endpoint records the auditable approval.

    The co-creation route's twin (same ``trigger_not_approved`` code, session
    not advanced) is covered in ``test_co_creation_api.py``.
    """

    _PAYLOAD = {
        "skill_id": "guided-character-v1",
        "version": "1.2.0",
        "name": "Guided character methodology",
        "source": "## Construcción segura\n\nHaz preguntas de a una.\n",
    }

    def _draft(self, client: TestClient) -> str:
        draft = client.post("/api/methodologies/drafts", json=self._PAYLOAD)
        assert draft.status_code == 200, draft.text
        return draft.json()["draft_id"]

    def test_publish_without_approval_refused_with_dedicated_code(
        self, client: TestClient, monkeypatch,
    ):
        """A gate refusal maps to 409 ``trigger_not_approved`` — never the
        generic ``reserved_skill_id`` (TD-D catch-ordering) and never a 500."""
        _principal(monkeypatch, "author-1")
        draft_id = self._draft(client)
        published = client.post(f"/api/methodologies/drafts/{draft_id}/publish")
        assert published.status_code == 409
        assert published.json()["code"] == "trigger_not_approved"
        # No immutable version was created and the draft remains editable.
        library = api_server._methodology_library()
        assert library.list_published() == []
        assert library.get_draft(draft_id) is not None

    def test_approve_endpoint_records_audit_fields_and_enables_publish(
        self, client: TestClient, monkeypatch,
    ):
        _principal(monkeypatch, "author-1")
        draft_id = self._draft(client)
        approved = client.post(
            f"/api/methodologies/drafts/{draft_id}/trigger/approve",
            json={"description": "  Ayuda   a crear personajes  "},
        )
        assert approved.status_code == 200, approved.text
        approval = approved.json()["trigger_approval"]
        assert approval["text"] == "Ayuda a crear personajes"  # normalized
        assert approval["digest"]
        assert approval["approved_by"] == "author-1"
        assert approval["approved_at"]
        published = client.post(f"/api/methodologies/drafts/{draft_id}/publish")
        assert published.status_code == 200, published.text
        # The approval binds the trigger; the method description is untouched.
        assert published.json()["trigger"] == "Ayuda a crear personajes"
        assert published.json()["description"] == ""

    def test_approve_requires_authentication(self, client: TestClient):
        denied = client.post(
            "/api/methodologies/drafts/whatever/trigger/approve",
            json={"description": "x"},
        )
        assert denied.status_code == 401

    def test_approve_unknown_draft_is_404(self, client: TestClient, monkeypatch):
        _principal(monkeypatch, "author-1")
        missing = client.post(
            "/api/methodologies/drafts/ghost/trigger/approve",
            json={"description": "x"},
        )
        assert missing.status_code == 404

    def test_approve_rejects_empty_and_over_bound_without_recording(
        self, client: TestClient, monkeypatch,
    ):
        _principal(monkeypatch, "author-1")
        draft_id = self._draft(client)
        empty = client.post(
            f"/api/methodologies/drafts/{draft_id}/trigger/approve",
            json={"description": "   "},
        )
        assert empty.status_code == 422
        assert empty.json()["code"] == "trigger_invalid"
        over = client.post(
            f"/api/methodologies/drafts/{draft_id}/trigger/approve",
            json={"description": "x" * 61},
        )
        assert over.status_code == 422
        assert over.json()["code"] == "trigger_invalid"
        # The server bound is authoritative: no approval was recorded.
        library = api_server._methodology_library()
        assert library.get_draft(draft_id).trigger_approval is None

    def test_status_drafts_exposes_trigger_approval(
        self, client: TestClient, monkeypatch,
    ):
        _principal(monkeypatch, "author-1")
        draft_id = self._draft(client)
        client.post(
            f"/api/methodologies/drafts/{draft_id}/trigger/approve",
            json={"description": "Trigger visible en estado"},
        )
        status = client.get("/api/methodologies/status")
        assert status.status_code == 200, status.text
        entry = next(
            item for item in status.json()["drafts"] if item["draft_id"] == draft_id
        )
        assert entry["trigger_approval"]["text"] == "Trigger visible en estado"

    def test_trigger_drift_after_approval_fails_closed(
        self, client: TestClient, monkeypatch,
    ):
        _principal(monkeypatch, "author-1")
        draft_id = self._draft(client)
        client.post(
            f"/api/methodologies/drafts/{draft_id}/trigger/approve",
            json={"description": "Trigger A"},
        )
        # A later trigger edit invalidates the prior approval (fail closed).
        api_server._methodology_library().update_draft(draft_id, trigger="Trigger B")
        published = client.post(f"/api/methodologies/drafts/{draft_id}/publish")
        assert published.status_code == 409
        assert published.json()["code"] == "trigger_not_approved"

    def test_description_drift_after_approval_keeps_the_gate_open(
        self, client: TestClient, monkeypatch,
    ):
        """The method summary is a separate surface: editing it never revokes
        the trigger approval."""
        _principal(monkeypatch, "author-1")
        draft_id = self._draft(client)
        client.post(
            f"/api/methodologies/drafts/{draft_id}/trigger/approve",
            json={"description": "Trigger A"},
        )
        api_server._methodology_library().update_draft(
            draft_id, description="Resumen del método",
        )
        published = client.post(f"/api/methodologies/drafts/{draft_id}/publish")
        assert published.status_code == 200, published.text
        assert published.json()["trigger"] == "Trigger A"
        assert published.json()["description"] == "Resumen del método"


# ---------------------------------------------------------------------------
# Export leak: the package must carry the index trigger and the guided-flow
# declaration the published record holds (round-trip fidelity).
# ---------------------------------------------------------------------------


def test_export_carries_the_seed_trigger_and_guided_flow(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """A published skill's label and flow declaration ship in the package and
    re-inspect clean instead of being silently dropped."""
    _principal(monkeypatch, "author-1")
    library = MethodologyLibrary(tmp_path / "library.json")
    install_seeds(library, SEED_ROOT)
    monkeypatch.setattr(api_server, "_METHODOLOGY_LIBRARY", library)

    exported = client.post(
        "/api/methodologies/published/narrative-entity-creation/1.0/export",
    )
    assert exported.status_code == 200, exported.text
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    manifest = yaml.safe_load(archive.read("manifest.yaml"))
    assert manifest["trigger"] == (
        "Co-crea lugares, facciones, criaturas y otras entidades."
    )
    assert manifest["guided_flow"]["flow_id"] == "guided-entity"
    assert manifest["guided_flow"]["entity_type"] == "entidad"

    verdict = inspect_package(exported.content)
    assert verdict.ok, verdict.issues
    assert verdict.compiled is not None
    assert verdict.compiled.trigger == manifest["trigger"]
    assert verdict.compiled.guided_flow is not None
    assert verdict.compiled.guided_flow.flow_id == "guided-entity"


def test_export_without_trigger_or_flow_keeps_the_old_manifest_shape(
    client: TestClient, monkeypatch, tmp_path: Path,
) -> None:
    """Backward compatibility: a record with neither field exports exactly as
    before — no invented keys."""
    _principal(monkeypatch, "author-1")
    compiled = compile_methodology({
        "skill_id": "plain-method",
        "version": "1.0",
        "name": "Plain method",
        "description": "A safe method.",
    }, "## Método\n\nPreguntas de a una.\n").compiled
    assert compiled is not None
    library = MethodologyLibrary(tmp_path / "library.json")
    library.install_published_version(
        compiled, clasificacion="Oficiales", trust_attributes=(),
    )
    monkeypatch.setattr(api_server, "_METHODOLOGY_LIBRARY", library)

    exported = client.post("/api/methodologies/published/plain-method/1.0/export")
    assert exported.status_code == 200, exported.text
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    manifest = yaml.safe_load(archive.read("manifest.yaml"))
    assert "trigger" not in manifest
    assert "guided_flow" not in manifest
    assert inspect_package(exported.content).ok


def test_world_creation_is_refused_until_the_content_move_is_restarted(
    empty_client: TestClient, tmp_path: Path, monkeypatch
):
    """A world created after a move would land in the OLD root.

    The record of a completed move whose pointer already names the new folder,
    while this process still uses the old one, is the signal: restart first.
    """
    api_server._LOCAL_STATE = None
    old = tmp_path / "viejo"
    new = tmp_path / "nuevo"
    old.mkdir()
    new.mkdir()
    monkeypatch.setattr(api_server, "PROJECT_ROOT", old)
    monkeypatch.setattr(
        api_server,
        "read_last_move",
        lambda record_dir: {
            "schema_version": 1,
            "state": "done",
            "pointer_written": True,
            "source": str(old),
            "target": str(new),
            "finished_at": "2026-10-29T00:00:00Z",
        },
    )
    monkeypatch.setattr(api_server, "_mundos_dir", lambda: old / "mundos")

    response = empty_client.post("/api/worlds", json={"name": "tarde"})

    assert response.status_code == 409
    assert "restart" in response.json()["detail"].lower()
    assert not (old / "mundos" / "tarde").exists()


def test_a_pointer_that_differs_without_a_move_record_still_creates(
    empty_client: TestClient, tmp_path: Path, monkeypatch
):
    """An environment override is a legitimate configuration, not a pending move.

    Without a recorded move there is nothing to restart for: refusing here would
    break every install that runs under DEMIURGOS_DATA_ROOT.
    """
    api_server._LOCAL_STATE = None
    root = tmp_path / "contenido"
    (root / "mundos").mkdir(parents=True)
    monkeypatch.setattr(api_server, "PROJECT_ROOT", root)
    monkeypatch.setattr(api_server, "read_last_move", lambda record_dir: None)
    monkeypatch.setattr(api_server, "_mundos_dir", lambda: root / "mundos")

    response = empty_client.post("/api/worlds", json={"name": "temprano"})

    assert response.status_code == 201, response.text


def test_the_move_route_is_not_shadowed_by_the_world_move_route(
    empty_client: TestClient,
):
    """`POST /api/{mundo}/move` is registered earlier and matches "data-root".

    With the route named `/move`, the app never reached it: it answered "Se
    requieren los campos 'from' y 'to'" — the world-file move. The content move
    lives at `/move-content`, which cannot collide.
    """
    hijacked = empty_client.post("/api/data-root/move", json={})
    assert hijacked.status_code == 400
    assert "from" in hijacked.json()["detail"]  # the world-file route, for the record

    mine = empty_client.post("/api/data-root/move-content", json={})
    assert mine.status_code != 400 or "from" not in str(mine.json().get("detail", ""))
    assert "from 'y' to" not in str(mine.json().get("detail", ""))


def test_the_content_root_routes_are_mounted():
    """Step 4: the app exposes the content root on /api/data-root (GET + POST)."""
    import api_server

    paths = api_server.app.openapi()["paths"]
    assert "/api/data-root" in paths
    assert set(paths["/api/data-root"]) == {"get", "post"}
    # Step 5: the move is a job, plus the record and the confirmed cleanup.
    for route in (
        "/api/data-root/move-content",
        "/api/data-root/move-content/{job_id}",
        "/api/data-root/move-content/{job_id}/cancel",
        "/api/data-root/last-move",
        "/api/data-root/cleanup",
        "/api/data-root/candidates",
        "/api/data-root/pick-folder",
    ):
        assert route in paths, route
