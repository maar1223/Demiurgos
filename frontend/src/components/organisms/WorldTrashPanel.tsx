import { useCallback, useState } from "react";
import useSWR from "swr";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
// World-level recycle bin API — deliberately imported from @/api/worlds and
// NOT from @/api/wiki, which exports a DIFFERENT `listTrash(mundo)` for the
// per-ficha papelera (requires a mundo argument).
import { listTrash, permanentDelete, restoreWorld } from "@/api/worlds";
import type { ApiError, WorldTrashEntry } from "@/api/types";
import { getErrorMessage } from "@/lib/utils";

/** SWR cache key namespace for the world-level recycle bin list. */
export const WORLD_TRASH_KEY = "worlds-trash";

interface WorldTrashPanelProps {
  /** Parent bumps this after a world delete so the panel refetches. */
  refreshToken: number;
  /** Called after restore/permanent-delete — parent refreshes the worlds list. */
  onChanged: () => void;
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
 * Papelera de mundos — the world-level recycle bin (REQ-010).
 *
 * Lists every deleted world (GET /api/worlds/trash) with its deletion date,
 * size, entity counts and days remaining until the 30-day purge. Per entry:
 * "Restaurar" (POST restore, non-destructive) and "Eliminar permanentemente"
 * (DELETE trash entry, behind a ConfirmDialog — irreversible).
 *
 * The list is loaded via SWR on the compound key `[WORLD_TRASH_KEY,
 * refreshToken]`; the parent bumps `refreshToken` after a delete so the new
 * trash entry appears without remounting the panel.
 */
export function WorldTrashPanel({ refreshToken, onChanged }: WorldTrashPanelProps) {
  const { data, error, isLoading, mutate } = useSWR<WorldTrashEntry[], Error>(
    [WORLD_TRASH_KEY, refreshToken],
    () => listTrash(),
    {
      revalidateOnFocus: true,
      revalidateOnReconnect: true,
      errorRetryCount: 2,
    },
  );
  const entries = data ?? [];

  const [busyName, setBusyName] = useState<string | null>(null);
  const [purgeTarget, setPurgeTarget] = useState<WorldTrashEntry | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [restoreNotice, setRestoreNotice] = useState<string | null>(null);

  const handleRestore = useCallback(
    async (entry: WorldTrashEntry) => {
      setBusyName(entry.world_name);
      setActionError(null);
      setRestoreNotice(null);
      try {
        // The server auto-names the restore when the original name is taken by
        // an active world, so a conflict never blocks the user.
        const result = await restoreWorld(entry.world_name);
        if (result.world_name !== entry.world_name) {
          setRestoreNotice(
            `El mundo ya existía con ese nombre; se restauró como «${result.world_name}».`,
          );
        }
        await mutate();
        onChanged();
      } catch (err) {
        const apiErr = err as ApiError;
        setActionError(getErrorMessage(apiErr.status, apiErr.detail));
      } finally {
        setBusyName(null);
      }
    },
    [mutate, onChanged],
  );

  const handlePurgeConfirm = useCallback(async () => {
    if (!purgeTarget) return;
    const target = purgeTarget;
    setBusyName(target.world_name);
    setActionError(null);
    try {
      await permanentDelete(target.world_name);
      setPurgeTarget(null);
      await mutate();
      onChanged();
    } catch (err) {
      const apiErr = err as ApiError;
      setActionError(getErrorMessage(apiErr.status, apiErr.detail));
    } finally {
      setBusyName(null);
    }
  }, [purgeTarget, mutate, onChanged]);

  return (
    <div>
      <h3 className="flex items-center gap-2 font-heading text-body text-primary">
        <Icon name="trash" size={18} className="text-icon-muted" />
        Papelera de mundos
      </h3>
      <p className="mt-1 text-small text-muted">
        Mundos eliminados: quedan 30 días para restaurarlos antes de que se purguen.
      </p>

      {error && (
        <div
          role="alert"
          className="mt-3 rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-small text-status-error"
        >
          {getErrorMessage((error as ApiError).status, (error as ApiError).detail)}
        </div>
      )}
      {actionError && !purgeTarget && (
        <div
          role="alert"
          className="mt-3 rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-small text-status-error"
        >
          {actionError}
        </div>
      )}
      {restoreNotice && (
        <div
          role="status"
          className="mt-3 rounded-lg border border-action/30 bg-action/10 px-3 py-2 text-small text-primary"
        >
          {restoreNotice}
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center py-10">
          <Spinner size="lg" />
        </div>
      ) : entries.length === 0 ? (
        <div className="mt-3 flex flex-col items-center gap-2 rounded-lg border border-dashed border-edge py-8 text-center">
          <Icon name="trash" size={32} className="text-muted" />
          <p className="text-body text-muted">La papelera está vacía</p>
        </div>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {entries.map((entry) => {
            const busy = busyName === entry.world_name;
            return (
              <li
                key={entry.world_name}
                className="flex items-center gap-3 rounded-lg border border-edge bg-surface/50 px-3 py-2"
              >
                <Icon name="world" size={18} className="shrink-0 text-icon-muted" />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-mono text-small text-primary">{entry.world_name}</p>
                  <p className="text-xs text-muted">
                    eliminado el {formatDeletedAt(entry.deleted_at)} · {formatBytes(entry.size_bytes)}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-1">
                    <Badge variant="warning">{entry.days_remaining} días</Badge>
                    <Badge>Lore {entry.lore_count}</Badge>
                    <Badge>Personajes {entry.character_count}</Badge>
                  </div>
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
                    Eliminar permanentemente
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Permanent-delete confirmation — irreversible, so it needs its own
          confirm step on top of the list action (REQ-010) and the danger
          treatment on its confirm action (REQ-PIA-08). */}
      {purgeTarget && (
        <ConfirmDialog
          title="Eliminar permanentemente"
          message={`¿Eliminar permanentemente el mundo «${purgeTarget.world_name}»? Esta acción no se puede deshacer y también limpia sus datos asociados.`}
          confirmLabel="Eliminar permanentemente"
          confirmVariant="danger"
          isBusy={busyName === purgeTarget.world_name}
          error={actionError}
          onConfirm={() => void handlePurgeConfirm()}
          onClose={() => {
            setPurgeTarget(null);
            setActionError(null);
          }}
        />
      )}
    </div>
  );
}