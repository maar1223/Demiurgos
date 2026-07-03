import { useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import type { FileNode } from "@/api/types";
import { cn } from "@/lib/utils";

interface FileTreeNodeProps {
  node: FileNode;
  selectedPath?: string;
  onSelect?: (path: string) => void;
  depth?: number;
}

/**
 * A single node in the file tree: renders a directory or file entry.
 *
 * - Directories: expand/collapse toggle on click, shows children recursively
 * - Files: click to select
 * - Selected file gets a `bg-filio` background and `border-l-2 border-llamita`
 * - Depth-based left padding for nesting visual
 */
export function FileTreeNode({
  node,
  selectedPath,
  onSelect,
  depth = 0,
}: FileTreeNodeProps) {
  const [expanded, setExpanded] = useState(
    // Auto-expand the directory that contains the selected file
    node.is_dir && selectedPath
      ? selectedPath.startsWith(node.path)
      : false,
  );

  const isSelected = !node.is_dir && selectedPath === node.path;
  const isDirectory = node.is_dir;

  const handleClick = () => {
    if (isDirectory) {
      setExpanded((prev) => !prev);
    } else {
      onSelect?.(node.path);
    }
  };

  return (
    <li>
      <button
        type="button"
        onClick={handleClick}
        className={cn(
          "flex w-full items-center gap-2 rounded-r-lg py-1.5 pr-3 text-left text-small transition-colors",
          isSelected
            ? "border-l-2 border-llamita bg-filio text-pergamino"
            : "border-l-2 border-transparent text-tinta-desvaida hover:bg-piedra hover:text-pergamino",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-llamita/50",
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
            />
          ))}
        </ul>
      )}
    </li>
  );
}
