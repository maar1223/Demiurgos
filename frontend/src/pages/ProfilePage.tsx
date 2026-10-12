import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon, type IconName } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { LocaleForm } from "@/components/organisms/LocaleForm";
import { IdeaCapturePanel } from "@/components/organisms/IdeaCapturePanel";
import { AssistantSettingsPanel } from "@/components/organisms/AssistantSettingsPanel";
import { BackupSection } from "@/components/organisms/BackupSection";
import { ProfileSectionRail } from "@/components/organisms/ProfileSectionRail";
import { ReportSection } from "@/components/organisms/ReportSection";
import { StatusOverviewHeader } from "@/components/organisms/StatusOverviewHeader";
import { UpdateSection } from "@/components/organisms/UpdateSection";
import { DeleteWorldModal } from "@/components/organisms/DeleteWorldModal";
import { WorldPickerDialog } from "@/components/organisms/WorldPickerDialog";
import { CreateWorldModal } from "@/components/organisms/CreateWorldModal";
import { WorldNameDialog } from "@/components/organisms/WorldNameDialog";
import { renameWorld } from "@/api/worlds";
import { clearCurrentWorld, getCurrentWorld, setCurrentWorld } from "@/lib/currentWorld";
import { WorldTrashPanel } from "@/components/organisms/WorldTrashPanel";
import { SecretInput } from "@/components/molecules/SecretInput";
import {
  ConnectionsPanel,
  type ConnectionStatusSummary,
} from "@/components/molecules/ConnectionsPanel";
import { getIdeaCaptureStatus } from "@/api/ideaCapture";
import { getReadiness } from "@/api/onboarding";
import {
  changePassword,
  changeUsername,
  disableVault,
  enableVault,
  getAuthStatus,
  getVaultConfig,
  removePassword,
  rotateWords,
  setReauthInterval,
} from "@/api/wiki";
import { useWorlds } from "@/hooks/useWorlds";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";
import { useRecoveryWordsUnlock } from "@/hooks/useRecoveryWordsUnlock";
import { useAuthSession } from "@/hooks/useAuthSession";
import type {
  ApiError,
  AuthSessionStatus,
  ReadinessSnapshot,
  VaultConfig,
  WorldInfo,
} from "@/api/types";
import {
  MigrationPanel,
  STATE_META,
  cardLabel,
  cardState,
} from "@/pages/ConfigurationCenter";
import { cn, getErrorMessage } from "@/lib/utils";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { MessageKey } from "@/i18n/messages";

type ProfileSection =
  | "cuenta"
  | "respaldo"
  | "preferencias"
  | "conexiones"
  | "mundos"
  | "actualizaciones"
  | "reporte";

/** The intent-based sections (REQ-PIA-01) with rail label and icon
 *  (REQ-PIA-06). `cuenta` is the default landing section. */
const PROFILE_SECTIONS: { id: ProfileSection; labelKey: MessageKey; icon: IconName }[] = [
  { id: "cuenta", labelKey: "profile.section.cuenta", icon: "avatar" },
  { id: "respaldo", labelKey: "profile.section.respaldo", icon: "save" },
  { id: "preferencias", labelKey: "profile.section.preferencias", icon: "monitor" },
  { id: "conexiones", labelKey: "profile.section.conexiones", icon: "lightbulb" },
  { id: "mundos", labelKey: "profile.section.mundos", icon: "world" },
  { id: "actualizaciones", labelKey: "profile.section.actualizaciones", icon: "download" },
  { id: "reporte", labelKey: "profile.section.reporte", icon: "error" },
];

function isProfileSection(value: string | null): value is ProfileSection {
  return PROFILE_SECTIONS.some((section) => section.id === value);
}

/**
 * Perfil → Cuenta — the single account/security surface (REQ-PIA-09). Vault ON
 * and vault OFF are two states of the same section: a compact status card is
 * always present, and below it the vault renders either the credentials
 * management disclosures (ON) or the activation flow (OFF).
 *
 * Management lives behind collapsed disclosures because this is a
 * rarely-visited Operate surface: "Gestionar credenciales" shows one segmented
 * form at a time and a danger-treated "Zona peligrosa" holds the destructive
 * actions. Logout and the local-dev session start both live in the Navbar and
 * are intentionally not duplicated here (approved REQ-PIA-09 deviation).
 *
 * The recovery-words unlock (REQ-SRW-01..04) is session-scoped: the first
 * successful words-gated action arms the verified words and later actions
 * replay them without re-prompting. The words live in page-level memory only
 * (never localStorage/sessionStorage/cookies) and are cleared on unmount; a
 * logout reloads the page, so they are cleared trivially.
 */

/** The four credentials panels — exactly one visible at a time. */
type CredentialPanel = "usuario" | "password" | "words" | "reauth";

const CREDENTIAL_PANELS: { id: CredentialPanel; labelKey: MessageKey }[] = [
  { id: "usuario", labelKey: "profile.cuenta.panel.username" },
  { id: "password", labelKey: "profile.cuenta.panel.password" },
  { id: "words", labelKey: "profile.cuenta.panel.words" },
  { id: "reauth", labelKey: "profile.cuenta.panel.reauth" },
];

