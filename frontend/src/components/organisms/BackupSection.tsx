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

const PROVIDER_LABELS: Record<string, string> = {
  onedrive: "OneDrive",
  google_drive: "Google Drive",
  icloud: "iCloud Drive",
  unknown: "Sin proveedor detectado",
};

const SOURCE_LABELS: Record<string, string> = {
  env: "detectada por variable de entorno",
  registry: "detectada en el registro del sistema",
  heuristic: "sugerida por proximidad",
  user: "elegida por ti",
};

const CONFIDENCE_LABELS: Record<string, string> = {
  verified: "verificada",
  heuristic: "heurística",
};

const MODE_LABELS: Record<string, string> = {
  mirrored: "Copia local (espejo)",
  streaming: "Ubicación en streaming/virtual",
  unknown: "Modo local sin verificar",
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
export function backupWriteCopy(status: BackupStatus): string | null {
  if (status.copy?.es) return status.copy.es;
  if (!status.last_write) return null;
  return `Escrito en ${status.last_write.destination} — ${status.last_write.written_at} UTC`;
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

function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? "Otro proveedor";
}

function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? "origen desconocido";
}

function confidenceLabel(confidence: string): string {
  return CONFIDENCE_LABELS[confidence] ?? "sin verificar";
}

function modeLabel(mode: string | null): string {
  if (!mode) return "Sin modo detectado";
  return MODE_LABELS[mode] ?? "Modo desconocido";
}

