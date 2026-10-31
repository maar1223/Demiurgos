"""Regression probes for relations-lifecycle-p1 (S2,S5,S6,S7,S8 + digest order)."""
import hashlib
from pathlib import Path

import pytest

import api_server
from test_api_server import (  # noqa: F401
    client, _confirm, _confirm_new, _gated_create, _gated_write, _principal,
    _write_idea, _wire_materialize, _materialize_delta, _materialize_preview,
)


def _world() -> Path:
    return api_server.MUNDOS_DIR / "test_mundo" / "lore"


def _add(world: Path, rel: str, fm: str, body: str) -> Path:
    p = world / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{fm}---\n{body}", encoding="utf-8")
    api_server._graph_indices.clear()
    return p


def _save(client, path, content, edit_id="e1"):
    conf, base = _confirm(client, path, content, edit_id=edit_id)
    return _gated_write(client, path, content, conf, base, edit_id=edit_id)


def test_s8_additive_merge_keeps_existing(client, monkeypatch):          # S8
    _principal(monkeypatch)
    w = _world()
    _add(w, "beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    _add(w, "gamma.md", "type: personaje\nid: lore::gamma\ntitle: Gamma\n", "Gamma.\n")
    content = ("---\ntype: criatura\ntitle: Inicio\nrelaciones:\n  - lore::gamma\n---\n"
               "Beta arrives.\n")
    assert _save(client, "00_inicio.md", content).status_code == 200
    saved = (w / "00_inicio.md").read_text(encoding="utf-8")
    assert "lore::gamma" in saved and "lore::beta" in saved, saved


def test_s8_additive_merge_flow_form_entry_survives(client, monkeypatch):  # S8
    _principal(monkeypatch)
    w = _world()
    _add(w, "beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    content = ("---\ntype: criatura\ntitle: Inicio\nrelaciones: [lore::gamma]\n---\n"
               "Beta arrives.\n")
    assert _save(client, "00_inicio.md", content).status_code == 200
    saved = (w / "00_inicio.md").read_text(encoding="utf-8")
    assert "lore::gamma" in saved and "lore::beta" in saved, saved


def test_s2_s5_second_save_hook_writes_nothing(client, monkeypatch):      # S2,S5
    _principal(monkeypatch)
    w = _world()
    _add(w, "beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    content = "---\ntype: criatura\ntitle: Inicio\n---\nBeta arrives.\n"
    assert _save(client, "00_inicio.md", content).status_code == 200
    p = w / "00_inicio.md"
    after1 = p.read_bytes()
    assert after1.decode().count("lore::beta") == 1
    real = api_server._atomic_write
    calls = []

    def counting(full, data):
        calls.append(str(full))
        return real(full, data)

    monkeypatch.setattr(api_server, "_atomic_write", counting)
    assert _save(client, "00_inicio.md", after1.decode(), edit_id="e2").status_code == 200
    assert p.read_bytes() == after1
    assert after1.decode().count("lore::beta") == 1
    assert len(calls) == 1, calls  # only the pre-existing save write; hook wrote nothing


def test_s2_s5_service_apply_twice_writes_nothing_second(monkeypatch):    # S2,S5
    import tempfile
    from relation_service import build_relation_plan
    from test_relation_service import FakeIndex

    with tempfile.TemporaryDirectory() as td:
        mundos = Path(td) / "mundos"
        world = mundos / "w" / "lore"
        world.mkdir(parents=True)
        (world / "alpha.md").write_text(
            "---\ntype: personaje\nid: lore::alpha\ntitle: Alpha\n---\nAlpha names Beta.\n",
            encoding="utf-8")
        (world / "beta.md").write_text(
            "---\ntype: personaje\nid: lore::beta\ntitle: Beta\n---\nBeta.\n",
            encoding="utf-8")
        index = FakeIndex([{"path": "lore/beta.md", "id": "lore::beta",
                            "name": "Beta", "content": "Beta."}])
        monkeypatch.setattr(api_server, "_mundos_dir", lambda: mundos)
        plan = build_relation_plan(mundo="w", changed_paths=["lore/alpha.md"],
                                   mundos_dir=mundos, index=index)
        assert plan.relations.get("lore/alpha.md") == ("lore::beta",), plan
        real = api_server._atomic_write
        calls = []

        def counting(full, data):
            calls.append(str(full))
            return real(full, data)

        monkeypatch.setattr(api_server, "_atomic_write", counting)
        api_server._apply_relation_plan("w", plan)
        assert len(calls) == 1, calls
        api_server._apply_relation_plan("w", plan)
        assert len(calls) == 1, calls
        text = (world / "alpha.md").read_text(encoding="utf-8")
        assert text.count("lore::beta") == 1, text


def test_s2_reverse_pass_via_api(client, monkeypatch):                    # S2
    _principal(monkeypatch)
    w = _world()
    _add(w, "delta.md", "type: personaje\nid: lore::delta\ntitle: Delta\n",
         "Delta mentions Gamma.\n")
    content = ("---\ntype: personaje\nid: lore::gamma\ntitle: Gamma\n---\nGamma is new.\n")
    conf = _confirm_new(client, "gamma.md", content)
    assert _gated_create(client, "gamma.md", content, conf).status_code == 200
    assert "lore::gamma" in (w / "delta.md").read_text(encoding="utf-8")


def test_s7_graph_false_target_is_skipped(client, monkeypatch):           # S7
    _principal(monkeypatch)
    w = _world()
    _add(w, "ghost.md", "type: concepto\nid: lore::ghost\ntitle: Ghost\ngraph: false\n",
         "Ghost.\n")
    content = "---\ntype: criatura\ntitle: Inicio\n---\nGhost appears.\n"
    assert _save(client, "00_inicio.md", content).status_code == 200
    assert "lore::ghost" not in (w / "00_inicio.md").read_text(encoding="utf-8")


def test_s7_graph_false_source_is_skipped(client, monkeypatch):           # S7
    _principal(monkeypatch)
    w = _world()
    _add(w, "beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    content = "---\ntype: criatura\ntitle: Inicio\ngraph: false\n---\nBeta arrives.\n"
    assert _save(client, "00_inicio.md", content).status_code == 200
    assert (w / "00_inicio.md").read_text(encoding="utf-8") == content


def test_s6_hook_exception_is_fail_open(client, monkeypatch):             # S6
    _principal(monkeypatch)
    w = _world()

    def boom(**kwargs):
        raise RuntimeError("relation service exploded")

    monkeypatch.setattr(api_server, "build_relation_plan", boom)
    content = "---\ntype: criatura\ntitle: Inicio\n---\nBody text.\n"
    assert _save(client, "00_inicio.md", content).status_code == 200
    assert (w / "00_inicio.md").read_text(encoding="utf-8") == content


def test_s6_apply_failure_is_fail_open(client, monkeypatch):              # S6
    _principal(monkeypatch)
    w = _world()
    _add(w, "beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")

    def boom(mundo, plan):
        raise OSError("disk gone")

    monkeypatch.setattr(api_server, "_apply_relation_plan", boom)
    content = "---\ntype: criatura\ntitle: Inicio\n---\nBeta arrives.\n"
    assert _save(client, "00_inicio.md", content).status_code == 200
    assert (w / "00_inicio.md").read_text(encoding="utf-8") == content


def test_edit_response_shape_is_unchanged(client, monkeypatch):           # regression
    _principal(monkeypatch)
    _add(_world(), "beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    content = "---\ntype: criatura\ntitle: Inicio\n---\nBeta arrives.\n"
    r = _save(client, "00_inicio.md", content)
    assert r.status_code == 200
    assert r.json() == {"success": True, "path": "00_inicio.md"}, r.text


def test_materialize_create_digest_ordering_does_not_500(client, monkeypatch):  # digest order
    w = _world()
    _add(w, "beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    _write_idea("arquero-ciego")
    _wire_materialize(monkeypatch,
                      lambda request, _c: _materialize_delta(request, body="Beta arrives.\n"))
    preview = _materialize_preview(client)
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    path = payload["target"]["path"]
    conf = client.post("/api/test_mundo/lore/edit-confirmation?path=" + path,
                       json={"edit_id": payload["proposal_id"], "kind": "new",
                             "proposed_content": payload["content"]})
    assert conf.status_code == 200, conf.text
    conf = conf.json()
    r = client.post("/api/test_mundo/lore/create?path=" + path,
                    json={"content": payload["content"],
                          "edit_id": payload["proposal_id"],
                          "proposed_digest": conf["proposed_digest"],
                          "token": conf["token"]})
    assert r.status_code == 200, r.text
    text = (api_server.MUNDOS_DIR / "test_mundo" / "lore" / path).read_text(encoding="utf-8")
    assert "lore::beta" in text, text


def test_folder_index_mutual_relation_via_api(client, monkeypatch):       # S2 folder index
    _principal(monkeypatch)
    w = _world()
    _add(w, "regions/regions.md",
         "type: region\nid: lore::regions::regions\ntitle: Regions\n", "Index of regions.\n")
    content = "---\ntype: region\nid: lore::regions::alpha\ntitle: Alpha\n---\nA region.\n"
    conf = _confirm_new(client, "regions/alpha.md", content)
    assert _gated_create(client, "regions/alpha.md", content, conf).status_code == 200
    assert "lore::regions::regions" in (w / "regions" / "alpha.md").read_text(encoding="utf-8")
    assert "lore::regions::alpha" in (w / "regions" / "regions.md").read_text(encoding="utf-8")


def _dir_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_rejected_save_leaves_world_byte_identical(client, monkeypatch):  # invariants
    _principal(monkeypatch)
    w = _world()
    _add(w, "beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    root = api_server.MUNDOS_DIR / "test_mundo"
    before = _dir_hash(root)
    content = "---\ntype: criatura\ntitle: Inicio\n---\nBeta arrives.\n"
    conf, base = _confirm(client, "00_inicio.md", content)
    r = client.post("/api/test_mundo/lore/save?path=00_inicio.md",
                    json={"content": content, "edit_id": "e1",
                          "proposed_digest": conf["proposed_digest"],
                          "token": "not-the-token", "base_revision": base})
    assert r.status_code == 403, r.text
    assert _dir_hash(root) == before
