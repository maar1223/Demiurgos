import { useMemo, useState } from "react";
import type { DiffLine } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { cn } from "@/lib/utils";

interface DiffViewerProps {
  /** Array of diff lines from the API. */
  diff: DiffLine[];
  /** Called when the user accepts the changes. */
  onAccept?: () => void;
  /** Called when the user rejects the changes. */
  onReject?: () => void;
  /** Whether the diff is currently loading. */
  isLoading?: boolean;
  /** Error message if the diff fetch failed. */
  error?: string | null;
  /** Callback to retry fetching the diff. */
  onRetry?: () => void;
  /** Whether accept/reject actions are disabled (e.g., during save). */
  actionsDisabled?: boolean;
  /** If true, render single-column (mobile mode) with a toggle. */
  singleColumn?: boolean;
}

/**
 * Side-by-side diff viewer for comparing original vs new file content.
 *
 * Color mapping per spec R3 (S21):
 * - Added lines: musgo (#4A6B3E)
 * - Removed lines: sangre (#8B2D24)
 * - Unchanged lines: pergamino
 *
 * States:
 * - Loading: spinner
 * - Error: error banner with retry
 * - Empty (no changes): "No hay cambios" message
 * - Data: side-by-side diff with action bar
 *
 * Mobile: renders single-column with tabs to toggle original/modified views.
 */
export function DiffViewer({
  diff,
  onAccept,
  onReject,
  isLoading = false,
  error = null,
  onRetry,
  actionsDisabled = false,
  singleColumn = false,
}: DiffViewerProps) {
  const [mobileView, setMobileView] = useState<"original" | "modified">(
    "modified",
  );

  // Compute paired lines for side-by-side rendering
  const pairedLines = useMemo(() => {
    const pairs: Array<{
      left: { text: string; type: "same" | "removed" } | null;
      right: { text: string; type: "same" | "added" } | null;
    }> = [];

    // Track line numbers for each side
    for (const line of diff) {
      if (line.type === "same") {
        pairs.push({
          left: { text: line.text, type: "same" },
          right: { text: line.text, type: "same" },
        });
      } else if (line.type === "removed") {
        pairs.push({
          left: { text: line.text, type: "removed" },
          right: null, // blank on right
        });
      } else if (line.type === "added") {
        pairs.push({
          left: null, // blank on left
          right: { text: line.text, type: "added" },
        });
      }
    }
    return pairs;
  }, [diff]);

  const hasChanges = diff.some((l) => l.type !== "same");
  const isNewFile = diff.every((l) => l.type === "added");

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Spinner size="lg" />
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex flex-col items-center gap-4 py-12">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-piedra text-sangre">
          <Icon name="error" size={32} />
        </div>
        <p className="text-body text-sangre">{error}</p>
        {onRetry && (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Reintentar
          </Button>
        )}
      </div>
    );
  }

  // Empty / no diff data yet
  if (!diff || diff.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-16">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-piedra text-plata/50">
          <Icon name="diff" size={32} />
        </div>
        <p className="text-body text-tinta-desvaida">
          Editá un archivo primero para ver el diff.
        </p>
      </div>
    );
  }

  // No changes
  if (!hasChanges) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-16">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-piedra text-musgo">
          <Icon name="check" size={32} />
        </div>
        <p className="text-body text-pergamino">No hay cambios</p>
        {onReject && (
          <Button variant="secondary" size="sm" onClick={onReject}>
            Volver al editor
          </Button>
        )}
      </div>
    );
  }

  // ── Side-by-side render ──
  const renderSideBySide = () => (
    <div className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-filio md:grid-cols-2">
      {/* Left panel: original */}
      <div className="min-w-0 bg-madero">
        <div className="border-b border-filio bg-piedra px-4 py-2">
          <span className="text-small font-medium text-tinta-desvaida">
            {isNewFile ? "Archivo nuevo" : "Original"}
          </span>
        </div>
        <div className="overflow-x-auto font-mono text-small">
          {pairedLines.map((pair, i) => (
            <div
              key={i}
              className={cn(
                "flex px-4 py-0.5 leading-relaxed",
                pair.left?.type === "removed"
                  ? "bg-sangre/10 text-sangre"
                  : "text-pergamino",
              )}
            >
              <span className="mr-4 w-8 shrink-0 text-right text-xs text-sombra select-none">
                {i + 1}
              </span>
              <span className="whitespace-pre-wrap break-all">
                {pair.left?.text ?? ""}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Right panel: modified */}
      <div className="min-w-0 bg-madero">
        <div className="border-b border-filio bg-piedra px-4 py-2">
          <span className="text-small font-medium text-tinta-desvaida">
            Modificado
          </span>
        </div>
        <div className="overflow-x-auto font-mono text-small">
          {pairedLines.map((pair, i) => (
            <div
              key={i}
              className={cn(
                "flex px-4 py-0.5 leading-relaxed",
                pair.right?.type === "added"
                  ? "bg-musgo/10 text-musgo"
                  : "text-pergamino",
              )}
            >
              <span className="mr-4 w-8 shrink-0 text-right text-xs text-sombra select-none">
                {i + 1}
              </span>
              <span className="whitespace-pre-wrap break-all">
                {pair.right?.text ?? ""}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  // ── Single-column render (mobile) ──
  const renderSingleColumn = () => (
    <div className="overflow-hidden rounded-lg border border-filio bg-madero">
      {/* Tabs */}
      <div className="flex border-b border-filio">
        <button
          type="button"
          onClick={() => setMobileView("original")}
          className={cn(
            "flex-1 px-4 py-2 text-small font-medium transition-colors",
            mobileView === "original"
              ? "border-b-2 border-llamita text-pergamino"
              : "text-tinta-desvaida hover:text-pergamino",
          )}
        >
          {isNewFile ? "Archivo nuevo" : "Original"}
        </button>
        <button
          type="button"
          onClick={() => setMobileView("modified")}
          className={cn(
            "flex-1 px-4 py-2 text-small font-medium transition-colors",
            mobileView === "modified"
              ? "border-b-2 border-llamita text-pergamino"
              : "text-tinta-desvaida hover:text-pergamino",
          )}
        >
          Modificado
        </button>
      </div>

      {/* Content */}
      <div className="overflow-x-auto font-mono text-small">
        {pairedLines.map((pair, i) => {
          const line =
            mobileView === "original" ? pair.left : pair.right;
          return (
            <div
              key={i}
              className={cn(
                "flex px-4 py-0.5 leading-relaxed",
                mobileView === "original" && pair.left?.type === "removed"
                  ? "bg-sangre/10 text-sangre"
                  : mobileView === "modified" && pair.right?.type === "added"
                    ? "bg-musgo/10 text-musgo"
                    : "text-pergamino",
              )}
            >
              <span className="mr-4 w-8 shrink-0 text-right text-xs text-sombra select-none">
                {i + 1}
              </span>
              <span className="whitespace-pre-wrap break-all">
                {line?.text ?? ""}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Diff content */}
      {singleColumn ? renderSingleColumn() : renderSideBySide()}

      {/* Action bar */}
      <div className="flex items-center justify-end gap-3 rounded-lg border border-filio bg-madero px-4 py-3">
        <Button
          variant="secondary"
          size="sm"
          onClick={onReject}
          disabled={actionsDisabled || !onReject}
        >
          <Icon name="close" size={14} />
          Rechazar cambios
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={onAccept}
          disabled={actionsDisabled || !onAccept}
        >
          <Icon name="check" size={14} />
          Aceptar cambios
        </Button>
      </div>
    </div>
  );
}

