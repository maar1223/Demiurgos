import { useCallback, useEffect, useState } from "react";
import {
  getBackupCandidates,
  getBackupRestoreStatus,
  getBackupSnapshots,
  getBackupStatus,
  previewBackupRestore,
  restoreBackup,
  runBackupNow,
  setBackupDestination,
} from "@/api/backup";
import { ApiError } from "@/api/types";
import type {
  BackupCandidate,
  BackupConflictReport,
  BackupRestorePreview,
  BackupRestoreResult,
  BackupSnapshot,
  BackupStatus,
  CardState,
} from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { getContentRoot } from "@/api/contentRoot";
import { ContentFolderCard } from "@/components/organisms/ContentFolderCard";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { overlapsContentRoot } from "@/lib/contentRootOverlap";
import type { MessageKey, TFunction } from "@/i18n/messages";

/**
 * Respaldo y restauración (REQ-BUI-1/2/3, WU-15) — the Profile → Centro de
 * Configuración backup section.
 *
 * Five states, all driven by the LIVE `GET /api/backup/status` payload:
 *
 * 1. **No folder chosen** — the picker plus the `/api/backup/candidates`
 *    suggestions; a suggestion is never auto-selected.
 * 2. **Folder chosen** — its absolute path, provider and provenance
 *    (`source`/`confidence`), plus the mode verdict.
 * 3. **Streaming detected** — a warning block REPLACES the success area: the
 *    API's remedy is rendered verbatim, no run is offered and no success claim
 *    is made (SC-BUI-2.1).
 * 4. **Last local write** — "Escrito en <carpeta> — <timestamp> UTC" plus the
 *    `Backup ahora` action. The copy is the API's local-write string.
 * 5. **Restore** — list → preview → confirm → progress → result, with its own
 *    explicit confirmation.
 *
 * There is deliberately NO quota, account, connection state or upload field:
 * the backend asserts the payload is cloud-free, and the UI renders exactly
 * what the payload proves. The card renders "Configurado" only with real
 * evidence (a chosen folder AND a recorded successful local write).
 */

const PROVIDER_LABELS: Record<string, MessageKey> = {
  onedrive: "backup.provider.onedrive",
  google_drive: "backup.provider.googleDrive",
  icloud: "backup.provider.icloud",
  unknown: "backup.provider.unknown",
};

const SOURCE_LABELS: Record<string, MessageKey> = {
  env: "backup.source.env",
  registry: "backup.source.registry",
  heuristic: "backup.source.heuristic",
  user: "backup.source.user",
};

const CONFIDENCE_LABELS: Record<string, MessageKey> = {
  verified: "backup.confidence.verified",
  heuristic: "backup.confidence.heuristic",
};

const MODE_LABELS: Record<string, MessageKey> = {
  mirrored: "backup.mode.mirrored",
  streaming: "backup.mode.streaming",
  unknown: "backup.mode.unknown",
};

const inputClass =
  "w-full rounded-md border border-edge bg-surface-raised py-1.5 px-3 text-small text-primary " +
  "placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50";
const labelClass = "mb-1 block text-small text-muted";

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

/**
 * True when a failed `/api/backup/*` read means "no session", not "the backup
 * is broken". The router fails CLOSED behind `require_principal`: an
 * unauthenticated call is a 401 whose detail is `Autenticación requerida`. That
 * case gets its own actionable state; every other failure keeps the honest
 * error path.
 */
export function isSessionRequiredError(cause: unknown): boolean {
  const message = cause instanceof Error ? cause.message : "";
  if (cause instanceof ApiError && cause.status === 401) return true;
  return /autenticación requerida/i.test(message);
}

export interface BackupSectionProps {
  /**
   * Concrete way forward for the session-required state. The Profile page
   * passes a callback that opens its "Sesión de edición" tab, where the local
   * session can actually be started.
   */
  onRequestSignIn?: () => void;
}

/**
 * The card may render "Configurado" ONLY with real evidence: the backend state
 * is `configured` AND a folder is persisted AND a successful local write is
 * recorded (REQ-CC-1/REQ-BUI-3). A bare `configured` claim from a stale/buggy
 * payload is downgraded instead of overstated.
 */
