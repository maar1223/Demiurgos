import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { getGoogleNonce, startGoogleSession } from "@/api/wiki";
import { reloadPage } from "@/lib/reloadPage";

/**
 * Google Identity Services script-load state.
 *
 * The library context (`useGoogleOAuth`) only exposes
 * `scriptLoadedSuccessfully`, which is `false` BOTH while the script is still
 * loading AND after it failed — it cannot distinguish the two. So the
 * provider's `onScriptLoadError` callback is threaded explicitly through this
 * context: App.tsx sets it, consumers (LoginScreen) read it to fall back to
 * the emergency key.
 */
export const GoogleScriptErrorContext = createContext<boolean>(false);

export interface GoogleAuthState {
  /** "Recordarme" opt-in → 14d session TTL instead of the 8h default. */
  rememberMe: boolean;
  setRememberMe: (remember: boolean) => void;
  /**
   * Server-issued nonce (GET /api/auth/google/nonce) that MUST be embedded in
   * the id_token claim. The Google button renders only once it is available.
   */
  nonce: string | null;
  /** The nonce endpoint failed → Google login cannot start. */
  nonceFailed: boolean;
  /** The GSI script failed to load (set by App's GoogleOAuthProvider). */
  scriptError: boolean;
  /** Last Google flow / session-start error message. */
  error: string | null;
  /** POST the id_token; reloads the app on success. */
  startGoogle: (credential: string) => Promise<void>;
  /** GIS `onError` callback → surface the emergency-key fallback. */
  handleGoogleError: () => void;
}

/**
 * Google vault login hook.
 *
 * Fetches the server-bound nonce, exchanges the id_token returned by Google
 * Identity Services for a vault session cookie, and exposes the remember-me
 * opt-in. `enabled` MUST be true only in google auth mode
 * (DEMIURGOS_AUTH_MODE=google): the nonce endpoint answers 403 otherwise.
 */
export function useGoogleAuth(enabled: boolean): GoogleAuthState {
  const scriptError = useContext(GoogleScriptErrorContext);
  const [rememberMe, setRememberMe] = useState(false);
  const [nonce, setNonce] = useState<string | null>(null);
  const [nonceFailed, setNonceFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    setNonce(null);
    setNonceFailed(false);
    void getGoogleNonce()
      .then(({ nonce: next }) => {
        if (active) setNonce(next);
      })
      .catch(() => {
        if (active) setNonceFailed(true);
      });
    return () => {
      active = false;
    };
  }, [enabled]);

  const startGoogle = useCallback(
    async (credential: string) => {
      setError(null);
      try {
        await startGoogleSession(credential, rememberMe);
        // After a successful login the AuthGate re-evaluates the session
        // cookie; a full reload keeps the app state honest.
        reloadPage();
      } catch (cause) {
        setError(
          cause instanceof Error
            ? cause.message
            : "No se pudo iniciar sesión con Google",
        );
      }
    },
    [rememberMe],
  );

  const handleGoogleError = useCallback(() => {
    setError(
      "No se pudo completar el inicio de sesión con Google. Probá con la clave de emergencia.",
    );
  }, []);

  return {
    rememberMe,
    setRememberMe,
    nonce,
    nonceFailed,
    scriptError,
    error,
    startGoogle,
    handleGoogleError,
  };
}