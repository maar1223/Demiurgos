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
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { MessageKey, TFunction } from "@/i18n/messages";

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
  const { t } = useAppLanguage();
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
      setError(errorText(cause, t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-edge bg-surface-raised p-4">
      <h3 className="font-heading text-body text-primary">
        {t("migration.title")}
      </h3>
      <p className="mt-1 text-small text-muted">{t("migration.intro")}</p>

      {outcome && (
        <div
          role="status"
          aria-live="polite"
          className={
            outcome.status === "completed"
              ? "mt-3 rounded-lg border border-status-success/30 bg-status-success/10 px-3 py-2 text-small text-status-success"
              : "mt-3 rounded-lg border border-action/30 bg-action/10 px-3 py-2 text-small text-action"
          }
        >
          {outcome.status === "completed"
            ? t("migration.completed", {
                world: outcome.world,
                tx: outcome.transaction_id,
              })
            : [
                t("migration.rolledBackBase", { world: outcome.world }),
                outcome.restore_verified ? t("migration.rolledBackRestored") : "",
                outcome.error ? t("migration.rolledBackReason", { error: outcome.error }) : "",
                t("migration.rolledBackTail", { tx: outcome.transaction_id }),
              ].join("")}
        </div>
      )}

      {error && !confirmTarget && (
        <p role="alert" className="mt-3 text-small text-status-error">
          {error}
        </p>
      )}

      <ul className="mt-4 space-y-3">
        {findings.map((finding) => (
          <li
            key={finding.world}
            className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-edge bg-surface-raised px-3 py-2"
          >
            <span className="flex flex-wrap items-center gap-2 text-small">
              <strong className="text-primary">{finding.world}</strong>
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
              {t("migration.migrateFolders", { world: finding.world })}
            </Button>
          </li>
        ))}
      </ul>

      {confirmTarget && (
        <ConfirmDialog
          title={t("migration.confirmTitle")}
          message={t("migration.confirmMessage", {
            folders: confirmTarget.folders.join(", "),
            world: confirmTarget.world,
          })}
          confirmLabel={t("migration.confirmLabel")}
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
 *  are the stable remediation keys (ApiError.code); an expired/missing
 *  session maps to 401. Never surfaces raw paths or evidence internals. */
function errorText(cause: unknown, t: TFunction): string {
  if (cause instanceof ApiError) {
    if (cause.status === 401) {
      return t("common.sessionExpired");
    }
    if (cause.code && ERROR_GUIDANCE[cause.code]) {
      return t(ERROR_GUIDANCE[cause.code]);
    }
  }
  return cause instanceof Error
    ? cause.message
    : t("migration.errorFallback");
}

const ERROR_GUIDANCE: Record<string, MessageKey> = {
  empty_approval: "migration.guidance.emptyApproval",
  unknown_folder: "migration.guidance.unknownFolder",
  invalid_world: "migration.guidance.invalidWorld",
  collision: "migration.guidance.collision",
  symlink_escape: "migration.guidance.symlinkEscape",
  io_error: "migration.guidance.ioError",
};
