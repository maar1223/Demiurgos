# -*- coding: utf-8 -*-
"""Boot the app from the payload manifest only (design S0-D / tasks 0.4).

Stages exactly the files named by ``payload_manifest.json`` (the derived
allow-list) into a temp tree, makes the real source repo unreachable on
``sys.path``, imports ``api_server`` from the staged tree, and boots the app.

Asserts the four verified required additions are present (``capability_probes``,
``idea_capture``, ``sync_lore``, ``data/methodology/seeds``) and that
``plantillas`` (author data, ``data_root.py:4-5``) is absent — the PM-3 fix:
a hand-maintained allow-list already missed three runtime packages and the
seeds, so the payload is derived from real import sites and this boot proves
the derivation is sufficient for the app to come up.
"""

import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[4]
_MANIFEST = _REPO_ROOT / "payload_manifest.json"

_WIKI = _HERE.parent
_SUITE = _WIKI.parent
_TOOLS = _SUITE.parent

_REQUIRED_SUBTREES = (
    "src/tools/capability_probes",
    "src/tools/idea_capture",
    "src/tools/sync_lore",
    "data/methodology/seeds",
)
_DENIED_SUBTREE = "plantillas"


@pytest.fixture()
def staged_payload(tmp_path: Path):
    """Stage the manifest allow-list; scrub the repo from sys.path/modules.

    Hermetic: ``sys.path`` and ``sys.modules`` are snapshotted and restored
    EXACTLY on teardown, so the staged anchors never leak into later tests. An
    earlier version left them at the front of ``sys.path``, which made unrelated
    tests (e.g. the sync_lore import flow) resolve modules from the temp payload
    copy and fail.
    """
    assert _MANIFEST.is_file(), f"missing derived manifest: {_MANIFEST}"
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))

    original_sys_path = list(sys.path)
    original_modules = dict(sys.modules)

    staged_root = tmp_path / "payload"
    for rel in manifest["payload"]:
        source = _REPO_ROOT / rel
        if source.is_file():
            target = staged_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    # Make the real repo unreachable: drop every sys.path anchor that lives
    # under the repo's src/tools, then purge the modules that were resolved
    # from there so nothing can be reused from the real checkout.
    real_anchors = {str(p) for p in (_WIKI, _SUITE, _TOOLS)}
    removed_paths = [p for p in sys.path if p in real_anchors]
    for p in removed_paths:
        sys.path.remove(p)

    purged = [
        name
        for name, module in list(sys.modules.items())
        if getattr(module, "__file__", "") and str(Path(module.__file__).resolve()).startswith(
            str(_TOOLS.resolve())
        )
    ]
    for name in purged:
        del sys.modules[name]

    # Add the staged anchors and import the app from the payload tree.
    staged_anchors = (
        staged_root / "src/tools/demiurgos-suite/wiki",
        staged_root / "src/tools/demiurgos-suite",
        staged_root / "src/tools",
    )
    for anchor in reversed(staged_anchors):
        sys.path.insert(0, str(anchor))

    api_server = importlib.import_module("api_server")
    staged = staged_root / "src/tools/demiurgos-suite/wiki/api_server.py"
    assert Path(api_server.__file__).resolve() == staged.resolve(), (
        "api_server resolved outside the staged payload — isolation failed"
    )

    yield staged_root, api_server

    # Restore sys.path and sys.modules EXACTLY (no leak into later tests).
    sys.path[:] = original_sys_path
    for name in list(sys.modules):
        if name not in original_modules:
            del sys.modules[name]
    for name, module in original_modules.items():
        sys.modules[name] = module


class TestPayloadBoot:
    def test_manifest_only_boot_serves_health(self, staged_payload):
        staged_root, api_server = staged_payload
        client = TestClient(api_server.app)
        response = client.get("/health")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "ok"

    def test_required_subtrees_are_present(self, staged_payload):
        staged_root, _ = staged_payload
        for subtree in _REQUIRED_SUBTREES:
            assert (staged_root / subtree).exists(), f"missing required subtree: {subtree}"

    def test_plantillas_is_absent(self, staged_payload):
        staged_root, _ = staged_payload
        assert not (staged_root / _DENIED_SUBTREE).exists()

    def test_seeds_are_ten_files(self, staged_payload):
        staged_root, _ = staged_payload
        seeds = [p for p in (staged_root / "data/methodology/seeds").rglob("*") if p.is_file()]
        assert len(seeds) == 10, f"expected 10 seeded files, found {len(seeds)}"