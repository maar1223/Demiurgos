import { Badge } from "@/components/atoms/Badge";
import { Spinner } from "@/components/atoms/Spinner";
import { backupCardState } from "@/components/organisms/BackupSection";
import { useProfileStatus } from "@/hooks/useProfileStatus";
import type {
  AssistantSettingsStatus,
  AuthSessionStatus,
  BackupStatus,
} from "@/api/types";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { MessageKey } from "@/i18n/messages";

type BadgeVariant = "default" | "success" | "error" | "warning" | "info";

interface StatusBadge {
  labelKey: MessageKey;
  /** Optional server-provided label that overrides the catalogue copy. */
  label?: string;
  variant: BadgeVariant;
}

/** Identity summary: session label when authenticated, else the honest state. */
function identityBadge(auth: AuthSessionStatus | null): StatusBadge {
  if (auth === null)
    return { labelKey: "profileStatus.sessionUnavailable", variant: "default" };
  if (!auth.enabled)
    return { labelKey: "profileStatus.authDisabled", variant: "default" };
  if (auth.authenticated)
    return {
      labelKey: "profileStatus.sessionActive",
      label: auth.label ?? undefined,
      variant: "success",
    };
  return { labelKey: "profileStatus.noSession", variant: "default" };
}

/** Backup summary: the honest card state (`backupCardState`), never a claim.
 *  A failed read (null) is told apart from a real `pending` verdict. */
function backupBadge(backup: BackupStatus | null): StatusBadge {
  if (backup === null)
    return { labelKey: "profileStatus.backupUnavailable", variant: "default" };
  const state = backupCardState(backup);
  if (state === "configured")
    return { labelKey: "profileStatus.backupConfigured", variant: "success" };
  if (state === "error")
    return { labelKey: "profileStatus.backupError", variant: "error" };
  return { labelKey: "profileStatus.backupPending", variant: "default" };
}

/** Assistant summary: key presence plus the runtime state verdict. */
function assistantBadge(assistant: AssistantSettingsStatus | null): StatusBadge {
  if (assistant === null)
    return { labelKey: "profileStatus.assistantUnavailable", variant: "default" };
  if (!assistant.key_configured)
    return { labelKey: "profileStatus.assistantUnconfigured", variant: "default" };
  if (assistant.runtime_state === "active")
    return { labelKey: "profileStatus.assistantActive", variant: "success" };
  if (assistant.runtime_state === "pending-reload") {
    return { labelKey: "profileStatus.assistantUnverified", variant: "warning" };
  }
  return { labelKey: "profileStatus.assistantSavedInactive", variant: "default" };
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
  const { t } = useAppLanguage();
  const { auth, backup, assistant, isLoading } = useProfileStatus();

  if (isLoading) {
    return (
      <div
        aria-label={t("profileStatus.aria")}
        className="mt-6 flex items-center gap-2 text-small text-muted"
        role="status"
      >
        <Spinner size="sm" /> {t("profileStatus.checking")}
      </div>
    );
  }

  const identity = identityBadge(auth);
  const backupStatus = backupBadge(backup);
  const assistantStatus = assistantBadge(assistant);

  return (
    <div
      aria-label={t("profileStatus.aria")}
      className="mt-6 grid gap-4 rounded-lg border border-edge bg-surface-raised p-4 sm:grid-cols-3"
    >
      <div className="min-w-0">
        <p className="text-small text-muted">{t("profileStatus.identity")}</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Badge variant={identity.variant}>
            {identity.label ?? t(identity.labelKey)}
          </Badge>
        </div>
      </div>

      <div className="min-w-0">
        <p className="text-small text-muted">{t("profileStatus.backup")}</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Badge variant={backupStatus.variant}>
            {t(backupStatus.labelKey)}
          </Badge>
        </div>
      </div>

      <div className="min-w-0">
        <p className="text-small text-muted">{t("profileStatus.assistant")}</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Badge variant={assistantStatus.variant}>
            {t(assistantStatus.labelKey)}
          </Badge>
        </div>
      </div>
    </div>
  );
}