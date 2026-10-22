import { useCallback, useEffect, useRef, useState } from "react";
import {
  AssistantActivityUnavailable,
  type AssistantActivityUnavailableReason,
  INCOMPLETE_EVIDENCE_WARNING,
  streamAssistantActivity,
} from "@/api/assistantActivity";
import type {
  AssistantActivityEvent,
  AssistantActivityEvidence,
  AssistantActivityItem,
  EditProposal,
  GuidedCharacterSession,
  SemanticDecisionEvent,
} from "@/api/types";
import {
  acceptGuidedCharacterProposal,
  acceptGuidedConsent,
  declineGuidedConsent,
  rejectGuidedCharacterProposal,
  serializeGuidedCharacter,
} from "@/api/guidedCharacter";
import type { GuidedMethodChoice } from "@/api/guidedCharacter";
import { askAssistant } from "@/api/wiki";
import { mapSemanticDecision, semanticBlockedText, isUsableGuidedSession } from "@/lib/semanticIntent";
import { useAppLanguage } from "@/hooks/useAppLanguage";

export interface Message {
  role: "user" | "assistant";
  content: string;
}

export interface Session {
  id: string;
  title: string;
  /**
   * Structural marker that the title is the localized default (AD-12): set on
   * creation, cleared when a derived title replaces it. Replaces the brittle
   * string-identity comparison (`title === "Nueva sesión"`) so automatic
   * replacement fires for ANY language and for legacy mojibake drafts.
   */
  titleIsDefault?: boolean;
  messages: Message[];
  createdAt: number;
  guided?: GuidedCharacterSession;
  pendingReview?: EditProposal;
  /**
   * One-shot token for a musing consent suggestion (REQ-GFC-08). Present only
   * while the user has neither accepted nor declined; sending another message
   * counts as "keep chatting" and dismisses it.
   */
  consentToken?: string;
}

const STORAGE_KEY = "demiurgos-ai-sessions";
const ACTIVE_SESSION_STORAGE_KEY = "demiurgos-ai-sessions-active";
const MAX_SESSION_TITLE_LENGTH = 40;

/**
 * Stable context key for world-agnostic assistant sessions (null-mundo, e.g.
 * the Taller de Ideas). The backend AI routes are mundo-scoped
 * (`/api/{mundo}/ai/ask`); this key is the frontend-side stable identity for
 * the global context and is sent as the mundo segment of those URLs.
 */
export const GLOBAL_ASSISTANT_CONTEXT = "ideas-global";

export interface AssistantActivityState {
  accepted: boolean;
  items: AssistantActivityItem[];
  status: "neutral" | "running" | "complete";
  warning: string | null;
  availability: "unknown" | "available" | "unavailable";
  availabilityReason?: AssistantActivityUnavailableReason;
  /** Fail-closed turn: the semantic decision was blocked, missing, or malformed. */
  blocked?: boolean;
}

export interface AIAssistantSessionsResult {
  sessions: Session[];
  activeSession: Session | null;
  activeSessionId: string | null;
  isSending: boolean;
  error: string | null;
  activity: AssistantActivityState;
  evidence: AssistantActivityEvidence;
  createSession: () => void;
  switchSession: (id: string) => void;
  deleteSession: (id: string) => void;
  sendMessage: (prompt: string) => Promise<void>;
  resolveGuidedProposal: (accept: boolean) => Promise<void>;
  resolveGuidedConsent: (
    accept: boolean,
    method?: GuidedMethodChoice,
  ) => Promise<void>;
  requestGuidedReview?: () => Promise<EditProposal | null>;
  cancelSend: () => void;
}

const INITIAL_ACTIVITY: AssistantActivityState = {
  accepted: false,
  items: [],
  status: "neutral",
  warning: null,
  availability: "unknown",
};

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

/**
 * Title values that identify a "default" session title across languages and
 * legacy persisted data. The double-encoded mojibake draft (the legacy
 * "Nueva sesion" default with the box-drawing lead bytes U+251C U+2502) is
 * written with escape sequences so the catalogue guard's mojibake scan never
 * flags the migration marker itself.
 */
const DEFAULT_TITLE_MARKERS = [
  "Nueva sesión",
  "Nueva sesi\u251c\u2502n",
  "New session",
];

function isDefaultTitle(title: string, titleIsDefault?: boolean): boolean {
  if (titleIsDefault === true) return true;
  return DEFAULT_TITLE_MARKERS.includes(title);
}

