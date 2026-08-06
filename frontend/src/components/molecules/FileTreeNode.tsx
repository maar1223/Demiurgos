import { useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import type { FileNode } from "@/api/types";
import { cn } from "@/lib/utils";
import {
  isFolderDropValid,
  joinPath,
  readDragPayload,
  setDragPayload,
  type DropDnd,
} from "@/lib/dnd";

interface FileTreeNodeProps {
  node: FileNode;
  selectedPath?: string;
  onSelect?: (path: string) => void;
  depth?: number;
  /** DnD wiring provided by the FileTree container (drag state + handlers). */
  dnd?: DropDnd;
  /** Path of the node playing the drop absorption animation. */
  absorbingPath?: string | null;
  /** Path of the node that should briefly highlight after a move. */
  movedPath?: string | null;
}

/**
 * A single node in the file tree: renders a directory or file entry.
 *
 * - Directories: expand/collapse toggle on click, shows children recursively
 * - Files: click to select
 * - Selected file gets a `bg-filio` background and `border-l-2 border-llamita`
 * - Depth-based left padding for nesting visual
 *
 * Drag & drop (same section): every node is draggable; directories are drop
 * targets (drop = move into them). Validity follows `isFolderDropValid`
 * (no self/parent/descendant drops); the tree panel background handles the
 * "move to section root" case in the FileTree container. Drag events are
 * stopped at the node so the container background never intercepts them.
 */
export function FileTreeNode({
  node,
  selectedPath,
  onSelect,
  depth = 0,
  dnd,
  absorbingPath = null,
  movedPath = null,
}: FileTreeNodeProps) {
  const [expanded, setExpanded] = useState(
    // Auto-expand the directory that contains the selected file
    node.is_dir && selectedPath
      ? selectedPath.startsWith(node.path)
      : false,
  );

  const isSelected = !node.is_dir && selectedPath === node.path;
  const isDirectory = node.is_dir;

  const isDragSource = dnd?.drag?.path === node.path;
  const isDropTarget = dnd?.drag?.target?.path === node.path;
  const targetValid = isDropTarget && !!dnd?.drag?.target?.valid;
  // Reddish tint on the dragged node while hovering an INVALID target.
  const invalidHover =
    isDragSource && !!dnd?.drag?.target && !dnd.drag.target.valid;
  const isAbsorbing = absorbingPath === node.path;

  const handleClick = () => {
    if (isDirectory) {
      setExpanded((prev) => !prev);
    } else {
      onSelect?.(node.path);
    }
  };

  const handleDragStart = (e: React.DragEvent) => {
    if (!dnd) return;
    setDragPayload(e.dataTransfer, { path: node.path, is_dir: node.is_dir });
    e.dataTransfer.effectAllowed = "move";
    dnd.onDragStart({ path: node.path, is_dir: node.is_dir });
  };

  const handleDragEnd = () => {
    dnd?.onDragEnd();
  };

  const handleDragEnter = (e: React.DragEvent) => {
    if (!dnd?.drag) return;
    e.stopPropagation();
    // Files are never valid targets — hovering them still reports an
    // invalid target so the ghost shows the sangre tint.
    const valid = node.is_dir && isFolderDropValid(dnd.drag, node.path);
    dnd.onTargetEnter(node.path, valid);
  };

  const handleDragOver = (e: React.DragEvent) => {
    if (!dnd?.drag) return;
    // Swallow drags on files too: the drop must fire HERE (as a no-op)
    // instead of bubbling to the panel background ("move to section root").
    e.stopPropagation();
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    if (!dnd?.drag) return;
    e.stopPropagation();
    e.preventDefault();
    if (!node.is_dir) return;
    const dragged = readDragPayload(e.dataTransfer);
    if (!dragged || !isFolderDropValid(dragged, node.path)) return;
    const name = dragged.path.split("/").pop() ?? "";
    dnd.onDropMove(dragged.path, joinPath(node.path, name));
  };

  return (
    <li>
      <button
        type="button"
        onClick={handleClick}
        draggable={!!dnd}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className={cn(
          "flex w-full items-center gap-2 rounded-r-lg py-1.5 pr-3 text-left text-small transition-all",
          isSelected
            ? "border-l-2 border-llamita bg-filio text-pergamino"
            : "border-l-2 border-transparent text-tinta-desvaida hover:bg-piedra hover:text-pergamino",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-llamita/50",
          // Drag feedback: dimmed source, sangre tint on invalid hover,
          // llamita ring + slight grow on a valid folder target.
          isDragSource && "cursor-grabbing opacity-50 shadow-lg",
          invalidHover && "ring-2 ring-inset ring-sangre/50",
          targetValid &&
            "scale-[1.03] bg-piedra ring-2 ring-inset ring-llamita",
          isAbsorbing && "scale-75 opacity-0",
          movedPath === node.path && "fade-slide-in",
        )}
        style={{ paddingLeft: `${12 + depth * 16}px` }}
        aria-expanded={isDirectory ? expanded : undefined}
        aria-selected={isSelected}
      >
        {/* Expand/collapse chevron for directories */}
        {isDirectory ? (
          <Icon
            name={expanded ? "chevron-down" : "chevron-right"}
            size={14}
            className="shrink-0 text-sombra"
          />
        ) : (
          <span className="w-3.5 shrink-0" />
        )}

        {/* Folder / file icon */}
        <Icon
          name={
            isDirectory
              ? expanded
                ? "folder-open"
                : "folder"
              : node.name.endsWith(".md")
                ? "markdown"
                : "file"
          }
          size={16}
          className={cn(
            "shrink-0",
            isDirectory ? "text-llamita" : "text-plata",
          )}
        />

        {/* Node name */}
        <span className="truncate">{node.name}</span>
      </button>

      {/* Recursive children (only when expanded) */}
      {isDirectory && expanded && node.children && node.children.length > 0 && (
        <ul className="list-none">
          {node.children.map((child) => (
            <FileTreeNode
              key={child.path}
              node={child}
              selectedPath={selectedPath}
              onSelect={onSelect}
              depth={depth + 1}
              dnd={dnd}
              absorbingPath={absorbingPath}
              movedPath={movedPath}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
