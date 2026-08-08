import { useEffect, useState } from "react";
import {
  getLocalDevSession,
  logoutLocalDevSession,
  startLocalDevSession,
} from "@/api/wiki";
import type { LocalDevSessionStatus } from "@/api/types";

/**
 * Loads local development auth only while the profile control is open.
 * Session material remains in the browser cookie and never enters this state.
 */
export function useLocalDevAuth(isOpen: boolean) {
  const [status, setStatus] = useState<LocalDevSessionStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    let active = true;
    setIsLoading(true);
    setError(null);
    void getLocalDevSession()
      .then((next) => {
        if (active) setStatus(next);
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause : new Error("No se pudo consultar la sesión local"));
        }
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });

    return () => {
      active = false;
    };
  }, [isOpen]);

  const start = async () => {
    const next = await startLocalDevSession();
    setStatus(next);
    return next;
  };

  const logout = async () => {
    const next = await logoutLocalDevSession();
    setStatus(next);
    return next;
  };

  return { status, isLoading, error, start, logout };
}