const CREDENTIALS_REGION_ID = "cuenta-credentials-region";
const SENSITIVE_REGION_ID = "cuenta-sensitive-region";
function CuentaSection({
  unlockedWords,
  onUnlocked,
}: {
  unlockedWords: string | null;
  onUnlocked: (words: string) => void;
}) {
  const { t } = useAppLanguage();
  const localDev = useLocalDevAuth(true);
  const [vaultStatus, setVaultStatus] = useState<AuthSessionStatus | null>(null);
  const [config, setConfig] = useState<VaultConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  // Disclosures start collapsed: this is a rarely-visited Operate surface, so
  // its first read is a compact status summary instead of the former stack of
  // forms.
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const [sensitiveOpen, setSensitiveOpen] = useState(false);
  const [credentialPanel, setCredentialPanel] =
    useState<CredentialPanel>("usuario");

  // Unified status decides the session-card branch (credentials vs local-dev);
  // on failure the card degrades to the local-dev view — a low-stakes read,
  // never a wall.
  useEffect(() => {
    let active = true;
    void getAuthStatus()
      .then((next) => {
        if (active) setVaultStatus(next);
      })
      .catch(() => {
        if (active) setVaultStatus(null);
      });
    return () => {
      active = false;
    };
  }, []);

  const load = () => {
    setError(null);
    void getVaultConfig()
      .then(setConfig)
      .catch((cause: unknown) => setError(cause))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const daysUntilReauth =
    vaultStatus?.authenticated && typeof vaultStatus.days_until_reauth === "number"
      ? vaultStatus.days_until_reauth
      : null;

  // The status chip reflects whichever session source is authoritative: the
  // credentials session when the vault is active, the loopback session
  // otherwise. `enabled`/`authenticated` from GET /api/auth/session/status are
  // false in local-dev mode, so the loopback hook supplies that state.
  const sessionActive =
    vaultStatus?.mode === "credentials"
      ? Boolean(vaultStatus.authenticated)
      : Boolean(localDev.status?.authenticated);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-small text-muted">
        <Spinner size="sm" /> {t("profile.cuenta.checkingVault")}
      </div>
    );
  }

  if (!!error && !config) {
    return (
      <ErrorBanner message={t("profile.cuenta.loadError")} onRetry={load} />
    );
  }

  if (!config) return null;

  return (
    <div className="space-y-4">
      {/* One status card (absorbs the former Sesión card): the account, the
          session words lock and the re-auth countdown as compact rows. */}
      <section className="rounded-lg border border-edge bg-surface-raised p-4">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-heading text-body text-primary">{t("profile.cuenta.session")}</h3>
          <Badge variant={sessionActive ? "success" : "default"}>
            {sessionActive ? t("profile.cuenta.sessionActive") : t("profile.cuenta.sessionOff")}
          </Badge>
        </div>

        {vaultStatus?.mode === "credentials" ? (
          vaultStatus.authenticated ? (
            <dl className="mt-2 text-small">
              <div className="flex items-baseline justify-between gap-3 border-t border-edge py-2">
                <dt className="text-muted">{t("profile.cuenta.account")}</dt>
                <dd className="text-right">
                  <span className="block text-primary">
                    {config.username ?? "—"}
                  </span>
                  <span className="block text-muted">
                    {config.has_password ? t("profile.cuenta.passwordSet") : t("profile.cuenta.noPassword")}
                  </span>
                  {config.env_override && (
                    <span className="block text-muted">
                      {t("profile.cuenta.forcedBy")}{" "}
                      <code className="text-icon-muted">DEMIURGOS_AUTH_MODE</code>
                    </span>
                  )}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 border-t border-edge py-2">
                <dt className="text-muted">{t("profile.cuenta.recoveryWords")}</dt>
                <dd>
                  <Badge variant={unlockedWords !== null ? "success" : "default"}>
                    {unlockedWords !== null
                      ? t("profile.cuenta.wordsUnlocked")
                      : t("profile.cuenta.wordsLocked")}
                  </Badge>
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-3 border-t border-edge py-2">
                <dt className="text-muted">{t("profile.cuenta.reauth")}</dt>
                <dd className="text-primary">
                  {daysUntilReauth !== null
                    ? daysUntilReauth <= 0
                      ? t("profile.cuenta.today")
                      : daysUntilReauth === 1
                        ? t("profile.cuenta.inDaysOne")
                        : t("profile.cuenta.inDaysMany", { days: daysUntilReauth })
                    : "—"}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="mt-3 text-small text-muted">
              {t("profile.cuenta.noActiveSession")}
            </p>
          )
        ) : localDev.isLoading ? (
          <div className="flex items-center gap-2 py-6 text-small text-muted">
            <Spinner size="sm" /> {t("profile.cuenta.localChecking")}
          </div>
        ) : localDev.error ? (
          <p className="text-small text-status-error">{localDev.error.message}</p>
        ) : !localDev.status ? null : localDev.status.authenticated ? (
          <dl className="mt-2 text-small">
            <div className="flex items-baseline justify-between gap-3 border-t border-edge py-2">
              <dt className="text-muted">{t("profile.cuenta.account")}</dt>
              <dd className="text-right text-primary">
                {localDev.status.label ?? t("profile.cuenta.localSession")}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3 border-t border-edge py-2">
              <dt className="text-muted">{t("profile.cuenta.keywords")}</dt>
              <dd>
                <Badge variant={unlockedWords !== null ? "success" : "default"}>
                  {unlockedWords !== null
                    ? t("profile.cuenta.wordsUnlocked")
                    : t("profile.cuenta.wordsLocked")}
                </Badge>
              </dd>
            </div>
          </dl>
        ) : localDev.status.enabled ? (
          <p className="mt-3 text-small text-muted">
            {t("profile.cuenta.localNotStarted")}
          </p>
        ) : (
          <p className="mt-3 text-small text-muted">
            {t("profile.cuenta.localDisabled")}
          </p>
        )}
      </section>

      {config.enabled ? (
        <>
          <section className="rounded-lg border border-edge bg-surface-raised">
            <h3>
              <button
                type="button"
                aria-expanded={credentialsOpen}
                aria-controls={CREDENTIALS_REGION_ID}
                onClick={() => setCredentialsOpen((open) => !open)}
                className="flex w-full items-center justify-between gap-3 p-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-icon-muted/50"
              >
                <span className="font-heading text-body text-primary">
                  {t("profile.cuenta.manageCredentials")}
                </span>
                <Icon
                  name={credentialsOpen ? "chevron-down" : "chevron-right"}
                  size={16}
                  className="text-icon-muted"
                />
              </button>
            </h3>
            <div
              id={CREDENTIALS_REGION_ID}
              hidden={!credentialsOpen}
              className="px-4 pb-4"
            >
              <p className="text-small text-muted">
                {t("profile.cuenta.credentialsIntro")}
              </p>

              <div
                role="group"
                aria-label={t("profile.cuenta.credentialsAria")}
                className="mt-3 flex flex-wrap gap-2"
              >
                {CREDENTIAL_PANELS.map((panel) => {
                  const active = credentialPanel === panel.id;
                  return (
                    <button
                      key={panel.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => setCredentialPanel(panel.id)}
                      className={cn(
                        "rounded-full border px-3 py-1 text-small transition-colors",
                        active
                          ? "border-icon-muted bg-surface-hover text-primary"
                          : "border-edge text-muted hover:text-primary",
                      )}
                    >
                      {t(panel.labelKey)}
                    </button>
                  );
                })}
              </div>

              <div className="mt-4">
                {credentialPanel === "usuario" && (
                  <WordsForm
                    title={t("profile.words.changeUsername.title")}
                    description={t("profile.words.changeUsername.desc")}
                    extraLabel={t("profile.words.changeUsername.extraLabel")}
                    extraPlaceholder={t("profile.words.changeUsername.extraPlaceholder")}
                    submitLabel={t("profile.words.changeUsername.submit")}
                    busyLabel={t("profile.words.busy")}
                    unlockedWords={unlockedWords}
                    onSubmit={async (words, newUsername) => {
                      await changeUsername(words, newUsername);
                      onUnlocked(words);
                      load();
                    }}
                  />
                )}

                {credentialPanel === "password" && (
                  <WordsForm
                    title={t("profile.words.changePassword.title")}
                    description={t("profile.words.changePassword.desc")}
                    extraLabel={t("profile.words.changePassword.extraLabel")}
                    extraType="password"
                    extraPlaceholder={t("profile.words.changePassword.extraPlaceholder")}
                    extraRequired
                    submitLabel={t("profile.words.changePassword.submit")}
                    busyLabel={t("profile.words.busy")}
                    unlockedWords={unlockedWords}
                    onSubmit={async (words, newPassword) => {
                      await changePassword(words, newPassword);
                      onUnlocked(words);
                      load();
                    }}
                  />
                )}

                {credentialPanel === "words" && (
                  <RotateWordsCard
                    unlockedWords={unlockedWords}
                    onUnlocked={onUnlocked}
                  />
                )}

                {credentialPanel === "reauth" && (
                  <>
                    <ReauthIntervalForm config={config} onSaved={load} />
                    {daysUntilReauth !== null && (
                      <p className="mt-3 text-small text-muted">
                        {daysUntilReauth <= 0
                          ? t("profile.reauth.recommendedToday")
                          : daysUntilReauth === 1
                            ? t("profile.reauth.recommendedInDaysOne")
                            : t("profile.reauth.recommendedInDaysMany", { days: daysUntilReauth })}{" "}
                        {t("profile.reauth.warning")}
                      </p>
                    )}
                  </>
                )}
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-status-error/30 bg-status-error/10 p-4">
            <h3>
              <button
                type="button"
                aria-expanded={sensitiveOpen}
                aria-controls={SENSITIVE_REGION_ID}
                onClick={() => setSensitiveOpen((open) => !open)}
                className="flex w-full items-center justify-between gap-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-status-error/50"
              >
                <span className="font-heading text-body text-status-error">
                  {t("profile.cuenta.dangerZone")}
                </span>
                <Icon
                  name={sensitiveOpen ? "chevron-down" : "chevron-right"}
                  size={16}
                  className="text-status-error"
                />
              </button>
            </h3>
            <div
              id={SENSITIVE_REGION_ID}
              hidden={!sensitiveOpen}
              className="mt-4 space-y-4"
            >
              <p className="text-small text-muted">
                {t("profile.cuenta.dangerIntro")}
              </p>
              <WordsForm
                title={t("profile.words.removePassword.title")}
                description={t("profile.words.removePassword.desc")}
                submitLabel={t("profile.words.removePassword.submit")}
                busyLabel={t("profile.words.removing")}
                confirmLabel={t("profile.words.removePassword.confirm")}
                destructive
                unlockedWords={unlockedWords}
                onSubmit={async (words) => {
                  await removePassword(words);
                  onUnlocked(words);
                  load();
                }}
              />
              <WordsForm
                title={t("profile.words.disableVault.title")}
                description={t("profile.words.disableVault.desc")}
                submitLabel={t("profile.words.disableVault.submit")}
                busyLabel={t("profile.words.disabling")}
                confirmLabel={t("profile.words.disableVault.confirm")}
                destructive
                unlockedWords={unlockedWords}
                onSubmit={async (words) => {
                  await disableVault(words);
                  onUnlocked(words);
                  load();
                }}
              />
            </div>
          </section>
        </>
      ) : (
        <ActivationPanel
          config={config}
          onActivated={load}
          onVerified={onUnlocked}
        />
      )}
    </div>
  );
}

