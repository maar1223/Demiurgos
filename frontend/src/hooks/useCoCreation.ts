import { useCallback, useEffect, useState } from "react";
import {
  activateCoCreationSession,
  createCoCreationSession,
  materializeCoCreationSession,
  publishCoCreationSession,
  recoverCoCreationSession,
  turnCoCreationSession,
} from "@/api/coCreation";
import type {
  CoCreationActivateResult,
  CoCreationMaterializeMetadata,
  CoCreationMaterializeResult,
  CoCreationPublishResult,
  CoCreationSession,
} from "@/api/types";

const STORAGE_KEY = "demiurgos-co-creation-session";

/** The localStorage entry is ONLY a recovery hint — the backend is the
 *  authoritative session store (durable, principal-bound, revision-guarded). */
function storedSessionId(): string | null {
  try {
    const value = JSON.parse(
      localStorage.getItem(STORAGE_KEY) ?? "null",
    ) as { sessionId?: string } | null;
    return value?.sessionId ?? null;
  } catch {
    return null;
  }
}

function rememberSession(sessionId: string | null): void {
  try {
    if (sessionId) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ sessionId }));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // Browser storage is only a recovery hint; the backend remains authoritative.
  }
}

/** Shared co-creation state distributed across the ToolWorkshop "Crear skill"
 *  panes (sidebar milestones, chat, right context/validation panel). */
export interface UseCoCreationReturn {
  session: CoCreationSession | null;
  /** Immutable published version after the Author approves publishing. */
  published: CoCreationPublishResult | null;
  /** Per-world activation after the Author pins a published version. */
  activation: CoCreationActivateResult | null;
  isLoading: boolean;
  error: string | null;
  /** Start a new session (optionally world-scoped; null = transversal). */
  create: (
    input: string,
    world?: string | null,
  ) => Promise<CoCreationSession | null>;
  /** One Author answer -> one Skill Madre question (starts when no session). */
  send: (input: string) => Promise<CoCreationSession | null>;
  /** Re-read the session from the backend (authoritative). */
  recover: () => Promise<void>;
  /** Author confirms Borrador listo -> draft materialization + compile. */
  materialize: (
    metadata?: CoCreationMaterializeMetadata,
  ) => Promise<CoCreationMaterializeResult | null>;
  /** Author approval -> immutable publish. */
  publish: () => Promise<CoCreationPublishResult | null>;
  /** Author approval -> pin the published version to a world. */
  activate: (world: string) => Promise<CoCreationActivateResult | null>;
  /** Discard the hint and the local session (backend session stays intact). */
  reset: () => void;
}

export function useCoCreation(): UseCoCreationReturn {
  const [session, setSession] = useState<CoCreationSession | null>(null);
  const [published, setPublished] = useState<CoCreationPublishResult | null>(
    null,
  );
  const [activation, setActivation] =
    useState<CoCreationActivateResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Recovery hint -> backend recovery (backend authoritative). A failed
  // recovery clears the hint; a session the server no longer knows is gone.
  useEffect(() => {
    const sessionId = storedSessionId();
    if (!sessionId) return;
    let cancelled = false;
    setIsLoading(true);
    recoverCoCreationSession(sessionId)
      .then((next) => {
        if (!cancelled) setSession(next);
      })
      .catch(() => {
        if (!cancelled) rememberSession(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** Shared success/error path for session-returning calls (create/send). */
  const apply = useCallback((request: () => Promise<CoCreationSession>) => {
    setIsLoading(true);
    setError(null);
    return request()
      .then((next) => {
        setSession(next);
        rememberSession(next.session_id);
        return next;
      })
      .catch((cause) => {
        const message =
          cause instanceof Error
            ? cause.message
            : "Skill co-creation is unavailable.";
        setError(message);
        throw cause;
      })
      .finally(() => setIsLoading(false));
  }, []);

  const create = useCallback(
    (input: string, world?: string | null) => {
      const trimmed = input.trim();
      if (!trimmed) return Promise.resolve(null);
      return apply(() => createCoCreationSession(trimmed, world ?? null));
    },
    [apply],
  );

  const send = useCallback(
    (input: string) => {
      const trimmed = input.trim();
      if (!trimmed) return Promise.resolve(null);
      return apply(() =>
        session
          ? turnCoCreationSession(
              session.session_id,
              session.revision,
              trimmed,
            )
          : createCoCreationSession(trimmed),
      );
    },
    [apply, session],
  );

  const recover = useCallback(async () => {
    const sessionId = storedSessionId();
    if (!sessionId) return;
    setIsLoading(true);
    setError(null);
    try {
      const next = await recoverCoCreationSession(sessionId);
      setSession(next);
      rememberSession(next.session_id);
    } catch (cause) {
      rememberSession(null);
      setError(
        cause instanceof Error
          ? cause.message
          : "Skill co-creation is unavailable.",
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  const materialize = useCallback(
    (metadata?: CoCreationMaterializeMetadata) => {
      if (!session) return Promise.resolve(null);
      setIsLoading(true);
      setError(null);
      return materializeCoCreationSession(
        session.session_id,
        session.revision,
        metadata,
      )
        .then((result) => {
          if (result.ok && result.session_id) {
            // Success returns the full public state: fold the authoritative
            // fields in and keep the rest of the local transcript.
            setSession((current) =>
              current
                ? {
                    ...current,
                    revision: result.revision,
                    phase: result.phase,
                    milestone: result.milestone,
                    draft_id: result.draft_id,
                    compile_issues: result.compile_issues ?? [],
                  }
                : current,
            );
          } else {
            // Compile issues: the session STAYS at borrador_listo for
            // correction (REQ-CC-5); surface the issues in the panel.
            setSession((current) =>
              current
                ? {
                    ...current,
                    compile_issues:
                      result.compile_issues ?? result.issues ?? [],
                  }
                : current,
            );
          }
          return result;
        })
        .catch((cause) => {
          const message =
            cause instanceof Error
              ? cause.message
              : "Skill draft materialization is unavailable.";
          setError(message);
          throw cause;
        })
        .finally(() => setIsLoading(false));
    },
    [session],
  );

  const publish = useCallback(() => {
    if (!session?.draft_id) return Promise.resolve(null);
    setIsLoading(true);
    setError(null);
    return publishCoCreationSession(session.session_id, session.revision)
      .then((result) => {
        setPublished(result);
        setSession((current) =>
          current
            ? { ...current, phase: result.phase, revision: result.revision }
            : current,
        );
        return result;
      })
      .catch((cause) => {
        const message =
          cause instanceof Error
            ? cause.message
            : "Skill publishing is unavailable.";
        setError(message);
        throw cause;
      })
      .finally(() => setIsLoading(false));
  }, [session]);

  const activate = useCallback(
    (world: string) => {
      if (!session) return Promise.resolve(null);
      setIsLoading(true);
      setError(null);
      return activateCoCreationSession(session.session_id, session.revision, world)
        .then((result) => {
          setActivation(result);
          setSession((current) =>
            current
              ? { ...current, phase: result.phase, revision: result.revision }
              : current,
          );
          return result;
        })
        .catch((cause) => {
          const message =
            cause instanceof Error
              ? cause.message
              : "Skill activation is unavailable.";
          setError(message);
          throw cause;
        })
        .finally(() => setIsLoading(false));
    },
    [session],
  );

  const reset = useCallback(() => {
    rememberSession(null);
    setSession(null);
    setPublished(null);
    setActivation(null);
    setError(null);
  }, []);

  return {
    session,
    published,
    activation,
    isLoading,
    error,
    create,
    send,
    recover,
    materialize,
    publish,
    activate,
    reset,
  };
}