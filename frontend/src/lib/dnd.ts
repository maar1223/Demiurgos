/**
 * Drag & drop primitives shared by the FileTree (sidebar) and SectionCards
 * (grid) same-section move flows.
 *
 * Both surfaces follow the same contract: the dragged node's payload is
 * carried in the dataTransfer under a custom MIME type (plus a text/plain
 * fallback — Firefox will not initiate a drag without a text format), and
 * the drop handlers recompute validity from the event payload instead of
 * trusting hover state.
 */

/** Custom MIME type carrying the dragged node payload (path + kind). */
export const DND_NODE_MIME = "application/x-demiurgos-node";

export interface DragPayload {
  path: string;
  is_dir: boolean;
}

/**
 * Hover state of a drag over one container: the dragged node plus the last
 * entered drop target ("" = the container background) and its validity.
 */
export interface DragState {
  path: string;
  is_dir: boolean;
  target: { path: string; valid: boolean } | null;
}

/**
 * Callback bundle a drop container (FileTree / SectionCards) passes down to
 * its draggable nodes/cards.
 */
export interface DropDnd {
  drag: DragState | null;
  onDragStart: (payload: DragPayload) => void;
  onDragEnd: () => void;
  onTargetEnter: (path: string, valid: boolean) => void;
  onDropMove: (from: string, to: string) => void;
}

export function setDragPayload(
  dataTransfer: DataTransfer,
  payload: DragPayload,
): void {
  dataTransfer.setData(DND_NODE_MIME, JSON.stringify(payload));
  dataTransfer.setData("text/plain", payload.path);
}

export function readDragPayload(
  dataTransfer: DataTransfer | null,
): DragPayload | null {
  if (!dataTransfer) return null;
  const raw = dataTransfer.getData(DND_NODE_MIME);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as DragPayload;
    if (typeof parsed.path === "string" && typeof parsed.is_dir === "boolean") {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}

/** Parent of a path ("" for a root-level node). */
export function parentPath(path: string): string {
  const idx = path.lastIndexOf("/");
  return idx === -1 ? "" : path.slice(0, idx);
}

/** Joins a directory path and an item name (name alone at the root). */
export function joinPath(dir: string, name: string): string {
  return dir ? `${dir}/${name}` : name;
}

/**
 * Same-section folder drop rule (tree node AND grid card): a folder accepts
 * a node unless the target is the node itself, its current parent (a no-op),
 * or — for folders — a descendant of the dragged folder (a cycle).
 */
export function isFolderDropValid(
  dragged: DragPayload,
  targetPath: string,
): boolean {
  if (dragged.path === targetPath) return false;
  if (parentPath(dragged.path) === targetPath) return false;
  if (targetPath.startsWith(dragged.path + "/")) return false;
  return true;
}

/**
 * Dropping on the file-tree panel background = section root: meaningful
 * only for nodes that are not already at the root (otherwise a no-op).
 */
export function canDropToTreeBackground(dragged: DragPayload): boolean {
  return dragged.path.includes("/");
}

/**
 * Dropping on the cards grid background = one level up (into the parent of
 * the browsed directory): valid only while browsing a subdirectory — the
 * section root has no parent to move up to.
 */
export function canDropToGridBackground(
  dragged: DragPayload,
  browsingDirPath: string,
): boolean {
  return browsingDirPath !== "" && dragged.path !== browsingDirPath;
}