export function backupCardConfigured(status: BackupStatus | null): boolean {
  return (
    !!status &&
    status.state === "configured" &&
    status.destination !== null &&
    !status.blocked &&
    status.last_write !== null &&
    (status.last_write.status === "ok" || status.last_write.status === "ok_with_warnings")
  );
}

/** The honest badge state shown in the section header. */
export function backupCardState(status: BackupStatus | null): CardState {
  if (!status) return "pending";
  if (backupCardConfigured(status)) return "configured";
  if (status.blocked || status.state === "error") return "error";
  return "pending";
}

/**
 * The local-write copy. The API builds it (`copy.es`) from the recorded write;
 * the fallback repeats the SAME local-write phrasing, never a delivery claim.
 */
export function backupWriteCopy(
  status: BackupStatus,
  t?: TFunction,
): string | null {
  if (status.copy?.es) return status.copy.es;
  if (!status.last_write) return null;
  const fallback = `Escrito en ${status.last_write.destination} — ${status.last_write.written_at} UTC`;
  if (!t) return fallback;
  return t("backup.writeCopy", {
    destination: status.last_write.destination,
    writtenAt: status.last_write.written_at,
  });
}

/** Normalize the preview payload: the router nests the report under `conflicts`. */
export function normalizeConflicts(preview: BackupRestorePreview): BackupConflictReport {
  if (preview.conflicts) return preview.conflicts;
  return {
    snapshot_id: preview.snapshot_id ?? "",
    counts: preview.counts ?? { added: 0, modified: 0, removed: 0 },
    examples: preview.examples ?? [],
    blockers: preview.blockers ?? [],
  };
}

type RestoreStage = "list" | "preview" | "confirm" | "running" | "result";

function providerLabel(provider: string, t: TFunction): string {
  const key = PROVIDER_LABELS[provider];
  return key ? t(key) : t("backup.provider.other");
}

function sourceLabel(source: string, t: TFunction): string {
  const key = SOURCE_LABELS[source];
  return key ? t(key) : t("backup.source.unknown");
}

function confidenceLabel(confidence: string, t: TFunction): string {
  const key = CONFIDENCE_LABELS[confidence];
  return key ? t(key) : t("backup.confidence.unknown");
}

function modeLabel(mode: string | null, t: TFunction): string {
  if (!mode) return t("backup.mode.none");
  const key = MODE_LABELS[mode];
  return key ? t(key) : t("backup.mode.unknownFallback");
}

