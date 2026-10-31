"""Verifier probes for relations-lifecycle-p1: S4, S9, S10 (+ idempotency)."""
import hashlib

import api_server
from import_relations import RelationTarget, grounded_relations, relation_quality
from test_api_server import client, _confirm, _gated_write, _principal  # noqa: F401


def _world():
    return api_server.MUNDOS_DIR / "test_mundo" / "lore"


def _add(world, rel, fm, body):
    p = world / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{fm}---\n{body}", encoding="utf-8")
    api_server._graph_indices.clear()
    return p


def _save(client, path, content, edit_id="e1"):
    conf, base = _confirm(client, path, content, edit_id=edit_id)
    return _gated_write(client, path, content, conf, base, edit_id=edit_id)


def _members(text):
    return [ln.strip()[2:].strip() for ln in text.splitlines()
            if ln.strip().startswith("- ") and "lore::regions::m" in ln]


# --- S9: a folder index that lists its members in the body -------------------
def test_s9_folder_index_body_mentioning_members_keeps_all(client, monkeypatch):
    _principal(monkeypatch)
    w = _world()
    regions = w / "regions"
    regions.mkdir(parents=True, exist_ok=True)
    listing = "\n".join(f"- Member {n}" for n in range(13))
    (regions / "regions.md").write_text(
        f"---\ntype: region\nid: lore::regions::regions\ntitle: Regions\n---\n{listing}\n",
        encoding="utf-8")
    for n in range(13):
        (regions / f"m{n:02d}.md").write_text(
            f"---\ntype: region\nid: lore::regions::m{n:02d}\n"
            f"title: Member {n}\n---\nA member.\n", encoding="utf-8")
    api_server._graph_indices.clear()
    content = "---\ntype: region\nid: lore::regions::m00\ntitle: Member 0\n---\nA member.\n"
    assert _save(client, "regions/m00.md", content).status_code == 200
    saved = (regions / "regions.md").read_text(encoding="utf-8")
    assert len(_members(saved)) == 13, saved


# --- S9: a member always keeps its one belonging edge ------------------------
def test_s9_member_keeps_belonging_edge_with_full_body():
    members = [RelationTarget(f"lore::a{n:02d}", f"Ally {n}", f"lore/guilds/ally{n:02d}.md")
               for n in range(12)]
    index = RelationTarget("lore::guilds::guilds", "Atlas", "lore/guilds/guilds.md")
    body = "Atlas. " + " ".join(f"Ally {n}." for n in range(12))
    rels = grounded_relations(
        body=body, source_id="lore::guilds::a00", source_path="lore/guilds/a00.md",
        targets=members + [index], structural_uncapped=True)
    assert "lore::guilds::guilds" in [r.canonical_id for r in rels]


# --- S9: regular hub stays capped, structural does not eat the textual budget
def test_s9_regular_hub_capped_at_12(client, monkeypatch):
    _principal(monkeypatch)
    w = _world()
    names = [f"Target{n:02d}" for n in range(20)]
    for n, name in enumerate(names):
        _add(w, f"tg{n:02d}.md",
             f"type: personaje\nid: lore::tg{n:02d}\ntitle: {name}\n", name + ".\n")
    _add(w, "hub.md", "type: region\nid: lore::hub\ntitle: Hub\n", "Hub.\n")
    content = ("---\ntype: region\nid: lore::hub\ntitle: Hub\n---\n"
               + " ".join(f"{n}." for n in names) + "\n")
    assert _save(client, "hub.md", content).status_code == 200
    saved = (w / "hub.md").read_text(encoding="utf-8")
    assert len([ln for ln in saved.splitlines() if "lore::tg" in ln]) == 12, saved


def test_s9_existing_structural_does_not_block_new_textual(client, monkeypatch):
    _principal(monkeypatch)
    w = _world()
    regions = w / "regions"
    regions.mkdir(parents=True, exist_ok=True)
    (regions / "regions.md").write_text(
        "---\ntype: region\nid: lore::regions::regions\ntitle: Regions\n---\nIndex.\n",
        encoding="utf-8")
    for n in range(13):
        (regions / f"m{n:02d}.md").write_text(
            f"---\ntype: region\nid: lore::regions::m{n:02d}\n"
            f"title: Member {n}\n---\nA member.\n", encoding="utf-8")
    api_server._graph_indices.clear()
    member = "---\ntype: region\nid: lore::regions::m00\ntitle: Member 0\n---\nA member.\n"
    assert _save(client, "regions/m00.md", member).status_code == 200
    assert len(_members((regions / "regions.md").read_text(encoding="utf-8"))) == 13
    _add(w, "new-target.md", "type: personaje\nid: lore::newtarget\ntitle: New Target\n",
         "New Target.\n")
    index_content = ("---\ntype: region\nid: lore::regions::regions\n"
                     "title: Regions\n---\nNew Target is nearby.\n")
    assert _save(client, "regions/regions.md", index_content, edit_id="e2").status_code == 200
    saved = (regions / "regions.md").read_text(encoding="utf-8")
    assert len(_members(saved)) == 13, saved
    assert "lore::newtarget" in saved, saved


