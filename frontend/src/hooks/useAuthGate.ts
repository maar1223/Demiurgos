import { useEffect, useState } from "react";
import { getAuthStatus } from "@/api/wiki";

export interface AuthGateState {
  loading: boolean;
  needsLogin: boolean;
  authEnabled: boolean;
}

/**
 * Authentication gate: when auth is enabled (the local vault flag
 * `capabilities.vault.enabled` OR `DEMIURGOS_AUTH_MODE=credentials`, evaluated
 * server-side as `_vault_active()`), the user MUST be authenticated before
 * accessing the application.
 *
 * This is a HARD GATE, not a soft redirect. When auth is enabled and the user
 * is not authenticated, they cannot access any application surface. This
 * prevents the common UX failure where users navigate the app without realizing
 * they need to authenticate, then encounter silent failures on write operations.
 *
 * Server-driven: `enabled` comes verbatim from the unified
 * GET /api/auth/session/status endpoint, whose `enabled` equals `_vault_active()`
 * (R-VC-06). When the vault is OFF the gate always passes through — the
 * Settings panel stays reachable without login (S-VC-06a).
 */
export function useAuthGate(): AuthGateState {
  const [state, setState] = useState<AuthGateState>({
    loading: true,
    needsLogin: false,
    authEnabled: false,
  });

  useEffect(() => {
    let active = true;
    void getAuthStatus()
      .then((status) => {
        if (!active) return;
        setState({
          loading: false,
          needsLogin: status.enabled && !status.authenticated,
          authEnabled: status.enabled,
        });
      })
      .catch(() => {
        if (!active) return;
        // On error, fail open: let the user see the app and handle errors
        // at the operation level. This is a UX gate, not a security boundary.
        setState({ loading: false, needsLogin: false, authEnabled: false });
      });
    return () => {
      active = false;
    };
  }, []);

  return state;
}