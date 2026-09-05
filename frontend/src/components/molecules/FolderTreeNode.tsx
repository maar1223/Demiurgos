import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import type { FolderNode } from "@/lib/graphFilters";

interface FolderTreeNodeProps {
  node: FolderNode;
  selectedFolders: string[];
  onToggle: (path: string) => void;
  depth?: number;
}

/**
 * True when any descendant folder (at any depth) is in the selection.
 * Used to render the parent checkbox as indeterminate (partial) when some
 * but not all of its descendants are checked.
 */
function hasSelectedDescendant(
  node: FolderNode,
  selected: string[],
): boolean {
  return node.children.some(
    (child) =>
      selected.includes(child.path) || hasSelectedDescendant(child, selected),
  );
}

/**
 * A single folder node in the graph folder tree: an expand/collapse chevron,
 * a checkbox, and the folder name, recursing into children.
 *
 * - The checkbox is checked when `node.path` is in `selectedFolders`; it is
 *   rendered indeterminate (via `ref.indeterminate`) when some descendants
 *   are checked but the node itself is not.
 * - Expand/collapse is LOCAL UI state only — it never affects filtering.
 *   The "Ver todo" / tree still participates in the filter regardless of
 *   whether its children are visible.
 * - Depth-based left padding provides the nesting visual.
 */
export function FolderTreeNode({
  node,
  selectedFolders,
  onToggle,
  depth = 0,
}: FolderTreeNodeProps) {
  const [expanded, setExpanded] = useState(false);
  const checkboxRef = useRef<HTMLInputElement>(null);

  const checked = selectedFolders.includes(node.path);
  const partial = !checked && hasSelectedDescendant(node, selectedFolders);
  const hasChildren = node.children.length > 0;

  // `ref.indeterminate` is a DOM property, not an HTML attribute — it must be
  // set imperatively. It expresses "some, but not all, descendants checked".
  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = partial;
    }
  }, [partial]);

  return (
    <li>
      <div
        className="flex items-center gap-1 rounded-md py-1 pr-2 transition-colors hover:bg-surface-hover"
        style={{ paddingLeft: `${4 + depth * 16}px` }}
      >
        {/* Expand/collapse chevron for folders with children */}
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            aria-expanded={expanded}
            aria-label={
              expanded ? `Contraer ${node.name}` : `Expandir ${node.name}`
            }
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
          >
            <Icon name={expanded ? "chevron-down" : "chevron-right"} size={14} />
          </button>
        ) : (
          <span className="w-5 shrink-0" />
        )}

        <input
          ref={checkboxRef}
          type="checkbox"
          checked={checked}
          onChange={() => onToggle(node.path)}
          aria-label={node.name}
          className="h-4 w-4 shrink-0"
        />

        <button
          type="button"
          onClick={() => onToggle(node.path)}
          className="truncate text-small text-primary transition-colors hover:text-action"
        >
          {node.name}
        </button>
      </div>

      {/* Recursive children (only when expanded) */}
      {expanded && hasChildren && (
        <ul className="list-none">
          {node.children.map((child) => (
            <FolderTreeNode
              key={child.path}
              node={child}
              selectedFolders={selectedFolders}
              onToggle={onToggle}
              depth={depth + 1}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
