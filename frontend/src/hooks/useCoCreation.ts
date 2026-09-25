import { useCallback, useEffect, useRef, useState } from "react";
import {
  activateCoCreationSession,
  createCoCreationSession,
  deriveDraft as deriveDraftApi,
  getPublishedDetail as getPublishedDetailApi,
  listHistory as listHistoryApi,
  materializeCoCreationSession,
  publishCoCreationSession,
  recoverCoCreationSession,
  restoreHistory as restoreHistoryApi,
  setPendingQuestionStatus as setPendingQuestionStatusApi,
  setWarningStatus as setWarningStatusApi,
  turnCoCreationSession,
  updateCanvas as updateCanvasApi,
  uploadCoCreationAdjunto,
  validatePayload as validatePayloadApi,
} from "@/api/coCreation";
import { ApiError } from "@/api/types";
import { tStatic } from "@/lib/utils";
import type {
  CoCreationActivateResult,
  CoCreationDeriveResult,
  CoCreationMaterializeMetadata,
  CoCreationMaterializeResult,
  CoCreationPublishResult,
  CoCreationRestoreResult,
  CoCreationSession,
  CoCreationValidationResult,
  DerivedFrom,
  DraftHistoryEntry,
  DraftPayload,
  MethodologyAdjunto,
  PublishedMethodologyDetail,
  WarningState,
} from "@/api/types";

const STORAGE_KEY = "demiurgos-co-creation-session";

/** Debounce window for canvas autosave (REQ-CC-15): edits coalesce into one
 *  PUT /canvas after this much idle time. */
const AUTOSAVE_DEBOUNCE_MS = 800;

/** Optional hook configuration (tests shorten the autosave debounce). */
export interface UseCoCreationOptions {
  autosaveDebounceMs?: number;
}

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
 *  panes (sidebar milestones, chat, canvas, right context/validation panel). */
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
  /** One Author answer -> one Skill Madre question (starts when no session).
   *  Pending canvas edits are flushed BEFORE the turn so the Skill Madre sees
   *  the latest payload (REQ-CC-12 bidirectional sync). */
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

  // -- TW12 canvas (REQ-CC-11/15) ------------------------------------------

  /** Local editable copy of the session's structured draft payload. The
   *  backend is authoritative: server-driven changes (chat merges, restores,
   *  derive seeds) resync this value. */
  draftPayload: DraftPayload | null;
  /** TW16 attribution (REQ-TW16-3): coarse `DraftPayload` section keys the
   *  Author touched in the canvas during this session; empty set means nothing
   *  was touched (all sections read "propuesto por el Asistente"). */
  touchedSections: Set<string>;
  /** Autosave/validation error surfaced in the canvas toolbar. */
  canvasError: string | null;
  /** Apply an Author section edit locally, push the previous payload onto the
   *  in-memory undo stack, and schedule the debounced autosave. The payload
   *  NEVER carries `pending_questions` changes (REQ-CC-14: chat-owned). */
  editCanvas: (patch: Partial<DraftPayload>) => void;
  /** Traverse the in-memory edit stack (REQ-CC-15). Persisted restores pull
   *  snapshots through the revision-guarded history API instead. */
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  isSavingCanvas: boolean;
  /** Pure render+compile preview (REQ-CC-13); never creates or publishes. */
  validateCanvas: () => Promise<CoCreationValidationResult | null>;
  validation: CoCreationValidationResult | null;
  isValidating: boolean;
  /** Load the immutable autosave snapshot list (REQ-CC-15). */
  loadHistory: () => Promise<DraftHistoryEntry[]>;
  historyEntries: DraftHistoryEntry[];
  isLoadingHistory: boolean;
  /** Revision-guarded snapshot restore (REQ-CC-15). */
  restoreSnapshot: (revision: number) => Promise<CoCreationRestoreResult | null>;
  isRestoring: boolean;
  restoreError: string | null;
  /** Author-only warning transition (REQ-CC-13). */
  setWarningStatus: (idx: number, state: WarningState) => Promise<void>;
  /** Author-only pending-question transition (REQ-CC-14). */
  setPendingQuestionStatus: (
    idx: number,
    state: WarningState,
  ) => Promise<void>;

  // -- TW16 exemplar authoring (REQ-CC-24) --------------------------------

  /** Stage ONE exemplar through the upload route and fold its pin into the
   *  canvas payload via the shared edit path, so `adjuntos` is attributed as
   *  Author-touched (TW16) and autosaved. Returns the pin, or null on failure
   *  (the error is surfaced in `canvasError`). */
  uploadAdjunto: (
    file: File,
    nivel: string,
  ) => Promise<MethodologyAdjunto | null>;
  /** Remove a pinned exemplar by its basename path through the canvas-payload
   *  edit path (the route map exposes no dedicated remove endpoint). */
  removeAdjunto: (path: string) => void;
  /** An exemplar upload is in flight (disables the canvas add controls). */
  isUploadingAdjunto: boolean;

  // -- TW13/TW14 adaptation + provenance -----------------------------------

  /** Derive an adaptation draft from a PUBLISHED skill and load the new
   *  session (REQ-CC-16/17/20). The client sends ONLY the original identity. */
  derive: (
    skillId: string,
    version: string,
    world?: string | null,
  ) => Promise<CoCreationDeriveResult | null>;
  /** Full published version + source for the TW13 compare view. */
  getPublishedDetail: (
    skillId: string,
    version: string,
  ) => Promise<PublishedMethodologyDetail>;
  /** Server-injected provenance (TW14); null for non-derived sessions. */
  derivedFrom: DerivedFrom | null;
}

