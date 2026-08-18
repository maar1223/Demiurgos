import { useState } from "react";
import { executeMigration } from "@/api/migration";
import {
  ApiError,
  type LegacyFinding,
  type MigrationExecuteResult,
} from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";

/**
 * ONB-4.3 (WU-4c2) — Legacy migration approval panel.
 *
 * Renders the worlds detected with uppercase legacy folders (ONB-4.2) and
 * lets the Author approve a migration explicitly. Safety rules:
 *
 * - NEVER automatic: mounting the panel or refreshing readiness never calls
 *   the API; a migration runs only after the ConfirmDialog's explicit
 *   "Migrar" action (the backend also requires the explicit approval payload
 *   and a local session, failing closed with 401).
 * - Honest outcomes: `completed` (canonical lowercase tree + transaction id)
 *   and `rolled_back` (originals restored + evidence) are rendered exactly as
 *   the server reported them; server error codes map to retryable guidance.
 * - No path/hash leak: the evidence record contains absolute filesystem
 *   paths and sha256 digests, but the UI renders only folder names and the
 *   transaction id — never raw paths or hashes.
 * - Readiness refresh: after a completed migration `onMigrated` fires so the
 *   Configuration Center re-reads the canonical tree and the legacy notice
 *   disappears. A rolled-back migration moved nothing, so no refresh runs.
 */
export function MigrationPanel({
  findings,
  onMigrated,
}: {
  findings: LegacyFinding[];
  onMigrated?: () => void;
}) {
  const [confirmTarget, setConfirmTarget] = useState<{
    world: string;
    folders: string[];
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<MigrationExecuteResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (findings.length === 0) {
    return null;
  }

  const run = async () => {
    if (!confirmTarget || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await executeMigration(
        confirmTarget.world,
        confirmTarget.folders,
      );
      setOutcome(result);
      setConfirmTarget(null);
      if (result.status === "completed") onMigrated?.();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-filio bg-madero p-4">
      <h3 className="font-heading text-body text-pergamino">
        Migración de carpetas legacy
      </h3>
      <p className="mt-1 text-small text-tinta-desvaida">
        Las carpetas con mayúsculas no son reconocidas como contenido canónico
        porque las rutas distinguen mayúsculas y minúsculas. La migración es
        opcional y explícita: mueve solo las carpetas aprobadas, verifica su
        contenido y registra evidencia de la transacción. Nunca se ejecuta de
        forma automática.
      </p>

      {outcome && (
        <div
          role="status"
          aria-live="polite"
          className={
            outcome.status === "completed"
              ? "mt-3 rounded-lg border border-musgo/30 bg-musgo/10 px-3 py-2 text-small text-musgo"
              : "mt-3 rounded-lg border border-llamita/30 bg-llamita/10 px-3 py-2 text-small text-llamita"
          }
        >
          {outcome.status === "completed" ? (
            <>
              Migración completada: las carpetas de {outcome.world} ya usan el
              árbol canónico en minúsculas. Transacción {outcome.transaction_id}.
            </>
          ) : (
            <>
              La migración de {outcome.world} se revirtió automáticamente
              {outcome.restore_verified
                ? " y los archivos originales fueron restaurados"
                : ""}
              {outcome.error ? `. Motivo: ${outcome.error}` : ""}. Transacción{" "}
              {outcome.transaction_id}.
            </>
          )}
        </div>
      )}

      {error && !confirmTarget && (
        <p role="alert" className="mt-3 text-small text-sangre">
          {error}
        </p>
      )}

      <ul className="mt-4 space-y-3">
        {findings.map((finding) => (
          <li
            key={finding.world}
            className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-filio bg-piedra px-3 py-2"
          >
            <span className="flex flex-wrap items-center gap-2 text-small">
              <strong className="text-pergamino">{finding.world}</strong>
              {finding.folders.map((folder) => (
                <Badge key={folder} variant="warning">
                  {folder}
                </Badge>
              ))}
            </span>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setError(null);
                setOutcome(null);
                setConfirmTarget({
                  world: finding.world,
                  folders: finding.folders,
                });
              }}
            >
              Migrar carpetas de {finding.world}
            </Button>
          </li>
        ))}
      </ul>

      {confirmTarget && (
        <ConfirmDialog
          title="Migrar carpetas legacy"
          message={`¿Migrar las carpetas ${confirmTarget.folders.join(", ")} del mundo ${confirmTarget.world}? Solo las carpetas aprobadas se mueven a su forma canónica en minúsculas; el contenido se verifica y se registra evidencia de la transacción. Esta acción modifica el árbol del mundo.`}
          confirmLabel="Migrar"
          isBusy={busy}
          error={error}
          onConfirm={() => void run()}
          onClose={() => {
            if (!busy) {
              setConfirmTarget(null);
              setError(null);
            }
          }}
        />
      )}
    </div>
  );
}

/** Map a migration failure to honest, retryable guidance. Server error codes
 *  are the stable remediation keys (ApiError.code); a missing local session
 *  maps to 401. Never surfaces raw paths or evidence internals. */
function errorText(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.status === 401) {
      return "La sesión local terminó. Iniciala desde el Perfil e intentá de nuevo.";
    }
    if (cause.code && ERROR_GUIDANCE[cause.code]) {
      return ERROR_GUIDANCE[cause.code];
    }
  }
  return cause instanceof Error ? cause.message : "No se pudo migrar las carpetas legacy";
}

const ERROR_GUIDANCE: Record<string, string> = {
  empty_approval: "No se aprobó ninguna carpeta para migrar.",
  unknown_folder: "Una carpeta aprobada no forma parte del layout legacy detectado.",
  invalid_world: "El mundo no existe o ya no tiene carpetas legacy detectadas.",
  collision: "El destino ya está ocupado por otra carpeta. No se movió nada.",
  symlink_escape: "Una carpeta aprobada es un enlace simbólico fuera del mundo. No se movió nada.",
  io_error: "Ocurrió un error al escribir los archivos. La migración no se completó.",
};
