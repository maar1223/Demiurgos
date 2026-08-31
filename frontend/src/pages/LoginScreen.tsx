import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { completeRecovery, getAuthStatus, recoverAccount } from "@/api/wiki";
import type { AuthSessionStatus } from "@/api/types";
import { useCredentialsAuth } from "@/hooks/useCredentialsAuth";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";
import { reloadPage } from "@/lib/reloadPage";

/**
 * Full-screen login page (mandatory when DEMIURGOS_AUTH_MODE=local-dev or
 * =credentials).
 *
 * This is the authentication gate: when auth is enabled, the user MUST
 * authenticate before accessing any application surface. Similar to
 * onboarding, this is a blocking screen that cannot be dismissed.
 *
 * Mode-aware:
 * - `credentials` — password login (when the account has one) or "Entrar"
 *   (passwordless), the "Recordarme" opt-in (30d TTL), the
 *   "¿Olvidaste tu contraseña?" recovery flow (words → recovery token →
 *   new credentials) and the soft re-auth banner/countdown (R-AC-04). No
 *   username field: the vault holds a single account.
 * - `local-dev` — the legacy single-button loopback session (unchanged).
 * - `disabled` — never blocks; shows an explanatory card if reached.
 *
 * Warning copy (S-AC-04, neutral Spanish): the soft re-auth reminder is
 * dismissible at ~14d and NEVER a hard block.
 */
export default function LoginScreen() {
  const [status, setStatus] = useState<AuthSessionStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState<Error | null>(null);

  const credentialsEnabled = status?.mode === "credentials";
  const creds = useCredentialsAuth(credentialsEnabled);
  const localDev = useLocalDevAuth(status?.mode === "local-dev");

  const [localActionLoading, setLocalActionLoading] = useState(false);
  const [localActionError, setLocalActionError] = useState<string | null>(null);

  const [reauthDismissed, setReauthDismissed] = useState(false);

  useEffect(() => {
    let active = true;
    void getAuthStatus()
      .then((next) => {
        if (active) setStatus(next);
      })
      .catch((cause: unknown) => {
        if (active) {
          setStatusError(
            cause instanceof Error
              ? cause
              : new Error("No se pudo consultar la sesión"),
          );
        }
      })
      .finally(() => {
        if (active) setStatusLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleLocalLogin = async () => {
    setLocalActionLoading(true);
    setLocalActionError(null);
    try {
      await localDev.start();
      // After successful login, the page will reload and the AuthGate
      // will allow access to the application.
      reloadPage();
    } catch (cause) {
      setLocalActionError(
        cause instanceof Error
          ? cause.message
          : "No se pudo iniciar sesión",
      );
    } finally {
      setLocalActionLoading(false);
    }
  };

  if (statusLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface">
        <div className="flex flex-col items-center gap-4">
          <Spinner size="lg" />
          <p className="text-body text-muted">Verificando sesión…</p>
        </div>
      </div>
    );
  }

  if (statusError && !status) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface px-4">
        <div className="w-full max-w-md rounded-lg border border-status-error/30 bg-surface-raised p-6">
          <h1 className="font-heading text-h3 text-status-error">Error de conexión</h1>
          <p className="mt-3 text-body text-primary">{statusError.message}</p>
          <p className="mt-3 text-small text-muted">
            Verificá que el servidor esté corriendo y recargá la página.
          </p>
        </div>
      </div>
    );
  }

  if (!status) return null;

  // Auth is disabled: this screen should never appear, but if it does,
  // show a clear message instead of blocking the user.
  if (!status.enabled) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface px-4">
        <div className="w-full max-w-md rounded-lg border border-edge bg-surface-raised p-6">
          <h1 className="font-heading text-h3 text-primary">Autenticación desactivada</h1>
          <p className="mt-3 text-body text-muted">
            La autenticación está desactivada. No es necesario iniciar sesión.
          </p>
          <p className="mt-3 text-small text-muted">
            Si querés habilitar la autenticación, configurá{" "}
            <code className="rounded bg-surface px-1.5 py-0.5 text-icon-muted">
              DEMIURGOS_AUTH_MODE
            </code>{" "}
            en <code className="rounded bg-surface px-1.5 py-0.5 text-icon-muted">.env</code>.
          </p>
        </div>
      </div>
    );
  }

  const showReauthBanner =
    creds.enabled &&
    creds.status?.authenticated &&
    creds.reauthDue &&
    !reauthDismissed;

  // Auth is enabled but the user is not authenticated: show login screen.
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4">
      <div className="w-full max-w-md rounded-lg border border-edge bg-surface-raised p-6">
        {showReauthBanner && (
          <ReauthBanner onDismiss={() => setReauthDismissed(true)} />
        )}

        <h1 className="font-heading text-h3 text-primary">Bienvenido a Demiurgos</h1>
        <p className="mt-3 text-body text-muted">
          Iniciá sesión para acceder al Taller de Mundo y todas sus capacidades.
        </p>

        {status.authenticated ? (
          <div className="mt-6">
            {creds.daysUntilReauth !== null && (
              <div
                role="status"
                className="mb-4 rounded-lg border border-edge bg-surface/50 p-3"
              >
                <p className="text-small text-primary">
                  {creds.reauthDue
                    ? "Reingreso recomendado: hoy"
                    : `Reingreso recomendado en ${creds.daysUntilReauth} día${creds.daysUntilReauth === 1 ? "" : "s"}`}
                </p>
                <p className="mt-2 text-small text-muted">
                  Si no reingresas tu contraseña, la sesión de Demiurgos se
                  cerrará. Y si olvidaste tu contraseña, solo vas a poder
                  recuperarla con tus palabras claves.
                </p>
              </div>
            )}
            <p className="text-small text-status-success">Sesión activa</p>
            <p className="mt-1 text-small text-muted">{status.label}</p>
            <p className="mt-3 text-small text-muted">
              Redirigiendo a la aplicación…
            </p>
          </div>
        ) : creds.enabled ? (
          <CredentialsLogin
            currentUsername={status.label ?? undefined}
            loginLoading={creds.loginLoading}
            loginError={creds.loginError}
            noAccount={creds.noAccount}
            hasPassword={creds.hasPassword}
            onLogin={(password, rememberMe) =>
              void creds.login(password, rememberMe)
            }
            onClearError={creds.clearLoginError}
          />
        ) : (
          <LocalDevLogin
            authenticated={localDev.status?.authenticated ?? false}
            label={localDev.status?.label ?? null}
            isLoading={localDev.isLoading}
            error={localDev.error}
            actionLoading={localActionLoading}
            actionError={localActionError}
            onLogin={() => void handleLocalLogin()}
          />
        )}
      </div>
    </div>
  );
}

