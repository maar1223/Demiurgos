/**
 * Pure helpers for the graph folder filter.
 *
 * `buildFolderTree` derives a hierarchical folder tree from entity paths,
 * and `filterEntitiesByFolders` applies a prefix-union visibility rule:
 * an entity is visible when its path equals a selected folder or starts
 * with the selected folder followed by a "/". Multiple selections are a
 * union; an empty selection means every entity is visible.
 *
 * Kept in `lib/` (alongside `utils.ts` / `dnd.ts`) so the helpers stay
 * trivially testable and `GraphView` remains focused on orchestration.
 */

import type { GraphEntity } from "@/api/types";

/** A folder node in the derived tree. `path` is the full folder path. */
export interface FolderNode {
  /** e.g. "lore" or "lore/historia" */
  path: string;
  /** Last path segment, e.g. "historia". */
  name: string;
  children: FolderNode[];
}

/**
 * Builds a hierarchical folder tree from entity paths.
 *
 * Only directories contribute nodes — the trailing file segment of each
 * entity path is dropped. Supports arbitrary depth; level-1 segments are
 * top-level categories. Children are sorted deterministically by name.
 * Empty input yields an empty tree.
 */
export function buildFolderTree(entities: GraphEntity[]): FolderNode[] {
  const roots: FolderNode[] = [];
  const byPath = new Map<string, FolderNode>();

  const getOrCreate = (
    path: string,
    name: string,
    parentChildren: FolderNode[],
  ): FolderNode => {
    let node = byPath.get(path);
    if (!node) {
      node = { path, name, children: [] };
      byPath.set(path, node);
      parentChildren.push(node);
    }
    return node;
  };

  for (const entity of entities) {
    const segments = entity.path.split("/");
    segments.pop(); // last segment is the file, not a folder
    let path = "";
    let children = roots;
    for (const segment of segments) {
      path = path ? `${path}/${segment}` : segment;
      children = getOrCreate(path, segment, children).children;
    }
  }

  const sort = (nodes: FolderNode[]): void => {
    nodes.sort((a, b) => a.name.localeCompare(b.name));
    nodes.forEach((node) => sort(node.children));
  };
  sort(roots);
  return roots;
}

/**
 * Filters entities by prefix-union of selected folders.
 *
 * An entity is visible when its path equals a selected folder or starts
 * with the selected folder plus a "/" (so `lore` matches `lore/a.md` but
 * not `lore-extra/a.md`). An empty selection returns every entity.
 */
export function filterEntitiesByFolders(
  entities: GraphEntity[],
  selectedFolders: string[],
): GraphEntity[] {
  if (selectedFolders.length === 0) return entities;
  return entities.filter((entity) =>
    selectedFolders.some(
      (folder) =>
        entity.path === folder || entity.path.startsWith(folder + "/"),
    ),
  );
}