/**
 * Derive a session title from the first message. Unicode-aware: letters and
 * numbers from ANY script survive (accents included — SES-SCN-2.4), while
 * punctuation/emoji are stripped. An empty result falls back to the
 * localized default title.
 */
function truncateTitle(text: string, defaultTitle: string): string {
  const cleaned = text.replace(/[^\p{L}\p{N}\s]/gu, "").trim();
  if (cleaned.length === 0) return defaultTitle;
  return cleaned.length > MAX_SESSION_TITLE_LENGTH
    ? cleaned.slice(0, MAX_SESSION_TITLE_LENGTH) + "..."
    : cleaned;
}

/**
 * Migrate legacy persisted drafts whose title is a known default marker
 * (including the mojibake default) to the CURRENT locale's default title,
 * flagged structurally so automatic replacement fires on the first message.
 */
function migrateLegacyDefaultTitles(
  sessions: Session[],
  defaultTitle: string,
): Session[] {
  return sessions.map((session) =>
    session.titleIsDefault === true || !DEFAULT_TITLE_MARKERS.includes(session.title)
      ? session
      : { ...session, title: defaultTitle, titleIsDefault: true },
  );
}

function isRecordLike(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Restore sessions defensively. The stored payload is untrusted: a non-array
 * value, a non-object entry, or a guided handle without the candidate the
 * sidebar dereferences must never survive into the render tree. A malformed
 * guided handle is dropped while the rest of the session (messages, title,
 * consent token) is preserved, so mount never crashes on an old shape.
 */
function loadSessions(): Session[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return [];
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (value): value is Session =>
          isRecordLike(value) && typeof value.id === "string" && value.id.length > 0,
      )
      .map((session) => {
        if (session.guided === undefined || isUsableGuidedSession(session.guided)) {
          return session;
        }
        const { guided: _malformedGuided, ...rest } = session;
        return rest;
      });
  } catch {
    return [];
  }
}

function saveSessions(sessions: Session[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  } catch {
    // localStorage might be full — silently fail
  }
}

function loadActiveSessionId(): string | null {
  try {
    const stored = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (!stored) return null;
    const parsed = JSON.parse(stored) as unknown;
    return typeof parsed === "string" && parsed.length > 0 ? parsed : null;
  } catch {
    return null;
  }
}

function saveActiveSessionId(id: string | null): void {
  try {
    if (id === null) {
      localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    } else {
      localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, JSON.stringify(id));
    }
  } catch {
    // localStorage might be full — silently fail
  }
}

export function applyAssistantActivityEvent(
  current: AssistantActivityState,
  event: AssistantActivityEvent,
): AssistantActivityState {
  if (event.kind === "activity") {
    const existing = current.items.find((item) => item.item_id === event.item_id);
    if (!existing && event.status !== "running") return current;
    if (existing && existing.status !== "running" && event.status !== "running") {
      return current;
    }
    const nextItem = {
      item_id: event.item_id,
      operation: event.operation,
      status: event.status,
      ...(event.path ? { path: event.path } : {}),
      ...(event.warning ? { warning: event.warning } : {}),
    };
    return {
      ...current,
      accepted: true,
      availability: "available",
      status: event.status === "failed" ? "complete" : "running",
      warning: event.warning ?? current.warning,
      items: existing
        ? current.items.map((item) => (item.item_id === event.item_id ? nextItem : item))
        : [...current.items, nextItem],
    };
  }
  if (event.kind === "terminal") {
    return {
      ...current,
      accepted: true,
      availability: "available",
      status: "complete",
      warning: event.warning ?? current.warning,
    };
  }
  return { ...current, accepted: true, availability: "available" };
}

function activityEvidence(activity: AssistantActivityState): AssistantActivityEvidence {
  const sources = activity.items
    .filter((item) => item.status === "succeeded" && item.path)
    .map((item) => item.path as string);
  const warnings = activity.warning ? [activity.warning] : [];
  return {
    sources,
    warnings,
    status: warnings.length ? "incomplete" : sources.length ? "confirmed" : "neutral",
  };
}

/**
 * Manages AI assistant chat sessions with localStorage persistence.
 * Sessions are sorted newest-first. Each session has an id, title,
 * and a list of messages.
 */
