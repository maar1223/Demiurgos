import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { useEditReview } from "@/hooks/useEditReview";
import { useFileHistory } from "@/hooks/useFileHistory";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { TFunction } from "@/i18n/messages";
import type { ApiError, EditProposal, HistoryEntry } from "@/api/types";
import { getErrorMessage } from "@/lib/utils";

interface HistoryPanelProps {
  mundo: string;
  section: string;
  path: string;
  currentRevision: string | null;
  currentContent: string;
  open: boolean;
  onClose: () => void;
  onRestored: () => Promise<unknown> | unknown;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

/** Compact localized relative label ("2 hours ago") for recent snapshots;
 *  returns "" for older ones where the absolute timestamp is clearer. */
function formatRelativeTime(value: string, t: TFunction): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const elapsedSeconds = Math.round((date.getTime() - Date.now()) / 1000);
  if (elapsedSeconds > -45) return t("history.relative.justNow");
  const minutes = Math.round(-elapsedSeconds / 60);
  if (minutes < 60) {
    return minutes === 1
      ? t("history.relative.minuteOne")
      : t("history.relative.minutesMany", { count: minutes });
  }
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return hours === 1
      ? t("history.relative.hourOne")
      : t("history.relative.hoursMany", { count: hours });
  }
  const days = Math.round(hours / 24);
  if (days <= 7) {
    return days === 1
      ? t("history.relative.dayOne")
      : t("history.relative.daysMany", { count: days });
  }
  return "";
}

function isCurrentVersion(
  entry: HistoryEntry,
  currentRevision: string | null,
  currentContent: string,
): boolean {
  return (
    (currentRevision !== null && entry.revision === currentRevision) ||
    entry.content === currentContent
  );
}

/** Lists retained snapshots and restores only through confirmation-gated APIs. */
export function HistoryPanel({
  mundo,
  section,
  path,
  currentRevision,
  currentContent,
  open,
  onClose,
  onRestored,
}: HistoryPanelProps) {
  const { t } = useAppLanguage();
  // History endpoints resolve a canonical mundo-relative target
  // (`personajes/Pert.md`), while the section-scoped review pipeline
  // consumes the section-relative `path` (`Pert.md`).
  const historyPath = section ? `${section}/${path}` : path;
  const history = useFileHistory(mundo, historyPath);
  const review = useEditReview({ mundo, section, path });
  const [restoreTarget, setRestoreTarget] = useState<HistoryEntry | null>(null);
  const [pendingRestore, setPendingRestore] = useState<{
    target: HistoryEntry;
    proposal: EditProposal;
  } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const entries = useMemo(
    () =>
      [...history.entries].sort(
        (left, right) =>
          new Date(right.created_at).getTime() -
          new Date(left.created_at).getTime(),
      ),
    [history.entries],
  );

  const handleRestoreConfirm = useCallback(() => {
    if (!restoreTarget || !currentRevision) return;

    const target = restoreTarget;
    if (isCurrentVersion(target, currentRevision, currentContent)) {
      setRestoreTarget(null);
      setActionError(t("history.error.alreadyCurrent"));
      return;
    }

    const proposal: EditProposal = {
      proposal_id: `restore-${target.snapshot_id}`,
      target: path,
      base_revision: currentRevision,
      proposed_content: target.content,
      proposed_digest: target.revision,
      rationale: t("history.rationale.restore"),
      is_new_file: false,
    };

    review.startReview(proposal);
    setPendingRestore({ target, proposal });
  }, [currentContent, currentRevision, restoreTarget, review, t]);

  // Wait for startReview() to commit before requesting a token. The review
  // hook intentionally reads its proposal from state, so both calls cannot
  // safely happen in the same event callback.
  useEffect(() => {
    if (!pendingRestore || review.proposal?.proposal_id !== pendingRestore.proposal.proposal_id) {
      return;
    }

    const { target, proposal } = pendingRestore;
    setPendingRestore(null);
    void (async () => {
      try {
        const confirmation = await review.requestConfirmation(
          proposal.proposal_id,
          "restore",
          target.snapshot_id,
        );
        await history.restore({
          path: historyPath,
          snapshot_id: target.snapshot_id,
          content: target.content,
          base_revision: proposal.base_revision,
          proposed_digest: confirmation.proposed_digest,
          edit_id: proposal.proposal_id,
          token: confirmation.token,
        });
        await onRestored();
        review.reset();
        setRestoreTarget(null);
        setActionError(null);
      } catch (error) {
        const apiError = error as ApiError;
        if (apiError.status === 409) {
          await history.mutate();
          setActionError(t("history.error.stale"));
        } else {
          setActionError(getErrorMessage(apiError.status, apiError.detail));
        }
        review.reset();
      }
    })();
  }, [history, onRestored, historyPath, pendingRestore, review, t]);

  if (!open) return null;

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
        aria-labelledby="history-panel-title"
      >
        <div className="flex items-center justify-between border-b border-edge px-6 py-4">
          <div className="min-w-0">
            <h2 id="history-panel-title" className="font-heading text-h4 text-primary">
              {t("history.title")}
            </h2>
            <p className="truncate text-small text-muted">{path}</p>
          </div>
          <button type="button" onClick={onClose} aria-label={t("history.closeAria")}>
            <Icon name="close" size={20} />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-6">
          {(history.error || actionError || history.restoreError) && (
            <div role="alert" className="rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-small text-status-error">
              {actionError ?? history.restoreError?.message ?? history.error?.message}
            </div>
          )}

          {history.isLoading ? (
            <div className="flex items-center justify-center py-16" role="status">
              <Spinner size="lg" />
            </div>
          ) : entries.length === 0 ? (
            <p className="py-16 text-center text-body text-muted">{t("history.empty")}</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {entries.map((entry) => {
                const current = isCurrentVersion(entry, currentRevision, currentContent);
                const relative = formatRelativeTime(entry.created_at, t);
                return (
                  <li
                    key={entry.snapshot_id}
                    className="flex items-center gap-3 rounded-lg border border-edge bg-surface/50 px-3 py-3"
                  >
                    <Icon name="history" size={18} className="shrink-0 text-icon-muted" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-small text-primary">
                        {t("history.versionSavedOn", { date: formatDate(entry.created_at) })}
                      </p>
                      <p className="text-xs text-muted">
                        {relative
                          ? t("history.savedMeta", { relative, size: entry.size })
                          : t("history.sizeBytes", { size: entry.size })}
                      </p>
                    </div>
                    {current ? (
                      <span className="text-xs text-muted">{t("history.current")}</span>
                    ) : (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          setActionError(null);
                          setRestoreTarget(entry);
                        }}
                        disabled={history.isRestoring}
                      >
                        {t("history.restore")}
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
          title={t("history.restoreTitle")}
          message={t("history.restoreMessage", { snapshot: restoreTarget.snapshot_id })}
          confirmLabel={t("history.restore")}
          isBusy={history.isRestoring || review.isLoading || pendingRestore !== null}
          error={actionError}
          onConfirm={() => void handleRestoreConfirm()}
          onClose={() => {
            setPendingRestore(null);
            setRestoreTarget(null);
            setActionError(null);
            review.reset();
          }}
        />
      )}
    </div>
  );
}

export default HistoryPanel;
