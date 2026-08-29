import { useEffect, useState } from "react";
import { getAuthStatus } from "@/api/wiki";
import type { AuthSessionStatus } from "@/api/types";

/**
 * Loads the unified mode-aware session status (GET /api/auth/session/status)
 * only while `active` is true. Works for every auth mode (disabled, local-dev,
 * credentials): the status carries the mode, whether auth is enabled and
 * whether a session is authenticated.
 *
 * Fail-open: on error the status stays null and `error` is populated — the
 * caller decides how to react (the profile panels show a connection message,
 * never a session wall). The request is cancelled on unmount.
 */
export function useAuthSession(active: boolean) {
  const [status, setStatus] = useState<AuthSessionStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!active) return;

    let activeRequest = true;
    setIsLoading(true);
    setError(null);
    void getAuthStatus()
      .then((next) => {
        if (activeRequest) setStatus(next);
      })
      .catch((cause: unknown) => {
        if (activeRequest) {
          setError(
            cause instanceof Error
              ? cause
              : new Error("No se pudo consultar la sesión"),
          );
        }
      })
      .finally(() => {
        if (activeRequest) setIsLoading(false);
      });

    return () => {
      activeRequest = false;
    };
  }, [active]);

  return { status, isLoading, error };
}