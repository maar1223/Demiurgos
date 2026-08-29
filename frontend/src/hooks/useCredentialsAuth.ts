import { useCallback, useEffect, useState } from "react";
import { credentialsLogin, getAuthStatus } from "@/api/wiki";
import { ApiError, type AuthSessionStatus } from "@/api/types";
import { reloadPage } from "@/lib/reloadPage";

export interface CredentialsAuthState {
  /** True only in credentials mode (DEMIURGOS_AUTH_MODE=credentials). */
  enabled: boolean;
  /** Unified session status — carries the soft re-auth countdown fields. */
  status: AuthSessionStatus | null;
  /** Initial status fetch in flight. */
  statusLoading: boolean;
  loginLoading: boolean;
  loginError: string | null;
  /** The last login failed because no account is configured yet (fresh
   *  install) — the UI should route the user to onboarding. */
  noAccount: boolean;
  /** Days until the soft re-auth reminder; null without a credentials
   *  session or when the backend omits the countdown. */
  daysUntilReauth: number | null;
  /** The re-auth interval elapsed (countdown reached 0) — show the banner. */
  reauthDue: boolean;
  /** POST /api/auth/credentials/login; reloads the app on success. */
  login: (password: string, rememberMe: boolean) => Promise<void>;
  clearLoginError: () => void;
}

/**
 * Credentials vault login hook (R-AC-02): password login (when the account
 * has a password), passwordless "Enter" (empty password), the remember-me
 * opt-in, and the session status that powers the soft re-auth countdown
 * (R-AC-04: `last_auth_at` / `days_until_reauth` come from the backend).
 *
 * `enabled` MUST be true only in credentials mode: the login endpoint answers
 * 403 otherwise. Error mapping: 422 = password required, 401 = invalid
 * password or (fresh install) no account configured.
 */
export function useCredentialsAuth(enabled: boolean): CredentialsAuthState {
  const [status, setStatus] = useState<AuthSessionStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [noAccount, setNoAccount] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    setStatusLoading(true);
    void getAuthStatus()
      .then((next) => {
        if (active) setStatus(next);
      })
      .catch(() => {
        // Fail open: a status read failure never blocks the login form.
        if (active) setStatus(null);
      })
      .finally(() => {
        if (active) setStatusLoading(false);
      });
    return () => {
      active = false;
    };
  }, [enabled]);

  const login = useCallback(
    async (password: string, rememberMe: boolean) => {
      setLoginLoading(true);
      setLoginError(null);
      setNoAccount(false);
      try {
        await credentialsLogin(password.trim() ? password : undefined, rememberMe);
        // After a successful login the AuthGate re-evaluates the session
        // cookie; a full reload keeps the app state honest.
        reloadPage();
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 422) {
          setLoginError("Ingresá tu contraseña para continuar.");
        } else if (
          cause instanceof ApiError &&
          cause.status === 401 &&
          cause.detail?.includes("No account configured")
        ) {
          setNoAccount(true);
          setLoginError("Todavía no hay una cuenta configurada en esta instalación.");
        } else {
          setLoginError(
            cause instanceof Error
              ? cause.message
              : "No se pudo iniciar sesión",
          );
        }
      } finally {
        setLoginLoading(false);
      }
    },
    [],
  );

  const clearLoginError = useCallback(() => {
    setLoginError(null);
    setNoAccount(false);
  }, []);

  const isCredentialsSession =
    enabled && status?.provider === "credentials" && status.authenticated;
  const daysUntilReauth =
    isCredentialsSession && typeof status?.days_until_reauth === "number"
      ? status.days_until_reauth
      : null;

  return {
    enabled,
    status,
    statusLoading,
    loginLoading,
    loginError,
    noAccount,
    daysUntilReauth,
    reauthDue: daysUntilReauth !== null && daysUntilReauth <= 0,
    login,
    clearLoginError,
  };
}