export function BackupSection({ onRequestSignIn }: BackupSectionProps = {}) {
  const { t } = useAppLanguage();
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [candidates, setCandidates] = useState<BackupCandidate[]>([]);
  const [pickerPath, setPickerPath] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // The content root is read once, best effort: the backup card must never fail
  // because the folder endpoint did.
  const [contentRoot, setContentRoot] = useState<string | null>(null);
  // A 401 / `Autenticación requerida` is not a crash: it is a missing session
  // with a concrete next step, kept separate from the honest error path.
  const [sessionRequired, setSessionRequired] = useState(false);

  // Restore sub-flow state (state 5): list → preview → confirm → running → result.
  const [restoreOpen, setRestoreOpen] = useState(false);
  const [restoreStage, setRestoreStage] = useState<RestoreStage>("list");
  const [snapshots, setSnapshots] = useState<BackupSnapshot[]>([]);
  const [selectedSnapshot, setSelectedSnapshot] = useState<string | null>(null);
  const [preview, setPreview] = useState<BackupConflictReport | null>(null);
  const [restoreResult, setRestoreResult] = useState<BackupRestoreResult | null>(null);
  // Unresolved restore from a previous crash: surfaced, never hidden.
  const [restorePending, setRestorePending] = useState(false);
  const [restoreLeftovers, setRestoreLeftovers] = useState<string[]>([]);

  const loadStatus = useCallback(() => {
    return getBackupStatus()
      .then((next) => {
        setStatus(next);
        setSessionRequired(false);
        return next;
      })
      .catch((cause: unknown) => {
        if (isSessionRequiredError(cause)) {
          setSessionRequired(true);
          return null;
        }
        setError(errorText(cause, t("backup.error.loadStatus")));
        return null;
      });
  }, []);

  const loadRestoreStatus = useCallback(() => {
    return getBackupRestoreStatus()
      .then((next) => {
        setRestorePending(next.pending);
        setRestoreLeftovers(next.leftovers);
      })
      .catch(() => {
        // The marker read is advisory: a failure never invents an unresolved restore.
        setRestorePending(false);
        setRestoreLeftovers([]);
      });
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    void Promise.all([loadStatus(), loadRestoreStatus(), getBackupCandidates()])
      .then(([, , discovered]) => {
        if (!active) return;
        setCandidates(discovered.candidates);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        if (isSessionRequiredError(cause)) {
          setSessionRequired(true);
          return;
        }
        setError(errorText(cause, t("backup.error.loadConfig")));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [loadStatus, loadRestoreStatus]);

  useEffect(() => {
    let alive = true;
    getContentRoot()
      .then((info) => alive && setContentRoot(info.path))
      .catch(() => alive && setContentRoot(null));
    return () => {
      alive = false;
    };
  }, []);

  const chooseFolder = async (path: string) => {
    const chosen = path.trim();
    if (!chosen) return;
    // Say it before sending: the server refuses this pair, and a 400 would
    // arrive as a surprise on a folder that looks perfectly fine.
    if (overlapsContentRoot(chosen, contentRoot)) {
      setNotice(null);
      setError(t("backup.error.overlapsContent"));
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await setBackupDestination(chosen);
      setStatus(next);
      setPickerOpen(false);
      setPickerPath("");
      // A verified streaming target is persisted WITH its verdict: the warning
      // state takes over and no run is offered.
      if (!next.blocked) setNotice(t("backup.notice.folderSaved"));
    } catch (cause) {
      setError(errorText(cause, t("backup.error.saveFolder")));
    } finally {
      setBusy(false);
    }
  };

  const runNow = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await runBackupNow();
      setStatus(next);
      setNotice(t("backup.notice.wrote"));
    } catch (cause) {
      setError(errorText(cause, t("backup.error.run")));
      // The run may have been refused (streaming/quiesced): re-read the truth.
      void loadStatus();
    } finally {
      setBusy(false);
    }
  };

  const openRestore = async () => {
    setRestoreOpen(true);
    setRestoreStage("list");
    setSnapshots([]);
    setSelectedSnapshot(null);
    setPreview(null);
    setRestoreResult(null);
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const list = await getBackupSnapshots();
      setSnapshots(list.snapshots);
    } catch (cause) {
      setError(errorText(cause, t("backup.error.list")));
    } finally {
      setBusy(false);
    }
  };

  const closeRestore = () => {
    setRestoreOpen(false);
    setRestoreStage("list");
    setSelectedSnapshot(null);
    setPreview(null);
    setRestoreResult(null);
  };

  const previewSnapshot = async (snapshotId: string) => {
    setBusy(true);
    setError(null);
    setSelectedSnapshot(snapshotId);
    try {
      setPreview(normalizeConflicts(await previewBackupRestore(snapshotId)));
      setRestoreStage("preview");
    } catch (cause) {
      setError(errorText(cause, t("backup.error.preview")));
    } finally {
      setBusy(false);
    }
  };

  const confirmRestore = async () => {
    if (!selectedSnapshot) return;
    setRestoreStage("running");
    setError(null);
    try {
      const result = await restoreBackup(selectedSnapshot);
      setRestoreResult(result);
      setRestoreStage("result");
      // The data root changed: refresh the honest write state and the marker.
      await Promise.all([loadStatus(), loadRestoreStatus()]);
    } catch (cause) {
      setError(errorText(cause, t("backup.error.restore")));
      setRestoreStage("confirm");
    }
  };

  if (loading) {
    return (
      <div className="mt-4 flex items-center gap-2 text-small text-muted">
        <Spinner size="sm" /> {t("backup.loading")}
      </div>
    );
  }

  if (sessionRequired && !status) {
    return (
      <div
        data-testid="backup-session-required"
        role="status"
        className="mt-3 rounded-lg border border-edge bg-surface-raised p-4"
      >
        <p className="text-small font-medium text-primary">
          {t("backup.sessionRequired.title")}
        </p>
        <p className="mt-1 text-small text-muted">
          {t("backup.sessionRequired.body")}
        </p>
        {onRequestSignIn && (
          <Button variant="primary" size="sm" className="mt-3" onClick={onRequestSignIn}>
            {t("backup.sessionRequired.cta")}
          </Button>
        )}
      </div>
    );
  }

  if (!status) {
    return (
      <p className="mt-3 text-small text-status-error" role="alert">
        {error ?? t("backup.error.loadStatus")}
      </p>
    );
  }

  const badge = backupCardState(status);
  const badgeVariant = badge === "configured" ? "success" : badge === "error" ? "error" : "default";
  const badgeLabel =
    badge === "configured"
      ? t("backup.badge.configured")
      : badge === "error"
        ? t("backup.badge.error")
        : t("backup.badge.pending");
  const hasDestination = status.destination !== null;
  const writeCopy = backupWriteCopy(status, t);
  const pickerVisible = pickerOpen || !hasDestination;

  return (
    <div className="mt-3" aria-live="polite">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-heading text-small text-primary">
          {t("backup.status.title")}
        </h3>
        <span className="flex items-center gap-2">
          <Badge variant={badgeVariant}>{badgeLabel}</Badge>
          <span className="sr-only">
            {t("backup.status.aria", { label: badgeLabel })}
          </span>
        </span>
      </div>

      {restorePending && (
        <p className="mt-3 rounded-lg border border-status-error/30 bg-status-error/10 p-3 text-small text-status-error" role="alert">
          {t("backup.restorePending")}
          {restoreLeftovers.length > 0
            ? t("backup.restorePending.leftovers", {
                leftovers: restoreLeftovers.join(", "),
              })
            : ""}
          .
        </p>
      )}

      {error && (
        <p className="mt-3 text-small text-status-error" role="alert">
          {error}
        </p>
      )}
      {notice && <p className="mt-3 text-small text-status-success">{notice}</p>}

      {/* State 1 — no folder yet: the picker plus the candidate suggestions. */}
      {/* Where the author's content lives: the folder the backup must never
          overlap, and the place a move to another disk starts. */}
      <ContentFolderCard />

      {!hasDestination && (
        <p className="mt-3 text-small text-muted">{t("backup.noFolder")}</p>
      )}

      {/* States 2/3/4 — the chosen folder and its honest mode verdict. */}
      {hasDestination && status.destination && (
        <dl className="mt-3 space-y-2 border-t border-edge pt-3">
          <div>
            <dt className="text-small text-muted">{t("backup.folder")}</dt>
            <dd className="break-all text-small text-primary" data-testid="backup-destination-path">
              {status.destination.path}
            </dd>
          </div>
          {overlapsContentRoot(status.destination.path, contentRoot) && (
            <p
              className="rounded-lg border border-status-error/30 bg-status-error/10 p-3 text-small text-status-error"
              role="alert"
              data-testid="backup-overlap-warning"
            >
              {t("backup.warning.overlapsContent")}
            </p>
          )}
          <div>
            <dt className="text-small text-muted">{t("backup.provider")}</dt>
            <dd className="text-small text-primary">
              {providerLabel(status.destination.provider, t)}
            </dd>
          </div>
          <div>
            <dt className="text-small text-muted">{t("backup.origin")}</dt>
            <dd className="text-small text-primary">
              {t("backup.originValue", {
                source: sourceLabel(status.destination.source, t),
                confidence: confidenceLabel(
                  status.destination.confidence,
                  t,
                ),
              })}
            </dd>
          </div>
          <div>
            <dt className="text-small text-muted">{t("backup.mode")}</dt>
            <dd className="text-small text-primary">
              {modeLabel(status.mode, t)}
            </dd>
          </div>
        </dl>
      )}

      {/*
        State 3 — streaming warning REPLACES the success area. The remedy comes
        from the API verbatim; no success copy and no run action are rendered.
      */}
      {status.blocked ? (
        <div
          data-testid="backup-warning"
          role="alert"
          className="mt-4 rounded-lg border border-status-error/30 bg-status-error/10 p-4"
        >
          <p className="text-small font-medium text-status-error">
            {t("backup.blocked.title")}
          </p>
          <p className="mt-1 text-small text-muted">
            {t("backup.blocked.body")}
          </p>
          {status.warning && (
            <p className="mt-2 text-small text-primary" data-testid="backup-warning-remedy">
              {t("backup.blocked.remedy", { remedy: status.warning })}
            </p>
          )}
        </div>
      ) : (
        hasDestination && (
          <div className="mt-4 border-t border-edge pt-3" data-testid="backup-success-area">
            {writeCopy ? (
              <p className="text-small text-status-success" data-testid="backup-last-write">
                {writeCopy}
              </p>
            ) : (
              <p className="text-small text-muted">
                {t("backup.noWrite")}
              </p>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <Button onClick={() => void runNow()} disabled={busy}>
                {busy ? t("backup.run.running") : t("backup.run.now")}
              </Button>
              <Button variant="secondary" onClick={() => setPickerOpen((open) => !open)} disabled={busy}>
                {t("backup.chooseOther")}
              </Button>
            </div>
          </div>
        )
      )}

      {/* The folder picker: always offered, and always explicit (never auto-selected). */}
      {pickerVisible && (
        <form
          className="mt-4 border-t border-edge pt-3"
          onSubmit={(event) => {
            event.preventDefault();
            void chooseFolder(pickerPath);
          }}
        >
          <label className={labelClass} htmlFor="backup-destination-path-input">
            {t("backup.picker.label")}
          </label>
          <div className="flex flex-wrap gap-2">
            <input
              id="backup-destination-path-input"
              className={`${inputClass} sm:max-w-md`}
              value={pickerPath}
              onChange={(event) => setPickerPath(event.target.value)}
              placeholder={t("backup.picker.placeholder")}
              autoComplete="off"
            />
            <Button type="submit" disabled={busy || !pickerPath.trim()}>
              {t("backup.picker.use")}
            </Button>
          </div>
          <p className="mt-2 text-small text-muted">
            {t("backup.picker.hint")}
          </p>

          {candidates.length > 0 && (
            <ul className="mt-3 space-y-2" aria-label={t("backup.picker.suggestionsAria")}>
              {candidates.map((candidate) => (
                <li
                  key={`${candidate.provider}:${candidate.path}`}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-edge bg-surface-raised p-2"
                >
                  <span className="min-w-0">
                    <span className="block break-all text-small text-primary">{candidate.path}</span>
                    <span className="block text-small text-muted">
                      {t("backup.candidate.meta", {
                        provider: providerLabel(candidate.provider, t),
                        source: sourceLabel(candidate.source, t),
                        confidence: confidenceLabel(candidate.confidence, t),
                      })}
                    </span>
                  </span>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => void chooseFolder(candidate.path)}
                    disabled={busy}
                  >
                    {t("backup.picker.use")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </form>
      )}

      {/* State 5 — restore: list → preview → confirm → progress → result. */}
      {hasDestination && !status.blocked && (
        <div className="mt-4 border-t border-edge pt-3">
          {!restoreOpen ? (
            <Button variant="secondary" onClick={() => void openRestore()} disabled={busy}>
              {t("backup.restore.open")}
            </Button>
          ) : (
            <div>
              <div className="flex items-center justify-between gap-3">
                <h4 className="font-heading text-small text-primary">
                  {t("backup.restore.heading")}
                </h4>
                <Button variant="ghost" size="sm" onClick={closeRestore} disabled={busy && restoreStage === "running"}>
                  {t("backup.restore.close")}
                </Button>
              </div>

              {restoreStage === "list" && (
                <div className="mt-2">
                  {busy && snapshots.length === 0 ? (
                    <div className="flex items-center gap-2 text-small text-muted">
                      <Spinner size="sm" /> {t("backup.restore.searching")}
                    </div>
                  ) : snapshots.length === 0 ? (
                    <p className="text-small text-muted">
                      {t("backup.restore.empty")}
                    </p>
                  ) : (
                    <ul className="space-y-2" aria-label={t("backup.restore.listAria")}>
                      {snapshots.map((snapshot) => (
                        <li
                          key={snapshot.snapshot_id}
                          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-edge bg-surface-raised p-2"
                        >
                          <span>
                            <span className="block text-small text-primary">{snapshot.snapshot_id}</span>
                            <span className="block text-small text-muted">
                              {snapshot.complete
                                ? t("backup.restore.complete")
                                : t("backup.restore.incomplete")}{" "}
                              ·{" "}
                              {t("backup.restore.entries", {
                                count: snapshot.entries,
                              })}
                            </span>
                          </span>
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => void previewSnapshot(snapshot.snapshot_id)}
                            disabled={busy}
                          >
                            {t("backup.restore.preview")}
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {restoreStage === "preview" && preview && (
                <div className="mt-2">
                  <p className="text-small text-primary">
                    {t("backup.restore.warning")}
                  </p>
                  <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <div>
                      <dt className="text-small text-muted">
                        {t("backup.restore.added")}
                      </dt>
                      <dd className="text-small text-primary">{preview.counts.added}</dd>
                    </div>
                    <div>
                      <dt className="text-small text-muted">
                        {t("backup.restore.modified")}
                      </dt>
                      <dd className="text-small text-primary">{preview.counts.modified}</dd>
                    </div>
                    <div>
                      <dt className="text-small text-muted">
                        {t("backup.restore.removed")}
                      </dt>
                      <dd className="text-small text-primary">{preview.counts.removed}</dd>
                    </div>
                  </dl>
                  {preview.examples.length > 0 && (
                    <ul className="mt-3 space-y-1" aria-label={t("backup.restore.examplesAria")}>
                      {preview.examples.slice(0, 10).map((example) => (
                        <li key={`${example.change}:${example.path}`} className="break-all text-small text-muted">
                          {example.change}: {example.path}
                        </li>
                      ))}
                    </ul>
                  )}
                  {preview.blockers.length > 0 ? (
                    <div className="mt-3" role="alert">
                      <p className="text-small text-status-error">
                        {t("backup.restore.blocked")}
                      </p>
                      <ul className="mt-1 space-y-1">
                        {preview.blockers.map((blocker) => (
                          <li key={blocker} className="break-all text-small text-status-error">
                            {blocker}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button onClick={() => setRestoreStage("confirm")} disabled={busy}>
                        {t("backup.restore.continue")}
                      </Button>
                      <Button variant="secondary" onClick={closeRestore} disabled={busy}>
                        {t("backup.restore.cancel")}
                      </Button>
                    </div>
                  )}
                </div>
              )}

              {restoreStage === "confirm" && (
                <div className="mt-2">
                  <p className="text-small text-primary">
                    {t("backup.restore.confirm", {
                      snapshot: selectedSnapshot ?? "",
                    })}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button onClick={() => void confirmRestore()} disabled={busy}>
                      {t("backup.restore.now")}
                    </Button>
                    <Button variant="secondary" onClick={() => setRestoreStage("preview")} disabled={busy}>
                      {t("backup.restore.back")}
                    </Button>
                  </div>
                </div>
              )}

              {restoreStage === "running" && (
                <div className="mt-2 flex items-center gap-2 text-small text-muted">
                  <Spinner size="sm" />{" "}
                  {t("backup.restore.running", {
                    snapshot: selectedSnapshot ?? "",
                  })}
                </div>
              )}

              {restoreStage === "result" && restoreResult && (
                <div className="mt-2" role="status">
                  <p className="text-small text-status-success">
                    {t("backup.restore.result", {
                      status: restoreResult.status,
                    })}
                  </p>
                  <p className="mt-1 text-small text-muted">
                    {t("backup.restore.resultDetail", {
                      swapped: restoreResult.swapped.length,
                      databases: restoreResult.databases.length,
                      worlds: restoreResult.worlds.length,
                    })}
                  </p>
                  {restoreResult.warnings.length > 0 && (
                    <ul className="mt-2 space-y-1">
                      {restoreResult.warnings.map((warning) => (
                        <li key={warning} className="break-all text-small text-muted">
                          {warning}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
