import { useCallback, useMemo, useRef, useState } from "react";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { FileTreeNode } from "@/components/molecules/FileTreeNode";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";
import {
  canDropToTreeBackground,
  resolveDragPayload,
  upLevelTarget,
  type DragPayload,
  type DragState,
  type DropDnd,
} from "@/lib/dnd";
import type { FileNode } from "@/api/types";
import { useAppLanguage } from "@/hooks/useAppLanguage";

interface FileTreeProps {
  nodes: FileNode[];
  selectedPath?: string;
  onSelect?: (path: string) => void;
  isLoading?: boolean;
  error?: Error | null;
  onRetry?: () => void;
  /** Same-section move via drag & drop: from/to are section-relative paths. */
  onMove?: (from: string, to: string) => void;
  /** Path of the node that should briefly highlight after a move. */
  movedPath?: string | null;
}

/**
 * Recursive, case-insensitive filter over a file tree.
 *
 * - A file node matches if its name contains the query.
 * - A directory node is kept if its name matches (whole subtree) OR any
 *   descendant matches — in the latter case only the matching descendants
 *   are kept, and non-matching siblings are dropped.
 * - An empty query returns the nodes unchanged.
 */
export function filterFileTree(nodes: FileNode[], query: string): FileNode[] {
  const q = query.toLowerCase();
  if (q === "") {
    return nodes;
  }
  const result: FileNode[] = [];
  for (const node of nodes) {
    const nameMatches = node.name.toLowerCase().includes(q);
    if (nameMatches) {
      result.push(node);
      continue;
    }
    if (!node.is_dir || !node.children || node.children.length === 0) {
      continue;
    }
    const filteredChildren = filterFileTree(node.children, query);
    if (filteredChildren.length > 0) {
      result.push({ ...node, children: filteredChildren });
    }
  }
  return result;
}

/**
 * Recursive sidebar file tree with lazy rendering, empty state, and error state.
 *
 * Delegates individual node rendering to `FileTreeNode`, which handles
 * expand/collapse, selection highlighting, and recursive children.
 *
 * A search input filters the tree client-side (recursive, case-insensitive).
 *
 * States:
 * - 🟡 Loading: Spinner centered in sidebar
 * - 🔴 Error: ErrorBanner with retry button
 * - 🟢 Empty: "Esta sección está vacía"
 * - 🟢 Data: search input + recursive file tree
 */