interface WordsFormProps {
  title: string;
  description: string;
  extraLabel?: string;
  extraType?: string;
  extraPlaceholder?: string;
  /** Require a non-empty extra value (e.g. the new password). */
  extraRequired?: boolean;
  submitLabel: string;
  busyLabel: string;
  /** Two-click confirm for destructive actions (e.g. password removal). */
  confirmLabel?: string;
  /** Render the submit/confirm button with the danger treatment (REQ-PIA-08).
   *  Destructive actions (password removal, vault deactivation) opt in. */
  destructive?: boolean;
  /** Session-unlocked words (REQ-SRW-01): when present the words input is
   *  hidden and these cached words replay on submit without re-prompting. */
  unlockedWords?: string | null;
  onSubmit: (words: string, extra: string) => Promise<void>;
}

/**
 * A words-gated credential action (R-AC-05): recovery words + optional extra
 * value (new username/password). The words are the ownership proof; every
 * action shows its own inline busy/error/success state. When the session has
 * unlocked words (REQ-SRW-01) the input is hidden and the cached words replay.
 */
function WordsForm({
  title,
  description,
  extraLabel,
  extraType = "text",
  extraPlaceholder,
  extraRequired = false,
  submitLabel,
  busyLabel,
  confirmLabel,
  destructive = false,
  unlockedWords,
  onSubmit,
}: WordsFormProps) {
  const { t } = useAppLanguage();
  const [words, setWords] = useState("");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [confirming, setConfirming] = useState(false);

  // While the session unlock is armed the cached words replay; otherwise the
  // user types them (the words input is only rendered in that state).
  const effectiveWords = unlockedWords ?? words;

  const handleSubmit = async () => {
    if (extraRequired && extra.trim() === "") {
      setError(t("profile.words.requiredError", { field: extraLabel?.toLowerCase() ?? t("profile.words.required") }));
      return;
    }
    if (confirmLabel && !confirming) {
      setConfirming(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit(effectiveWords.trim(), extra.trim());
      setDone(true);
      setWords("");
      setExtra("");
      setConfirming(false);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : t("profile.words.actionError"),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-edge bg-surface/50 p-3">
      <h4 className="font-heading text-body text-primary">{title}</h4>
      <p className="mt-1 text-small text-muted">{description}</p>

      {unlockedWords ? (
        <p className="mt-3 text-small text-muted">
          {t("profile.words.verifiedHint")}
        </p>
      ) : (
        <>
          <label htmlFor={`${title}-words`} className="sr-only">
            {t("profile.words.inputLabel", { title })}
          </label>
          <input
            id={`${title}-words`}
            type="text"
            autoComplete="off"
            placeholder={t("profile.words.inputPlaceholder")}
            value={words}
            onChange={(event) => {
              setWords(event.target.value);
              setError(null);
              setConfirming(false);
            }}
            disabled={busy}
            className="mt-3 w-full rounded-lg border border-edge bg-surface-raised px-3 py-2 text-body text-primary placeholder:text-muted focus:border-icon-muted focus:outline-none disabled:opacity-50"
          />
        </>
      )}

      {extraLabel &&
        (extraType === "password" ? (
          <div className="mt-3 block">
            <label
              htmlFor={`${title}-extra`}
              className="block text-small text-primary"
            >
              {extraLabel}
            </label>
            <div className="mt-1">
              <SecretInput
                id={`${title}-extra`}
                autoComplete="off"
                placeholder={extraPlaceholder}
                value={extra}
                onChange={(event) => {
                  setExtra(event.target.value);
                  setError(null);
                }}
                disabled={busy}
                className="rounded-lg border border-edge bg-surface-raised px-3 py-2 text-body text-primary placeholder:text-muted focus:border-icon-muted focus:outline-none disabled:opacity-50"
              />
            </div>
          </div>
        ) : (
          <label
            htmlFor={`${title}-extra`}
            className="mt-3 block text-small text-primary"
          >
            {extraLabel}
            <input
              id={`${title}-extra`}
              type={extraType}
              autoComplete="off"
              placeholder={extraPlaceholder}
              value={extra}
              onChange={(event) => {
                setExtra(event.target.value);
                setError(null);
              }}
              disabled={busy}
              className="mt-1 w-full rounded-lg border border-edge bg-surface-raised px-3 py-2 text-body text-primary placeholder:text-muted focus:border-icon-muted focus:outline-none disabled:opacity-50"
            />
          </label>
        ))}

      <Button
        variant={destructive ? "danger" : "secondary"}
        size="sm"
        onClick={() => void handleSubmit()}
        disabled={busy || (unlockedWords ? false : words.trim() === "")}
        className="mt-3"
      >
        {busy
          ? busyLabel
          : confirming && confirmLabel
            ? confirmLabel
            : submitLabel}
      </Button>

      {error && (
        <p className="mt-2 text-small text-status-error" role="alert">
          {error}
        </p>
      )}
      {done && (
        <p className="mt-2 text-small text-status-success" role="status">
          {t("profile.words.done")}
        </p>
      )}
    </div>
  );
}

/** Rotate the recovery words (R-ERK-01, amended): the CURRENT words are the
 *  ownership proof, so the card is words-gated like the sibling tabs. The new
 *  plaintext words are shown exactly once; the previous words are invalidated
 *  server-side. On success the verified words arm the session unlock
 *  (REQ-SRW-01) and are never persisted (REQ-SRW-02). */
function RotateWordsCard({
  unlockedWords,
  onUnlocked,
}: {
  unlockedWords: string | null;
  onUnlocked: (words: string) => void;
}) {
  const { t } = useAppLanguage();
  const [newWords, setNewWords] = useState<string | null>(null);

  return (
    <div className="rounded-lg border border-edge bg-surface/50 p-3">
      <WordsForm
        title={t("profile.words.rotate.title")}
        description={t("profile.words.rotate.desc")}
        submitLabel={t("profile.words.rotate.submit")}
        busyLabel={t("profile.words.rotating")}
        unlockedWords={unlockedWords}
        onSubmit={async (words) => {
          const { new_words } = await rotateWords(words);
          // Rotation invalidates the words just submitted, so the session
          // unlock must arm with the NEW ownership key: replaying the old
          // words would make the next words-gated action fail (REQ-SRW-01).
          // The server persists only the hash and the plaintext is shown once
          // below.
          onUnlocked(new_words);
          setNewWords(new_words);
        }}
      />
      {newWords && (
        <div
          role="status"
          className="mt-3 rounded-lg border border-status-success/40 bg-surface-raised p-3"
        >
          <p className="text-small text-status-success">
            {t("profile.words.rotate.result")}
          </p>
          <p className="mt-2 break-words font-mono text-small text-primary">
            {newWords}
          </p>
        </div>
      )}
    </div>
  );
}

/** Vault OFF — activation. With no account: create one (username + optional
 *  password); the recovery words are shown EXACTLY once (S-VC-03a). With an
 *  existing account (e.g. a migrated install): verify the words (ownership
 *  proof) before enabling (S-VC-03b/c). */
function ActivationPanel({
  config,
  onActivated,
  onVerified,
}: {
  config: VaultConfig;
  onActivated: () => void;
  /** Arm the session unlock after a words-based activation succeeds
   *  (REQ-SRW-01): the typed words were just verified server-side. */
  onVerified?: (words: string) => void;
}) {
  const { t } = useAppLanguage();
  const [words, setWords] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [verifyWords, setVerifyWords] = useState("");

  const handleActivate = async (body: {
    username?: string;
    password?: string;
    words?: string;
  }) => {
    setBusy(true);
    setError(null);
    try {
      const result = await enableVault(body);
      if (result.words) {
        // New account: the words are shown exactly once before continuing.
        setWords(result.words);
      } else {
        // Existing account: the typed words were just verified server-side,
        // so they arm the session unlock (REQ-SRW-01) before switching to
        // the vault-ON management surface.
        if (body.words) onVerified?.(body.words);
        onActivated();
      }
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : t("profile.vault.activationError"),
      );
    } finally {
      setBusy(false);
    }
  };

  if (words) {
    return (
      <section className="rounded-lg border border-status-success/40 bg-surface-raised p-4">
        <h3 className="font-heading text-body text-primary">{t("profile.vault.activatedTitle")}</h3>
        <p className="mt-1 text-small text-muted">
          {t("profile.vault.activatedIntro")}
        </p>
        <p
          data-testid="vault-words"
          className="mt-4 break-words rounded-lg border border-edge bg-surface p-4 font-mono text-body text-primary"
        >
          {words}
        </p>
        <Button className="mt-4" onClick={onActivated}>
          {t("profile.vault.confirmWords")}
        </Button>
      </section>
    );
  }

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-edge bg-surface-raised p-4">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-heading text-body text-primary">
            {t("profile.vault.title")}
          </h3>
          <span className="text-small text-muted">{t("profile.vault.off")}</span>
        </div>
        <p className="mt-1 text-small text-muted">
          {t("profile.vault.intro")}
        </p>
        {config.env_override && (
          <p className="mt-3 rounded-lg border border-edge bg-surface/50 p-3 text-small text-muted">
            {t("profile.vault.envForced")}{" "}
            <code className="text-icon-muted">DEMIURGOS_AUTH_MODE=credentials</code>.
          </p>
        )}
      </section>

      {config.account_exists ? (
        <form
          className="rounded-lg border border-edge bg-surface-raised p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void handleActivate({ words: verifyWords.trim() });
          }}
        >
          <h4 className="font-heading text-body text-primary">
            {t("profile.vault.activateTitle")}
          </h4>
          <p className="mt-1 text-small text-muted">
            {t("profile.vault.activateIntro", {
              username: config.username ?? t("profile.vault.noUsername"),
            })}
          </p>
          <label htmlFor="vault-verify-words" className="sr-only">
            {t("profile.vault.verifyWordsLabel")}
          </label>
          <input
            id="vault-verify-words"
            type="text"
            autoComplete="off"
            placeholder={t("profile.words.inputPlaceholder")}
            value={verifyWords}
            onChange={(e) => {
              setVerifyWords(e.target.value);
              setError(null);
            }}
            disabled={busy}
            className="mt-3 w-full rounded-lg border border-edge bg-surface-raised px-3 py-2 text-body text-primary placeholder:text-muted focus:border-icon-muted focus:outline-none disabled:opacity-50"
          />
          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={busy || verifyWords.trim() === ""}
            className="mt-3"
          >
            {busy ? t("profile.vault.activating") : t("profile.vault.activate")}
          </Button>
        </form>
      ) : (
        <form
          className="rounded-lg border border-edge bg-surface-raised p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void handleActivate({
              username: username.trim(),
              password: password || undefined,
            });
          }}
        >
          <h4 className="font-heading text-body text-primary">
            {t("profile.vault.createTitle")}
          </h4>
          <p className="mt-1 text-small text-muted">
            {t("profile.vault.createIntro")}
          </p>
          <div className="mt-3 grid gap-4">
            <label
              htmlFor="vault-create-username"
              className="flex flex-col gap-1 text-small text-primary"
            >
              {t("profile.vault.username")}
              <input
                id="vault-create-username"
                value={username}
                onChange={(e) => {
                  setUsername(e.target.value);
                  setError(null);
                }}
                disabled={busy}
                autoComplete="username"
                placeholder={t("profile.vault.usernamePlaceholder")}
                className="rounded-lg border border-edge bg-surface-raised px-3 py-2 text-body text-primary placeholder:text-muted focus:border-icon-muted focus:outline-none disabled:opacity-50"
              />
            </label>
            <div className="flex flex-col gap-1">
              <label
                htmlFor="vault-create-password"
                className="text-small text-primary"
              >
                {t("profile.vault.password")}
              </label>
              <SecretInput
                id="vault-create-password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setError(null);
                }}
                disabled={busy}
                autoComplete="new-password"
                placeholder={t("profile.vault.passwordPlaceholder")}
                className="rounded-lg border border-edge bg-surface-raised px-3 py-2 text-body text-primary placeholder:text-muted focus:border-icon-muted focus:outline-none disabled:opacity-50"
              />
            </div>
          </div>
          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={busy || username.trim() === ""}
            className="mt-3"
          >
            {busy ? t("profile.vault.activating") : t("profile.vault.create")}
          </Button>
        </form>
      )}

      {error && (
        <p className="text-small text-status-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** Adjust the soft re-auth interval (days) via POST /api/auth/vault/reauth-interval. */
function ReauthIntervalForm({
  config,
  onSaved,
}: {
  config: VaultConfig;
  onSaved: () => void;
}) {
  const { t } = useAppLanguage();
  const [value, setValue] = useState(String(config.reauth_interval_d));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const handleSubmit = async () => {
    const days = Number(value);
    if (!Number.isFinite(days) || days < 1) {
      setError(t("profile.reauth.invalid"));
      return;
    }
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await setReauthInterval(days);
      setDone(true);
      onSaved();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : t("profile.reauth.error"),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-edge bg-surface/50 p-3">
      <h4 className="font-heading text-body text-primary">
        {t("profile.reauth.title")}
      </h4>
      <p className="mt-1 text-small text-muted">
        {t("profile.reauth.intro")}
      </p>
      <div className="mt-3 flex items-center gap-3">
        <label htmlFor="reauth-interval" className="sr-only">
          {t("profile.reauth.daysLabel")}
        </label>
        <input
          id="reauth-interval"
          type="number"
          min={1}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setError(null);
          }}
          disabled={busy}
          className="w-28 rounded-lg border border-edge bg-surface-raised px-3 py-2 text-body text-primary focus:border-icon-muted focus:outline-none disabled:opacity-50"
        />
        <span className="text-small text-muted">{t("profile.reauth.daysUnit")}</span>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void handleSubmit()}
          disabled={busy}
        >
          {busy ? t("common.saving") : t("common.save")}
        </Button>
      </div>
      {error && (
        <p className="mt-2 text-small text-status-error" role="alert">
          {error}
        </p>
      )}
      {done && (
        <p className="mt-2 text-small text-status-success" role="status">
          {t("profile.reauth.done")}
        </p>
      )}
    </div>
  );
}

