import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon, type IconName } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { IdeaCapturePanel } from "@/components/organisms/IdeaCapturePanel";
import { AssistantSettingsPanel } from "@/components/organisms/AssistantSettingsPanel";
import { BackupSection } from "@/components/organisms/BackupSection";
import { ProfileSectionRail } from "@/components/organisms/ProfileSectionRail";
import { StatusOverviewHeader } from "@/components/organisms/StatusOverviewHeader";
import { DeleteWorldModal } from "@/components/organisms/DeleteWorldModal";
import { WorldPickerDialog } from "@/components/organisms/WorldPickerDialog";
import { CreateWorldModal } from "@/components/organisms/CreateWorldModal";
import { WorldNameDialog } from "@/components/organisms/WorldNameDialog";
import { renameWorld } from "@/api/worlds";
import { clearCurrentWorld, getCurrentWorld, setCurrentWorld } from "@/lib/currentWorld";
import { WorldTrashPanel } from "@/components/organisms/WorldTrashPanel";
import { SecretInput } from "@/components/molecules/SecretInput";
import { getIdeaCaptureStatus } from "@/api/ideaCapture";
import { getReadiness } from "@/api/onboarding";
import {
  changePassword,
  changeUsername,
  disableVault,
  enableVault,
  getAuthStatus,
  getVaultConfig,
  logoutSession,
  removePassword,
  rotateWords,
  setReauthInterval,
} from "@/api/wiki";
import { useWorlds } from "@/hooks/useWorlds";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";
import { useRecoveryWordsUnlock } from "@/hooks/useRecoveryWordsUnlock";
import { useAuthSession } from "@/hooks/useAuthSession";
import { reloadPage } from "@/lib/reloadPage";
import type {
  ApiError,
  AuthSessionStatus,
  ReadinessSnapshot,
  VaultConfig,
  WorldInfo,
} from "@/api/types";
import {
  CARD_DEFS,
  ESSENTIAL_BADGES,
  MigrationPanel,
  REMOTE_LABELS,
  STATE_META,
  cardLabel,
  cardState,
  essentialBadgeFor,
} from "@/pages/ConfigurationCenter";
import { getErrorMessage } from "@/lib/utils";

type ProfileSection =
  | "cuenta"
  | "respaldo"
  | "preferencias"
  | "conexiones"
  | "mundos";

/** The five intent-based sections (REQ-PIA-01) with rail label and icon
 *  (REQ-PIA-06). `cuenta` is the default landing section. */
const PROFILE_SECTIONS: { id: ProfileSection; label: string; icon: IconName }[] = [
  { id: "cuenta", label: "Cuenta", icon: "avatar" },
  { id: "respaldo", label: "Respaldo", icon: "save" },
  { id: "preferencias", label: "Preferencias", icon: "monitor" },
  { id: "conexiones", label: "Conexiones", icon: "lightbulb" },
  { id: "mundos", label: "Mundos", icon: "world" },
];

function isProfileSection(value: string | null): value is ProfileSection {
  return PROFILE_SECTIONS.some((section) => section.id === value);
}

/**
 * Perfil → Cuenta — the single account/security surface (REQ-PIA-09), merging
 * the former session panel, credentials Account section and vault
 * management/activation panels into one section. Vault ON and vault OFF are
 * two states of the same surface: the session card is always present
 * (credentials or local-dev branch), and below it the vault card renders
 * either the words-management forms (ON) or the activation forms (OFF).
 *
 * The recovery-words unlock (REQ-SRW-01..04) is session-scoped: the first
 * successful words-gated action arms the verified words and later actions
 * replay them without re-prompting. The words live in page-level memory only
 * (never localStorage/sessionStorage/cookies) and are cleared on logout and
 * on unmount.
 */
