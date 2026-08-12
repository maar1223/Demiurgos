import { useCallback, useEffect, useState } from "react";
import {
  acceptGuidedCharacterProposal,
  continueGuidedCharacter,
  recoverGuidedCharacter,
  rejectGuidedCharacterProposal,
  retryGuidedCharacterIndex,
  startGuidedCharacter,
} from "@/api/guidedCharacter";
import type { GuidedCharacterSession } from "@/api/types";

const STORAGE_KEY = "demiurgos-guided-character-session";

function storedSessionId(world: string): string | null {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as { world?: string; sessionId?: string } | null;
    return value?.world === world && value.sessionId ? value.sessionId : null;
  } catch {
    return null;
  }
}

function rememberSession(world: string, sessionId: string | null): void {
  try {
    if (sessionId) localStorage.setItem(STORAGE_KEY, JSON.stringify({ world, sessionId }));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Browser storage is only a recovery hint; the backend remains authoritative.
  }
}

export function useGuidedCharacter(world: string) {
  const [session, setSession] = useState<GuidedCharacterSession | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const sessionId = storedSessionId(world);
    if (!sessionId) return;
    let cancelled = false;
    setIsLoading(true);
    recoverGuidedCharacter(world, sessionId)
      .then((next) => { if (!cancelled) setSession(next); })
      .catch(() => { if (!cancelled) rememberSession(world, null); })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
  }, [world]);

  const apply = useCallback((request: () => Promise<GuidedCharacterSession>) => {
    setIsLoading(true);
    setError(null);
    return request()
      .then((next) => {
        setSession(next);
        rememberSession(world, next.session_id);
        return next;
      })
      .catch((cause) => {
        const message = cause instanceof Error ? cause.message : "Guided creation is unavailable.";
        setError(message);
        throw cause;
      })
      .finally(() => setIsLoading(false));
  }, [world]);

  const send = useCallback((input: string) => {
    const trimmed = input.trim();
    if (!trimmed) return Promise.resolve(null);
    return apply(() => session
      ? continueGuidedCharacter(world, session.session_id, session.revision, trimmed)
      : startGuidedCharacter(world, trimmed));
  }, [apply, session, world]);

  const accept = useCallback(() => {
    if (!session?.proposal) return Promise.resolve(null);
    return apply(() => acceptGuidedCharacterProposal(world, session.session_id, session.revision, session.proposal!.key));
  }, [apply, session, world]);

  const reject = useCallback(() => {
    if (!session?.proposal) return Promise.resolve(null);
    return apply(() => rejectGuidedCharacterProposal(world, session.session_id, session.revision, session.proposal!.key));
  }, [apply, session, world]);

  const retryIndex = useCallback(() => {
    if (!session) return Promise.resolve(null);
    return apply(() => retryGuidedCharacterIndex(world, session.session_id, session.revision));
  }, [apply, session, world]);

  return { session, isLoading, error, send, accept, reject, retryIndex };
}