/**
 * Perfil → Conexiones — the two external-connection surfaces presented as ONE
 * card family: a two-row index (assistant first, Telegram second) drives a
 * single detail region. Both bodies stay mounted and the inactive one is
 * `hidden`, so each wizard keeps its step state and its status reads stay
 * warm. The section no longer owns a "Captura de ideas" heading or the
 * Hermes / Telegram intro paragraph: both moved into the shared card header
 * and subtitle (CON-PIA-05 keeps the embedded behavior intact).
 */
function ConexionesSection() {
  const { t } = useAppLanguage();
  const auth = useAuthSession(true);
  // Assistant first and active by default: it is the reachable-from-scroll-top
  // surface, while the idea-capture wizard keeps its step state mounted.
  const [activeConnection, setActiveConnection] = useState("assistant");
  const [assistantStatus, setAssistantStatus] =
    useState<ConnectionStatusSummary | null>(null);
  const [telegramStatus, setTelegramStatus] =
    useState<ConnectionStatusSummary | null>(null);

  // Status callbacks are stable and dedupe by label/variant. A child that
  // reports a fresh object every render must not loop the parent, so the
  // setter only stores when the summary actually changed.
  const handleAssistantStatus = useCallback((next: ConnectionStatusSummary) => {
    setAssistantStatus((prev) =>
      prev?.label === next.label && prev?.variant === next.variant ? prev : next,
    );
  }, []);
  const handleTelegramStatus = useCallback((next: ConnectionStatusSummary) => {
    setTelegramStatus((prev) =>
      prev?.label === next.label && prev?.variant === next.variant ? prev : next,
    );
  }, []);

  return (
    <ConnectionsPanel
      connections={[
        {
          id: "assistant",
          icon: "demiurgos",
          title: t("profile.conexiones.assistantTitle"),
          subtitle: t("profile.conexiones.assistantSubtitle"),
          status: assistantStatus ?? undefined,
          body: (
            <AssistantSettingsPanel
              auth={auth}
              onStatus={handleAssistantStatus}
            />
          ),
        },
        {
          id: "telegram",
          icon: "lightbulb",
          title: t("profile.conexiones.captureTitle"),
          subtitle: t("profile.conexiones.captureSubtitle"),
          status: telegramStatus ?? undefined,
          body: <IdeaCapturePanel auth={auth} onStatus={handleTelegramStatus} />,
        },
      ]}
      activeId={activeConnection}
      onSelect={setActiveConnection}
    />
  );
}

