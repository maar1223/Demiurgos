"""Verifier recheck probes for relations-lifecycle-p1: S9, S2, S10."""
import api_server
from import_relations import RelationTarget, grounded_relations
from test_api_server import (client, _confirm, _confirm_new, _gated_create,
                             _gated_write, _principal)  # noqa: F401


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


def test_s9_index_body_listing_all_13_members_keeps_13(client, monkeypatch):
    """S9: full-name matches in an index body stay outside the textual cap."""
    _principal(monkeypatch)
    w = _world()
    regions = w / "regions"
    regions.mkdir(parents=True, exist_ok=True)
    names = [f"Kappa {n:02d}" for n in range(13)]
    listing = "\n".join(f"- {name} lives here" for name in names)
    (regions / "regions.md").write_text(
        "---\ntype: region\nid: lore::regions::regions\ntitle: Regions Atlas\n---\n"
        f"{listing}\n", encoding="utf-8")
    for n, name in enumerate(names):
        (regions / f"k{n:02d}.md").write_text(
            f"---\ntype: region\nid: lore::regions::k{n:02d}\n"
            f"title: {name}\n---\nA member.\n", encoding="utf-8")
    api_server._graph_indices.clear()
    content = ("---\ntype: region\nid: lore::regions::k00\ntitle: Kappa 00\n---\n"
               "A member.\n")
    assert _save(client, "regions/k00.md", content).status_code == 200
    saved = (regions / "regions.md").read_text(encoding="utf-8")
    ids = [ln for ln in saved.splitlines() if "lore::regions::k" in ln]
    assert len(ids) == 13, saved
    assert "lore::regions::regions" in (regions / "k00.md").read_text(
        encoding="utf-8")


def test_s9_member_with_12_textual_relations_keeps_index_edge(client, monkeypatch):
    """S9: the belonging edge never loses to the 12-relation textual budget."""
    _principal(monkeypatch)
    w = _world()
    guilds = w / "guilds"
    people = w / "people"
    guilds.mkdir(parents=True, exist_ok=True)
    people.mkdir(parents=True, exist_ok=True)
    (guilds / "guilds.md").write_text(
        "---\ntype: guild\nid: lore::guilds::guilds\ntitle: Atlas\n---\nIndex.\n",
        encoding="utf-8")
    allies = []
    for n in range(12):
        name = f"Ally {n:02d}"
        allies.append(name)
        (people / f"ally{n:02d}.md").write_text(
            f"---\ntype: personaje\nid: lore::people::ally{n:02d}\n"
            f"title: {name}\n---\nAlly.\n", encoding="utf-8")
    rels = "".join(f"  - lore::people::ally{n:02d}\n" for n in range(12))
    body = "Atlas. " + " ".join(f"{name}." for name in allies) + "\n"
    content = (
        "---\ntype: guild\nid: lore::guilds::a00\ntitle: Guild A\nrelaciones:\n"
        f"{rels}---\n{body}")
    (guilds / "a00.md").write_text(content, encoding="utf-8")
    api_server._graph_indices.clear()
    resp = _save(client, "guilds/a00.md", content)
    assert resp.status_code == 200, resp.text
    saved = (guilds / "a00.md").read_text(encoding="utf-8")
    assert "lore::guilds::guilds" in saved, saved
    for n in range(12):
        assert f"lore::people::ally{n:02d}" in saved, saved


def test_s9_regular_hub_caps_inferred_relations_at_12(client, monkeypatch):
    """S9: a hub with no folder index still caps inferred relations at 12."""
    _principal(monkeypatch)
    w = _world()
    names = [f"Signal {n:02d}" for n in range(20)]
    for n, name in enumerate(names):
        _add(w, f"sig{n:02d}.md",
             f"type: personaje\nid: lore::sig{n:02d}\ntitle: {name}\n", f"{name}.\n")
    _add(w, "hub2.md", "type: region\nid: lore::hub2\ntitle: Crossroads\n", "Hub.\n")
    content = ("---\ntype: region\nid: lore::hub2\ntitle: Crossroads\n---\n"
               + " ".join(f"{name}." for name in names) + "\n")
    assert _save(client, "hub2.md", content).status_code == 200
    saved = (w / "hub2.md").read_text(encoding="utf-8")
    assert len([ln for ln in saved.splitlines() if "lore::sig" in ln]) == 12, saved


def test_s10_ambiguous_identity_keys_are_not_evidence():
    """S10: a shared title is dropped; a unique title still links."""
    twin = [RelationTarget("lore::x::twin", "Twin", "lore/x/twin.md"),
            RelationTarget("lore::y::twin", "Twin", "lore/y/twin.md")]
    assert grounded_relations(body="Twin appears.", source_id="lore::p",
                              source_path="lore/p.md", targets=twin) == []
    unique = grounded_relations(
        body="Oracle appears.", source_id="lore::p", source_path="lore/p.md",
        targets=[RelationTarget("lore::oracle", "Oracle", "lore/oracle.md")])
    assert [(r.canonical_id, r.evidence) for r in unique] == [
        ("lore::oracle", "full-name")]


def test_s2_reverse_pass_sees_body_edited_before_target_existed(client, monkeypatch):
    """S2/cache: a save that writes no relation must not leave a stale body."""
    _principal(monkeypatch)
    w = _world()
    _add(w, "gamma.md", "type: personaje\nid: lore::gamma\ntitle: Gamma\n", "Gamma.\n")
    alpha = ("type: personaje\nid: lore::alpha\ntitle: Alpha\nrelaciones:\n"
             "  - lore::gamma\n")
    _add(w, "alpha.md", alpha, "Gamma is near.\n")
    # The world graph was already read (UI graph view) before this edit.
    api_server._graph_indices.clear()
    api_server._get_graph("test_mundo")
    new = ("---\ntype: personaje\nid: lore::alpha\ntitle: Alpha\nrelaciones:\n"
           "  - lore::gamma\n---\nGamma is near. Beta is coming.\n")
    conf, base = _confirm(client, "alpha.md", new, edit_id="e1")
    assert _gated_write(client, "alpha.md", new, conf, base,
                        edit_id="e1").status_code == 200
    beta = "---\ntype: personaje\nid: lore::beta\ntitle: Beta\n---\nBeta.\n"
    conf_new = _confirm_new(client, "beta.md", beta, edit_id="n1")
    resp = _gated_create(client, "beta.md", beta, conf_new, edit_id="n1")
    assert resp.status_code == 200, resp.text
    saved = (w / "alpha.md").read_text(encoding="utf-8")
    assert "lore::beta" in saved, saved