/** Dismissible soft re-auth reminder (R-AC-04, S-AC-04a/c). Never a hard
 *  block — dismissing only hides the banner for this page view. */
function ReauthBanner({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div
      role="alert"
      className="mb-5 rounded-lg border border-action/40 bg-action/10 p-3"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-small text-primary">
          Si no reingresas tu contraseña, la sesión de Demiurgos se cerrará. Y
          si olvidaste tu contraseña, solo vas a poder recuperarla con tus
          palabras claves.
        </p>
        <button
          type="button"
          aria-label="Descartar aviso"
          onClick={onDismiss}
          className="shrink-0 rounded px-1.5 text-small text-muted hover:text-primary"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

interface CredentialsLoginProps {
  currentUsername?: string;
  loginLoading: boolean;
  loginError: string | null;
  noAccount: boolean;
  /** False hides the password field (passwordless account, S-AC-02b). */
  hasPassword: boolean | null;
  onLogin: (password: string, rememberMe: boolean) => void;
  onClearError: () => void;
}

/**
 * Credentials login block: the password input (or the "Entrar" button for a
 * passwordless account — decided by the backend `has_password` flag,
 * S-AC-02b), the remember-me opt-in and the "¿Olvidaste tu contraseña?"
 * recovery flow. There is intentionally NO username field: the vault holds a
 * single account (R-AC-02).
 */
function CredentialsLogin({
  currentUsername,
  loginLoading,
  loginError,
  noAccount,
  hasPassword,
  onLogin,
  onClearError,
}: CredentialsLoginProps) {
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [recoveryOpen, setRecoveryOpen] = useState(false);

  if (recoveryOpen) {
    return (
      <RecoveryFlow
        currentUsername={currentUsername}
        onClose={() => {
          setRecoveryOpen(false);
          onClearError();
        }}
      />
    );
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onLogin(password, rememberMe);
  };

  return (
    <form onSubmit={handleSubmit} className="mt-6">
      <div className="flex flex-col gap-3">
        {hasPassword !== false && (
          <>
            <label htmlFor="credentials-password" className="sr-only">
              Contraseña
            </label>
            <input
              id="credentials-password"
              type="password"
              autoComplete="current-password"
              placeholder="Contraseña"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                onClearError();
              }}
              className="w-full rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary placeholder:text-muted focus:border-icon-muted focus:outline-none"
            />
          </>
        )}

        <label className="flex items-center gap-2 text-small text-muted">
          <input
            type="checkbox"
            checked={rememberMe}
            onChange={(event) => setRememberMe(event.target.checked)}
            className="h-4 w-4 rounded border-edge bg-surface accent-status-success"
          />
          Recordarme por 30 días
        </label>

        <Button
          type="submit"
          variant="primary"
          disabled={loginLoading}
          className="w-full"
        >
          {loginLoading ? (
            <span className="flex items-center justify-center gap-2">
              <Spinner size="sm" />
              Iniciando sesión…
            </span>
          ) : (
            "Entrar"
          )}
        </Button>
      </div>

      <p className="mt-3 text-center text-small text-muted">
        La sesión es local y segura. No requiere credenciales externas.
      </p>

      {loginError && (
        <p className="mt-3 text-small text-status-error" role="alert">
          {loginError}
        </p>
      )}

      {noAccount && (
        <p className="mt-3 text-small text-muted">
          ¿Primera vez?{" "}
          <Link to="/onboarding" className="text-icon-muted underline">
            Configurá tu cuenta
          </Link>{" "}
          para poder entrar.
        </p>
      )}

      <div className="mt-4 border-t border-edge pt-3 text-center">
        <button
          type="button"
          onClick={() => setRecoveryOpen(true)}
          className="text-small text-icon-muted underline hover:text-primary"
        >
          ¿Olvidaste tu contraseña?
        </button>
      </div>
    </form>
  );
}