export function FileTree({
  nodes,
  selectedPath,
  onSelect,
  isLoading = false,
  error = null,
  onRetry,
  onMove,
  movedPath = null,
}: FileTreeProps) {
  const { t } = useAppLanguage();
  const [query, setQuery] = useState("");
  const filteredNodes = useMemo(
    () => filterFileTree(nodes, query),
    [nodes, query],
  );

  // ── Drag & drop state (same-section moves) ──────────────────────────
  const [drag, setDrag] = useState<DragState | null>(null);
  const [absorbing, setAbsorbing] = useState<string | null>(null);
  const absorbTimer = useRef<number | null>(null);

  const handleDragStart = useCallback((payload: DragPayload) => {
    setDrag({ path: payload.path, is_dir: payload.is_dir, target: null });
  }, []);

  const handleDragEnd = useCallback(() => {
    setDrag(null);
  }, []);

  const handleTargetEnter = useCallback((path: string, valid: boolean) => {
    setDrag((prev) =>
      prev ? { ...prev, target: { path, valid } } : prev,
    );
  }, []);

  // Absorption animation (~150ms) BEFORE the actual move: the node shrinks
  // into the target, then onMove fires and the tree refreshes.
  const handleDropMove = useCallback(
    (from: string, to: string) => {
      setDrag(null);
      setAbsorbing(from);
      if (absorbTimer.current) window.clearTimeout(absorbTimer.current);
      absorbTimer.current = window.setTimeout(() => {
        setAbsorbing(null);
        onMove?.(from, to);
      }, 150);
    },
    [onMove],
  );

  // Panel background = "move the node one level up" (out of its current
  // parent folder). Only events that never hit a node reach these handlers
  // (nodes stop propagation). The payload comes from React state, NOT from
  // dataTransfer: dragenter/dragover run in the spec's "protected mode" where
  // getData() returns "" (Chrome/Safari), so reading the payload there
  // silently disabled the drop feedback in real browsers.
  const handleBackgroundDragEnter = useCallback(() => {
    setDrag((prev) =>
      prev
        ? { ...prev, target: { path: "", valid: canDropToTreeBackground(prev) } }
        : prev,
    );
  }, []);

  const handleBackgroundDragOver = useCallback((e: React.DragEvent) => {
    if (drag) e.preventDefault();
  }, [drag]);

  const handleBackgroundDrop = useCallback(
    (e: React.DragEvent) => {
      const dragged = resolveDragPayload(e.dataTransfer, drag);
      if (!dragged || !canDropToTreeBackground(dragged)) return;
      e.preventDefault();
      handleDropMove(dragged.path, upLevelTarget(dragged.path));
    },
    [drag, handleDropMove],
  );

  // ── "Subir un nivel" drop bar ──────────────────────────────────────────
  // A first-class drop target pinned to the bottom of the panel (sticky), so
  // the up gesture stays reachable even when the tree is packed and every
  // node would otherwise swallow the background drop. Its handlers stop
  // propagation so the bar always wins over the background beneath it.
  const handleUpBarDragEnter = useCallback((e: React.DragEvent) => {
    e.stopPropagation();
    setDrag((prev) =>
      prev
        ? { ...prev, target: { path: "", valid: canDropToTreeBackground(prev) } }
        : prev,
    );
  }, []);

  const handleUpBarDragOver = useCallback(
    (e: React.DragEvent) => {
      if (!drag) return;
      e.stopPropagation();
      e.preventDefault();
    },
    [drag],
  );

  const handleUpBarDrop = useCallback(
    (e: React.DragEvent) => {
      e.stopPropagation();
      e.preventDefault();
      const dragged = resolveDragPayload(e.dataTransfer, drag);
      if (!dragged || !canDropToTreeBackground(dragged)) return;
      handleDropMove(dragged.path, upLevelTarget(dragged.path));
    },
    [drag, handleDropMove],
  );

  const dnd: DropDnd = {
    drag,
    onDragStart: handleDragStart,
    onDragEnd: handleDragEnd,
    onTargetEnter: handleTargetEnter,
    onDropMove: handleDropMove,
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner size="md" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-4 py-4">
        <ErrorBanner
          message={t("fileTree.loadError")}
          onRetry={onRetry}
        />
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <EmptyState
        icon="empty"
        message={t("fileTree.empty")}
      />
    );
  }

  const hasQuery = query.length > 0;

  // A nested node (path has a parent) can be moved one level up. The drop bar
  // renders as a first-class target while such a node is being dragged; it is
  // pinned to the bottom of the panel so the gesture is always discoverable,
  // even when the tree is packed and every node swallows the background drop.
  const draggedCanGoUp = drag ? canDropToTreeBackground(drag) : false;
  const backgroundIsTarget =
    !!drag && drag.target?.path === "" && drag.target.valid;
  const upTarget = drag ? upLevelTarget(drag.path) : "";

  return (
    <div
      data-testid="file-tree-drop-area"
      // min-h-full + flex-col: the drop area covers the whole scrollable
      // panel (not just the rendered rows), so "empty space" below a short
      // tree is a valid up-level target too.
      className="flex min-h-full flex-col"
      onDragEnter={handleBackgroundDragEnter}
      onDragOver={handleBackgroundDragOver}
      onDrop={handleBackgroundDrop}
    >
      {/* Search input */}
      <div className="px-3 py-2">
        <div className="relative">
          <Icon
            name="search"
            size={14}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("fileTree.searchPlaceholder")}
            aria-label={t("fileTree.searchAria")}
            className={cn(
              "w-full rounded-md border border-edge bg-surface-raised",
              "py-1.5 pl-8 pr-3",
              "text-small text-primary placeholder:text-muted",
              "focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50",
              "transition-colors",
            )}
          />
          {hasQuery && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label={t("fileTree.clearSearch")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-primary"
            >
              <Icon name="close" size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Empty search results */}
      {hasQuery && filteredNodes.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <Icon name="search" size={20} className="text-muted" />
          <p className="text-small text-muted">{t("fileTree.noResults")}</p>
        </div>
      ) : (
        <nav aria-label={t("fileTree.treeAria")}>
          <ul className="list-none">
            {filteredNodes.map((node) => (
              <FileTreeNode
                key={node.path}
                node={node}
                selectedPath={selectedPath}
                onSelect={onSelect}
                dnd={dnd}
                absorbingPath={absorbing}
                movedPath={movedPath}
              />
            ))}
          </ul>
        </nav>
      )}

      {/* "Subir un nivel" drop target — visible only while dragging a nested
          node. Pinned to the bottom of the panel (sticky + mt-auto) so it is
          always on screen and reachable, and the label shows where the node
          will land. Dropping here moves the node out of its current folder. */}
      {draggedCanGoUp && (
        <div
          data-testid="file-tree-up-one-level"
          onDragEnter={handleUpBarDragEnter}
          onDragOver={handleUpBarDragOver}
          onDrop={handleUpBarDrop}
          className={cn(
            "sticky bottom-2 z-10 mx-3 mt-auto flex select-none items-center justify-center gap-2 rounded-lg border-2 border-dashed px-3 py-2 text-small transition-colors",
            backgroundIsTarget
              ? "border-action/60 bg-action/10 text-action"
              : "border-edge bg-surface text-muted",
          )}
        >
          <Icon name="arrow-up" size={14} />
          <span className="min-w-0 truncate">
            {t("fileTree.upOneLevel")}
            {upTarget && (
              <span className="ml-1 font-semibold">→ {upTarget}</span>
            )}
          </span>
        </div>
      )}
    </div>
  );
}
