import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { completeRecovery, getAuthStatus, recoverAccount } from "@/api/wiki";
import type { AuthSessionStatus } from "@/api/types";
import { useCredentialsAuth } from "@/hooks/useCredentialsAuth";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";
import { useAppLanguage } from "@/hooks/useAppLanguage";
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
  const { t } = useAppLanguage();
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
              : new Error(t("login.error.status")),
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
          : t("login.error.local"),
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
          <p className="text-body text-muted">{t("login.checking")}</p>
        </div>
      </div>
    );
  }

  if (statusError && !status) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface px-4">
        <div className="w-full max-w-md rounded-lg border border-status-error/30 bg-surface-raised p-6">
          <h1 className="font-heading text-h3 text-status-error">{t("login.connectionError")}</h1>
          <p className="mt-3 text-body text-primary">{statusError.message}</p>
          <p className="mt-3 text-small text-muted">
            {t("login.serverHint")}
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
          <h1 className="font-heading text-h3 text-primary">{t("login.disabled.title")}</h1>
          <p className="mt-3 text-body text-muted">
            {t("login.disabled.body")}
          </p>
          <p className="mt-3 text-small text-muted">
            {t("login.disabled.hint")}{" "}
            <code className="rounded bg-surface px-1.5 py-0.5 text-icon-muted">
              DEMIURGOS_AUTH_MODE
            </code>{" "}
            {t("login.disabled.hintTail")}{" "}<code className="rounded bg-surface px-1.5 py-0.5 text-icon-muted">.env</code>.
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

        <h1 className="font-heading text-h3 text-primary">{t("login.welcome")}</h1>
        <p className="mt-3 text-body text-muted">
          {t("login.intro")}
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
                    ? t("login.reauthToday")
                    : creds.daysUntilReauth === 1
                      ? t("login.reauthInDaysOne")
                      : t("login.reauthInDaysMany", {
                          days: creds.daysUntilReauth,
                        })}
                </p>
                <p className="mt-2 text-small text-muted">
                  {t("login.reauthWarning")}
                </p>
              </div>
            )}
            <p className="text-small text-status-success">{t("login.sessionActive")}</p>
            <p className="mt-1 text-small text-muted">{status.label}</p>
            <p className="mt-3 text-small text-muted">
              {t("login.redirecting")}
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
  const { t } = useAppLanguage();
  return (
    <div
      role="alert"
      className="mb-5 rounded-lg border border-action/40 bg-action/10 p-3"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-small text-primary">{t("login.reauthWarning")}</p>
        <button
          type="button"
          aria-label={t("login.dismissAria")}
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
  const { t } = useAppLanguage();
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
              {t("login.password")}
            </label>
            <input
              id="credentials-password"
              type="password"
              autoComplete="current-password"
              placeholder={t("login.password")}
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
          {t("login.rememberMe")}
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
              {t("login.signingIn")}
            </span>
          ) : (
            t("login.enter")
          )}
        </Button>
      </div>

      <p className="mt-3 text-center text-small text-muted">
        {t("login.localNote")}
      </p>

      {loginError && (
        <p className="mt-3 text-small text-status-error" role="alert">
          {loginError}
        </p>
      )}

      {noAccount && (
        <p className="mt-3 text-small text-muted">
          {t("login.noAccount")}{" "}
          <Link to="/onboarding" className="text-icon-muted underline">
            {t("login.configureAccount")}
          </Link>{" "}
          {t("login.noAccountTail")}
        </p>
      )}

      <div className="mt-4 border-t border-edge pt-3 text-center">
        <button
          type="button"
          onClick={() => setRecoveryOpen(true)}
          className="text-small text-icon-muted underline hover:text-primary"
        >
          {t("login.forgotPassword")}
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
  const { t } = useAppLanguage();
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
          : t("login.recovery.wordsError"),
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
          : t("login.recovery.credentialsError"),
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
            {t("login.recovery.done")}
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={onClose}
          className="mt-4 w-full"
        >
          {t("login.recovery.back")}
        </Button>
      </div>
    );
  }

  if (!recoveryToken) {
    return (
      <form onSubmit={handleRecover} className="mt-6">
        <h2 className="font-heading text-body text-primary">
          {t("login.recovery.title")}
        </h2>
        <p className="mt-1 text-small text-muted">
          {t("login.recovery.intro")}
        </p>
        <label htmlFor="recovery-words" className="sr-only">
          {t("login.recovery.words")}
        </label>
        <input
          id="recovery-words"
          type="text"
          autoComplete="off"
          placeholder={t("login.recovery.words")}
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
          {busy ? t("login.recovery.verifying") : t("login.recovery.submit")}
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
            {t("login.recovery.back")}
          </button>
        </div>
      </form>
    );
  }

  return (
    <form onSubmit={handleComplete} className="mt-6">
      <h2 className="font-heading text-body text-primary">
        {t("login.recovery.changeTitle")}
      </h2>
      <p className="mt-1 text-small text-muted">
        {t("login.recovery.changeIntro")}
      </p>

      <label htmlFor="recovery-username" className="mt-3 block text-small text-primary">
        {t("login.recovery.username")}
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
        {t("login.recovery.newPassword")}
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
        {busy ? t("login.recovery.saving") : t("login.recovery.save")}
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
          {t("login.recovery.back")}
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
  const { t } = useAppLanguage();
  if (isLoading) {
    return (
      <div className="mt-6 flex items-center gap-2 text-small text-muted">
        <Spinner size="sm" /> {t("login.local.checking")}
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
          <p className="text-small text-status-success">{t("login.local.active")}</p>
          <p className="mt-1 text-small text-muted">{label}</p>
          <p className="mt-3 text-small text-muted">
            {t("login.redirecting")}
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
                {t("login.signingIn")}
              </span>
            ) : (
              t("login.local.start")
            )}
          </Button>
          <p className="mt-3 text-center text-small text-muted">
            {t("login.localNote")}
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