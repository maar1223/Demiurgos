"""P4 verifier probes — global reconciliation, pre-image backup, curation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import api_server
from relation_reconcile import create_preimage_backup
from relation_rejections import record_rejection
from test_api_server import client, _principal  # noqa: F401


def _world() -> Path:
    return api_server.MUNDOS_DIR / "test_mundo"


def _add(world: Path, rel: str, fm: str, body: str) -> Path:
    path = world / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm}---\n{body}", encoding="utf-8")
    api_server._graph_indices.clear()
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed(world: Path) -> None:
    _add(world, "lore/beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    _add(world, "lore/gamma.md", "type: personaje\nid: lore::gamma\ntitle: Gamma\n", "Gamma.\n")
    _add(world, "lore/alpha.md",
         "type: personaje\nid: lore::alpha\ntitle: Alpha\nrelaciones:\n  - lore::gamma\n",
         "Alpha served Beta.\n")


def test_s5_backup_is_byte_exact_with_manifest(tmp_path: Path) -> None:
    world = tmp_path / "w"
    (world / "lore").mkdir(parents=True)
    raw = b"---\r\ntype: x\r\nid: lore::a\r\n---\r\nCaf\xc3\xa9\r\n"
    (world / "lore" / "a.md").write_bytes(raw)
    root, skipped = create_preimage_backup(world, ["lore/a.md"], counts={"additions": 1})
    assert skipped == ()
    assert (root / "files" / "lore" / "a.md").read_bytes() == raw
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"] == ["lore/a.md"]
    assert manifest["counts"] == {"additions": 1}
    assert manifest["created_at"]


def test_s5_backup_failure_writes_nothing(client, monkeypatch) -> None:
    _principal(monkeypatch)
    world = _world()
    _seed(world)
    before = _digest(world / "lore" / "alpha.md")
    (world / ".relations").mkdir(exist_ok=True)
    (world / ".relations" / "preimages").write_text("block", encoding="utf-8")
    response = client.post("/api/test_mundo/relations/reconcile")
    assert response.status_code == 500, response.text
    assert _digest(world / "lore" / "alpha.md") == before


def test_s7_rewrite_failure_is_reported_and_does_not_abort(client, monkeypatch) -> None:
    _principal(monkeypatch)
    world = _world()
    _seed(world)
    locked = world / "lore" / "locked"
    locked.mkdir()
    delta = _add(world, "lore/locked/delta.md",
                 "type: personaje\nid: lore::delta\ntitle: Delta\nrelaciones:\n  - lore::gamma\n",
                 "Delta mentions nobody.\n")
    alpha_before, delta_before = _digest(world / "lore" / "alpha.md"), _digest(delta)
    locked.chmod(0o555)
    try:
        body = client.post("/api/test_mundo/relations/reconcile").json()
    finally:
        locked.chmod(0o755)
    assert body["applied"] == 1
    assert body["failed"] == ["lore/locked/delta.md"]
    assert _digest(world / "lore" / "alpha.md") != alpha_before
    assert _digest(delta) == delta_before


def test_s7_unreadable_file_is_reported_and_does_not_abort(client, monkeypatch) -> None:
    _principal(monkeypatch)
    world = _world()
    _seed(world)
    hidden = world / "lore" / "hidden"
    hidden.mkdir()
    delta = _add(world, "lore/hidden/delta.md",
                 "type: personaje\nid: lore::delta\ntitle: Delta\nrelaciones:\n  - lore::gamma\n",
                 "Delta mentions nobody.\n")
    assert client.get("/api/test_mundo/relations/reconcile/preview").json()["files"] == 2
    alpha_before = _digest(world / "lore" / "alpha.md")
    delta.chmod(0o000)
    try:
        response = client.post("/api/test_mundo/relations/reconcile")
    finally:
        delta.chmod(0o644)
    assert response.status_code == 200, response.text
    assert response.json()["failed"] == ["lore/hidden/delta.md"]
    assert _digest(world / "lore" / "alpha.md") != alpha_before


def test_s3_muted_ficha_is_skipped_for_every_accepted_path_spelling(client, monkeypatch) -> None:
    _principal(monkeypatch)
    world = _world()
    _seed(world)
    before = _digest(world / "lore" / "alpha.md")
    assert client.post(
        "/api/test_mundo/relations/mute", json={"path": "lore/./alpha.md"}
    ).status_code == 200
    assert client.get("/api/test_mundo/relations/reconcile/preview").json()["files"] == 0
    assert client.post("/api/test_mundo/relations/reconcile").json()["applied"] == 0
    assert _digest(world / "lore" / "alpha.md") == before


def test_s3_s7_rejected_pair_removed_not_readded_and_second_pass_no_backup(client, monkeypatch) -> None:
    _principal(monkeypatch)
    world = _world()
    _add(world, "lore/beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    alpha = _add(world, "lore/alpha.md",
                 "type: personaje\nid: lore::alpha\ntitle: Alpha\nrelaciones:\n  - lore::beta\n",
                 "Alpha served Beta.\n")
    record_rejection(world, "lore::alpha", "lore::beta")
    item = client.get("/api/test_mundo/relations/reconcile/preview").json()["items"][0]
    assert item["add"] == [] and item["remove"][0]["reason"] == "rejected"
    assert client.post("/api/test_mundo/relations/reconcile").json()["applied"] == 1
    assert "lore::beta" not in alpha.read_text(encoding="utf-8")
    backups = list((world / ".relations" / "preimages").iterdir())
    second = client.post("/api/test_mundo/relations/reconcile").json()
    assert second["applied"] == 0 and second["backup"] == ""
    assert list((world / ".relations" / "preimages").iterdir()) == backups


def test_s2_display_name_kept_when_grounded_and_dangling_removed(client, monkeypatch) -> None:
    _principal(monkeypatch)
    world = _world()
    _add(world, "lore/beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    kept = _add(world, "lore/kept.md",
                "type: personaje\nid: lore::kept\ntitle: Kept\nrelaciones:\n  - Beta\n",
                "Kept served Beta.\n")
    gone = _add(world, "lore/gone.md",
                "type: personaje\nid: lore::gone\ntitle: Gone\nrelaciones:\n  - Ghost\n",
                "Gone mentions nobody.\n")
    items = {i["path"]: i for i in client.get("/api/test_mundo/relations/reconcile/preview").json()["items"]}
    assert "lore/kept.md" not in items
    assert items["lore/gone.md"]["remove"][0]["reason"] == "unresolved"
    assert client.post("/api/test_mundo/relations/reconcile").status_code == 200
    assert "Beta" in kept.read_text(encoding="utf-8")
    assert "Ghost" not in gone.read_text(encoding="utf-8")


def test_s2_s3_legacy_empty_id_source_adds_and_honours_rejection(client, monkeypatch) -> None:
    _principal(monkeypatch)
    world = _world()
    _add(world, "lore/beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    legacy = _add(world, "lore/legacy.md", "type: personaje\ntitle: Legacy\n", "Legacy served Beta.\n")
    assert client.get("/api/test_mundo/relations/reconcile/preview").json()["items"][0]["add"] == ["lore::beta"]
    assert client.post("/api/test_mundo/relations/reconcile").status_code == 200
    assert "lore::beta" in legacy.read_text(encoding="utf-8")
    record_rejection(world, "lore/legacy.md", "lore::beta")
    assert client.get("/api/test_mundo/relations/reconcile/preview").json()["files"] == 1


def test_s4_s6_client_cannot_inject_and_preview_is_read_only(client, monkeypatch) -> None:
    _principal(monkeypatch)
    world = _world()
    _seed(world)

    def tree_hash() -> str:
        h = hashlib.sha256()
        for p in sorted(world.rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(world)).encode())
                h.update(p.read_bytes())
        return h.hexdigest()

    before = tree_hash()
    assert client.get("/api/test_mundo/relations/reconcile/preview").status_code == 200
    assert tree_hash() == before
    response = client.post("/api/test_mundo/relations/reconcile",
                           json={"add": ["lore::gamma"], "remove": ["lore::beta"]})
    assert response.status_code == 200
    saved = (world / "lore" / "alpha.md").read_text(encoding="utf-8")
    assert "lore::beta" in saved and "lore::gamma" not in saved


def test_s6_crlf_file_line_endings_are_preserved(client, monkeypatch) -> None:
    _principal(monkeypatch)
    world = _world()
    _add(world, "lore/beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    raw = (b"---\r\ntype: personaje\r\nid: lore::alpha\r\ntitle: Alpha\r\n"
           b"relaciones:\r\n  - lore::gamma\r\n---\r\nAlpha served Beta.\r\n")
    alpha = world / "lore" / "alpha.md"
    alpha.write_bytes(raw)
    _add(world, "lore/gamma.md", "type: personaje\nid: lore::gamma\ntitle: Gamma\n", "Gamma.\n")
    assert client.post("/api/test_mundo/relations/reconcile").status_code == 200
    after = alpha.read_bytes()
    assert b"\r\n" in after
    assert "lore::beta" in after.decode("utf-8") and "lore::gamma" not in after.decode("utf-8")
