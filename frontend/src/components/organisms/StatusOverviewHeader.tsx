import { Badge } from "@/components/atoms/Badge";
import { Spinner } from "@/components/atoms/Spinner";
import { backupCardState } from "@/components/organisms/BackupSection";
import { useProfileStatus } from "@/hooks/useProfileStatus";
import type {
  AssistantSettingsStatus,
  AuthSessionStatus,
  BackupStatus,
} from "@/api/types";

type BadgeVariant = "default" | "success" | "error" | "warning" | "info";

interface StatusBadge {
  label: string;
  variant: BadgeVariant;
}

/** Identity summary: session label when authenticated, else the honest state. */
function identityBadge(auth: AuthSessionStatus | null): StatusBadge {
  if (auth === null) return { label: "Sesión no disponible", variant: "default" };
  if (!auth.enabled) return { label: "Autenticación desactivada", variant: "default" };
  if (auth.authenticated) return { label: auth.label ?? "Sesión activa", variant: "success" };
  return { label: "Sin sesión", variant: "default" };
}

/** Backup summary: the honest card state (`backupCardState`), never a claim.
 *  A failed read (null) is told apart from a real `pending` verdict. */
function backupBadge(backup: BackupStatus | null): StatusBadge {
  if (backup === null) return { label: "Respaldo no disponible", variant: "default" };
  const state = backupCardState(backup);
  if (state === "configured") return { label: "Respaldo configurado", variant: "success" };
  if (state === "error") return { label: "Respaldo con error", variant: "error" };
  return { label: "Respaldo pendiente", variant: "default" };
}

/** Assistant summary: key presence plus the runtime state verdict. */
function assistantBadge(assistant: AssistantSettingsStatus | null): StatusBadge {
  if (assistant === null) return { label: "Asistente no disponible", variant: "default" };
  if (!assistant.key_configured) return { label: "Asistente no configurado", variant: "default" };
  if (assistant.runtime_state === "active") return { label: "Asistente activo", variant: "success" };
  if (assistant.runtime_state === "pending-reload") {
    return { label: "Asistente sin verificar", variant: "warning" };
  }
  return { label: "Asistente guardado, no activo", variant: "default" };
}

/**
 * Perfil status overview header (REQ-PIA-05). Renders above the section rail
 * and stays visible on every section: identity (session status), backup
 * (honest local-write card state) and assistant (Hermes configuration) in one
 * compact strip. All three sources are existing endpoints (CON-PIA-01); each
 * fails open, so an unavailable source shows a neutral badge instead of
 * taking the header down.
 */
export function StatusOverviewHeader() {
  const { auth, backup, assistant, isLoading } = useProfileStatus();

  if (isLoading) {
    return (
      <div
        aria-label="Estado del perfil"
        className="mt-6 flex items-center gap-2 text-small text-muted"
        role="status"
      >
        <Spinner size="sm" /> Consultando estado…
      </div>
    );
  }

  const identity = identityBadge(auth);
  const backupStatus = backupBadge(backup);
  const assistantStatus = assistantBadge(assistant);

  return (
    <div
      aria-label="Estado del perfil"
      className="mt-6 grid gap-4 rounded-lg border border-edge bg-surface-raised p-4 sm:grid-cols-3"
    >
      <div className="min-w-0">
        <p className="text-small text-muted">Identidad</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Badge variant={identity.variant}>{identity.label}</Badge>
        </div>
      </div>

      <div className="min-w-0">
        <p className="text-small text-muted">Respaldo</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Badge variant={backupStatus.variant}>{backupStatus.label}</Badge>
        </div>
      </div>

      <div className="min-w-0">
        <p className="text-small text-muted">Asistente</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Badge variant={assistantStatus.variant}>{assistantStatus.label}</Badge>
        </div>
      </div>
    </div>
  );
}