function CuentaSection({
  unlockedWords,
  onUnlocked,
  onLock,
}: {
  unlockedWords: string | null;
  onUnlocked: (words: string) => void;
  onLock: () => void;
}) {
  const localDev = useLocalDevAuth(true);
  const [vaultStatus, setVaultStatus] = useState<AuthSessionStatus | null>(null);
  const [config, setConfig] = useState<VaultConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

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

  // Credentials logout clears the unlocked words before the reload (REQ-SRW-03).
  const handleLogout = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      await logoutSession();
      onLock();
      reloadPage();
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : "No se pudo cerrar la sesión",
      );
    } finally {
      setActionLoading(false);
    }
  };

  // Local-dev / disabled session action (start or close the local session).
  const handleLocalAction = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      if (localDev.status?.authenticated) {
        await localDev.logout();
        onLock();
      } else {
        await localDev.start();
      }
    } catch (cause) {
      setActionError(
        cause instanceof Error
          ? cause.message
          : "No se pudo actualizar la sesión local",
      );
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-small text-muted">
        <Spinner size="sm" /> Comprobando la bóveda…
      </div>
    );
  }

  if (!!error && !config) {
    return (
      <ErrorBanner message="No se pudo cargar el estado de la bóveda." onRetry={load} />
    );
  }

  if (!config) return null;

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-edge bg-surface-raised p-4">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-heading text-body text-primary">Sesión</h3>
          <span className="text-small text-muted">
            {vaultStatus?.mode === "credentials" ? "Credenciales" : "Local"}
          </span>
        </div>

        {vaultStatus?.mode === "credentials" ? (
          vaultStatus.authenticated ? (
            <>
              <p className="mt-3 text-small text-status-success">Sesión activa</p>
              <p className="mt-1 text-small text-muted">{vaultStatus.label}</p>
              <p className="mt-1 text-small text-muted">
                Proveedor: {providerLabel(vaultStatus.provider)}
              </p>

              {daysUntilReauth !== null && (
                <div
                  role="status"
                  className="mt-3 rounded-lg border border-edge bg-surface/50 p-3"
                >
                  <p className="text-small text-primary">
                    {daysUntilReauth <= 0
                      ? "Reingreso recomendado: hoy"
                      : `Reingreso recomendado en ${daysUntilReauth} día${daysUntilReauth === 1 ? "" : "s"}`}
                  </p>
                  <p className="mt-2 text-small text-muted">
                    Si no reingresas tu contraseña, la sesión de Demiurgos se
                    cerrará. Y si olvidaste tu contraseña, solo vas a poder
                    recuperarla con tus palabras claves.
                  </p>
                </div>
              )}

              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  onClick={() => void handleLogout()}
                  disabled={actionLoading}
                >
                  {actionLoading ? "Cerrando…" : "Cerrar sesión"}
                </Button>
              </div>
            </>
          ) : (
            <p className="mt-3 text-small text-muted">
              No hay una sesión de cuenta activa. Iniciá sesión para editar y
              configurar el perfil.
            </p>
          )
        ) : localDev.isLoading ? (
          <div className="flex items-center gap-2 py-6 text-small text-muted">
            <Spinner size="sm" /> Comprobando sesión local…
          </div>
        ) : localDev.error ? (
          <p className="text-small text-status-error">{localDev.error.message}</p>
        ) : !localDev.status ? null : (
          <>
            {localDev.status.authenticated && (
              <>
                <p className="mt-3 text-small text-status-success">
                  Sesión local activa
                </p>
                <p className="mt-1 text-small text-muted">{localDev.status.label}</p>
                <Button
                  variant="secondary"
                  onClick={() => void handleLocalAction()}
                  disabled={actionLoading}
                  className="mt-3"
                >
                  {actionLoading ? "Cerrando…" : "Cerrar sesión local"}
                </Button>
              </>
            )}

            {!localDev.status.authenticated && localDev.status.enabled && (
              <>
                <p className="mt-3 text-small text-muted">
                  Sesión local no iniciada. Iniciala para editar y configurar el
                  perfil.
                </p>
                <Button
                  variant="primary"
                  onClick={() => void handleLocalAction()}
                  disabled={actionLoading}
                  className="mt-3"
                >
                  {actionLoading ? "Iniciando…" : "Iniciar sesión local"}
                </Button>
              </>
            )}

            {!localDev.status.enabled && (
              <p className="mt-3 text-small text-muted">
                Autenticación local desactivada. Activá{" "}
                <code className="text-icon-muted">DEMIURGOS_AUTH_MODE=local-dev</code>{" "}
                en <code className="text-icon-muted">.env</code> para probar la
                edición.
              </p>
            )}
          </>
        )}

        {actionError && (
          <p className="mt-3 text-small text-status-error">{actionError}</p>
        )}
      </section>

      {config.enabled ? (
        <section className="rounded-lg border border-edge bg-surface-raised p-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-heading text-body text-primary">
              Seguridad / Bóveda
            </h3>
            <span className="text-small text-muted">Activa</span>
          </div>
          <p className="mt-1 text-small text-muted">
            Cuenta: <span className="text-primary">{config.username ?? "—"}</span>
            {config.has_password ? " · contraseña definida" : " · sin contraseña"}
            {config.env_override && (
              <span className="text-muted">
                {" "}
                · forzada por{" "}
                <code className="text-icon-muted">DEMIURGOS_AUTH_MODE</code>
              </span>
            )}
          </p>

          <div className="mt-4 space-y-4">
            <WordsUnlockBanner unlocked={unlockedWords !== null} />

            <WordsForm
              title="Cambiar usuario"
              description="Demostrá que la cuenta es tuya con tus palabras claves y elegí un nuevo usuario."
              extraLabel="Nuevo usuario"
              extraPlaceholder="nuevo-usuario"
              submitLabel="Cambiar usuario"
              busyLabel="Cambiando…"
              unlockedWords={unlockedWords}
              onSubmit={async (words, newUsername) => {
                await changeUsername(words, newUsername);
                onUnlocked(words);
                load();
              }}
            />

            <WordsForm
              title="Cambiar contraseña"
              description="Demostrá que la cuenta es tuya con tus palabras claves y definí una nueva contraseña."
              extraLabel="Nueva contraseña"
              extraType="password"
              extraPlaceholder="Nueva contraseña"
              extraRequired
              submitLabel="Cambiar contraseña"
              busyLabel="Cambiando…"
              unlockedWords={unlockedWords}
              onSubmit={async (words, newPassword) => {
                await changePassword(words, newPassword);
                onUnlocked(words);
                load();
              }}
            />

            <WordsForm
              title="Retirar contraseña"
              description="Tu cuenta pasa a ser sin contraseña: alcanza con el botón Entrar. Lo confirmás con tus palabras claves."
              submitLabel="Retirar contraseña"
              busyLabel="Retirando…"
              confirmLabel="¿Confirmás el retiro?"
              unlockedWords={unlockedWords}
              onSubmit={async (words) => {
                await removePassword(words);
                onUnlocked(words);
                load();
              }}
            />

            <RotateWordsCard />

            <ReauthIntervalForm config={config} onSaved={load} />

            <WordsForm
              title="Desactivar bóveda"
              description="Apagar la bóveda quita la autenticación de la instalación. Lo confirmás con tus palabras claves."
              submitLabel="Desactivar bóveda"
              busyLabel="Desactivando…"
              confirmLabel="¿Confirmás la desactivación?"
              unlockedWords={unlockedWords}
              onSubmit={async (words) => {
                await disableVault(words);
                onUnlocked(words);
                load();
              }}
            />
          </div>
        </section>
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

/**
 * Recovery-words unlock state for the current session (REQ-SRW-01). Locked
 * until the first successful words-gated action arms the verified words;
 * never persisted to web storage (REQ-SRW-02).
 */
function WordsUnlockBanner({ unlocked }: { unlocked: boolean }) {
  return (
    <section
      aria-live="polite"
      className="rounded-lg border border-edge bg-surface/50 p-3"
    >
      <div className="flex items-center justify-between gap-3">
        <h4 className="font-heading text-body text-primary">Palabras claves</h4>
        <Badge variant={unlocked ? "success" : "default"}>
          {unlocked ? "Desbloqueadas" : "Bloqueadas"}
        </Badge>
      </div>
      <p className="mt-1 text-small text-muted">
        {unlocked
          ? "Desbloqueadas para esta sesión: las acciones que piden palabras claves ya no las vuelven a solicitar. No se guardan en el navegador."
          : "Bloqueadas para esta sesión. La primera acción que pida palabras claves las desbloquea; se recuerdan hasta cerrar sesión, recargar o salir del perfil."}
      </p>
    </section>
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
  unlockedWords,
  onSubmit,
}: WordsFormProps) {
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
      setError(`Completá el campo ${extraLabel?.toLowerCase() ?? "obligatorio"}.`);
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
        cause instanceof Error ? cause.message : "No se pudo completar la acción",
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
          Palabras claves ya verificadas para esta sesión.
        </p>
      ) : (
        <>
          <label htmlFor={`${title}-words`} className="sr-only">
            Palabras claves para {title}
          </label>
          <input
            id={`${title}-words`}
            type="text"
            autoComplete="off"
            placeholder="Palabras claves"
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
        variant="secondary"
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
          Listo. Cambio guardado.
        </p>
      )}
    </div>
  );
}

