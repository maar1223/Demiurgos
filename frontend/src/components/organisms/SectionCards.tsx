import { Icon, type IconName } from "@/components/atoms/Icon";
import type { FileNode } from "@/api/types";

interface SectionCardsProps {
  nodes: FileNode[];
  mundo: string;
  section: string;
  onSelect: (path: string) => void;
}

/**
 * Visual grid of directory and file cards for a section (or a subdirectory).
 *
 * Embedded in the WikiEditor content area when no file is selected: the
 * cards replace the old "Seleccioná un archivo" placeholder so the section
 * contents are browsable without leaving the editor. Directories render
 * first (tree order), then files.
 *
 * Clicking a card calls `onSelect` with the node's path — the parent
 * decides where to navigate. `mundo` and `section` are part of the public
 * props for parity with the standalone section view; navigation itself
 * goes through `onSelect`.
 */
export function SectionCards({ nodes, onSelect }: SectionCardsProps) {
  const dirs = nodes.filter((n) => n.is_dir);
  const files = nodes.filter((n) => !n.is_dir);

  return (
    <div className="grid grid-cols-1 gap-4 tablet:grid-cols-2 desktop:grid-cols-3">
      {dirs.map((dir) => (
        <DirectoryCard key={dir.path} node={dir} onSelect={onSelect} />
      ))}
      {files.map((file) => (
        <FileCard key={file.path} node={file} onSelect={onSelect} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Directory card
// ---------------------------------------------------------------------------

function DirectoryCard({
  node,
  onSelect,
}: {
  node: FileNode;
  onSelect: (path: string) => void;
}) {
  const fileCount = countFiles(node);
  const subdirCount = countDirs(node);

  const badge =
    fileCount > 0
      ? `${fileCount} ${fileCount === 1 ? "archivo" : "archivos"}${
          subdirCount > 0
            ? `, ${subdirCount} ${subdirCount === 1 ? "subcarpeta" : "subcarpetas"}`
            : ""
        }`
      : "vacía";

  return (
    <button
      type="button"
      onClick={() => onSelect(node.path)}
      className="group flex w-full flex-col gap-3 rounded-xl border border-filio bg-madero p-5 text-left transition-all hover:border-llamita/40 hover:bg-piedra focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-llamita/50 focus-visible:ring-offset-2 focus-visible:ring-offset-cripta"
    >
      {/* Cover area with folder icon */}
      <div className="flex h-32 items-center justify-center rounded-lg bg-filio/30 transition-colors group-hover:bg-filio/50">
        <Icon name="folder" size={40} className="text-llamita/40" />
      </div>

      {/* Name + recursive counts */}
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-heading text-h4 text-pergamino transition-colors group-hover:text-llamita">
          {node.name}
        </h3>
        <span className="rounded-md bg-filio/30 px-2 py-0.5 text-xs text-tinta-desvaida">
          {badge}
        </span>
      </div>

      {/* Chevron */}
      <div className="mt-auto flex items-center justify-end text-plata/50 transition-colors group-hover:text-llamita">
        <Icon name="chevron-right" size={16} />
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// File card
// ---------------------------------------------------------------------------

function FileCard({
  node,
  onSelect,
}: {
  node: FileNode;
  onSelect: (path: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(node.path)}
      className="group flex w-full flex-col gap-3 rounded-xl border border-filio bg-madero p-5 text-left transition-all hover:border-llamita/40 hover:bg-piedra focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-llamita/50 focus-visible:ring-offset-2 focus-visible:ring-offset-cripta"
    >
      {/* Icon area */}
      <div className="flex h-32 items-center justify-center rounded-lg bg-filio/30 transition-colors group-hover:bg-filio/50">
        <Icon name={fileIconName(node.name)} size={40} className="text-llamita/40" />
      </div>

      {/* Name */}
      <div className="flex items-center justify-between">
        <h3 className="font-heading text-h4 text-pergamino transition-colors group-hover:text-llamita">
          {node.name}
        </h3>
      </div>

      {/* Chevron */}
      <div className="mt-auto flex items-center justify-end text-plata/50 transition-colors group-hover:text-llamita">
        <Icon name="chevron-right" size={16} />
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Recursively counts all files inside a directory node (direct + nested).
 */
function countFiles(node: FileNode): number {
  let count = 0;
  if (node.children) {
    for (const child of node.children) {
      if (!child.is_dir) count++;
      else count += countFiles(child);
    }
  }
  return count;
}

/**
 * Recursively counts all subdirectories inside a directory node.
 */
function countDirs(node: FileNode): number {
  let count = 0;
  if (node.children) {
    for (const child of node.children) {
      if (child.is_dir) {
        count++;
        count += countDirs(child);
      }
    }
  }
  return count;
}

/**
 * Depth-first search for a node by exact path.
 */
export function findTreeNode(
  nodes: FileNode[],
  path: string,
): FileNode | undefined {
  for (const node of nodes) {
    if (node.path === path) return node;
    if (node.is_dir && node.children) {
      const found = findTreeNode(node.children, path);
      if (found) return found;
    }
  }
  return undefined;
}

/**
 * Maps a file name to the icon that represents it: markdown for `.md`,
 * image for common image extensions, generic file otherwise.
 */
export function fileIconName(name: string): IconName {
  const lower = name.toLowerCase();
  if (lower.endsWith(".md")) return "markdown";
  if (/\.(jpg|jpeg|png|gif|webp)$/.test(lower)) return "image";
  return "file";
}
