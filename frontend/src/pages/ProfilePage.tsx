import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { IdeaCapturePanel } from "@/components/organisms/IdeaCapturePanel";
import { AssistantSettingsPanel } from "@/components/organisms/AssistantSettingsPanel";
import { DeleteWorldModal } from "@/components/organisms/DeleteWorldModal";
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
import { useAuthSession } from "@/hooks/useAuthSession";
import { reloadPage } from "@/lib/reloadPage";
import type {
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
import { cn } from "@/lib/utils";

type ProfileSection =
  | "sesion"
  | "seguridad"
  | "configuracion"
  | "integraciones"
  | "asistente"
  | "mundos";

/** Sesión de edición — the same local-dev session controls as the Navbar
 *  dropdown, kept accessible from the full Profile page. Mode-aware: in the
 *  credentials vault mode (DEMIURGOS_AUTH_MODE=credentials) the panel shows
 *  the Account section (session + logout + credential management via words +
 *  re-auth indicator); local-dev and disabled keep their legacy behavior
 *  unchanged. */
function SessionSection() {
  const localDev = useLocalDevAuth(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Unified status decides the vault branch; on failure the panel degrades
  // to the local-dev view — a low-stakes read, never a wall.
  const [vaultStatus, setVaultStatus] = useState<AuthSessionStatus | null>(null);

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

  const handleAction = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      if (localDev.status?.authenticated) {
        await localDev.logout();
      } else {
        await localDev.start();
      }
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : "No se pudo actualizar la sesión local",
      );
    } finally {
      setActionLoading(false);
    }
  };

  // Credentials vault mode: Account section (session + credential management).
  if (vaultStatus?.mode === "credentials") {
    return <AccountSection status={vaultStatus} />;
  }

  // Local-dev / disabled: legacy panel (unchanged).
  if (localDev.isLoading) {
    return (
      <div className="flex items-center gap-2 py-6 text-small text-muted">
        <Spinner size="sm" /> Comprobando sesión local…
      </div>
    );
  }

  if (localDev.error) {
    return <p className="text-small text-status-error">{localDev.error.message}</p>;
  }

  if (!localDev.status) return null;

  return (
    <div className="rounded-lg border border-edge bg-surface-raised p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-heading text-body text-primary">Sesión de edición</h3>
        <span className="text-small text-muted">Local</span>
      </div>

      {localDev.status.authenticated && (
        <>
          <p className="mt-3 text-small text-status-success">Sesión local activa</p>
          <p className="mt-1 text-small text-muted">{localDev.status.label}</p>
          <Button
            variant="secondary"
            onClick={() => void handleAction()}
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
            Sesión local no iniciada. Iniciala para editar y configurar el perfil.
          </p>
          <Button
            variant="primary"
            onClick={() => void handleAction()}
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
          <code className="text-icon-muted">DEMIURGOS_AUTH_MODE=local-dev</code> en{" "}
          <code className="text-icon-muted">.env</code> para probar la edición.
        </p>
      )}

      {actionError && <p className="mt-3 text-small text-status-error">{actionError}</p>}
    </div>
  );
}

/**
 * Credentials Account section (R-AC-05, replaces the vault session panel):
 * session info + logout, the soft re-auth indicator (R-AC-04d), and the
 * credential-management actions — change username, change/remove password and
 * rotate the recovery words — each gated on the recovery words (ownership
 * key). The words are NEVER displayed here (S-AC-01c); rotation returns new
 * plaintext words exactly once.
 */
