import { describe, it, expect } from "vitest";
import {
  buildFolderTree,
  filterEntitiesByFolders,
  neighborhoodKeys,
} from "@/lib/graphFilters";
import type { GraphEntity } from "@/api/types";

/** Minimal GraphEntity factory for tests (only `path` matters here). */
function entity(path: string): GraphEntity {
  return {
    id: path,
    name: path,
    type: "file",
    path,
    status: "stable",
    content: "",
    forward_links: [],
    backlinks: [],
    relaciones: [],
  };
}

describe("buildFolderTree", () => {
  it("returns an empty tree for empty input", () => {
    expect(buildFolderTree([])).toEqual([]);
  });

  it("builds nested trees from nested paths", () => {
    const tree = buildFolderTree([
      entity("lore/historia/a.md"),
      entity("lore/c.md"),
      entity("personajes/d.md"),
    ]);

    expect(tree.map((n) => n.name)).toEqual(["lore", "personajes"]);
    expect(tree[0].path).toBe("lore");
    expect(tree[0].children.map((c) => c.name)).toEqual(["historia"]);
    expect(tree[0].children[0].path).toBe("lore/historia");
    expect(tree[1].children).toEqual([]);
  });

  it("derives folders only (trailing file segment is dropped)", () => {
    const tree = buildFolderTree([entity("capitulos/viejos/cap0.md")]);
    const cap = tree[0];
    expect(cap.name).toBe("capitulos");
    expect(cap.children.map((c) => c.name)).toEqual(["viejos"]);
    expect(cap.children[0].children).toEqual([]);
  });

  it("deduplicates folders shared by multiple entities", () => {
    const tree = buildFolderTree([
      entity("lore/a.md"),
      entity("lore/b.md"),
      entity("lore/historia/c.md"),
    ]);
    expect(tree).toHaveLength(1);
    expect(tree[0].children.map((c) => c.name)).toEqual(["historia"]);
  });

  it("sorts children deterministically by name", () => {
    const tree = buildFolderTree([
      entity("zebra/a.md"),
      entity("alpha/b.md"),
      entity("alpha/mid/c.md"),
      entity("alpha/mid/d.md"),
    ]);
    expect(tree.map((n) => n.name)).toEqual(["alpha", "zebra"]);
    expect(tree[0].children.map((c) => c.name)).toEqual(["mid"]);
  });

  it("ignores root-level files (no directory segments)", () => {
    expect(buildFolderTree([entity("root.md")])).toEqual([]);
  });
});

describe("filterEntitiesByFolders", () => {
  it("returns all entities when selection is empty", () => {
    const entities = [entity("lore/a.md"), entity("personajes/b.md")];
    expect(filterEntitiesByFolders(entities, [])).toEqual(entities);
  });

  it("includes descendants for a top-level selection", () => {
    const entities = [
      entity("lore/a.md"),
      entity("lore/sub/b.md"),
      entity("personajes/c.md"),
    ];
    const result = filterEntitiesByFolders(entities, ["lore"]);
    expect(result.map((e) => e.path)).toEqual(["lore/a.md", "lore/sub/b.md"]);
  });

  it("scopes a subfolder selection", () => {
    const entities = [
      entity("lore/historia/a.md"),
      entity("lore/other/b.md"),
    ];
    const result = filterEntitiesByFolders(entities, ["lore/historia"]);
    expect(result.map((e) => e.path)).toEqual(["lore/historia/a.md"]);
  });

  it("unions multiple selections", () => {
    const entities = [
      entity("lore/a.md"),
      entity("personajes/b.md"),
      entity("referencias/c.md"),
    ];
    const result = filterEntitiesByFolders(entities, ["lore", "personajes"]);
    expect(result.map((e) => e.path)).toEqual([
      "lore/a.md",
      "personajes/b.md",
    ]);
  });

  it("does not let a folder prefix match a sibling-like path", () => {
    const entities = [
      entity("lore/a.md"),
      entity("lore-extra/a.md"),
      entity("lore-extra/sub/b.md"),
    ];
    const result = filterEntitiesByFolders(entities, ["lore"]);
    expect(result.map((e) => e.path)).toEqual(["lore/a.md"]);
  });

  it("matches an exact file-path selection without a trailing slash", () => {
    const entities = [
      entity("lore/a.md"),
      entity("lore-extra/a.md"),
    ];
    // Selecting a file path exactly includes only that file.
    const result = filterEntitiesByFolders(entities, ["lore/a.md"]);
    expect(result.map((e) => e.path)).toEqual(["lore/a.md"]);
  });
});

describe("neighborhoodKeys", () => {
  const links = [
    { source: "a", target: "b" },
    { source: "a", target: "c" },
    { source: "d", target: "a" },
    { source: "e", target: "f" },
  ];

  it("keeps the node and every direct neighbour in both directions", () => {
    expect([...neighborhoodKeys(links, "a")].sort()).toEqual(["a", "b", "c", "d"]);
  });

  it("returns only the node when it has no connections", () => {
    expect([...neighborhoodKeys(links, "z")]).toEqual(["z"]);
  });

  it("does not walk two hops", () => {
    expect(neighborhoodKeys(links, "b").has("c")).toBe(false);
  });
});