# --- S10: ambiguous keys are not evidence; unique names still link -----------
def test_s10_ambiguous_title_alias_stem_not_linked():
    title = [RelationTarget("lore::n::a", "Alpha", "lore/n/alpha.md"),
             RelationTarget("lore::s::a", "Alpha", "lore/s/alpha.md")]
    alias = [RelationTarget("lore::a", "X – Envoy", "lore/a.md"),
             RelationTarget("lore::b", "Y – Envoy", "lore/b.md")]
    stem = [RelationTarget("lore::n::o", "North One", "lore/n/omega.md"),
            RelationTarget("lore::s::o", "South Two", "lore/s/omega.md")]
    for body, targets in (("Alpha appears.", title),
                          ("The Envoy arrived.", alias),
                          ("Omega appears.", stem)):
        assert grounded_relations(body=body, source_id="lore::page",
                                  source_path="lore/page.md", targets=targets) == []


def test_s10_unique_name_links():
    rels = grounded_relations(body="Beta appears.", source_id="lore::page",
                              source_path="lore/page.md",
                              targets=[RelationTarget("lore::beta", "Beta", "lore/beta.md")])
    assert [(r.canonical_id, r.evidence) for r in rels] == [("lore::beta", "full-name")]


def test_s10_quality_report_uses_same_guard():
    candidates = [
        {"candidate_id": "c1", "canonical_id": "lore::n::a", "name": "Alpha",
         "path": "lore/n/alpha.md", "frontmatter": {"graph": True},
         "content_preview": "no mentions"},
        {"candidate_id": "c2", "canonical_id": "lore::s::a", "name": "Alpha",
         "path": "lore/s/alpha.md", "frontmatter": {"graph": True},
         "content_preview": "no mentions"},
        {"candidate_id": "c3", "canonical_id": "lore::page", "name": "Page",
         "path": "lore/page.md", "frontmatter": {"graph": True},
         "content_preview": "Alpha appears."},
    ]
    assert relation_quality(candidates)["c3"] == ["standalone"]


# --- S4: restore is byte-exact; the next normal save grows relations --------
def test_s4_restore_byte_exact_then_next_save_regrows(client, monkeypatch):
    _principal(monkeypatch)
    w = _world()
    old = "---\ntype: criatura\ntitle: Inicio\n---\nBeta arrives.\n"
    assert _save(client, "00_inicio.md", old, edit_id="e1").status_code == 200
    _add(w, "beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    other = "---\ntype: criatura\ntitle: Inicio\n---\nSomething else.\n"
    assert _save(client, "00_inicio.md", other, edit_id="e2").status_code == 200
    entries = client.get("/api/test_mundo/history?path=lore/00_inicio.md").json()["entries"]
    snap = next(e for e in entries if e["content"] == old)
    rev = hashlib.sha256((w / "00_inicio.md").read_bytes()).hexdigest()
    conf = client.post(
        "/api/test_mundo/lore/edit-confirmation?path=00_inicio.md",
        json={"edit_id": "r1", "kind": "restore", "base_revision": rev,
              "snapshot_id": snap["snapshot_id"], "proposed_content": old},
    ).json()
    restored = client.post(
        "/api/test_mundo/history/restore",
        json={"path": "lore/00_inicio.md", "snapshot_id": snap["snapshot_id"],
              "edit_id": "r1", "base_revision": rev, "content": old,
              "proposed_digest": conf["proposed_digest"], "token": conf["token"]},
    )
    assert restored.status_code == 200, restored.text
    on_disk = (w / "00_inicio.md").read_bytes()
    assert on_disk == old.encode("utf-8")
    assert hashlib.sha256(on_disk).hexdigest() == snap["revision"]
    assert _save(client, "00_inicio.md", old, edit_id="e3").status_code == 200
    assert "lore::beta" in (w / "00_inicio.md").read_text(encoding="utf-8")


# --- S2/S5: second save writes nothing --------------------------------------
def test_s2_second_save_writes_nothing(client, monkeypatch):
    _principal(monkeypatch)
    w = _world()
    _add(w, "beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    content = "---\ntype: criatura\ntitle: Inicio\n---\nBeta arrives.\n"
    assert _save(client, "00_inicio.md", content, edit_id="e1").status_code == 200
    first = (w / "00_inicio.md").read_bytes()
    real, calls = api_server._atomic_write, []

    def counting(full, data):
        calls.append(str(full))
        return real(full, data)

    monkeypatch.setattr(api_server, "_atomic_write", counting)
    assert _save(client, "00_inicio.md", first.decode(), edit_id="e2").status_code == 200
    assert (w / "00_inicio.md").read_bytes() == first
    assert len(calls) == 1, calls


# --- interaction: the graph index sees the new relation ---------------------
def test_graph_index_sees_the_new_relation(client, monkeypatch):
    _principal(monkeypatch)
    w = _world()
    _add(w, "beta.md", "type: personaje\nid: lore::beta\ntitle: Beta\n", "Beta.\n")
    content = "---\ntype: criatura\ntitle: Inicio\nid: lore::inicio\n---\nBeta arrives.\n"
    assert _save(client, "00_inicio.md", content).status_code == 200
    idx = api_server._get_graph("test_mundo")
    assert "lore::beta" in list(idx.get_entity("lore/00_inicio.md").relaciones)
    fwd = idx.get_links("lore/00_inicio.md", "forward")
    assert any(link.get("path") == "lore/beta.md" for link in fwd), fwd