function AccountSection({ status }: { status: AuthSessionStatus }) {
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const daysUntilReauth =
    status.authenticated && typeof status.days_until_reauth === "number"
      ? status.days_until_reauth
      : null;

  const handleLogout = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      await logoutSession();
      reloadPage();
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : "No se pudo cerrar la sesión",
      );
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="rounded-lg border border-edge bg-surface-raised p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-heading text-body text-primary">Cuenta</h3>
        <span className="text-small text-muted">Credenciales</span>
      </div>

      {status.authenticated ? (
        <>
          <p className="mt-3 text-small text-status-success">Sesión activa</p>
          <p className="mt-1 text-small text-muted">{status.label}</p>
          <p className="mt-1 text-small text-muted">
            Proveedor: {providerLabel(status.provider)}
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
      )}

      {actionError && <p className="mt-3 text-small text-status-error">{actionError}</p>}

      <div className="mt-5 space-y-4 border-t border-edge pt-4">
        <WordsForm
          title="Cambiar usuario"
          description="Demostrá que la cuenta es tuya con tus palabras claves y elegí un nuevo usuario."
          extraLabel="Nuevo usuario"
          extraPlaceholder="nuevo-usuario"
          submitLabel="Cambiar usuario"
          busyLabel="Cambiando…"
          onSubmit={async (words, newUsername) => {
            await changeUsername(words, newUsername);
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
          onSubmit={async (words, newPassword) => {
            await changePassword(words, newPassword);
          }}
        />

        <WordsForm
          title="Retirar contraseña"
          description="Tu cuenta pasa a ser sin contraseña: alcanza con el botón Entrar. Lo confirmás con tus palabras claves."
          submitLabel="Retirar contraseña"
          busyLabel="Retirando…"
          confirmLabel="¿Confirmás el retiro?"
          onSubmit={async (words) => {
            await removePassword(words);
          }}
        />

        <RotateWordsCard />
      </div>
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
  onSubmit: (words: string, extra: string) => Promise<void>;
}

/**
 * A words-gated credential action (R-AC-05): recovery words + optional extra
 * value (new username/password). The words are the ownership proof; every
 * action shows its own inline busy/error/success state.
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
  onSubmit,
}: WordsFormProps) {
  const [words, setWords] = useState("");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [confirming, setConfirming] = useState(false);

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
      await onSubmit(words.trim(), extra.trim());
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
        disabled={busy || words.trim() === ""}
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

/**
 * Perfil → Seguridad / Bóveda — the vault lifecycle panel, driven by
 * GET /api/auth/vault/config (`vault.enabled`, the persisted flag + optional
 * env override — NOT the auth-mode string). When the vault is OFF it renders
 * the ACTIVATION panel (create an account with the words shown exactly once,
 * or verify an existing account's words); when ON it renders the MANAGEMENT
 * panel (session, change user/password via words, remove password, rotate
 * words, adjust the soft re-auth interval, and disable with the words).
 */
function VaultSection() {
  const [config, setConfig] = useState<VaultConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = () => {
    setError(null);
    void getVaultConfig()
      .then(setConfig)
      .catch((cause: unknown) => setError(cause))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

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

  return config.enabled ? (
    <ManagementPanel config={config} onChanged={load} />
  ) : (
    <ActivationPanel config={config} onActivated={load} />
  );
}

/** Vault OFF — activation. With no account: create one (username + optional
 *  password); the recovery words are shown EXACTLY once (S-VC-03a). With an
 *  existing account (e.g. a migrated install): verify the words (ownership
 *  proof) before enabling (S-VC-03b/c). */
function ActivationPanel({
  config,
  onActivated,
}: {
  config: VaultConfig;
  onActivated: () => void;
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

/** Vault ON — management: session info + logout, credential management via
 *  the words (change user/password, remove password, rotate words), the soft
 *  re-auth interval, and disabling the vault (words + confirmation). */
function ManagementPanel({
  config,
  onChanged,
}: {
  config: VaultConfig;
  onChanged: () => void;
}) {
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const handleLogout = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      await logoutSession();
      reloadPage();
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : "No se pudo cerrar la sesión",
      );
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="space-y-4">
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
              · forzada por <code className="text-icon-muted">DEMIURGOS_AUTH_MODE</code>
            </span>
          )}
        </p>
        <div className="mt-4">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void handleLogout()}
            disabled={actionLoading}
          >
            {actionLoading ? "Cerrando…" : "Cerrar sesión"}
          </Button>
        </div>
        {actionError && <p className="mt-3 text-small text-status-error">{actionError}</p>}
      </section>

      <div className="space-y-4">
        <WordsForm
          title="Cambiar usuario"
          description="Demostrá que la cuenta es tuya con tus palabras claves y elegí un nuevo usuario."
          extraLabel="Nuevo usuario"
          extraPlaceholder="nuevo-usuario"
          submitLabel="Cambiar usuario"
          busyLabel="Cambiando…"
          onSubmit={async (words, newUsername) => {
            await changeUsername(words, newUsername);
            onChanged();
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
          onSubmit={async (words, newPassword) => {
            await changePassword(words, newPassword);
            onChanged();
          }}
        />

        <WordsForm
          title="Retirar contraseña"
          description="Tu cuenta pasa a ser sin contraseña: alcanza con el botón Entrar. Lo confirmás con tus palabras claves."
          submitLabel="Retirar contraseña"
          busyLabel="Retirando…"
          confirmLabel="¿Confirmás el retiro?"
          onSubmit={async (words) => {
            await removePassword(words);
            onChanged();
          }}
        />

        <RotateWordsCard />

        <ReauthIntervalForm config={config} onSaved={onChanged} />

        <WordsForm
          title="Desactivar bóveda"
          description="Apagar la bóveda quita la autenticación de la instalación. Lo confirmás con tus palabras claves."
          submitLabel="Desactivar bóveda"
          busyLabel="Desactivando…"
          confirmLabel="¿Confirmás la desactivación?"
          onSubmit={async (words) => {
            await disableVault(words);
            onChanged();
          }}
        />
      </div>
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
 * Perfil → Centro de Configuración — the configuration capabilities that have
 * NO home elsewhere in the Profile: Respaldo y restauración, Idioma/región/zona
 * horaria and Offline/dispositivo, plus the essential local readiness summary.
 *
 * The other Configuration Center cards (Identidad, IA texto y visión, Telegram,
 * Mundos, Importar mundo) are intentionally NOT duplicated here — each of those
 * already lives in a dedicated Profile tab (Asistente IA / Mundos /
 * Integraciones) or in the Profile/Taller de Mundo themselves (nav-restructure
 * decision): the idea-capture wizard (with the Telegram bot config folded in)
 * renders under Integraciones and the legacy-folder MigrationPanel under
 * Mundos. State semantics (ONB-3.1/ONB-3.5
 * anti-overstatement guard, OC19 assistant label, OC11/OC21 essential badges)
 * are reused from ConfigurationCenter.tsx so the Profile tabs and the shared
 * module never drift.
 */
function ConfigurationSection() {
  const navigate = useNavigate();
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

            {card.key === "backup" && (
              <>
                <p className="mt-3 text-small text-muted">
                  Pendiente — contrato dedicado en definición
                </p>
                {/* ONB-4.5 (WU-4d) — Backup/restore card: entry only.
                    Google Drive / rclone backup is not implemented in
                    this change; the card stays pending and is only an
                    entry for its dedicated contract. Drive consent is
                    separate from the identity consent, and backup
                    and restore are distinct flows (OC10/OC24). */}
                <div className="mt-4 border-t border-edge pt-4">
                  <p className="text-small text-muted">
                    El respaldo y la restauración (Google Drive / rclone) no están
                    implementados en esta versión: la tarjeta queda pendiente y es solo la
                    entrada para su contrato dedicado. El consentimiento de Drive es
                    independiente del consentimiento de identidad, y respaldo y
                    restauración son flujos distintos. Nunca se afirma configurado sin ese
                    contrato.
                  </p>
                </div>
              </>
            )}

            {card.key === "locale" && card.action && (
              <div className="mt-3">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => navigate(card.action!.to)}
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
    void mutate();
    setTrashRefresh((n) => n + 1);
    setDeleteTarget(null);
  }, [mutate]);

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
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={disabledReason !== null}
                    title={disabledReason ?? undefined}
                    onClick={() => setDeleteTarget(world)}
                  >
                    Borrar
                  </Button>
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
    </div>
  );
}

/**
 * Profile page (`/perfil`) — the unified configuration surface.
 *
 * Sections: Sesión de edición (unified session controls, same as the Navbar
 * dropdown), Centro de Configuración (configuration capabilities without a
 * Profile home: backup, locale, offline + essential readiness), Integraciones
 * (idea-capture wizard — the single Telegram surface, ONB-3.3), Asistente IA
 * (assistant settings) and Mundos (world delete + recycle bin + legacy-folder
 * migration, ONB-4.3). The gated sections depend on the unified session
 * (credentials vault or local-dev), matching the wiki editing boundary.
 */
export default function ProfilePage() {
  const [section, setSection] = useState<ProfileSection>("sesion");

  const tabs: { id: ProfileSection; label: string }[] = [
    { id: "sesion", label: "Sesión de edición" },
    { id: "seguridad", label: "Seguridad / Bóveda" },
    { id: "configuracion", label: "Centro de Configuración" },
    { id: "integraciones", label: "Integraciones" },
    { id: "asistente", label: "Asistente IA" },
    { id: "mundos", label: "Mundos" },
  ];

  return (
    <div className="flex min-h-screen flex-col bg-surface">
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
        <h1 className="font-heading text-h3 text-primary">Perfil</h1>
        <div className="mt-6 flex flex-col gap-6 md:flex-row">
          <nav
            aria-label="Secciones del perfil"
            className="flex gap-1 md:w-56 md:flex-col md:gap-1"
          >
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setSection(tab.id)}
                aria-current={section === tab.id ? "page" : undefined}
                className={cn(
                  "rounded-lg px-3 py-2 text-left text-body transition-colors",
                  section === tab.id
                    ? "bg-surface-raised text-primary"
                    : "text-muted hover:bg-surface-raised hover:text-primary",
                )}
              >
                {tab.label}
              </button>
            ))}
          </nav>
          <section className="min-w-0 flex-1">
            {section === "sesion" ? (
              <SessionSection />
            ) : section === "seguridad" ? (
              <VaultSection />
            ) : section === "configuracion" ? (
              <ConfigurationSection />
            ) : section === "integraciones" ? (
              <IntegrationsSection />
            ) : section === "mundos" ? (
              <WorldsSection />
            ) : (
              <AssistantSection />
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