/**
 * Perfil → Preferencias — the inline locale form (REQ-PIA-12), the only
 * configuration capability that has no home elsewhere in the Profile. The
 * backup card was removed (product-owner decision): it only navigated to the
 * Respaldo section, which already has its own rail entry, and its badge was
 * declared unnecessary; the real backup surface lives in the Respaldo section
 * (REQ-PIA-02). The Offline/dispositivo card was removed for the same
 * redundancy reason: it stated the storage probe three times, offered no
 * action, and duplicated state owned by Conexiones and Captura de ideas.
 *
 * The other Configuration Center cards (Identidad, Asistente de Demiurgos, Telegram,
 * Mundos, Importar mundo) are intentionally NOT duplicated here — each of those
 * already lives in a dedicated Profile section (Conexiones / Mundos) or in the
 * Profile/Taller de Mundo themselves (nav-restructure decision): the
 * idea-capture wizard (with the Telegram bot config folded in) renders under
 * Conexiones and the legacy-folder MigrationPanel under Mundos. State semantics
 * (ONB-3.1/ONB-3.5 anti-overstatement guard, OC19 assistant label, OC11/OC21
 * essential badges) are reused from ConfigurationCenter.tsx so the Profile tabs
 * and the shared module never drift.
 */
function ConfigurationSection() {
  const { t } = useAppLanguage();
  const [readiness, setReadiness] = useState<ReadinessSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  // A silent reload refreshes the locale badge after an inline save without
  // replacing the whole section with the loading spinner.
  const load = (options?: { silent?: boolean }) => {
    if (!options?.silent) setLoading(true);
    setError(null);
    void getReadiness()
      .then(setReadiness)
      .catch((cause: unknown) => setError(cause))
      .finally(() => {
        if (!options?.silent) setLoading(false);
      });
  };

  useEffect(() => load(), []);

  /**
   * Preferencias renders no navigation cards. The backup card was removed
   * (product-owner decision) and the Offline/dispositivo card was removed for
   * the same redundancy reason: it stated the storage probe three times,
   * offered no action, and duplicated state owned by Conexiones and Captura de
   * ideas. The locale surface renders as the inline form below, with its
   * honest badge.
   */

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-small text-muted">
        <Spinner size="sm" /> {t("profile.locale.checking")}
      </div>
    );
  }

  if (!!error && !readiness) {
    return (
      <ErrorBanner
        message={t("profile.locale.loadError")}
        onRetry={load}
      />
    );
  }

  if (!readiness) return null;

  const cards = readiness.cards ?? {};
  // The locale surface renders as the inline form below, not as a navigation
  // card, so its readiness state still drives the honest badge (REQ-PIA-12).
  const localeState = cardState(cards, "locale");
  const localeLabel = cardLabel("locale", localeState, t);
  const localeMeta = STATE_META[localeState];

  return (
    <div className="space-y-4" aria-live="polite">
      {/* Inline locale form (REQ-PIA-12) — the extracted Onboarding step-0
          form rendered directly in Preferencias, so the old `?step=step0`
          reconfigure handoff has no path left. Saving refreshes the badge
          silently. */}
      <section
        id="config-card-locale"
        tabIndex={-1}
        aria-labelledby="config-card-title-locale"
        className="rounded-lg border border-edge bg-surface-raised p-4"
      >
        <div className="flex items-center justify-between gap-3">
          <h3
            id="config-card-title-locale"
            className="font-heading text-body text-primary"
          >
            {t("profile.locale.title")}
          </h3>
          <span className="flex items-center gap-2">
            <Badge variant={localeMeta.badge}>{localeLabel}</Badge>
            <span className="sr-only">{t("profile.locale.stateLabel", { label: localeLabel })}</span>
          </span>
        </div>
        <LocaleForm onSaved={() => load({ silent: true })} />
      </section>
    </div>
  );
}

