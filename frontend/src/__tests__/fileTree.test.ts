import { describe, it, expect } from "vitest";
import { filterFileTree } from "@/components/organisms/FileTree";
import type { FileNode } from "@/api/types";

const tree: FileNode[] = [
  { name: "Anisa.md", path: "Anisa.md", is_dir: false },
  { name: "Bira.md", path: "Bira.md", is_dir: false },
  {
    name: "capitulos",
    path: "capitulos",
    is_dir: true,
    children: [
      { name: "inicio.md", path: "capitulos/inicio.md", is_dir: false },
      { name: "batalla.md", path: "capitulos/batalla.md", is_dir: false },
      {
        name: "parte2",
        path: "capitulos/parte2",
        is_dir: true,
        children: [
          { name: "final.md", path: "capitulos/parte2/final.md", is_dir: false },
        ],
      },
    ],
  },
];

function paths(nodes: FileNode[]): string[] {
  return nodes.map((n) => n.path);
}

describe("filterFileTree", () => {
  it("matches a file by name", () => {
    const result = filterFileTree(tree, "anisa");
    expect(paths(result)).toEqual(["Anisa.md"]);
  });

  it("matches by directory name keeping the whole dir", () => {
    const result = filterFileTree(tree, "capitulos");
    expect(paths(result)).toEqual(["capitulos"]);
    expect(result[0].children).toHaveLength(3);
  });

  it("keeps a dir with only matching descendants when matched by a child", () => {
    const result = filterFileTree(tree, "batalla");
    expect(paths(result)).toEqual(["capitulos"]);
    const children = result[0].children;
    expect(children).toBeDefined();
    expect(paths(children!)).toEqual(["capitulos/batalla.md"]);
  });

  it("filters recursively through nested directories", () => {
    const result = filterFileTree(tree, "final");
    expect(paths(result)).toEqual(["capitulos"]);
    const children = result[0].children!;
    expect(paths(children)).toEqual(["capitulos/parte2"]);
    expect(paths(children[0].children!)).toEqual(["capitulos/parte2/final.md"]);
  });

  it("is case-insensitive", () => {
    const result = filterFileTree(tree, "ANISA");
    expect(paths(result)).toEqual(["Anisa.md"]);
  });

  it("returns the same tree for an empty query", () => {
    const result = filterFileTree(tree, "");
    expect(paths(result)).toEqual(paths(tree));
    expect(result).toEqual(tree);
  });

  it("returns [] when nothing matches", () => {
    expect(filterFileTree(tree, "inexistente")).toEqual([]);
  });
});
