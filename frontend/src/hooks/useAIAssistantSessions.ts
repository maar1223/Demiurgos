import { useCallback, useEffect, useRef, useState } from "react";
import {
  AssistantActivityUnavailable,
  type AssistantActivityUnavailableReason,
  INCOMPLETE_EVIDENCE_WARNING,
  NEUTRAL_EVIDENCE_WARNING,
  streamAssistantActivity,
} from "@/api/assistantActivity";
import type {
  AssistantActivityEvent,
  AssistantActivityEvidence,
  AssistantActivityItem,
} from "@/api/types";

export interface Message {
  role: "user" | "assistant";
  content: string;
}

export interface Session {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
}

const STORAGE_KEY = "demiurgos-ai-sessions";
const MAX_SESSION_TITLE_LENGTH = 40;

export interface AssistantActivityState {
  accepted: boolean;
  items: AssistantActivityItem[];
  status: "neutral" | "running" | "complete";
  warning: string | null;
  availability: "unknown" | "available" | "unavailable";
  availabilityReason?: AssistantActivityUnavailableReason;
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
    // localStorage might be full ΓÇö silently fail
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
) {
  const [sessions, setSessions] = useState<Session[]>(() => loadSessions());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activity, setActivity] = useState<AssistantActivityState>(INITIAL_ACTIVITY);
  const activityAbortRef = useRef<AbortController | null>(null);

  // Persist sessions whenever they change
  useEffect(() => {
    saveSessions(sessions);
  }, [sessions]);

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

      const appendAssistantMessage = (content: string) => {
        const assistantMessage: Message = { role: "assistant", content };
        setSessions((prev) =>
          prev.map((s) =>
            s.id === sessionId
              ? { ...s, messages: [...s.messages, assistantMessage] }
              : s,
          ),
        );
      };

      const legacyRequest = async (): Promise<string> => {
        const response = await fetch(`/api/${encodeURIComponent(mundo)}/ai/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            prompt: trimmed,
            session_id: sessionId ?? "",
            ...(section ? { section } : {}),
            ...(filePath ? { file_path: filePath } : {}),
          }),
        });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail ?? `HTTP ${response.status}`);
        }
        const data = (await response.json()) as { response: string };
        return data.response;
      };

      try {
        const request = {
          prompt: trimmed,
          session_id: sessionId ?? "",
          ...(section ? { section } : {}),
          ...(filePath ? { file_path: filePath } : {}),
        };
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
            if (event.kind === "answer") streamedAnswer = event.response;
            setActivity((current) => applyAssistantActivityEvent(current, event));
          },
        });
        streamedAnswer = result.answer ?? streamedAnswer;
        if (streamedAnswer === null) throw new Error("Assistant returned no answer");
        appendAssistantMessage(streamedAnswer);
      } catch (err) {
        if (controller.signal.aborted) return;
        if (err instanceof AssistantActivityUnavailable && !activityAccepted) {
          setActivity({
            ...INITIAL_ACTIVITY,
            availability: "unavailable",
            availabilityReason: err.reasonCode,
          });
          try {
            appendAssistantMessage(await legacyRequest());
          } catch (legacyError) {
            const msg = legacyError instanceof Error ? legacyError.message : "Error desconocido";
            setError(msg);
            appendAssistantMessage(`Error: ${msg}`);
          }
        } else if (streamedAnswer !== null) {
          setActivity((current) => ({
            ...current,
            warning: INCOMPLETE_EVIDENCE_WARNING,
            status: "complete",
          }));
          appendAssistantMessage(streamedAnswer);
        } else {
          const msg = err instanceof Error ? err.message : "Error desconocido";
          setError(msg);
          setActivity((current) => ({
            ...current,
            warning: current.warning ?? NEUTRAL_EVIDENCE_WARNING,
          }));
          appendAssistantMessage(`Error: ${msg}`);
        }
      } finally {
        if (activityAbortRef.current === controller) activityAbortRef.current = null;
        setIsSending(false);
      }
    },
    [activeSessionId, isSending, mundo, section, filePath],
  );

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
    cancelSend,
  };
}
