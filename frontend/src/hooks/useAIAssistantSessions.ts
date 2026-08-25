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
  rejectGuidedCharacterProposal,
  serializeGuidedCharacter,
} from "@/api/guidedCharacter";
import { askAssistant } from "@/api/wiki";
import { mapSemanticDecision, semanticBlockedText } from "@/lib/semanticIntent";
import { useAppLanguage } from "@/hooks/useAppLanguage";

export interface Message {
  role: "user" | "assistant";
  content: string;
}

export interface Session {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
  guided?: GuidedCharacterSession;
  pendingReview?: EditProposal;
}

const STORAGE_KEY = "demiurgos-ai-sessions";
const ACTIVE_SESSION_STORAGE_KEY = "demiurgos-ai-sessions-active";
const MAX_SESSION_TITLE_LENGTH = 40;

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

function truncateTitle(text: string): string {
  const cleaned = text.replace(/[^a-zA-Z0-9├í├⌐├¡├│├║├▒├╝┬┐┬í\s]/g, "").trim();
  if (cleaned.length === 0) return "Nueva sesi├│n";
  return cleaned.length > MAX_SESSION_TITLE_LENGTH
    ? cleaned.slice(0, MAX_SESSION_TITLE_LENGTH) + "..."
    : cleaned;
}

function loadSessions(): Session[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? (JSON.parse(stored) as Session[]) : [];
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
  mundo: string,
  section?: string,
  filePath?: string,
): AIAssistantSessionsResult {
  const [sessions, setSessions] = useState<Session[]>(() => loadSessions());
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
  const language = useAppLanguage();

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
    const id = generateId();
    const session: Session = {
      id,
      title: "Nueva sesi├│n",
      messages: [],
      createdAt: Date.now(),
    };
    setSessions((prev) => [session, ...prev]);
    setActiveSessionId(id);
    setError(null);
  }, []);

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
          title: truncateTitle(trimmed),
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
                title:
                  s.title === "Nueva sesi├│n"
                    ? truncateTitle(trimmed)
                    : s.title,
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
        ...(section ? { section } : {}),
        ...(filePath ? { file_path: filePath } : {}),
        ...(guided ? {
          guided_session_id: guided.session_id,
          guided_revision: guided.revision,
        } : {}),
      };

      const legacyRequest = async () => {
        return askAssistant(mundo, requestBody, controller.signal);
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
        const result = await streamAssistantActivity(mundo, request, {
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
    [activeSession, activeSessionId, isSending, mundo, section, filePath, language],
  );

  const resolveGuidedProposal = useCallback(async (accept: boolean) => {
    if (!activeSession?.guided?.proposal || !activeSessionId) return;
    const guided = activeSession.guided;
    const proposal = guided.proposal;
    if (!proposal) return;
    const proposalKey = proposal.key;
    const action = accept ? acceptGuidedCharacterProposal : rejectGuidedCharacterProposal;
    const next = await action(mundo, guided.session_id, guided.revision, proposalKey);
    setSessions((prev) => prev.map((session) => (
      session.id === activeSessionId ? { ...session, guided: next } : session
    )));
  }, [activeSession, activeSessionId, mundo]);

  const requestGuidedReview = useCallback(async () => {
    const guided = activeSession?.guided;
    if (!guided || !activeSessionId) return null;
    const proposal = await serializeGuidedCharacter(mundo, guided.session_id, guided.revision);
    setSessions((prev) => prev.map((session) => (
      session.id === activeSessionId ? { ...session, pendingReview: proposal } : session
    )));
    return proposal;
  }, [activeSession, activeSessionId, mundo]);

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
    requestGuidedReview,
    cancelSend,
  };
}
