import { useCallback, useMemo, useRef, useState } from "react";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { FileTreeNode } from "@/components/molecules/FileTreeNode";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";
import {
  canDropToTreeBackground,
  readDragPayload,
  type DragPayload,
  type DragState,
  type DropDnd,
} from "@/lib/dnd";
import type { FileNode } from "@/api/types";

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

  // Panel background = "move to section root" target. Only events that
  // never hit a node reach these handlers (nodes stop propagation).
  const handleBackgroundDragEnter = useCallback(
    (e: React.DragEvent) => {
      const dragged = readDragPayload(e.dataTransfer);
      if (!dragged) return;
      setDrag((prev) =>
        prev
          ? { ...prev, target: { path: "", valid: canDropToTreeBackground(dragged) } }
          : prev,
      );
    },
    [],
  );

  const handleBackgroundDragOver = useCallback((e: React.DragEvent) => {
    if (drag) e.preventDefault();
  }, [drag]);

  const handleBackgroundDrop = useCallback(
    (e: React.DragEvent) => {
      const dragged = readDragPayload(e.dataTransfer);
      if (!dragged || !canDropToTreeBackground(dragged)) return;
      e.preventDefault();
      handleDropMove(dragged.path, dragged.path.split("/").pop() ?? "");
    },
    [handleDropMove],
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
          message="No se pudo cargar el árbol de archivos."
          onRetry={onRetry}
        />
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <EmptyState
        icon="empty"
        message="Esta sección está vacía"
      />
    );
  }

  const hasQuery = query.length > 0;

  return (
    <div
      data-testid="file-tree-drop-area"
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
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-sombra"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar archivos…"
            aria-label="Buscar archivos"
            className={cn(
              "w-full rounded-md border border-filio bg-piedra",
              "py-1.5 pl-8 pr-3",
              "text-small text-pergamino placeholder:text-sombra",
              "focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50",
              "transition-colors",
            )}
          />
          {hasQuery && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Limpiar búsqueda"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-sombra hover:text-pergamino"
            >
              <Icon name="close" size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Empty search results */}
      {hasQuery && filteredNodes.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <Icon name="search" size={20} className="text-sombra" />
          <p className="text-small text-tinta-desvaida">Sin resultados</p>
        </div>
      ) : (
        <nav aria-label="File tree">
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
    </div>
  );
}