export function useAIAssistantSessions(
  mundo?: string,
  section?: string,
  filePath?: string,
): AIAssistantSessionsResult {
  // World-agnostic sessions (mundo null/undefined) use the stable global
  // context key so the Taller de Ideas assistant never leaks into — nor is
  // polluted by — any mundo-scoped session.
  const contextMundo = mundo ?? GLOBAL_ASSISTANT_CONTEXT;
  const worldScoped = Boolean(mundo);
  const { language, t } = useAppLanguage();
  // Localized default session title (AD-12): correct in every language and
  // never the double-encoded mojibake literal.
  const defaultTitle = t("assistant.session.defaultTitle");
  // Legacy persisted drafts (including mojibake-default ones) are migrated to
  // the current locale's default and flagged so replacement fires on the
  // first message (SES-REQ-2).
  const [sessions, setSessions] = useState<Session[]>(() =>
    migrateLegacyDefaultTitles(loadSessions(), defaultTitle),
  );
  // Restore the last active session so the open conversation survives
  // remounts (the sidebar unmounts when the editor switches tabs). The
  // persisted id is validated against the sessions restored for this mount:
  // if it no longer exists (deleted or cleared storage) fall back to null —
  // never auto-pick a session the user did not have active. Sessions are
  // stored under a single global key (not per-context), so the active id is
  // scoped and validated consistently with how sessions are loaded.
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() => {
    const persisted = loadActiveSessionId();
    return persisted !== null && sessions.some((s) => s.id === persisted)
      ? persisted
      : null;
  });
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activity, setActivity] = useState<AssistantActivityState>(INITIAL_ACTIVITY);
  const activityAbortRef = useRef<AbortController | null>(null);

  // Persist sessions whenever they change
  useEffect(() => {
    saveSessions(sessions);
  }, [sessions]);

  // Persist the active session id whenever it changes; every create/switch/
  // delete/auto-create path flows through setActiveSessionId, and deleting
  // the active session sets it to null (removing the persisted id).
  useEffect(() => {
    saveActiveSessionId(activeSessionId);
  }, [activeSessionId]);

  useEffect(() => () => activityAbortRef.current?.abort(), []);

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null;

  const createSession = useCallback(() => {
    // A conversation that never received a message is not a real conversation:
    // reuse the existing empty draft instead of stacking empty default-title
    // entries every time the user taps "Nueva conversación" / "+ Nueva Sesión".
    const activeEmpty = activeSessionId
      ? sessions.find((s) => s.id === activeSessionId && s.messages.length === 0)
      : undefined;
    const existingEmpty = sessions.find((s) => s.messages.length === 0);
    const target = activeEmpty ?? existingEmpty;

    if (target) {
      // Focus the empty draft and drop any other empty drafts left behind so
      // empty conversations never accumulate in the history.
      setSessions(sessions.filter((s) => s.id === target.id || s.messages.length > 0));
      setActiveSessionId(target.id);
      setError(null);
      return;
    }

    const id = generateId();
    const session: Session = {
      id,
      title: defaultTitle,
      titleIsDefault: true,
      messages: [],
      createdAt: Date.now(),
    };
    setSessions([session, ...sessions]);
    setActiveSessionId(id);
    setError(null);
  }, [activeSessionId, sessions, defaultTitle]);

  const switchSession = useCallback((id: string) => {
    setActiveSessionId(id);
    setError(null);
  }, []);

  const deleteSession = useCallback((id: string) => {
    setSessions((prev) => prev.filter((s) => s.id !== id));
    setActiveSessionId((prev) => (prev === id ? null : prev));
  }, []);

  const sendMessage = useCallback(
    async (prompt: string) => {
      const trimmed = prompt.trim();
      if (!trimmed || isSending) return;

      // Auto-create a session if none is active
      let sessionId = activeSessionId;
      if (!sessionId) {
        const id = generateId();
        const newSession: Session = {
          id,
          title: truncateTitle(trimmed, defaultTitle),
          messages: [],
          createdAt: Date.now(),
        };
        setSessions((prev) => [newSession, ...prev]);
        setActiveSessionId(id);
        sessionId = id;
      }

      const userMessage: Message = { role: "user", content: trimmed };

      // Add user message and update title on first message
      setSessions((prev) =>
        prev.map((s) =>
          s.id === sessionId
            ? {
                ...s,
                messages: [...s.messages, userMessage],
                // Structural default-title check: fires for every language
                // and for legacy mojibake drafts (AD-12, SES-REQ-2).
                title: isDefaultTitle(s.title, s.titleIsDefault)
                  ? truncateTitle(trimmed, defaultTitle)
                  : s.title,
                titleIsDefault: false,
                // Sending another message counts as "keep chatting": the
                // pending suggestion is dismissed (REQ-GFC-06).
                consentToken: undefined,
              }
            : s,
        ),
      );

      setIsSending(true);
      setError(null);
      setActivity(INITIAL_ACTIVITY);
      const controller = new AbortController();
      activityAbortRef.current = controller;
      let activityAccepted = false;
      let streamedAnswer: string | null = null;
      let semanticDecision: SemanticDecisionEvent | null = null;

      const appendAssistantMessage = (content: string, guided?: GuidedCharacterSession) => {
        const assistantMessage: Message = { role: "assistant", content };
        setSessions((prev) =>
          prev.map((s) =>
            s.id === sessionId
              ? { ...s, messages: [...s.messages, assistantMessage], ...(guided ? { guided } : {}) }
              : s,
          ),
        );
      };

      const guided = activeSession?.guided;
      const requestBody = {
        prompt: trimmed,
        session_id: sessionId ?? "",
        // section/filePath are world-scoped context: they only make sense for
        // mundo-scoped sessions and are omitted in the null-mundo (global)
        // context.
        ...(worldScoped && section ? { section } : {}),
        ...(worldScoped && filePath ? { file_path: filePath } : {}),
        ...(guided ? {
          guided_session_id: guided.session_id,
          guided_revision: guided.revision,
        } : {}),
      };

      const legacyRequest = async () => {
        return askAssistant(contextMundo, requestBody, controller.signal);
      };

      const applySemanticOutcome = (outcome: ReturnType<typeof mapSemanticDecision>) => {
        if (outcome.kind === "review") {
          const assistantMessage: Message = { role: "assistant", content: outcome.text };
          setSessions((prev) =>
            prev.map((s) =>
              s.id === sessionId
                ? {
                    ...s,
                    messages: [...s.messages, assistantMessage],
                    guided: outcome.guided ?? s.guided,
                    pendingReview: outcome.proposal,
                  }
                : s,
            ),
          );
          return;
        }
        if (outcome.kind === "confirmation") {
          appendAssistantMessage(outcome.text, outcome.guided);
          return;
        }
        if (outcome.kind === "suggestion") {
          // Musing guided intent: no session is created server-side. Persist
          // the consent token so the chat renders the in-chat consent card;
          // the composer stays enabled (no guided session yet).
          setSessions((prev) =>
            prev.map((s) =>
              s.id === sessionId ? { ...s, consentToken: outcome.consentToken } : s,
            ),
          );
          return;
        }
        if (outcome.kind === "blocked") {
          appendAssistantMessage(outcome.text);
          setActivity((current) => ({
            ...current,
            blocked: true,
            status: "complete",
            availability: "unavailable",
          }));
          return;
        }
        if (outcome.kind === "answer") {
          appendAssistantMessage(outcome.text, outcome.guided);
          return;
        }
        appendAssistantMessage(outcome.text);
      };

      const applyBlocked = (text: string, unavailable: boolean) => {
        appendAssistantMessage(text);
        setActivity((current) => ({
          ...current,
          accepted: true,
          blocked: true,
          availability: unavailable ? "unavailable" : current.availability,
          status: "complete",
        }));
      };

      try {
        const request = requestBody;
        const result = await streamAssistantActivity(contextMundo, request, {
          signal: controller.signal,
          onAccepted: () => {
            activityAccepted = true;
            setActivity((current) => ({
              ...current,
              accepted: true,
              availability: "available",
            }));
          },
          onEvent: (event) => {
            if (event.kind === "semantic_decision") semanticDecision = event;
            if (event.kind === "answer") streamedAnswer = event.response;
            setActivity((current) => applyAssistantActivityEvent(current, event));
          },
        });
        semanticDecision = semanticDecision ?? result.semanticDecision;
        streamedAnswer = result.answer ?? streamedAnswer;

        // The semantic decision is authoritative: answer text alone never grants
        // an outcome. Missing/malformed/out-of-contract decisions fail closed.
        const state = semanticDecision?.state ?? null;
        if (state === "allow" || state === "clarify") {
          if (streamedAnswer === null) {
            applyBlocked(semanticBlockedText(language), true);
          } else {
            appendAssistantMessage(streamedAnswer);
          }
        } else if (state === "blocked") {
          applyBlocked(
            streamedAnswer ?? semanticBlockedText(language),
            semanticDecision?.unavailable ?? true,
          );
        } else {
          applyBlocked(semanticBlockedText(language), true);
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        if (err instanceof AssistantActivityUnavailable && !activityAccepted) {
          setActivity({
            ...INITIAL_ACTIVITY,
            availability: "unavailable",
            availabilityReason: err.reasonCode,
          });
          try {
            const result = await legacyRequest();
            applySemanticOutcome(mapSemanticDecision(result, language));
          } catch (legacyError) {
            applyBlocked(semanticBlockedText(language), true);
          }
        } else if (
          streamedAnswer !== null &&
          (semanticDecision?.state === "allow" || semanticDecision?.state === "clarify")
        ) {
          setActivity((current) => ({
            ...current,
            warning: INCOMPLETE_EVIDENCE_WARNING,
            status: "complete",
          }));
          appendAssistantMessage(streamedAnswer);
        } else {
          applyBlocked(semanticBlockedText(language), true);
        }
      } finally {
        if (activityAbortRef.current === controller) activityAbortRef.current = null;
        setIsSending(false);
      }
    },
    [activeSession, activeSessionId, isSending, mundo, contextMundo, section, filePath, language, defaultTitle],
  );

  const resolveGuidedProposal = useCallback(async (accept: boolean) => {
    if (!activeSession?.guided?.proposal || !activeSessionId) return;
    const guided = activeSession.guided;
    const proposal = guided.proposal;
    if (!proposal) return;
    const proposalKey = proposal.key;
    const action = accept ? acceptGuidedCharacterProposal : rejectGuidedCharacterProposal;
    const next = await action(contextMundo, guided.session_id, guided.revision, proposalKey);
    setSessions((prev) => prev.map((session) => (
      session.id === activeSessionId ? { ...session, guided: next } : session
    )));
  }, [activeSession, activeSessionId, contextMundo]);

  const resolveGuidedConsent = useCallback(async (
    accept: boolean,
    method?: GuidedMethodChoice,
  ) => {
    const token = activeSession?.consentToken;
    if (!token || !activeSessionId) return;
    try {
      if (accept) {
        // Accepting IS the imperative: the server opens the deferred guided
        // continuation with no second Hermes run. The endpoint answers with a
        // semantic decision envelope; the bare session lives in `guided_state`.
        // Normalize once, at this boundary, so `session.guided` is ALWAYS a
        // bare session (or undefined) — never the envelope. A legacy server
        // answering with the bare session directly is still admitted; anything
        // malformed is dropped instead of being stored as `guided`.
        const envelope = method
          ? await acceptGuidedConsent(contextMundo, token, method)
          : await acceptGuidedConsent(contextMundo, token);
        // Validate the unwrapped value too: a present-but-malformed
        // `guided_state` must not be stored either, so this boundary stays
        // symmetric with loadSessions instead of trusting the server's type.
        const unwrapped = envelope.guided_state ?? envelope;
        const guided = isUsableGuidedSession(unwrapped) ? unwrapped : undefined;
        setSessions((prev) =>
          prev.map((session) =>
            session.id === activeSessionId
              ? { ...session, guided, consentToken: undefined }
              : session,
          ),
        );
      } else {
        await declineGuidedConsent(contextMundo, token);
        setSessions((prev) =>
          prev.map((session) =>
            session.id === activeSessionId
              ? { ...session, consentToken: undefined }
              : session,
          ),
        );
      }
      setError(null);
    } catch {
      // Fail closed: keep the suggestion and surface the safe copy.
      setError(semanticBlockedText(language));
    }
  }, [activeSession, activeSessionId, contextMundo, language]);

  const requestGuidedReview = useCallback(async () => {
    const guided = activeSession?.guided;
    if (!guided || !activeSessionId) return null;
    const proposal = await serializeGuidedCharacter(contextMundo, guided.session_id, guided.revision);
    setSessions((prev) => prev.map((session) => (
      session.id === activeSessionId ? { ...session, pendingReview: proposal } : session
    )));
    return proposal;
  }, [activeSession, activeSessionId, contextMundo]);

  const cancelSend = useCallback(() => activityAbortRef.current?.abort(), []);

  return {
    sessions,
    activeSession,
    activeSessionId,
    isSending,
    error,
    activity,
    evidence: activityEvidence(activity),
    createSession,
    switchSession,
    deleteSession,
    sendMessage,
    resolveGuidedProposal,
    resolveGuidedConsent,
    requestGuidedReview,
    cancelSend,
  };
}