export function useCoCreation(
  options: UseCoCreationOptions = {},
): UseCoCreationReturn {
  const autosaveDebounceMs = options.autosaveDebounceMs ?? AUTOSAVE_DEBOUNCE_MS;
  const [session, setSession] = useState<CoCreationSession | null>(null);
  const [published, setPublished] = useState<CoCreationPublishResult | null>(
    null,
  );
  const [activation, setActivation] =
    useState<CoCreationActivateResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // -- TW12 canvas state ---------------------------------------------------

  const [draftPayload, setDraftPayload] = useState<DraftPayload | null>(null);
  const [past, setPast] = useState<DraftPayload[]>([]);
  const [future, setFuture] = useState<DraftPayload[]>([]);
  const [isSavingCanvas, setIsSavingCanvas] = useState(false);
  const [canvasError, setCanvasError] = useState<string | null>(null);
  const [validation, setValidation] =
    useState<CoCreationValidationResult | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [historyEntries, setHistoryEntries] = useState<DraftHistoryEntry[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isRestoring, setIsRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [isUploadingAdjunto, setIsUploadingAdjunto] = useState(false);
  /** TW16 attribution (REQ-TW16-3): coarse `DraftPayload` section keys the
   *  Author touched in the canvas during THIS session. Session-scoped — a
   *  different session or a reset starts a fresh set. */
  const [touchedSections, setTouchedSections] = useState<Set<string>>(
    () => new Set(),
  );

  // Refs mirroring mutable canvas state so async callbacks (debounce timers,
  // in-flight autosaves) always read the latest values without stale closures.
  const sessionRef = useRef<CoCreationSession | null>(null);
  const payloadRef = useRef<DraftPayload | null>(null);
  const pastRef = useRef<DraftPayload[]>([]);
  const futureRef = useRef<DraftPayload[]>([]);
  /** JSON of the last payload WE sent to the server. The sync effect below
   *  only replaces the working copy when the server holds a payload we did
   *  NOT originate (chat merge, restore, derive seed) — so an unsaved local
   *  edit is never clobbered by our own autosave response. */
  const lastSentPayloadJsonRef = useRef<string | null>(null);
  const autosaveTimerRef = useRef<number | null>(null);
  /** Revision to use for the next autosave once one is in flight (the server
   *  returned it); cleared whenever an external server state resyncs. */
  const pendingRevisionRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  const resetStacks = useCallback(() => {
    pastRef.current = [];
    futureRef.current = [];
    setPast([]);
    setFuture([]);
  }, []);

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

  /** Server-driven canvas resync (REQ-CC-12): when the backend holds a
   *  payload we did NOT autosave (chat merge, restore, derive seed), the
   *  canvas reflects it and the in-memory edit stack resets. Our own autosave
   *  responses fold the payload into the session, so they never trigger here
   *  (JSON-identical -> skipped) and in-flight edits are preserved. */
  useEffect(() => {
    const serverPayload = session?.draft_payload ?? null;
    if (serverPayload === null) {
      setDraftPayload(null);
      resetStacks();
      payloadRef.current = null;
      return;
    }
    const serverJson = JSON.stringify(serverPayload);
    if (serverJson !== lastSentPayloadJsonRef.current) {
      setDraftPayload(serverPayload);
      resetStacks();
      payloadRef.current = serverPayload;
      pendingRevisionRef.current = undefined;
    }
  }, [session, resetStacks]);

  /** TW16 attribution is session-scoped (design D2): the touch set starts
   *  fresh whenever the session identity changes (create, derive seed,
   *  recovery of a different session). Server resyncs WITHIN a session keep
   *  the touches — the Author still decided those sections. */
  useEffect(() => {
    setTouchedSections(new Set());
  }, [session?.session_id]);

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
            : tStatic("cocreation.unavailable");
        setError(message);
        throw cause;
      })
      .finally(() => setIsLoading(false));
  }, []);

  // -- TW12 canvas: debounced autosave -------------------------------------

  /** Persist the latest working payload through the revision-guarded canvas
   *  route. Stale responses (the session moved past our base revision) are
   *  dropped; a REVISION_CONFLICT resyncs from the authoritative session. */
  const persistCanvas = useCallback(async () => {
    const current = sessionRef.current;
    const payload = payloadRef.current;
    if (!current || !payload) return;
    const baseRevision = pendingRevisionRef.current ?? current.revision;
    setIsSavingCanvas(true);
    try {
      const result = await updateCanvasApi(
        current.session_id,
        baseRevision,
        payload,
      );
      lastSentPayloadJsonRef.current = JSON.stringify(payload);
      pendingRevisionRef.current = result.revision;
      setSession((prev) => {
        if (!prev || prev.revision !== baseRevision) return prev;
        return {
          ...prev,
          revision: result.revision,
          warnings: result.warnings,
          draft_payload: payload,
        };
      });
      setCanvasError(null);
    } catch (cause) {
      const message =
        cause instanceof Error
          ? cause.message
          : tStatic("cocreation.saveCanvasError");
      setCanvasError(message);
      if (cause instanceof ApiError && cause.code === "revision_conflict") {
        // The server payload moved on (chat turn, another edit source): resync
        // so the canvas never keeps editing over lost state.
        void recoverCoCreationSession(current.session_id)
          .then((next) => setSession(next))
          .catch(() => undefined);
      }
    } finally {
      setIsSavingCanvas(false);
    }
  }, []);

  const scheduleAutosave = useCallback(() => {
    if (autosaveTimerRef.current !== null) {
      window.clearTimeout(autosaveTimerRef.current);
    }
    autosaveTimerRef.current = window.setTimeout(() => {
      autosaveTimerRef.current = null;
      void persistCanvas();
    }, autosaveDebounceMs);
  }, [persistCanvas, autosaveDebounceMs]);

  /** Persist any pending debounced edit NOW (used before chat turns and the
   *  canonical Author mutations so the server always sees the latest payload). */
  const flushCanvas = useCallback(async () => {
    if (autosaveTimerRef.current !== null) {
      window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
      await persistCanvas();
    }
  }, [persistCanvas]);

  const editCanvas = useCallback(
    (patch: Partial<DraftPayload>) => {
      const current = payloadRef.current;
      if (!current) return;
      const next: DraftPayload = {
        ...current,
        ...patch,
        // The canvas NEVER authors pending_questions (REQ-CC-14): the chat
        // appends; the Author only transitions state via the status API.
        pending_questions: current.pending_questions,
      };
      const nextPast = [...pastRef.current.slice(-99), current];
      pastRef.current = nextPast;
      setPast(nextPast);
      futureRef.current = [];
      setFuture([]);
      payloadRef.current = next;
      setDraftPayload(next);
      // TW16 attribution (REQ-TW16-3): derive the coarse section keys the
      // Author actually edited from the patch. `pending_questions` is
      // chat-owned (REQ-CC-14) — the canvas never authors it, so a stray
      // patch key for it must not count as an Author decision.
      const touched = Object.keys(patch).filter(
        (key) => key !== "pending_questions",
      );
      if (touched.length > 0) {
        setTouchedSections((prev) => {
          const nextTouched = new Set(prev);
          for (const key of touched) nextTouched.add(key);
          return nextTouched;
        });
      }
      scheduleAutosave();
    },
    [scheduleAutosave],
  );

  /** Stage ONE exemplar (REQ-CC-24): the upload route computes the pin
   *  server-side and leaves the bytes in the per-session staging dir; we fold
   *  the returned pin through `editCanvas` so the payload autosaves and the
   *  `adjuntos` section is attributed as Author-touched (TW16). Failure is
   *  surfaced in `canvasError` and leaves the payload untouched. */
  const uploadAdjunto = useCallback(
    async (file: File, nivel: string) => {
      const current = sessionRef.current;
      if (!current) return null;
      setIsUploadingAdjunto(true);
      setCanvasError(null);
      try {
        const pin = await uploadCoCreationAdjunto(
          current.session_id,
          file,
          nivel,
        );
        const existing = payloadRef.current?.adjuntos ?? [];
        editCanvas({ adjuntos: [...existing, pin] });
        return pin;
      } catch (cause) {
        setCanvasError(
          cause instanceof Error
            ? cause.message
            : tStatic("cocreation.loadAdjuntoError"),
        );
        return null;
      } finally {
        setIsUploadingAdjunto(false);
      }
    },
    [editCanvas],
  );

  /** Remove a pinned exemplar by its basename path (REQ-CC-24). The route map
   *  has no remove endpoint, so removal is a canvas-payload edit — the staged
   *  bytes are abandoned to the best-effort staging sweep, never served. */
  const removeAdjunto = useCallback(
    (path: string) => {
      const current = payloadRef.current;
      if (!current) return;
      const next = (current.adjuntos ?? []).filter(
        (adjunto) => adjunto.path !== path,
      );
      editCanvas({ adjuntos: next });
    },
    [editCanvas],
  );

  const undo = useCallback(() => {
    const current = payloadRef.current;
    if (!current || pastRef.current.length === 0) return;
    const previous = pastRef.current[pastRef.current.length - 1];
    const nextPast = pastRef.current.slice(0, -1);
    pastRef.current = nextPast;
    setPast(nextPast);
    const nextFuture = [...futureRef.current, current];
    futureRef.current = nextFuture;
    setFuture(nextFuture);
    payloadRef.current = previous;
    setDraftPayload(previous);
    scheduleAutosave();
  }, [scheduleAutosave]);

  const redo = useCallback(() => {
    const current = payloadRef.current;
    if (!current || futureRef.current.length === 0) return;
    const next = futureRef.current[futureRef.current.length - 1];
    const nextFuture = futureRef.current.slice(0, -1);
    futureRef.current = nextFuture;
    setFuture(nextFuture);
    const nextPast = [...pastRef.current, current];
    pastRef.current = nextPast;
    setPast(nextPast);
    payloadRef.current = next;
    setDraftPayload(next);
    scheduleAutosave();
  }, [scheduleAutosave]);

  const validateCanvas = useCallback(async () => {
    await flushCanvas();
    const current = sessionRef.current;
    const payload = payloadRef.current;
    if (!current || !payload) return null;
    setIsValidating(true);
    setCanvasError(null);
    try {
      const result = await validatePayloadApi(current.session_id, payload);
      setValidation(result);
      return result;
    } catch (cause) {
      setCanvasError(
        cause instanceof Error
          ? cause.message
          : tStatic("cocreation.validateDraftError"),
      );
      return null;
    } finally {
      setIsValidating(false);
    }
  }, [flushCanvas]);

  const loadHistory = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return [];
    setIsLoadingHistory(true);
    setRestoreError(null);
    try {
      const result = await listHistoryApi(current.session_id);
      setHistoryEntries(result.entries);
      return result.entries;
    } catch (cause) {
      setRestoreError(
        cause instanceof Error
          ? cause.message
          : tStatic("cocreation.loadHistoryError"),
      );
      return [];
    } finally {
      setIsLoadingHistory(false);
    }
  }, []);

  const restoreSnapshot = useCallback(
    async (revision: number) => {
      const current = sessionRef.current;
      if (!current) return null;
      setIsRestoring(true);
      setRestoreError(null);
      try {
        const result = await restoreHistoryApi(
          current.session_id,
          current.revision,
          revision,
        );
        // The server replaced the payload and bumped the revision: fold both
        // in so the sync effect (which compares payloads) does not clobber it.
        lastSentPayloadJsonRef.current = JSON.stringify(result.payload);
        pendingRevisionRef.current = result.revision;
        payloadRef.current = result.payload;
        setDraftPayload(result.payload);
        resetStacks();
        setSession((prev) =>
          prev
            ? { ...prev, revision: result.revision, draft_payload: result.payload }
            : prev,
        );
        return result;
      } catch (cause) {
        setRestoreError(
          cause instanceof Error
            ? cause.message
            : tStatic("cocreation.restoreError"),
        );
        return null;
      } finally {
        setIsRestoring(false);
      }
    },
    [resetStacks],
  );

  const setWarningStatus = useCallback(
    async (idx: number, state: WarningState) => {
      const current = sessionRef.current;
      if (!current) return;
      setCanvasError(null);
      try {
        const result = await setWarningStatusApi(
          current.session_id,
          current.revision,
          idx,
          state,
        );
        setSession((prev) =>
          prev ? { ...prev, warnings: result.warnings } : prev,
        );
      } catch (cause) {
        setCanvasError(
          cause instanceof Error
            ? cause.message
            : tStatic("cocreation.warningError"),
        );
      }
    },
    [],
  );

  const setPendingQuestionStatus = useCallback(
    async (idx: number, state: WarningState) => {
      const current = sessionRef.current;
      if (!current) return;
      setCanvasError(null);
      try {
        const result = await setPendingQuestionStatusApi(
          current.session_id,
          current.revision,
          idx,
          state,
        );
        setSession((prev) => {
          if (!prev?.draft_payload) return prev;
          const nextPayload = {
            ...prev.draft_payload,
            pending_questions: result.pending_questions,
          };
          // The transition is server-authoritative and folded verbatim, so the
          // sync effect must treat it as "ours" (it is exactly what the server
          // returned) and not reset the canvas edit stack.
          lastSentPayloadJsonRef.current = JSON.stringify(nextPayload);
          return { ...prev, draft_payload: nextPayload };
        });
      } catch (cause) {
        setCanvasError(
          cause instanceof Error
            ? cause.message
            : tStatic("cocreation.questionError"),
        );
      }
    },
    [],
  );

  const derive = useCallback(
    async (skillId: string, version: string, world?: string | null) => {
      setIsLoading(true);
      setError(null);
      try {
        const result = await deriveDraftApi(skillId, version, world ?? null);
        // Load the full adaptation session: the server seeded the canvas
        // payload from the original and injected `derived_from` (REQ-CC-17/20).
        const next = await recoverCoCreationSession(result.session_id);
        setSession(next);
        rememberSession(next.session_id);
        return result;
      } catch (cause) {
        setError(
          cause instanceof Error
            ? cause.message
            : tStatic("cocreation.deriveError"),
        );
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  const getPublishedDetail = useCallback(
    (skillId: string, version: string) =>
      getPublishedDetailApi(skillId, version),
    [],
  );

  const create = useCallback(
    (input: string, world?: string | null) => {
      const trimmed = input.trim();
      if (!trimmed) return Promise.resolve(null);
      return apply(() => createCoCreationSession(trimmed, world ?? null));
    },
    [apply],
  );

  const send = useCallback(
    async (input: string) => {
      const trimmed = input.trim();
      if (!trimmed) return null;
      // Flush pending canvas edits so the Skill Madre sees the latest payload
      // in context (REQ-CC-12: canvas edits MUST be visible to the next turn).
      await flushCanvas();
      return apply(() =>
        sessionRef.current
          ? turnCoCreationSession(
              sessionRef.current.session_id,
              sessionRef.current.revision,
              trimmed,
            )
          : createCoCreationSession(trimmed),
      );
    },
    [apply, flushCanvas],
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
          : tStatic("cocreation.unavailable"),
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  const materialize = useCallback(
    async (metadata?: CoCreationMaterializeMetadata) => {
      await flushCanvas();
      const current = sessionRef.current;
      if (!current) return null;
      setIsLoading(true);
      setError(null);
      return materializeCoCreationSession(
        current.session_id,
        current.revision,
        metadata,
      )
        .then((result) => {
          if (result.ok && result.session_id) {
            // Success returns the full public state: fold the authoritative
            // fields in and keep the rest of the local transcript.
            setSession((prev) =>
              prev
                ? {
                    ...prev,
                    revision: result.revision,
                    phase: result.phase,
                    milestone: result.milestone,
                    draft_id: result.draft_id,
                    compile_issues: result.compile_issues ?? [],
                  }
                : prev,
            );
          } else {
            // Compile issues: the session STAYS at borrador_listo for
            // correction (REQ-CC-5); surface the issues in the panel.
            setSession((prev) =>
              prev
                ? {
                    ...prev,
                    compile_issues:
                      result.compile_issues ?? result.issues ?? [],
                  }
                : prev,
            );
          }
          return result;
        })
        .catch((cause) => {
          const message =
            cause instanceof Error
              ? cause.message
              : tStatic("cocreation.materializeUnavailable");
          setError(message);
          throw cause;
        })
        .finally(() => setIsLoading(false));
    },
    [flushCanvas],
  );

  const publish = useCallback(async () => {
    await flushCanvas();
    const current = sessionRef.current;
    if (!current?.draft_id) return null;
    setIsLoading(true);
    setError(null);
    return publishCoCreationSession(current.session_id, current.revision)
      .then((result) => {
        setPublished(result);
        setSession((prev) =>
          prev
            ? { ...prev, phase: result.phase, revision: result.revision }
            : prev,
        );
        return result;
      })
      .catch((cause) => {
        const message =
          cause instanceof Error
            ? cause.message
            : tStatic("cocreation.publishUnavailable");
        setError(message);
        throw cause;
      })
      .finally(() => setIsLoading(false));
  }, [flushCanvas]);

  const activate = useCallback(
    async (world: string) => {
      await flushCanvas();
      const current = sessionRef.current;
      if (!current) return null;
      setIsLoading(true);
      setError(null);
      return activateCoCreationSession(
        current.session_id,
        current.revision,
        world,
      )
        .then((result) => {
          setActivation(result);
          setSession((prev) =>
            prev
              ? { ...prev, phase: result.phase, revision: result.revision }
              : prev,
          );
          return result;
        })
        .catch((cause) => {
          const message =
            cause instanceof Error
              ? cause.message
              : tStatic("cocreation.activateUnavailable");
          setError(message);
          throw cause;
        })
        .finally(() => setIsLoading(false));
    },
    [flushCanvas],
  );

  const reset = useCallback(() => {
    if (autosaveTimerRef.current !== null) {
      window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
    rememberSession(null);
    setSession(null);
    setPublished(null);
    setActivation(null);
    setError(null);
    setDraftPayload(null);
    resetStacks();
    payloadRef.current = null;
    lastSentPayloadJsonRef.current = null;
    pendingRevisionRef.current = undefined;
    setCanvasError(null);
    setValidation(null);
    setHistoryEntries([]);
    setRestoreError(null);
    setIsUploadingAdjunto(false);
    setTouchedSections(new Set());
  }, [resetStacks]);

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

    // TW12 canvas
    draftPayload,
    touchedSections,
    canvasError,
    editCanvas,
    undo,
    redo,
    canUndo: past.length > 0,
    canRedo: future.length > 0,
    isSavingCanvas,
    validateCanvas,
    validation,
    isValidating,
    loadHistory,
    historyEntries,
    isLoadingHistory,
    restoreSnapshot,
    isRestoring,
    restoreError,
    setWarningStatus,
    setPendingQuestionStatus,

    // TW16 exemplar authoring
    uploadAdjunto,
    removeAdjunto,
    isUploadingAdjunto,

    // TW13/TW14
    derive,
    getPublishedDetail,
    derivedFrom: session?.derived_from ?? null,
  };
}