import { useState, useCallback } from "react";
import { API_BASE_URL } from "@/lib/constants";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ChatResponse {
  content?: string;
  error?: string;
}

/**
 * Hook for the AI Assistant chat.
 *
 * Manages message history and provides a `send` function that calls
 * POST /api/chat with the current message + mundo context.
 *
 * Session continuity: when `sessionId` is provided, the API server forwards it
 * to the Hermes gateway via X-Hermes-Session-Id so the agent keeps context
 * WITHOUT re-sending the full history as prompt text on every turn.
 */
export function useChat(mundo?: string, sessionId?: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = useCallback(
    async (text: string) => {
      if (!text.trim() || isLoading) return;

      const userMsg: ChatMessage = { role: "user", content: text };
      const updated = [...messages, userMsg];
      setMessages(updated);
      setError(null);
      setIsLoading(true);

      try {
        const resp = await fetch(`${API_BASE_URL}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: updated.map((m) => ({ role: m.role, content: m.content })),
            mundo: mundo ?? "",
            session_id: sessionId ?? "",
          }),
        });

        if (!resp.ok) {
          throw new Error(`Error ${resp.status}`);
        }

        const data: ChatResponse = await resp.json();

        if (data.error) {
          setError(data.error);
        } else if (data.content) {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: data.content! },
          ]);
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Error de conexión",
        );
      } finally {
        setIsLoading(false);
      }
    },
    [messages, isLoading, mundo, sessionId],
  );

  const clear = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  return { messages, isLoading, error, send, clear };
}