/** Rotate the recovery words (R-ERK-01): the new plaintext words are shown
 *  exactly once; the previous words are invalidated server-side. */
function RotateWordsCard() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newWords, setNewWords] = useState<string | null>(null);

  const handleRotate = async () => {
    setBusy(true);
    setError(null);
    setNewWords(null);
    try {
      const { new_words } = await rotateWords();
      // The server persists only the hash; the plaintext is shown once.
      setNewWords(new_words);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No se pudieron rotar las palabras de recuperación",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-edge bg-surface/50 p-3">
      <h4 className="font-heading text-body text-primary">
        Rotar palabras claves
      </h4>
      <p className="mt-1 text-small text-muted">
        Generá unas palabras nuevas y anulá las anteriores. Las palabras son tu
        única forma de recuperar la cuenta si olvidás la contraseña.
      </p>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => void handleRotate()}
        disabled={busy}
        className="mt-3"
      >
        {busy ? "Rotando…" : "Rotar palabras claves"}
      </Button>
      {error && (
        <p className="mt-2 text-small text-status-error" role="alert">
          {error}
        </p>
      )}
      {newWords && (
        <div
          role="status"
          className="mt-3 rounded-lg border border-status-success/40 bg-surface-raised p-3"
        >
          <p className="text-small text-status-success">
            Nuevas palabras claves — guardalas fuera del navegador; solo se
            muestran una vez:
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
        cause instanceof Error ? cause.message : "No se pudo activar la bóveda",
      );
    } finally {
      setBusy(false);
    }
  };

  if (words) {
    return (
      <section className="rounded-lg border border-status-success/40 bg-surface-raised p-4">
        <h4 className="font-heading text-body text-primary">Bóveda activada</h4>
        <p className="mt-1 text-small text-muted">
          Se creó tu cuenta. Estas son tus palabras claves — guardalas fuera del
          navegador: solo se muestran una vez.
        </p>
        <p
          data-testid="vault-words"
          className="mt-4 break-words rounded-lg border border-edge bg-surface p-4 font-mono text-body text-primary"
        >
          {words}
        </p>
        <Button className="mt-4" onClick={onActivated}>
          Guardé mis palabras
        </Button>
      </section>
    );
  }

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-edge bg-surface-raised p-4">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-heading text-body text-primary">
            Seguridad / Bóveda
          </h3>
          <span className="text-small text-muted">Apagada</span>
        </div>
        <p className="mt-1 text-small text-muted">
          La bóveda protege tu instalación con una cuenta y tus palabras
          claves. Activarla exige demostrar que la cuenta es tuya.
        </p>
        {config.env_override && (
          <p className="mt-3 rounded-lg border border-edge bg-surface/50 p-3 text-small text-muted">
            La autenticación está forzada por la variable de entorno{" "}
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
            Activar la bóveda
          </h4>
          <p className="mt-1 text-small text-muted">
            Ya existe una cuenta ({config.username ?? "sin usuario"}). Demostrá
            que es tuya con tus palabras claves para activar la bóveda.
          </p>
          <label htmlFor="vault-verify-words" className="sr-only">
            Palabras claves para activar la bóveda
          </label>
          <input
            id="vault-verify-words"
            type="text"
            autoComplete="off"
            placeholder="Palabras claves"
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
            {busy ? "Activando…" : "Activar bóveda"}
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
            Crear cuenta y activar
          </h4>
          <p className="mt-1 text-small text-muted">
            No hay una cuenta todavía. Creala ahora: la contraseña es opcional
            y se generan tus palabras claves (se muestran una sola vez).
          </p>
          <div className="mt-3 grid gap-4">
            <label
              htmlFor="vault-create-username"
              className="flex flex-col gap-1 text-small text-primary"
            >
              Usuario
              <input
                id="vault-create-username"
                value={username}
                onChange={(e) => {
                  setUsername(e.target.value);
                  setError(null);
                }}
                disabled={busy}
                autoComplete="username"
                placeholder="tu-usuario"
                className="rounded-lg border border-edge bg-surface-raised px-3 py-2 text-body text-primary placeholder:text-muted focus:border-icon-muted focus:outline-none disabled:opacity-50"
              />
            </label>
            <div className="flex flex-col gap-1">
              <label
                htmlFor="vault-create-password"
                className="text-small text-primary"
              >
                Contraseña (opcional)
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
                placeholder="Dejalo vacío para entrar sin contraseña"
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
            {busy ? "Activando…" : "Crear cuenta y activar"}
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
  const [value, setValue] = useState(String(config.reauth_interval_d));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const handleSubmit = async () => {
    const days = Number(value);
    if (!Number.isFinite(days) || days < 1) {
      setError("Ingresá un intervalo válido en días.");
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
        cause instanceof Error ? cause.message : "No se pudo ajustar el intervalo",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-edge bg-surface/50 p-3">
      <h4 className="font-heading text-body text-primary">
        Intervalo de reingreso
      </h4>
      <p className="mt-1 text-small text-muted">
        Cada cuántos días se te pide reingresar la contraseña.
      </p>
      <div className="mt-3 flex items-center gap-3">
        <label htmlFor="reauth-interval" className="sr-only">
          Días entre reingresos
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
        <span className="text-small text-muted">días</span>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void handleSubmit()}
          disabled={busy}
        >
          {busy ? "Guardando…" : "Guardar"}
        </Button>
      </div>
      {error && (
        <p className="mt-2 text-small text-status-error" role="alert">
          {error}
        </p>
      )}
      {done && (
        <p className="mt-2 text-small text-status-success" role="status">
          Listo. Intervalo guardado.
        </p>
      )}
    </div>
  );
}

/** Human label for the active session provider. */
function providerLabel(provider?: AuthSessionStatus["provider"]): string {
  switch (provider) {
    case "credentials":
      return "Credenciales";
    case "local-dev":
      return "Local";
    default:
      return "Desconocido";
  }
}

/** Perfil → Integraciones → Captura de ideas — the single Telegram surface.
 *  The guided wizard covers the write-only bot token (save/replace/clear) and
 *  getMe-backed connection validation via the "Detectar chat" step. */
function IntegrationsSection() {
  const auth = useAuthSession(true);
  return (
    <div>
      <h3 className="font-heading text-body text-primary">Captura de ideas</h3>
      <p className="mt-1 text-small text-muted">
        Hermes / Telegram — ingreso de ideas nativo desde el bot.
      </p>
      <div className="mt-4">
        <IdeaCapturePanel auth={auth} />
      </div>
    </div>
  );
}

function AssistantSection() {
  const auth = useAuthSession(true);
  return <AssistantSettingsPanel auth={auth} />;
}

/**
 * Perfil → Preferencias — the configuration capabilities that have no home
 * elsewhere in the Profile: Idioma/región/zona horaria and Offline/dispositivo,
 * plus the essential local readiness summary. The backup card stays here as an
 * honest entry point (badge + action); its action leads to the Respaldo
 * section, where the real backup surface lives (REQ-PIA-02/10).
 *
 * The other Configuration Center cards (Identidad, IA texto y visión, Telegram,
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
  const navigate = useNavigate();
  const location = useLocation();
  const [readiness, setReadiness] = useState<ReadinessSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    void getReadiness()
      .then(setReadiness)
      .catch((cause: unknown) => setError(cause))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  /**
   * Every declared card action is the card's real entry point, so the renderer
   * below draws `card.action` for ANY card that declares one — never a growing
   * allowlist of keys. When the target is EXACTLY the location already shown
   * (e.g. the locale card on `/perfil?tab=preferencias`), navigating would be
   * an invisible no-op, so the control performs an in-page move instead: scroll
   * the card section into view and focus it, the same landing guarantee an
   * anchor/skip-link gives keyboard and assistive-technology users. Any other
   * target — including a different `?tab=` section (REQ-PIA-10) — navigates.
   */
  const runCardAction = (card: (typeof CARD_DEFS)[number]) => {
    const action = card.action;
    if (!action) return;
    if (action.to === location.pathname + location.search) {
      const section = document.getElementById(`config-card-${card.key}`);
      if (section) {
        section.scrollIntoView?.({ behavior: "smooth", block: "start" });
        section.focus();
      }
      return;
    }
    navigate(action.to);
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-small text-muted">
        <Spinner size="sm" /> Comprobando configuración…
      </div>
    );
  }

  if (!!error && !readiness) {
    return (
      <ErrorBanner
        message="No se pudieron cargar los estados de configuración."
        onRetry={load}
      />
    );
  }

  if (!readiness) return null;

  const cards = readiness.cards ?? {};
  const keepCards = CARD_DEFS.filter((card) =>
    ["backup", "locale", "offline"].includes(card.key),
  );

  return (
    <div className="space-y-4" aria-live="polite">
      {/* Essential local readiness (OC11/OC21) — the tab's intro block. */}
      <section
        aria-labelledby="config-readiness-title"
        className="rounded-lg border border-edge bg-surface-raised p-4"
      >
        <div className="flex items-center justify-between gap-3">
          <h3
            id="config-readiness-title"
            className="font-heading text-body text-primary"
          >
            Listo para trabajar
          </h3>
        </div>
        <p className="mt-1 text-small text-muted">
          Capacidades esenciales locales: Mundo y editor local.
        </p>
        <div className="mt-3 flex flex-wrap gap-3">
          {ESSENTIAL_BADGES.map((badge) => {
            const meta = essentialBadgeFor(readiness, cards, badge.key);
            return (
              <span key={badge.key} className="flex items-center gap-2">
                <span className="text-small text-muted">{badge.title}:</span>
                <Badge variant={meta.badge}>{meta.label}</Badge>
                <span className="sr-only">Estado: {meta.label}</span>
              </span>
            );
          })}
        </div>
      </section>

      {/* Kept configuration cards — same rounded-box style as the other
          Profile sections (title row on top, content below). */}
      {keepCards.map((card) => {
        const state = cardState(cards, card.key);
        const label = cardLabel(card.key, state);
        const meta = STATE_META[state];
        return (
          <section
            key={card.key}
            id={`config-card-${card.key}`}
            tabIndex={-1}
            aria-labelledby={`config-card-title-${card.key}`}
            className="rounded-lg border border-edge bg-surface-raised p-4"
          >
            <div className="flex items-center justify-between gap-3">
              <h3
                id={`config-card-title-${card.key}`}
                className="font-heading text-body text-primary"
              >
                {card.title}
              </h3>
              <span className="flex items-center gap-2">
                <Badge variant={meta.badge}>{label}</Badge>
                <span className="sr-only">Estado: {label}</span>
              </span>
            </div>
            <p className="mt-1 text-small text-muted">{card.description}</p>

            {card.action && (
              <div className="mt-3">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => runCardAction(card)}
                >
                  {card.action.label}
                </Button>
              </div>
            )}

            {card.key === "offline" && (
              <dl className="mt-4 space-y-3 border-t border-edge pt-4">
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-small text-muted">Núcleo local</dt>
                  <dd className="flex items-center gap-2">
                    <Badge variant={readiness.offline.local_ready ? "success" : "error"}>
                      {readiness.offline.local_ready ? "Listo" : "No disponible"}
                    </Badge>
                    <span className="sr-only">
                      Estado: {readiness.offline.local_ready ? "Listo" : "No disponible"}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt className="text-small text-muted">Remoto</dt>
                  <dd className="mt-1 text-small text-muted">
                    {readiness.offline.remote_pending.length > 0 ? (
                      <span>
                        Capacidades remotas pendientes (requieren conexión):{" "}
                        {readiness.offline.remote_pending
                          .map((key) => REMOTE_LABELS[key] ?? key)
                          .join(", ")}.
                      </span>
                    ) : (
                      <span>Sin capacidades remotas pendientes.</span>
                    )}
                  </dd>
                </div>
              </dl>
            )}
          </section>
        );
      })}
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
 * The delete button mirrors the backend guards: it is disabled for the active
 * world (idea-capture config) and when the world is the only one left. A
 * successful delete refreshes the worlds list and bumps the trash panel's
 * refresh token so the new entry appears immediately.
 */