export function BackupSection({ onRequestSignIn }: BackupSectionProps = {}) {
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [candidates, setCandidates] = useState<BackupCandidate[]>([]);
  const [pickerPath, setPickerPath] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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
        setError(errorText(cause, "No se pudo cargar el estado del respaldo"));
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
        setError(errorText(cause, "No se pudo cargar la configuración de respaldo"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [loadStatus, loadRestoreStatus]);

  const chooseFolder = async (path: string) => {
    const chosen = path.trim();
    if (!chosen) return;
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
      if (!next.blocked) setNotice("Carpeta guardada. Ejecutá un respaldo para registrar la primera escritura.");
    } catch (cause) {
      setError(errorText(cause, "No se pudo guardar la carpeta elegida"));
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
      setNotice("Se escribió una copia local en la carpeta elegida.");
    } catch (cause) {
      setError(errorText(cause, "No se pudo ejecutar el respaldo"));
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
      setError(errorText(cause, "No se pudieron listar las copias"));
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
      setError(errorText(cause, "No se pudo previsualizar la restauración"));
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
      setError(errorText(cause, "No se pudo completar la restauración"));
      setRestoreStage("confirm");
    }
  };

  if (loading) {
    return (
      <div className="mt-4 flex items-center gap-2 text-small text-muted">
        <Spinner size="sm" /> Cargando estado del respaldo…
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
          Necesitás iniciar sesión para configurar el respaldo
        </p>
        <p className="mt-1 text-small text-muted">
          La carpeta de respaldo se lee y se escribe con tu sesión local. Iniciá sesión y volvé a
          esta tarjeta para elegir la carpeta y ejecutar la primera copia.
        </p>
        {onRequestSignIn && (
          <Button variant="primary" size="sm" className="mt-3" onClick={onRequestSignIn}>
            Iniciar sesión
          </Button>
        )}
      </div>
    );
  }

  if (!status) {
    return (
      <p className="mt-3 text-small text-status-error" role="alert">
        {error ?? "No se pudo cargar el estado del respaldo"}
      </p>
    );
  }

  const badge = backupCardState(status);
  const badgeVariant = badge === "configured" ? "success" : badge === "error" ? "error" : "default";
  const badgeLabel = badge === "configured" ? "Configurado" : badge === "error" ? "Error" : "Pendiente";
  const hasDestination = status.destination !== null;
  const writeCopy = backupWriteCopy(status);
  const pickerVisible = pickerOpen || !hasDestination;

  return (
    <div className="mt-3" aria-live="polite">
      <div className="flex items-center justify-between gap-3">
        <h4 className="font-heading text-small text-primary">Estado del respaldo</h4>
        <span className="flex items-center gap-2">
          <Badge variant={badgeVariant}>{badgeLabel}</Badge>
          <span className="sr-only">Estado del respaldo: {badgeLabel}</span>
        </span>
      </div>

      {restorePending && (
        <p className="mt-3 rounded-lg border border-status-error/30 bg-status-error/10 p-3 text-small text-status-error" role="alert">
          Una restauración anterior quedó sin resolver. La API permanece en modo mantenimiento hasta
          regularizarla
          {restoreLeftovers.length > 0 ? ` (residuos: ${restoreLeftovers.join(", ")})` : ""}.
        </p>
      )}

      {error && (
        <p className="mt-3 text-small text-status-error" role="alert">
          {error}
        </p>
      )}
      {notice && <p className="mt-3 text-small text-status-success">{notice}</p>}

      {/* State 1 — no folder yet: the picker plus the candidate suggestions. */}
      {!hasDestination && (
        <p className="mt-3 text-small text-muted">
          Aún no elegiste una carpeta. Demiurgos escribe la copia localmente en la carpeta que elijas.
        </p>
      )}

      {/* States 2/3/4 — the chosen folder and its honest mode verdict. */}
      {hasDestination && status.destination && (
        <dl className="mt-3 space-y-2 border-t border-edge pt-3">
          <div>
            <dt className="text-small text-muted">Carpeta</dt>
            <dd className="break-all text-small text-primary" data-testid="backup-destination-path">
              {status.destination.path}
            </dd>
          </div>
          <div>
            <dt className="text-small text-muted">Proveedor</dt>
            <dd className="text-small text-primary">
              {providerLabel(status.destination.provider)}
            </dd>
          </div>
          <div>
            <dt className="text-small text-muted">Origen</dt>
            <dd className="text-small text-primary">
              {sourceLabel(status.destination.source)} · confianza{" "}
              {confidenceLabel(status.destination.confidence)}
            </dd>
          </div>
          <div>
            <dt className="text-small text-muted">Modo</dt>
            <dd className="text-small text-primary">{modeLabel(status.mode)}</dd>
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
            La carpeta elegida es una ubicación en streaming o virtual.
          </p>
          <p className="mt-1 text-small text-muted">
            Los cambios sin sincronizar viven en una caché que puede vaciarse o dañarse, así que
            Demiurgos no escribió nada. Esa carpeta no es una copia confiable.
          </p>
          {status.warning && (
            <p className="mt-2 text-small text-primary" data-testid="backup-warning-remedy">
              Remediación indicada por el servidor: {status.warning}
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
                Todavía no hay una escritura local registrada en esta carpeta.
              </p>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <Button onClick={() => void runNow()} disabled={busy}>
                {busy ? "Ejecutando…" : "Backup ahora"}
              </Button>
              <Button variant="secondary" onClick={() => setPickerOpen((open) => !open)} disabled={busy}>
                Elegir otra carpeta
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
            Elegir carpeta
          </label>
          <div className="flex flex-wrap gap-2">
            <input
              id="backup-destination-path-input"
              className={`${inputClass} sm:max-w-md`}
              value={pickerPath}
              onChange={(event) => setPickerPath(event.target.value)}
              placeholder="/ruta/a/tu/carpeta"
              autoComplete="off"
            />
            <Button type="submit" disabled={busy || !pickerPath.trim()}>
              Usar esta carpeta
            </Button>
          </div>
          <p className="mt-2 text-small text-muted">
            Escribí la ruta absoluta de una carpeta local, o elegí una sugerencia.
          </p>

          {candidates.length > 0 && (
            <ul className="mt-3 space-y-2" aria-label="Carpetas sugeridas">
              {candidates.map((candidate) => (
                <li
                  key={`${candidate.provider}:${candidate.path}`}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-edge bg-surface-raised p-2"
                >
                  <span className="min-w-0">
                    <span className="block break-all text-small text-primary">{candidate.path}</span>
                    <span className="block text-small text-muted">
                      {providerLabel(candidate.provider)} · {sourceLabel(candidate.source)} ·
                      confianza {confidenceLabel(candidate.confidence)}
                    </span>
                  </span>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => void chooseFolder(candidate.path)}
                    disabled={busy}
                  >
                    Usar esta carpeta
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
              Restaurar…
            </Button>
          ) : (
            <div>
              <div className="flex items-center justify-between gap-3">
                <h5 className="font-heading text-small text-primary">Restaurar desde una copia</h5>
                <Button variant="ghost" size="sm" onClick={closeRestore} disabled={busy && restoreStage === "running"}>
                  Cerrar
                </Button>
              </div>

              {restoreStage === "list" && (
                <div className="mt-2">
                  {busy && snapshots.length === 0 ? (
                    <div className="flex items-center gap-2 text-small text-muted">
                      <Spinner size="sm" /> Buscando copias…
                    </div>
                  ) : snapshots.length === 0 ? (
                    <p className="text-small text-muted">No hay copias en la carpeta elegida.</p>
                  ) : (
                    <ul className="space-y-2" aria-label="Copias disponibles">
                      {snapshots.map((snapshot) => (
                        <li
                          key={snapshot.snapshot_id}
                          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-edge bg-surface-raised p-2"
                        >
                          <span>
                            <span className="block text-small text-primary">{snapshot.snapshot_id}</span>
                            <span className="block text-small text-muted">
                              {snapshot.complete ? "Completa" : "Incompleta"} · {snapshot.entries} entradas
                            </span>
                          </span>
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => void previewSnapshot(snapshot.snapshot_id)}
                            disabled={busy}
                          >
                            Previsualizar
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
                    La restauración reemplaza el contenido actual del árbol de datos.
                  </p>
                  <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <div>
                      <dt className="text-small text-muted">Se agregan</dt>
                      <dd className="text-small text-primary">{preview.counts.added}</dd>
                    </div>
                    <div>
                      <dt className="text-small text-muted">Se modifican</dt>
                      <dd className="text-small text-primary">{preview.counts.modified}</dd>
                    </div>
                    <div>
                      <dt className="text-small text-muted">Se quitan</dt>
                      <dd className="text-small text-primary">{preview.counts.removed}</dd>
                    </div>
                  </dl>
                  {preview.examples.length > 0 && (
                    <ul className="mt-3 space-y-1" aria-label="Cambios de ejemplo">
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
                        La restauración está bloqueada:
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
                        Continuar
                      </Button>
                      <Button variant="secondary" onClick={closeRestore} disabled={busy}>
                        Cancelar
                      </Button>
                    </div>
                  )}
                </div>
              )}

              {restoreStage === "confirm" && (
                <div className="mt-2">
                  <p className="text-small text-primary">
                    ¿Confirmás restaurar la copia <strong>{selectedSnapshot}</strong>? Se reemplaza el
                    árbol de datos completo y no se puede deshacer.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button onClick={() => void confirmRestore()} disabled={busy}>
                      Restaurar ahora
                    </Button>
                    <Button variant="secondary" onClick={() => setRestoreStage("preview")} disabled={busy}>
                      Volver
                    </Button>
                  </div>
                </div>
              )}

              {restoreStage === "running" && (
                <div className="mt-2 flex items-center gap-2 text-small text-muted">
                  <Spinner size="sm" /> Restaurando la copia {selectedSnapshot}…
                </div>
              )}

              {restoreStage === "result" && restoreResult && (
                <div className="mt-2" role="status">
                  <p className="text-small text-status-success">
                    Restauración terminada: {restoreResult.status}
                  </p>
                  <p className="mt-1 text-small text-muted">
                    Elementos restaurados: {restoreResult.swapped.length}. Bases de datos:{" "}
                    {restoreResult.databases.length}. Mundos: {restoreResult.worlds.length}.
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