/**
 * Recovery flow (R-AC-05): prove ownership with the recovery words to obtain
 * a short-lived single-use token, then set a new username/password (at least
 * one required). On success the user returns to the login form.
 */
function RecoveryFlow({
  currentUsername,
  onClose,
}: {
  currentUsername?: string;
  onClose: () => void;
}) {
  const [words, setWords] = useState("");
  const [recoveryToken, setRecoveryToken] = useState<string | null>(null);
  const [newUsername, setNewUsername] = useState(currentUsername ?? "");
  const [newPassword, setNewPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const handleRecover = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { recovery_token } = await recoverAccount(words.trim());
      setRecoveryToken(recovery_token);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No se pudieron verificar las palabras de recuperación",
      );
    } finally {
      setBusy(false);
    }
  };

  const handleComplete = async (event: FormEvent) => {
    event.preventDefault();
    if (!recoveryToken) return;
    setBusy(true);
    setError(null);
    try {
      await completeRecovery(
        recoveryToken,
        newUsername.trim() || undefined,
        newPassword || undefined,
      );
      setDone(true);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "No se pudieron actualizar las credenciales",
      );
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="mt-6">
        <div
          role="status"
          className="rounded-lg border border-status-success/40 bg-surface/50 p-3"
        >
          <p className="text-small text-status-success">
            Credenciales actualizadas. Iniciá sesión con tus nuevos datos.
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={onClose}
          className="mt-4 w-full"
        >
          Volver al inicio de sesión
        </Button>
      </div>
    );
  }

  if (!recoveryToken) {
    return (
      <form onSubmit={handleRecover} className="mt-6">
        <h2 className="font-heading text-body text-primary">
          Recuperar cuenta
        </h2>
        <p className="mt-1 text-small text-muted">
          Ingresá tus palabras claves para demostrar que la cuenta es tuya y
          poder cambiar el usuario o la contraseña.
        </p>
        <label htmlFor="recovery-words" className="sr-only">
          Palabras claves
        </label>
        <input
          id="recovery-words"
          type="text"
          autoComplete="off"
          placeholder="Palabras claves"
          value={words}
          onChange={(event) => setWords(event.target.value)}
          className="mt-3 w-full rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary placeholder:text-muted focus:border-icon-muted focus:outline-none"
        />
        <Button
          type="submit"
          variant="primary"
          disabled={busy || words.trim() === ""}
          className="mt-3 w-full"
        >
          {busy ? "Verificando…" : "Recuperar"}
        </Button>
        {error && (
          <p className="mt-3 text-small text-status-error" role="alert">
            {error}
          </p>
        )}
        <div className="mt-4 border-t border-edge pt-3 text-center">
          <button
            type="button"
            onClick={onClose}
            className="text-small text-icon-muted underline hover:text-primary"
          >
            Volver al inicio de sesión
          </button>
        </div>
      </form>
    );
  }

  return (
    <form onSubmit={handleComplete} className="mt-6">
      <h2 className="font-heading text-body text-primary">
        Cambiar usuario o contraseña
      </h2>
      <p className="mt-1 text-small text-muted">
        Completá al menos un campo. La contraseña es opcional: si la dejás
        vacía y ya existe, se conserva.
      </p>

      <label htmlFor="recovery-username" className="mt-3 block text-small text-primary">
        Usuario
        <input
          id="recovery-username"
          type="text"
          autoComplete="username"
          value={newUsername}
          onChange={(event) => setNewUsername(event.target.value)}
          className="mt-1 w-full rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary focus:border-icon-muted focus:outline-none"
        />
      </label>

      <label htmlFor="recovery-password" className="mt-3 block text-small text-primary">
        Nueva contraseña (opcional)
        <input
          id="recovery-password"
          type="password"
          autoComplete="new-password"
          value={newPassword}
          onChange={(event) => setNewPassword(event.target.value)}
          className="mt-1 w-full rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary focus:border-icon-muted focus:outline-none"
        />
      </label>

      <Button
        type="submit"
        variant="primary"
        disabled={busy}
        className="mt-4 w-full"
      >
        {busy ? "Guardando…" : "Guardar cambios"}
      </Button>
      {error && (
        <p className="mt-3 text-small text-status-error" role="alert">
          {error}
        </p>
      )}
      <div className="mt-4 border-t border-edge pt-3 text-center">
        <button
          type="button"
          onClick={onClose}
          className="text-small text-icon-muted underline hover:text-primary"
        >
          Volver al inicio de sesión
        </button>
      </div>
    </form>
  );
}

