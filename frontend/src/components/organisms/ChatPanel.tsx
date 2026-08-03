import { useState, useRef, useEffect, type FormEvent, type KeyboardEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useChat } from "@/hooks/useChat";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { cn } from "@/lib/utils";

interface ChatPanelProps {
  mundo?: string;
}

/**
 * AI Assistant chat panel.
 *
 * Renders in the "Asistente" tab of the right panel.
 * Sends messages to POST /api/chat and displays markdown responses.
 */
export function ChatPanel({ mundo }: ChatPanelProps) {
  const { messages, isLoading, error, send, clear } = useChat(mundo);
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, isLoading]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    send(input.trim());
    setInput("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-3 py-3">
        {messages.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
            <Icon name="lightbulb" size={24} className="text-sombra" />
            <p className="text-small text-sombra">
              Preguntame sobre personajes, lore, tramas...
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={cn(
              "mb-3 flex",
              msg.role === "user" ? "justify-end" : "justify-start",
            )}
          >
            <div
              className={cn(
                "max-w-[90%] rounded-lg px-3 py-2 text-small",
                msg.role === "user"
                  ? "bg-llamita/15 text-pergamino"
                  : "bg-piedra text-pergamino",
              )}
            >
              {msg.role === "assistant" ? (
                <div className="prose prose-sm prose-invert max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}
            </div>
          </div>
        ))}

        {/* Loading indicator */}
        {isLoading && (
          <div className="mb-3 flex justify-start">
            <div className="rounded-lg bg-piedra px-3 py-2">
              <Spinner size="sm" />
            </div>
          </div>
        )}

        {/* Error banner */}
        {error && (
          <div className="mb-3 rounded-lg border border-sangre/30 bg-sangre/10 px-3 py-2 text-small text-sangre">
            {error}
            <button
              type="button"
              onClick={clear}
              className="ml-2 underline hover:text-sangre/80"
            >
              Limpiar chat
            </button>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <form
        onSubmit={handleSubmit}
        className="border-t border-filio px-3 py-2"
      >
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Escribí tu mensaje..."
            rows={1}
            className={cn(
              "min-h-[36px] max-h-[120px] flex-1 resize-none rounded-lg border border-filio bg-madero px-3 py-2",
              "text-small text-pergamino placeholder:text-sombra",
              "focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50",
            )}
            disabled={isLoading}
            aria-label="Mensaje del chat"
          />
          <button
            type="submit"
            disabled={!input.trim() || isLoading}
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
              "bg-llamita text-cripta transition-colors",
              "hover:bg-llama-alta disabled:cursor-not-allowed disabled:opacity-50",
            )}
            aria-label="Enviar mensaje"
          >
            <Icon name="chevron-right" size={16} />
          </button>
        </div>
        <p className="mt-1 text-[10px] text-sombra">
          Enter para enviar · Shift+Enter para nueva línea
        </p>
      </form>
    </div>
  );
}