function WorldsSection() {
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
    <div>
      <h3 className="font-heading text-body text-primary">Mundos</h3>
      <p className="mt-1 text-small text-muted">
        Gestioná los mundos del taller: eliminá uno (queda recuperable 30 días en la papelera) o
        restaurá mundos eliminados.
      </p>

      {/* Zona peligrosa — 3-step confirmation before any delete. */}
      <div className="mt-4 rounded-lg border border-status-error/30 bg-status-error/10 p-4">
        <h4 className="flex items-center gap-2 font-heading text-body text-status-error">
          <Icon name="trash" size={18} />
          Zona peligrosa
        </h4>
        <p className="mt-1 text-small text-muted">
          Eliminar un mundo lo mueve a la papelera durante 30 días; no se destruye de inmediato.
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
          <p className="mt-3 text-small text-muted">No hay mundos creados todavía.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2">
            {worlds.map((world) => {
              const isActive = activeWorld.toLowerCase() === world.name.toLowerCase();
              const disabledReason = isActive
                ? "No se puede eliminar el mundo activo"
                : onlyWorld
                  ? "Debe existir al menos un mundo"
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
                      <Badge>Lore {world.lore_count}</Badge>
                      <Badge>Personajes {world.character_count}</Badge>
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
                      Renombrar
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={disabledReason !== null}
                      title={disabledReason ?? undefined}
                      onClick={() => setDeleteTarget(world)}
                    >
                      Borrar
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Papelera de mundos — restore / permanent delete. */}
      <div className="mt-6">
        <WorldTrashPanel refreshToken={trashRefresh} onChanged={handleTrashChanged} />
      </div>

      {/* ONB-4.2/4.3 (WU-4c2) — legacy uppercase-folder migration, relocated
          from the standalone Centro de Configuración page. Rendered only when
          readiness detected legacy folders; migration never runs automatically
          and always requires the panel's explicit confirm flow. */}
      {legacy.length > 0 && (
        <div className="mt-6">
          <MigrationPanel findings={legacy} onMigrated={loadLegacy} />
        </div>
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
          footerAction={{ label: "Cancelar", onAction: () => setPickerOpen(false) }}
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
          title="Renombrar mundo"
          message={`El mundo «${renameTarget.name}» se moverá a un nuevo nombre. Los enlaces viejos siguen funcionando (se redirigen).`}
          initialValue={renameTarget.name}
          confirmLabel="Renombrar"
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
 * affordance pointing back to `cuenta`; `preferencias` still hosts the
 * configuration hub (locale extraction is WU-4), `conexiones` stacks the
 * idea-capture and assistant panels (fold-in is WU-5).
 */
export default function ProfilePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab");
  const activeSection: ProfileSection = isProfileSection(rawTab) ? rawTab : "cuenta";
  // The session-scoped words unlock (REQ-SRW-01..04) lives at page level so
  // it survives section switches; the merged cuenta surface consumes it.
  const { unlockedWords, unlock, lock } = useRecoveryWordsUnlock();
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
        <h1 className="font-heading text-h3 text-primary">Perfil</h1>
        <StatusOverviewHeader />
        <div className="mt-6 flex flex-col gap-6 md:flex-row">
          <ProfileSectionRail
            sections={PROFILE_SECTIONS}
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
              {PROFILE_SECTIONS.find((section) => section.id === activeSection)?.label}
            </h2>
            <div className="mt-4">
              {activeSection === "cuenta" ? (
                <CuentaSection
                  unlockedWords={unlockedWords}
                  onUnlocked={unlock}
                  onLock={lock}
                />
              ) : activeSection === "respaldo" ? (
                <BackupSection onRequestSignIn={() => selectSection("cuenta")} />
              ) : activeSection === "preferencias" ? (
                <ConfigurationSection />
              ) : activeSection === "conexiones" ? (
                <>
                  <IntegrationsSection />
                  <div className="mt-4">
                    <AssistantSection />
                  </div>
                </>
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