/**
 * Perfil → Mundos — world management: the "Zona peligrosa" delete flow and
 * the world-level recycle bin ("Papelera de mundos"). Also hosts the legacy
 * uppercase-folder migration panel (ONB-4.3, WU-4c2), relocated from the
 * standalone Centro de Configuración page (nav-restructure decision):
 * detection stays read-only and the migration only runs through the panel's
 * explicit confirm flow.
 *
 * Visual alignment (WU-6, CON-PIA-04): the section presents its three intents
 * as bordered cards in the same rounded-box language as the other Profile
 * sections. The section intro stays `h3` and every subsection heading starts
 * at `h3`, so the recycle bin's former orphan `h4` is gone (REQ-PIA-07).
 * Behavior is unchanged.
 *
 * The delete button mirrors the backend guards: it is disabled for the active
 * world (idea-capture config) and when the world is the only one left. A
 * successful delete refreshes the worlds list and bumps the trash panel's
 * refresh token so the new entry appears immediately.
 */
function WorldsSection() {
  const { t } = useAppLanguage();
  const { worlds, isLoading, error, mutate } = useWorlds();
  const [deleteTarget, setDeleteTarget] = useState<WorldInfo | null>(null);
  const [trashRefresh, setTrashRefresh] = useState(0);
  const [activeWorld, setActiveWorld] = useState("");
  const [legacy, setLegacy] = useState<ReadinessSnapshot["legacy"]>([]);
  const navigate = useNavigate();
  // World-picker dialog shown immediately when the deleted world was the
  // selector's active world, so the user is steered to another world instead of
  // being left pointing at one that no longer exists.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerMundo, setPickerMundo] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  // Rename an active world (moves the world folder + updates references).
  const [renameTarget, setRenameTarget] = useState<WorldInfo | null>(null);
  const [renameBusy, setRenameBusy] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);

  // The backend refuses to delete the active world; mirror that rule in the
  // UI with a disabled button + tooltip. Fail-open: if the idea-capture
  // status cannot be read, no world is treated as active.
  useEffect(() => {
    let active = true;
    void getIdeaCaptureStatus()
      .then((status) => {
        if (active) setActiveWorld(status.config.active_world ?? "");
      })
      .catch(() => {
        if (active) setActiveWorld("");
      });
    return () => {
      active = false;
    };
  }, []);

  // ONB-4.2/4.3 — read-only legacy detection: readiness is the source of
  // truth for uppercase folders; after a completed migration the panel
  // refreshes readiness so the notice disappears once the tree is canonical.
  const loadLegacy = useCallback(() => {
    void getReadiness()
      .then((readiness) => setLegacy(readiness.legacy ?? []))
      .catch(() => setLegacy([]));
  }, []);

  useEffect(loadLegacy, [loadLegacy]);

  const onlyWorld = worlds.length <= 1;

  const handleDeleted = useCallback(() => {
    // If the deleted world was the active working world (the one the world
    // selector shows), clear it so the selector does not keep pointing at a
    // world that no longer exists, and offer the picker right away so the user
    // is steered to another world. `deleteTarget` is still set here (cleared
    // below), so we can compare its name against the persisted active world.
    if (deleteTarget?.name && deleteTarget.name === getCurrentWorld()) {
      clearCurrentWorld();
      setPickerMundo(deleteTarget.name);
      setPickerOpen(true);
    }
    void mutate();
    setTrashRefresh((n) => n + 1);
    setDeleteTarget(null);
  }, [mutate, deleteTarget]);

  const handleRename = useCallback(
    async (world: WorldInfo, newName: string) => {
      setRenameBusy(true);
      setRenameError(null);
      try {
        await renameWorld(world.name, newName);
        // If the renamed world was the selector's active world, keep the
        // persisted reference pointing at it under the new name.
        if (getCurrentWorld() === world.name) {
          setCurrentWorld(newName);
        }
        setRenameTarget(null);
        await mutate();
      } catch (err) {
        const apiErr = err as ApiError;
        setRenameError(getErrorMessage(apiErr.status, apiErr.detail));
      } finally {
        setRenameBusy(false);
      }
    },
    [mutate],
  );

  const handleTrashChanged = useCallback(() => {
    // A restore makes a world reappear; a purge only empties the trash.
    void mutate();
  }, [mutate]);

  return (
    <div className="space-y-6">
      <section aria-labelledby="mundos-title">
        <h3 id="mundos-title" className="font-heading text-body text-primary">
          {t("profile.mundos.title")}
        </h3>
        <p className="mt-1 text-small text-muted">
          {t("profile.mundos.intro")}
        </p>
      </section>

      {/* Zona peligrosa — 3-step confirmation before any delete. The intro
          heading carries no trash icon; the Papelera panel below owns the
          only one in this section. */}
      <section
        aria-labelledby="mundos-danger-title"
        className="rounded-lg border border-status-error/30 bg-status-error/10 p-4"
      >
        <h3
          id="mundos-danger-title"
          className="font-heading text-body text-status-error"
        >
          {t("profile.mundos.dangerTitle")}
        </h3>
        <p className="mt-1 text-small text-muted">
          {t("profile.mundos.dangerIntro")}
        </p>

        {error && (
          <div
            role="alert"
            className="mt-3 rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-small text-status-error"
          >
            {error.message}
          </div>
        )}

        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <Spinner size="md" />
          </div>
        ) : worlds.length === 0 ? (
          <p className="mt-3 text-small text-muted">{t("profile.mundos.empty")}</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2">
            {worlds.map((world) => {
              const isActive = activeWorld.toLowerCase() === world.name.toLowerCase();
              const disabledReason = isActive
                ? t("profile.mundos.deleteActiveReason")
                : onlyWorld
                  ? t("profile.mundos.deleteOnlyReason")
                  : null;
              return (
                <li
                  key={world.name}
                  className="flex items-center gap-3 rounded-lg border border-edge bg-surface/50 px-3 py-2"
                >
                  <Icon name="world" size={18} className="shrink-0 text-icon-muted" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-small text-primary">{world.name}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      <Badge>{t("profile.mundos.loreBadge", { count: world.lore_count })}</Badge>
                      <Badge>{t("profile.mundos.charactersBadge", { count: world.character_count })}</Badge>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setRenameError(null);
                        setRenameTarget(world);
                      }}
                    >
                      {t("profile.mundos.rename")}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={disabledReason !== null}
                      title={disabledReason ?? undefined}
                      onClick={() => setDeleteTarget(world)}
                    >
                      {t("profile.mundos.delete")}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* Papelera de mundos — restore / permanent delete. The panel owns its
          heading; it is wrapped in the same card treatment as the other
          intent blocks so the three Mundos subsections line up visually. */}
      <section
        aria-label={t("profile.mundos.trashAria")}
        className="rounded-lg border border-edge bg-surface-raised p-4"
      >
        <WorldTrashPanel refreshToken={trashRefresh} onChanged={handleTrashChanged} />
      </section>

      {/* ONB-4.2/4.3 (WU-4c2) — legacy uppercase-folder migration, relocated
          from the standalone Centro de Configuración page. Rendered only when
          readiness detected legacy folders; migration never runs automatically
          and always requires the panel's explicit confirm flow. */}
      {legacy.length > 0 && (
        <section aria-label={t("profile.mundos.migrationAria")}>
          <MigrationPanel findings={legacy} onMigrated={loadLegacy} />
        </section>
      )}

      {deleteTarget && (
        <DeleteWorldModal
          world={deleteTarget}
          onDeleted={handleDeleted}
          onClose={() => setDeleteTarget(null)}
        />
      )}

      {pickerOpen && (
        <WorldPickerDialog
          missingWorld={pickerMundo}
          available={worlds.filter((w) => w.name !== pickerMundo)}
          onPick={(name) => {
            setPickerOpen(false);
            navigate(`/wiki/${encodeURIComponent(name)}`);
          }}
          onCreate={() => {
            // Close the picker so the create dialog is the only modal (both
            // are z-50; the body-portaled picker could sit above the inline
            // create dialog otherwise).
            setPickerOpen(false);
            setCreateOpen(true);
          }}
          onClose={() => setPickerOpen(false)}
          footerAction={{ label: t("common.cancel"), onAction: () => setPickerOpen(false) }}
        />
      )}

      <CreateWorldModal
        isOpen={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(world) => {
          setCreateOpen(false);
          setPickerOpen(false);
          navigate(`/wiki/${encodeURIComponent(world.name)}`);
        }}
      />

      {renameTarget && (
        <WorldNameDialog
          title={t("profile.mundos.renameDialogTitle")}
          message={t("profile.mundos.renameDialogMessage", { name: renameTarget.name })}
          initialValue={renameTarget.name}
          confirmLabel={t("profile.mundos.renameDialogConfirm")}
          confirmBusy={renameBusy}
          error={renameError}
          onConfirm={(newName) => void handleRename(renameTarget, newName)}
          onClose={() => {
            setRenameTarget(null);
            setRenameError(null);
          }}
        />
      )}
    </div>
  );
}