interface LocalDevLoginProps {
  authenticated: boolean;
  label: string | null;
  isLoading: boolean;
  error: Error | null;
  actionLoading: boolean;
  actionError: string | null;
  onLogin: () => void;
}

/** Legacy local-dev login block: a single loopback session button. */
function LocalDevLogin({
  authenticated,
  label,
  isLoading,
  error,
  actionLoading,
  actionError,
  onLogin,
}: LocalDevLoginProps) {
  if (isLoading) {
    return (
      <div className="mt-6 flex items-center gap-2 text-small text-muted">
        <Spinner size="sm" /> Verificando sesión local…
      </div>
    );
  }

  if (error) {
    return <p className="mt-4 text-small text-status-error">{error.message}</p>;
  }

  return (
    <div className="mt-6">
      {authenticated ? (
        <div>
          <p className="text-small text-status-success">Sesión local activa</p>
          <p className="mt-1 text-small text-muted">{label}</p>
          <p className="mt-3 text-small text-muted">
            Redirigiendo a la aplicación…
          </p>
        </div>
      ) : (
        <div>
          <Button
            variant="primary"
            onClick={onLogin}
            disabled={actionLoading}
            className="w-full"
          >
            {actionLoading ? (
              <span className="flex items-center justify-center gap-2">
                <Spinner size="sm" />
                Iniciando sesión…
              </span>
            ) : (
              "Iniciar sesión local"
            )}
          </Button>
          <p className="mt-3 text-center text-small text-muted">
            La sesión es local y segura. No requiere credenciales externas.
          </p>
        </div>
      )}

      {actionError && (
        <div className="mt-4 rounded-lg border border-status-error/30 bg-status-error/10 p-3">
          <p className="text-small text-status-error">{actionError}</p>
        </div>
      )}
    </div>
  );
}