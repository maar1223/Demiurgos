import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { EmptyState } from "@/components/organisms/EmptyState";

interface MarkdownViewerProps {
  content?: string | null;
  fileName?: string;
  isLoading?: boolean;
  error?: Error | null;
  onRetry?: () => void;
}

/**
 * Renders GFM markdown content via react-markdown + remark-gfm.
 *
 * Uses @tailwindcss/typography (`prose prose-invert`) for styling.
 *
 * States:
 * - 🟡 Loading: Spinner centered in content area
 * - 🟢 No file selected: "Seleccioná un archivo" placeholder
 * - 🔴 Error: ErrorBanner with retry
 * - 🟢 Empty content: file selected but no content
 * - 🟢 Content: rendered markdown
 */
export function MarkdownViewer({
  content,
  fileName,
  isLoading = false,
  error = null,
  onRetry,
}: MarkdownViewerProps) {
  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" />
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="px-4 py-8">
        <ErrorBanner
          message={error.message || "Error al cargar el archivo."}
          onRetry={onRetry}
        />
      </div>
    );
  }

  // No file selected state
  if (content === undefined || content === null) {
    return (
      <EmptyState
        icon="file"
        message="Seleccioná un archivo del panel lateral para ver su contenido."
      />
    );
  }

  // Empty file content
  if (content === "") {
    return (
      <EmptyState
        icon="file"
        message={`El archivo "${fileName ?? "sin nombre"}" está vacío.`}
      />
    );
  }

  // Render markdown
  return (
    <div className="prose prose-invert max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