/**
 * Profile page (`/perfil`) — the unified configuration surface, organized by
 * user intent instead of implementation module (REQ-PIA-01/02).
 *
 * Five sections — Cuenta, Respaldo, Preferencias, Conexiones, Mundos — driven
 * by `?tab=<section>` (REQ-PIA-03): deep links and refresh preserve the
 * section, an explicit tab click pushes a history entry so Back cycles the
 * tabs, the default landing never pushes, and an invalid value falls back to
 * `cuenta` via a `replace` normalization. The rail is a page-owned ARIA
 * tablist/tab/tabpanel set with roving focus (REQ-PIA-04) and one icon per
 * section (REQ-PIA-06); each panel opens with its `h2` so the outline stays
 * `h1 → h2 → h3` with no orphan level (REQ-PIA-07).
 *
 * Interim content mapping (later WUs re-home without changing embedded
 * behavior, CON-PIA-05): `cuenta` is the merged account/security surface
 * (WU-2, REQ-PIA-09) with the session-scoped words unlock (REQ-SRW-01..04);
 * `respaldo` hosts BackupSection (WU-3, REQ-PIA-02) with its sign-in
 * affordance pointing back to `cuenta`; `preferencias` hosts the configuration
 * hub with the locale form inline (WU-4, REQ-PIA-12), `conexiones` folds the
 * idea-capture and assistant panels into one section (WU-5, REQ-PIA-02/07).
 */
