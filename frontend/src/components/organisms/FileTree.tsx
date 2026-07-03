import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { FileTreeNode } from "@/components/molecules/FileTreeNode";
import type { FileNode } from "@/api/types";

interface FileTreeProps {
  nodes: FileNode[];
  selectedPath?: string;
  onSelect?: (path: string) => void;
  isLoading?: boolean;
  error?: Error | null;
  onRetry?: () => void;
}

/**
 * Recursive sidebar file tree with lazy rendering, empty state, and error state.
 *
 * Delegates individual node rendering to `FileTreeNode`, which handles
 * expand/collapse, selection highlighting, and recursive children.
 *
 * States:
 * - 🟡 Loading: Spinner centered in sidebar
 * - 🔴 Error: ErrorBanner with retry button
 * - 🟢 Empty: "Esta sección está vacía"
 * - 🟢 Data: recursive file tree
 */
export function FileTree({
  nodes,
  selectedPath,
  onSelect,
  isLoading = false,
  error = null,
  onRetry,
}: FileTreeProps) {
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

  return (
    <nav aria-label="File tree">
      <ul className="list-none">
        {nodes.map((node) => (
          <FileTreeNode
            key={node.path}
            node={node}
            selectedPath={selectedPath}
            onSelect={onSelect}
          />
        ))}
      </ul>
    </nav>
  );
}
