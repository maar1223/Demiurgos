import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  cancelContentMove,
  cleanupOldContent,
  getContentMove,
  getLastContentMove,
  setContentRoot,
  startContentMove,
} from "@/api/contentRoot";
import type { ContentMoveJob, LastContentMove } from "@/api/contentRoot";
import { systemControlAction } from "@/api/wiki";
import { Button } from "@/components/atoms/Button";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { formatBytes } from "@/components/organisms/ContentFolderStep";
import { overlapsContentRoot } from "@/lib/contentRootOverlap";
import { FolderSuggestions } from "@/components/organisms/FolderSuggestions";

/**
 * "Mover el contenido" — copy the author's content to another folder or disk.
 *
 * A move is the one action that can leave the worlds unreachable, so the UI is
 * deliberately slow in the places that matter: it shows what will travel, it
 * polls the job with real counters, it never pretends the copy finished, and it
 * asks for a restart before anything else (the running process keeps the folder
 * it booted with). Deleting the old copy comes AFTER that, with the path typed
 * back, and is never offered when the record does not authorise it.
 */

function messageOf(error: unknown): string {
  const detail = (error as { detail?: unknown })?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (error instanceof Error && error.message) return error.message;
  return String(error);
}

export function MoveContentDialog({
  contentRoot,
  onClose,
  onMoved,
  pollMs = 700,
}: {
  contentRoot: string | null;
  onClose: () => void;
  onMoved: () => void;
  pollMs?: number;
}) {
  const { t } = useAppLanguage();
  const [target, setTarget] = useState("");
  const [job, setJob] = useState<ContentMoveJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The server refuses a destination that already holds content (it would be a
  // merge, not a move). When that happens the honest next action is "use this
  // folder" — the fourth row of the action table.
  const [useInstead, setUseInstead] = useState(false);
  const timer = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const poll = useCallback(
    (id: string) => {
      timer.current = window.setTimeout(() => {
        void getContentMove(id)
          .then(({ job: next }) => {
            setJob(next);
            if (next.state === "copying" || next.state === "queued") {
              poll(id);
              return;
            }
            setBusy(false);
            if (next.state === "done") onMoved();
          })
          .catch((failure) => {
            setBusy(false);
            setError(messageOf(failure));
          });
      }, pollMs);
    },
    [onMoved, pollMs],
  );

  const start = async (event: FormEvent) => {
    event.preventDefault();
    const chosen = target.trim();
    if (!chosen) return;
    setUseInstead(false);
    // Courtesy half: the server is the authority on both refusals.
    if (overlapsContentRoot(chosen, contentRoot)) {
      setError(t("backup.error.overlapsContent"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { job: started } = await startContentMove(chosen);
      setJob(started);
      if (started.state === "copying" || started.state === "queued") {
        poll(started.id);
      } else {
        setBusy(false);
      }
    } catch (failure) {
      setBusy(false);
      const message = messageOf(failure);
      setError(message);
      setUseInstead(/must be empty/i.test(message));
    }
  };

  const acceptInstead = async () => {
    const chosen = target.trim();
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      const payload = await setContentRoot(chosen);
      setUseInstead(false);
      if (payload.restart_required || payload.pending_restart) setRestartHint(true);
      onMoved();
    } catch (failure) {
      setBusy(false);
      setError(messageOf(failure));
    }
  };

  const cancel = async () => {
    if (!job) return;
    try {
      const { job: next } = await cancelContentMove(job.id);
      setJob(next);
    } catch (failure) {
      setError(messageOf(failure));
    }
  };

  const [restartHint, setRestartHint] = useState(false);
  const running = job !== null && (job.state === "copying" || job.state === "queued");
  const progress =
    job && job.total_files > 0
      ? Math.min(100, Math.round((job.copied_files / job.total_files) * 100))
      : 0;

  return (
    <div className="mt-4 rounded-lg border border-edge bg-surface p-4">
      <h4 className="font-heading text-h5 text-primary">{t("content.move.title")}</h4>
      <p className="mt-1 text-small text-secondary">{t("content.move.intro")}</p>
      <p className="mt-2 break-all font-mono text-small text-secondary">
        {t("content.move.from", { path: contentRoot ?? "—" })}
      </p>

      {!job && (
        <form className="mt-3 space-y-2" onSubmit={start}>
          <label className="block text-small text-secondary" htmlFor="content-move-target">
            {t("content.move.target")}
          </label>
          <input
            id="content-move-target"
            className="w-full rounded border border-edge bg-surface-raised px-3 py-2 font-mono text-small text-primary"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            placeholder={t("content.move.targetPlaceholder")}
            spellCheck={false}
            autoComplete="off"
          />
          <FolderSuggestions onPick={setTarget} disabled={busy} />
          <p className="text-small text-muted">{t("content.move.emptyOnly")}</p>
          <div className="flex flex-wrap gap-3">
            <Button type="submit" variant="primary" disabled={busy || !target.trim()}>
              {t("content.move.start")}
            </Button>
            <Button type="button" variant="ghost" onClick={onClose}>
              {t("common.cancel")}
            </Button>
          </div>
        </form>
      )}

      {job && running && (
        <div className="mt-4 space-y-2" data-testid="content-move-progress">
          <p className="text-small text-primary">
            {t("content.move.progress", {
              copied: job.copied_files,
              total: job.total_files,
            })}
          </p>
          <div className="h-2 w-full rounded bg-surface-raised">
            <div
              className="h-2 rounded bg-accent"
              style={{ width: `${progress}%` }}
              data-testid="content-move-bar"
            />
          </div>
          <p className="text-small text-muted">
            {formatBytes(job.copied_bytes)} / {formatBytes(job.total_bytes)}
          </p>
          <Button type="button" variant="secondary" onClick={() => void cancel()}>
            {t("content.move.cancel")}
          </Button>
        </div>
      )}

      {job && job.state === "done" && (
        <div className="mt-4 space-y-2" data-testid="content-move-done">
          <p className="text-small text-primary">{t("content.move.done")}</p>
          <p className="text-small text-secondary">{t("onboarding.folder.restartRequired")}</p>
          <Button
            type="button"
            variant="primary"
            onClick={() => void systemControlAction("restart")}
          >
            {t("onboarding.folder.restartAction")}
          </Button>
        </div>
      )}

      {job && (job.state === "failed" || job.state === "cancelled") && (
        <p className="mt-3 text-small text-danger" role="alert" data-testid="content-move-failed">
          {job.error ?? t("content.move.cancelled")}
        </p>
      )}

      {useInstead && (
        <div className="mt-3 space-y-2" data-testid="content-move-use-instead">
          <p className="text-small text-secondary">{t("content.move.useInstead")}</p>
          <Button type="button" variant="secondary" disabled={busy} onClick={() => void acceptInstead()}>
            {t("onboarding.folder.change")}
          </Button>
        </div>
      )}

      {restartHint && (
        <p className="mt-3 text-small text-primary" data-testid="content-move-restart">
          {t("onboarding.folder.restartRequired")}
        </p>
      )}

      {error && (
        <div className="mt-3">
          <ErrorBanner message={error} onRetry={() => setError(null)} />
        </div>
      )}
    </div>
  );
}

/**
 * Delete the OLD copy, after a verified move and after the restart.
 *
 * Two confirmations: the record must say a verified move ended with the pointer
 * on the new folder, and the author must type the old path back exactly. The
 * server refuses anything else — this is the courtesy half.
 */
export function CleanupOldContent({
  currentRoot,
  onCleaned,
}: {
  currentRoot: string | null;
  onCleaned: () => void;
}) {
  const { t } = useAppLanguage();
  const [record, setRecord] = useState<LastContentMove | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getLastContentMove()
      .then(({ last_move }) => alive && setRecord(last_move))
      .catch(() => alive && setRecord(null));
    return () => {
      alive = false;
    };
  }, []);

  if (
    record === null ||
    record.state !== "done" ||
    !record.pointer_written ||
    !currentRoot ||
    record.source === currentRoot
  ) {
    return null;
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await cleanupOldContent(typed.trim());
      onCleaned();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="mt-4 space-y-2 rounded-lg border border-status-warning/40 bg-status-warning/10 p-4" onSubmit={submit}>
      <p className="text-small text-primary" data-testid="content-cleanup-offer">
        {t("content.cleanup.offer", { path: record.source })}
      </p>
      <label className="block text-small text-secondary" htmlFor="content-cleanup-confirm">
        {t("content.cleanup.confirmLabel")}
      </label>
      <input
        id="content-cleanup-confirm"
        className="w-full rounded border border-edge bg-surface px-3 py-2 font-mono text-small text-primary"
        value={typed}
        onChange={(event) => setTyped(event.target.value)}
        placeholder={record.source}
        spellCheck={false}
        autoComplete="off"
      />
      <Button
        type="submit"
        variant="danger"
        disabled={busy || typed.trim() !== record.source}
      >
        {t("content.cleanup.action")}
      </Button>
      {error && (
        <div className="pt-2">
          <ErrorBanner message={error} onRetry={() => setError(null)} />
        </div>
      )}
    </form>
  );
}