export default function ProfilePage() {
  const { t } = useAppLanguage();
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab");
  const activeSection: ProfileSection = isProfileSection(rawTab) ? rawTab : "cuenta";
  // The session-scoped words unlock (REQ-SRW-01..04) lives at page level so
  // it survives section switches; the merged cuenta surface consumes it.
  const { unlockedWords, unlock } = useRecoveryWordsUnlock();
  // Click-driven changes move focus to the panel heading; the default landing
  // and arrow-key roves never steal focus (REQ-PIA-04).
  const [focusPanel, setFocusPanel] = useState(false);

  // An unknown or invalid `?tab` falls back to `cuenta` and the URL is
  // normalized with `replace` so the fallback never pollutes history.
  useEffect(() => {
    if (rawTab !== null && !isProfileSection(rawTab)) {
      const next = new URLSearchParams(searchParams);
      next.set("tab", "cuenta");
      setSearchParams(next, { replace: true });
    }
  }, [rawTab, searchParams, setSearchParams]);

  // After a click-driven section change, focus moves to the panel heading.
  useEffect(() => {
    if (!focusPanel) return;
    setFocusPanel(false);
    document.getElementById(`profile-panel-heading-${activeSection}`)?.focus();
  }, [activeSection, focusPanel]);

  const selectSection = (id: string, options?: { focusPanel?: boolean }) => {
    if (!isProfileSection(id) || id === activeSection) return;
    if (options?.focusPanel) setFocusPanel(true);
    const next = new URLSearchParams(searchParams);
    next.set("tab", id);
    setSearchParams(next);
  };

  return (
    <div className="flex min-h-screen flex-col bg-surface">
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
        <h1 className="font-heading text-h3 text-primary">{t("profile.title")}</h1>
        <StatusOverviewHeader />
        <div className="mt-6 flex flex-col gap-6 md:flex-row">
          <ProfileSectionRail
            sections={PROFILE_SECTIONS.map((section) => ({
              ...section,
              label: t(section.labelKey),
            }))}
            activeId={activeSection}
            onSelect={selectSection}
          />
          <section
            role="tabpanel"
            id={`profile-panel-${activeSection}`}
            aria-labelledby={`profile-tab-${activeSection}`}
            tabIndex={-1}
            className="min-w-0 flex-1"
          >
            <h2
              id={`profile-panel-heading-${activeSection}`}
              tabIndex={-1}
              className="font-heading text-h4 text-primary"
            >
              {t(PROFILE_SECTIONS.find((section) => section.id === activeSection)?.labelKey ?? "profile.section.cuenta")}
            </h2>
            <div className="mt-4">
              {activeSection === "cuenta" ? (
                <CuentaSection
                  unlockedWords={unlockedWords}
                  onUnlocked={unlock}
                />
              ) : activeSection === "respaldo" ? (
                <BackupSection onRequestSignIn={() => selectSection("cuenta")} />
              ) : activeSection === "preferencias" ? (
                <ConfigurationSection />
              ) : activeSection === "conexiones" ? (
                <ConexionesSection />
              ) : activeSection === "actualizaciones" ? (
                <UpdateSection />
              ) : activeSection === "reporte" ? (
                <ReportSection />
              ) : (
                <WorldsSection />
              )}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
