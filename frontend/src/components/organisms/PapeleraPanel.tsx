import { useCallback, useEffect, useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { Button } from "@/components/atoms/Button";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import {
  emptyTrash,
  listTrash,
  purgeTrashItem,
  restoreFromTrash,
} from "@/api/wiki";
import type { ApiError, TrashEntry } from "@/api/types";
import { SECTION_LABELS, type Section } from "@/lib/constants";
import { getErrorMessage } from "@/lib/utils";

interface PapeleraPanelProps {
  mundo: string;
  open: boolean;
  onClose: () => void;
  /** Called after a successful restore — parent refreshes the tree. */
  onRestored: () => void;
  /** Called after a successful purge/empty — parent refreshes the tree. */
  onPurged: () => void;
  /**
   * Called with the count of expired entries the lazy 30-day TTL purge
   * removed on this fetch — parent surfaces it as a non-blocking notice.
   */
  onTtlPurged: (count: number) => void;
}

const MONTHS = [
  "ene", "feb", "mar", "abr", "may", "jun",
  "jul", "ago", "sep", "oct", "nov", "dic",
];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDeletedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const day = d.getDate();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${day} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${hh}:${mm}`;
}

/**
 * Papelera (trash) panel — restore / purge / empty of deleted entries.
 *
 * Lists every trashed entry of a world (GET /papelera) with its original
 * path, section, kind, size and deletion date. Per entry: "Restaurar"
 * (POST /papelera/restore, no confirm — non-destructive) and "Purgar"
 * (DELETE individual, soft ConfirmDialog). A "Vaciar papelera" button at
 * the bottom empties the whole trash (DELETE without query) behind a
 * stronger confirm since it is total and irreversible.
 *
 * Overlay + Escape + close-button patterns mirror ImportImageModal /
 * ConfirmDialog. Mounted by WikiEditor with `open` gating; the list is
 * refetched every time the panel opens so a previous session's entries
 * never linger.
 */
export function PapeleraPanel({
  mundo,
  open,
  onClose,
  onRestored,
  onPurged,
  onTtlPurged,
}: PapeleraPanelProps) {
  const [entries, setEntries] = useState<TrashEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyEntryId, setBusyEntryId] = useState<string | null>(null);
  const [isEmptying, setIsEmptying] = useState(false);
  const [purgeTarget, setPurgeTarget] = useState<TrashEntry | null>(null);
  const [confirmEmpty, setConfirmEmpty] = useState(false);

  const loadEntries = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const { entries, purged } = await listTrash(mundo);
      setEntries(entries);
      // The TTL purge runs lazily server-side on every GET /papelera — when
      // it removed expired entries, surface the count to the Author. purged
      // is normalized to 0 by listTrash when the field is absent.
      if (purged > 0) onTtlPurged(purged);
    } catch (err) {
      const apiErr = err as ApiError;
      setError(getErrorMessage(apiErr.status, apiErr.detail));
    } finally {
      setIsLoading(false);
    }
  }, [mundo, onTtlPurged]);

  // Fetch the fresh list every time the panel opens (stale entries from a
  // previous session must never linger).
  useEffect(() => {
    if (!open) return;
    void loadEntries();
  }, [open, loadEntries]);

  const handleClose = useCallback(() => {
    setActionError(null);
    setPurgeTarget(null);
    setConfirmEmpty(false);
    onClose();
  }, [onClose]);

  // Escape closes the panel — unless a confirm dialog is open, whose own
  // Escape handler must win so it does not close both layers at once.
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !purgeTarget && !confirmEmpty) handleClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, purgeTarget, confirmEmpty, handleClose]);

  const handleRestore = useCallback(
    async (entry: TrashEntry) => {
      setBusyEntryId(entry.entry_id);
      setActionError(null);
      try {
        await restoreFromTrash(mundo, entry.entry_id, entry.section);
        await loadEntries();
        onRestored();
      } catch (err) {
        const apiErr = err as ApiError;
        setActionError(getErrorMessage(apiErr.status, apiErr.detail));
      } finally {
        setBusyEntryId(null);
      }
    },
    [mundo, loadEntries, onRestored],
  );

  const handlePurgeConfirm = useCallback(async () => {
    if (!purgeTarget) return;
    const target = purgeTarget;
    setBusyEntryId(target.entry_id);
    setActionError(null);
    try {
      await purgeTrashItem(mundo, target.entry_id, target.section);
      setPurgeTarget(null);
      await loadEntries();
      onPurged();
    } catch (err) {
      const apiErr = err as ApiError;
      setActionError(getErrorMessage(apiErr.status, apiErr.detail));
    } finally {
      setBusyEntryId(null);
    }
  }, [mundo, purgeTarget, loadEntries, onPurged]);

  const handleEmptyConfirm = useCallback(async () => {
    setIsEmptying(true);
    setActionError(null);
    try {
      await emptyTrash(mundo);
      setConfirmEmpty(false);
      setEntries([]);
      onPurged();
    } catch (err) {
      const apiErr = err as ApiError;
      setActionError(getErrorMessage(apiErr.status, apiErr.detail));
    } finally {
      setIsEmptying(false);
    }
  }, [mundo, onPurged]);

  if (!open) return null;

  const dialogOpen = purgeTarget !== null || confirmEmpty;

  return (
    <>
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-surface/80 backdrop-blur-sm"
        onClick={(e) => {
          if (e.target === e.currentTarget) handleClose();
        }}
      >
        <div
          className="mx-4 flex max-h-[80vh] w-full max-w-2xl flex-col rounded-xl border border-edge bg-surface-raised shadow-2xl"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-labelledby="papelera-title"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-edge px-6 py-4">
            <h2
              id="papelera-title"
              className="flex items-center gap-2 font-heading text-h4 text-primary"
            >
              <Icon name="trash" size={20} />
              Papelera
            </h2>
            <button
              type="button"
              onClick={handleClose}
              className="rounded-md p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary"
              aria-label="Cerrar"
            >
              <Icon name="close" size={20} />
            </button>
          </div>

          {/* Body */}
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
            {error && (
              <div
                role="alert"
                className="rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-small text-status-error"
              >
                {error}
              </div>
            )}
            {actionError && !dialogOpen && (
              <div
                role="alert"
                className="rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-small text-status-error"
              >
                {actionError}
              </div>
            )}

            {isLoading ? (
              <div className="flex items-center justify-center py-16">
                <Spinner size="lg" />
              </div>
            ) : entries.length === 0 ? (
              <div className="flex flex-col items-center gap-3 py-16 text-center">
                <Icon name="trash" size={40} className="text-muted" />
                <p className="text-body text-muted">
                  La papelera está vacía
                </p>
              </div>
            ) : (
              <>
                <ul className="flex flex-col gap-2">
                  {entries.map((entry) => {
                    const busy = busyEntryId === entry.entry_id;
                    return (
                      <li
                        key={`${entry.section}/${entry.entry_id}`}
                        className="flex items-center gap-3 rounded-lg border border-edge bg-surface/50 px-3 py-2"
                      >
                        <Icon
                          name={entry.kind === "dir" ? "folder" : "file"}
                          size={18}
                          className="shrink-0 text-icon-muted"
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-mono text-small text-primary">
                            {entry.original_path}
                          </p>
                          <p className="text-xs text-muted">
                            {SECTION_LABELS[entry.section as Section] ??
                              entry.section}
                            {" · "}
                            {formatBytes(entry.size)}
                            {" · "}
                            eliminado el {formatDeletedAt(entry.deleted_at)}
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={busy}
                            onClick={() => void handleRestore(entry)}
                          >
                            Restaurar
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busy}
                            onClick={() => {
                              setActionError(null);
                              setPurgeTarget(entry);
                            }}
                          >
                            Purgar
                          </Button>
                        </div>
                      </li>
                    );
                  })}
                </ul>

                {/* Full cleanup — deliberately set apart from the per-entry
                    actions: it is total and irreversible. */}
                <div className="flex justify-end border-t border-edge pt-4">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={isEmptying}
                    onClick={() => {
                      setActionError(null);
                      setConfirmEmpty(true);
                    }}
                  >
                    Vaciar papelera
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Per-entry purge confirm — irreversible, so it opts into the danger
          treatment (REQ-PIA-08). */}
      {purgeTarget && (
        <ConfirmDialog
          title="Purgar"
          message={`¿Purgar permanentemente "${purgeTarget.original_path.split("/").pop()}"? Se eliminará sin posibilidad de restaurarlo.`}
          confirmLabel="Purgar"
          confirmVariant="danger"
          isBusy={busyEntryId === purgeTarget.entry_id}
          error={actionError}
          onConfirm={() => void handlePurgeConfirm()}
          onClose={() => {
            setPurgeTarget(null);
            setActionError(null);
          }}
        />
      )}

      {/* Empty-all confirm (stronger — total and irreversible) */}
      {confirmEmpty && (
        <ConfirmDialog
          title="Vaciar papelera"
          message={`Se eliminarán permanentemente ${entries.length} ${
            entries.length === 1 ? "entrada" : "entradas"
          }. Esta acción no se puede deshacer.`}
          confirmLabel="Vaciar papelera"
          confirmVariant="danger"
          isBusy={isEmptying}
          error={actionError}
          onConfirm={() => void handleEmptyConfirm()}
          onClose={() => {
            setConfirmEmpty(false);
            setActionError(null);
          }}
        />
      )}
    </>
  );
}
