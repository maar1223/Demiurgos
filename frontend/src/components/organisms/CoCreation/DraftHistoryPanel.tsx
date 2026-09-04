import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import type { DraftHistoryEntry } from "@/api/types";

interface DraftHistoryPanelProps {
  entries: DraftHistoryEntry[];
  /** Current session revision — the row matching it is the live snapshot. */
  currentRevision: number;
  isOpen: boolean;
  onClose: () => void;
  /** Revision-guarded restore (REQ-CC-15). The panel closes on success. */
  onRestore: (revision: number) => Promise<unknown>;
  isRestoring: boolean;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
}

const SOURCE_LABELS: Record<DraftHistoryEntry["source"], string> = {
  author: "Autor",
  chat: "Chat",
  autosave: "Autoguardado",
};

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

/**
 * TW12 immutable autosave snapshot list (REQ-CC-15).
 *
 * Mirrors the `HistoryPanel` restore-confirmation pattern: the Author picks a
 * snapshot, a confirmation dialog gates the action, and the restore goes
 * through the revision-guarded history API (a stale base revision fails
 * closed). Undo/redo stays in-memory (REQ-CC-15); this panel pulls PERSISTED
 * snapshots.
 */
export function DraftHistoryPanel({
  entries,
  currentRevision,
  isOpen,
  onClose,
  onRestore,
  isRestoring,
  isLoading,
  error,
  onRefresh,
}: DraftHistoryPanelProps) {
  const [restoreTarget, setRestoreTarget] = useState<DraftHistoryEntry | null>(
    null,
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [restoreFailed, setRestoreFailed] = useState(false);

  if (!isOpen) return null;

  const confirmRestore = async () => {
    if (!restoreTarget) return;
    setActionError(null);
    setRestoreFailed(false);
    try {
      await onRestore(restoreTarget.revision);
      setRestoreTarget(null);
      onClose();
    } catch {
      setActionError(
        "No se pudo restaurar la versión. Revisá que la sesión no haya cambiado y reintentá.",
      );
      setRestoreFailed(true);
    }
  };

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-surface/80 backdrop-blur-sm"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="mx-4 flex max-h-[80vh] w-full max-w-2xl flex-col rounded-xl border border-edge bg-surface-raised shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="draft-history-title"
      >
        <div className="flex items-center justify-between border-b border-edge px-6 py-4">
          <div className="min-w-0">
            <h2
              id="draft-history-title"
              className="font-heading text-h4 text-primary"
            >
              Historial del lienzo
            </h2>
            <p className="truncate text-small text-muted">
              Autoguardados inmutables del borrador (máx. 50 por sesión).
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar historial"
            className="rounded-md p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-6">
          {(error || actionError) && (
            <div
              role="alert"
              className="rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-small text-status-error"
            >
              {actionError ?? error}
            </div>
          )}

          <div className="flex justify-end">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onRefresh}
              disabled={isLoading}
            >
              <Icon name="refresh" size={14} />
              Actualizar
            </Button>
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center py-16" role="status">
              <Spinner size="lg" />
            </div>
          ) : entries.length === 0 ? (
            <p className="py-16 text-center text-body text-muted">
              Todavía no hay autoguardados en esta sesión.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {entries.map((entry) => {
                const current = entry.revision === currentRevision;
                return (
                  <li
                    key={`${entry.revision}-${entry.ts}`}
                    className="flex items-center gap-3 rounded-lg border border-edge bg-surface/50 px-3 py-3"
                  >
                    <Icon
                      name="history"
                      size={18}
                      className="shrink-0 text-icon-muted"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-small text-primary">
                        Revisión {entry.revision} · {SOURCE_LABELS[entry.source]}
                      </p>
                      <p className="text-xs text-muted">
                        {formatDate(entry.ts)}
                      </p>
                    </div>
                    {current ? (
                      <span className="shrink-0 text-xs text-muted">
                        Versión actual
                      </span>
                    ) : (
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          setActionError(null);
                          setRestoreFailed(false);
                          setRestoreTarget(entry);
                        }}
                        disabled={isRestoring}
                      >
                        Restaurar
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      {restoreTarget && (
        <ConfirmDialog
          title="Restaurar versión"
          message={`¿Restaurar el autoguardado de la revisión ${restoreTarget.revision}? La versión actual queda preservada en el historial.`}
          confirmLabel="Restaurar"
          isBusy={isRestoring}
          error={restoreFailed ? actionError : null}
          onConfirm={() => void confirmRestore()}
          onClose={() => {
            setRestoreTarget(null);
            setActionError(null);
            setRestoreFailed(false);
          }}
        />
      )}
    </div>
  );
}

export default DraftHistoryPanel;