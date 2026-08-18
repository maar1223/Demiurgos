import { useEffect, useState } from "react";
import { getOnboardingStatus } from "@/api/onboarding";
import { listWorlds } from "@/api/wiki";

export interface OnboardingGateState {
  loading: boolean;
  needsOnboarding: boolean;
}

/**
 * First-run gate (ONB-1.1): the app redirects to onboarding only when
 * onboarding is not completed AND no world exists yet.
 *
 * An installation that already has a world is usable ("Listo para Trabajar"
 * is satisfiable with local defaults) and must never be forced back into
 * onboarding. On fetch failure the gate fails open to the normal app — this
 * is a UX redirect, not a security boundary; the security boundary is the
 * server-side gated writes.
 */
export function useOnboardingGate(): OnboardingGateState {
  const [state, setState] = useState<OnboardingGateState>({
    loading: true,
    needsOnboarding: false,
  });

  useEffect(() => {
    let active = true;
    void Promise.all([getOnboardingStatus(), listWorlds()])
      .then(([status, worlds]) => {
        if (!active) return;
        setState({
          loading: false,
          needsOnboarding: !status.completed && worlds.length === 0,
        });
      })
      .catch(() => {
        if (!active) return;
        setState({ loading: false, needsOnboarding: false });
      });
    return () => {
      active = false;
    };
  }, []);

  return state;
}