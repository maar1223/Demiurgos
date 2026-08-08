import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { useEditReview } from "@/hooks/useEditReview";
import { useFileHistory } from "@/hooks/useFileHistory";
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
  const history = useFileHistory(mundo, path);
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
      setActionError("The selected snapshot is already the current version.");
      return;
    }

    const proposal: EditProposal = {
      proposal_id: `restore-${target.snapshot_id}`,
      target: path,
      base_revision: currentRevision,
      proposed_content: target.content,
      proposed_digest: target.revision,
      rationale: "Restore a retained file version",
      is_new_file: false,
    };

    review.startReview(proposal);
    setPendingRestore({ target, proposal });
  }, [currentContent, currentRevision, restoreTarget, review]);

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
          path,
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
          setActionError("The file changed. History was reloaded; review the restore again.");
        } else {
          setActionError(getErrorMessage(apiError.status, apiError.detail));
        }
        review.reset();
      }
    })();
  }, [history, onRestored, path, pendingRestore, review]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-cripta/80 backdrop-blur-sm"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="mx-4 flex max-h-[80vh] w-full max-w-2xl flex-col rounded-xl border border-filio bg-madero shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="history-panel-title"
      >
        <div className="flex items-center justify-between border-b border-filio px-6 py-4">
          <div className="min-w-0">
            <h2 id="history-panel-title" className="font-heading text-h4 text-pergamino">
              File history
            </h2>
            <p className="truncate text-small text-tinta-desvaida">{path}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close history">
            <Icon name="close" size={20} />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-6">
          {(history.error || actionError || history.restoreError) && (
            <div role="alert" className="rounded-lg border border-sangre/30 bg-sangre/10 px-3 py-2 text-small text-sangre">
              {actionError ?? history.restoreError?.message ?? history.error?.message}
            </div>
          )}

          {history.isLoading ? (
            <div className="flex items-center justify-center py-16" role="status">
              <Spinner size="lg" />
            </div>
          ) : entries.length === 0 ? (
            <p className="py-16 text-center text-body text-tinta-desvaida">No history available.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {entries.map((entry) => {
                const current = isCurrentVersion(entry, currentRevision, currentContent);
                return (
                  <li
                    key={entry.snapshot_id}
                    className="flex items-center gap-3 rounded-lg border border-filio bg-cripta/50 px-3 py-3"
                  >
                    <Icon name="history" size={18} className="shrink-0 text-plata" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-mono text-small text-pergamino">
                        {entry.snapshot_id}
                      </p>
                      <p className="text-xs text-tinta-desvaida">
                        {formatDate(entry.created_at)} · {entry.size} bytes
                      </p>
                    </div>
                    {current ? (
                      <span className="text-xs text-tinta-desvaida">Current version</span>
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
                        Restore
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
          title="Restore version"
          message={`Restore snapshot "${restoreTarget.snapshot_id}"? The current version will be preserved in history.`}
          confirmLabel="Restore"
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
