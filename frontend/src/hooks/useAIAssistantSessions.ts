import { useCallback, useEffect, useState } from "react";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface Session {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
}

const STORAGE_KEY = "demiurgos-ai-sessions";
const MAX_SESSION_TITLE_LENGTH = 40;

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

  // Persist sessions whenever they change
  useEffect(() => {
    saveSessions(sessions);
  }, [sessions]);

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

      try {
        const response = await fetch(
          `/api/${encodeURIComponent(mundo)}/ai/ask`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: trimmed,
              session_id: sessionId ?? "",
              ...(section ? { section } : {}),
              ...(filePath ? { file_path: filePath } : {}),
            }),
          },
        );

        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail ?? `HTTP ${response.status}`);
        }

        const data = (await response.json()) as { response: string };
        const assistantMessage: Message = {
          role: "assistant",
          content: data.response,
        };

        setSessions((prev) =>
          prev.map((s) =>
            s.id === sessionId
              ? { ...s, messages: [...s.messages, assistantMessage] }
              : s,
          ),
        );
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Error desconocido";
        setError(msg);
        const errorMessage: Message = {
          role: "assistant",
          content: `Error: ${msg}`,
        };
        setSessions((prev) =>
          prev.map((s) =>
            s.id === sessionId
              ? { ...s, messages: [...s.messages, errorMessage] }
              : s,
          ),
        );
      } finally {
        setIsSending(false);
      }
    },
    [activeSessionId, isSending, mundo, section, filePath],
  );

  return {
    sessions,
    activeSession,
    activeSessionId,
    isSending,
    error,
    createSession,
    switchSession,
    deleteSession,
    sendMessage,
  };
}
