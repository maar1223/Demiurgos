import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { cn } from "@/lib/utils";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { MarkdownBody } from "@/components/organisms/MarkdownViewer";
import { useAIAssistantSessions } from "@/hooks/useAIAssistantSessions";
import { useWhisper } from "@/hooks/useWhisper";

/* ------------------------------------------------------------------ */
/*  Types & Constants                                                  */
/* ------------------------------------------------------------------ */

export interface AssistantEditRequest {
  prompt: string;
  sessionId: string;
}

interface AIAssistantSidebarProps {
  mundo: string;
  section?: string;
  filePath?: string;
  onProposeEdit?: (request: AssistantEditRequest) => void | Promise<void>;
}

type Screen = "chat" | "history";

const SUGGESTIONS = [
  "¿Quién es Rhyz?",
  "Explicame el sistema Stal",
  "¿Qué es el Flud?",
  "Contame sobre Ekkor",
];

/* ------------------------------------------------------------------ */
/*  Date helper                                                        */
/* ------------------------------------------------------------------ */

function formatDate(ts: number): string {
  const d = new Date(ts);
  const day = d.getDate();
  const months = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
  ];
  return `${day} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

/* ================================================================== */
/*  ChatScreen                                                         */
/* ================================================================== */

interface ChatScreenProps {
  mundo: string;
  section?: string;
  filePath?: string;
  activeSession: ReturnType<typeof useAIAssistantSessions>["activeSession"];
  isSending: boolean;
  error: string | null;
  sendMessage: (prompt: string) => void;
  whisperStatus: ReturnType<typeof useWhisper>["status"];
  whisperIsRecording: boolean;
  whisperIsTranscribing: boolean;
  whisperStartRecording: () => void;
  whisperStopRecording: () => void;
  whisperError: string | null;
  onHistoryClick: () => void;
  onProposeEdit?: (request: AssistantEditRequest) => void | Promise<void>;
}

function ChatScreen({
  mundo,
  section,
  filePath,
  activeSession,
  isSending,
  error,
  sendMessage,
  whisperStatus,
  whisperIsRecording,
  whisperIsTranscribing,
  whisperStartRecording,
  whisperStopRecording,
  whisperError,
  onHistoryClick,
  onProposeEdit,
}: ChatScreenProps) {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      messagesEndRef.current?.scrollIntoView?.({ behavior: "smooth" });
    } catch { /* jsdom */ }
  }, [activeSession?.messages, isSending]);

  const handleSend = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed || isSending) return;
    sendMessage(trimmed);
    setInput("");
  }, [input, isSending, sendMessage]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const handleSuggestion = useCallback(
    (text: string) => sendMessage(text),
    [sendMessage],
  );

  const handleLightbulb = useCallback(() => {
    const prompt = `Estoy en la sección ${section}${filePath ? `, archivo ${filePath}` : ""}. Dame ideas sobre qué puedo trabajar o profundizar aquí.`;
    sendMessage(prompt);
  }, [section, filePath, sendMessage]);

  const handleMicClick = useCallback(() => {
    if (whisperIsRecording) {
      whisperStopRecording();
    } else if (!whisperIsTranscribing) {
      whisperStartRecording();
    }
  }, [whisperIsRecording, whisperIsTranscribing, whisperStartRecording, whisperStopRecording]);

  const messages = activeSession?.messages ?? [];
  const latestUserPrompt = [...messages]
    .reverse()
    .find((message) => message.role === "user")?.content.trim();
  const canProposeEdit = Boolean(
    onProposeEdit &&
      section &&
      filePath &&
      activeSession?.id &&
      latestUserPrompt &&
      !isSending,
  );
  const proposeEditDisabledReason = !section || !filePath
    ? "Abrí un archivo para proponer una edición."
    : !latestUserPrompt
      ? "Escribí y enviá una solicitud al asistente primero."
      : isSending
        ? "Esperá a que termine la respuesta del asistente."
        : "Proponer una edición usando la última solicitud enviada.";

  const handleProposeEdit = useCallback(() => {
    if (
      !onProposeEdit ||
      !section ||
      !filePath ||
      !activeSession?.id ||
      !latestUserPrompt ||
      isSending
    ) {
      return;
    }
    void onProposeEdit({
      prompt: latestUserPrompt,
      sessionId: activeSession.id,
    });
  }, [activeSession?.id, filePath, isSending, latestUserPrompt, onProposeEdit, section]);

  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-filio px-4 py-3 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <button
            type="button"
            onClick={handleLightbulb}
            disabled={isSending}
            className="flex h-7 w-7 items-center justify-center rounded-md text-tinta-desvaida hover:text-pergamino hover:bg-piedra transition-colors shrink-0 disabled:opacity-40"
            title="Ideas para esta sección"
            aria-label="Ideas para esta sección"
          >
            <Icon name="lightbulb" size={14} />
          </button>
          <div className="min-w-0">
            <h2 className="text-body font-medium text-pergamino truncate">
              Asistente IA
            </h2>
            <p className="text-xs text-tinta-desvaida truncate">{mundo}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onHistoryClick}
          className="flex h-7 w-7 items-center justify-center rounded-md text-tinta-desvaida hover:text-pergamino hover:bg-piedra transition-colors shrink-0"
          title="Historial de sesiones"
          aria-label="Historial de sesiones"
        >
          <Icon name="history" size={14} />
        </button>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {messages.length === 0 && !isSending && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-llamita/10 text-llamita">
              <Icon name="lightbulb" size={24} />
            </div>
            <h3 className="mb-1 text-body font-medium text-pergamino">
              Preguntame sobre tu mundo
            </h3>
            <p className="mb-4 text-xs text-tinta-desvaida max-w-[200px]">
              Conozco todo el lore de{" "}
              <strong className="text-pergamino">{mundo}</strong>.
            </p>
            <div className="flex flex-wrap justify-center gap-1.5">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => handleSuggestion(suggestion)}
                  className="rounded-md border border-filio bg-cripta px-2.5 py-1 text-xs text-tinta-desvaida transition-colors hover:border-llamita/40 hover:text-pergamino"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="space-y-3">
          {messages.map((msg, i) => (
            <div
              key={i}
              className={cn(
                "flex",
                msg.role === "user" ? "justify-end" : "justify-start",
              )}
            >
              <div
                className={cn(
                  "max-w-[85%] rounded-lg px-3 py-2 text-body leading-relaxed overflow-hidden",
                  msg.role === "user"
                    ? "bg-llamita text-cripta"
                    : "bg-cripta text-pergamino",
                )}
              >
                {msg.role === "assistant" ? (
                  <MarkdownBody
                    content={msg.content}
                    mundo={mundo}
                    className="prose-sm"
                  />
                ) : (
                  <div className="whitespace-pre-wrap break-words text-body">
                    {msg.content}
                  </div>
                )}
              </div>
            </div>
          ))}

          {isSending && (
            <div className="flex justify-start">
              <div className="rounded-lg bg-cripta px-4 py-2.5">
                <Spinner size="sm" />
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {(error || whisperError) && (
        <div className="mx-4 mb-2 rounded-md border border-sangre/30 bg-sangre/10 px-3 py-1.5 text-xs text-sangre">
          {error || whisperError}
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-filio px-4 py-3 shrink-0">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Escribí tu pregunta..."
            rows={2}
            className="min-w-0 flex-1 resize-none rounded-lg border border-filio bg-cripta px-3 py-2 text-body text-pergamino placeholder:text-sombra focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50"
            disabled={isSending}
          />
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={handleMicClick}
              disabled={whisperIsTranscribing}
              className={cn(
                "flex h-9 w-9 items-center justify-center rounded-lg transition-colors shrink-0",
                whisperStatus === "recording"
                  ? "bg-sangre text-pergamino animate-pulse"
                  : whisperStatus === "transcribing"
                    ? "text-llamita"
                    : "text-tinta-desvaida hover:text-pergamino hover:bg-piedra",
              )}
              aria-label={
                whisperIsRecording
                  ? "Detener grabación"
                  : whisperIsTranscribing
                    ? "Transcribiendo..."
                    : "Grabar nota de voz"
              }
            >
              {whisperIsTranscribing ? (
                <Icon name="spinner" size={16} className="animate-spin" />
              ) : (
                <Icon
                  name={whisperIsRecording ? "stop" : "mic"}
                  size={16}
                />
              )}
            </button>

            <button
              type="button"
              onClick={handleSend}
              disabled={isSending || !input.trim()}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-llamita text-cripta hover:bg-llama-alta disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
              aria-label="Enviar"
            >
              {isSending ? (
                <Spinner size="sm" />
              ) : (
                <Icon name="chevron-right" size={16} />
              )}
            </button>
          </div>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <button
            type="button"
            onClick={handleProposeEdit}
            disabled={!canProposeEdit}
            title={proposeEditDisabledReason}
            aria-label="Proponer edición"
            className="flex items-center gap-1.5 rounded-md border border-filio px-2.5 py-1.5 text-xs text-tinta-desvaida transition-colors hover:border-llamita/40 hover:text-pergamino disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Icon name="edit" size={13} />
            Proponer edición
          </button>
          {!canProposeEdit && (
            <span className="text-xs text-sombra">{proposeEditDisabledReason}</span>
          )}
        </div>
        <p className="mt-1 text-xs text-sombra">
          Enter para enviar · Shift+Enter para nueva línea
        </p>
      </div>
    </>
  );
}

/* ================================================================== */
/*  HistoryScreen                                                      */
/* ================================================================== */

interface HistoryScreenProps {
  sessions: ReturnType<typeof useAIAssistantSessions>["sessions"];
  activeSessionId: string | null;
  switchSession: (id: string) => void;
  createSession: () => void;
  onChatClick: () => void;
}

function HistoryScreen({
  sessions,
  activeSessionId,
  switchSession,
  createSession,
  onChatClick,
}: HistoryScreenProps) {
  const totalMessages = sessions.reduce(
    (acc, s) => acc + s.messages.length,
    0,
  );

  const handleSessionClick = useCallback(
    (id: string) => {
      switchSession(id);
      onChatClick();
    },
    [switchSession, onChatClick],
  );

  const handleNewSession = useCallback(() => {
    createSession();
    onChatClick();
  }, [createSession, onChatClick]);

  return (
    <>
      <div className="flex items-center justify-between border-b border-filio px-4 py-3 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex h-7 w-7 items-center justify-center rounded-md text-llamita shrink-0">
            <Icon name="history" size={16} />
          </div>
          <h2 className="text-body font-medium text-pergamino truncate">
            Historial
          </h2>
        </div>
        <button
          type="button"
          onClick={handleNewSession}
          className="flex items-center gap-1 rounded-md bg-llamita px-2.5 py-1.5 text-xs font-medium text-cripta hover:bg-llama-alta transition-colors shrink-0"
          aria-label="Nueva sesión"
        >
          <Icon name="plus" size={12} />
          Nueva Sesión
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        {sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <p className="text-xs text-tinta-desvaida">
              No hay sesiones todavía.
            </p>
          </div>
        ) : (
          <div className="space-y-0.5 px-2">
            {sessions.map((session) => (
              <button
                key={session.id}
                type="button"
                onClick={() => handleSessionClick(session.id)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors",
                  session.id === activeSessionId
                    ? "bg-llamita/10 text-llamita"
                    : "text-tinta-desvaida hover:bg-piedra hover:text-pergamino",
                )}
              >
                <Icon
                  name="file"
                  size={14}
                  className="shrink-0 text-inherit opacity-60"
                />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate">
                    {session.title}
                  </p>
                  <p className="text-xs text-inherit opacity-50 mt-0.5">
                    {session.messages.length} mensaje
                    {session.messages.length !== 1 ? "s" : ""}
                  </p>
                </div>
                <span className="text-xs text-inherit opacity-40 shrink-0">
                  {formatDate(session.createdAt)}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="border-t border-filio px-4 py-2 shrink-0">
        <p className="text-xs text-sombra text-center">
          Mostrando {sessions.length} sesion
          {sessions.length !== 1 ? "es" : ""} ·{" "}
          {totalMessages} mensaje{totalMessages !== 1 ? "s" : ""} en total
        </p>
      </div>
    </>
  );
}

/* ================================================================== */
/*  Main Sidebar                                                       */
/* ================================================================== */

/**
 * AI Assistant sidebar with chat sessions, markdown-rendered responses,
 * voice recording (Whisper), suggestions, and session history.
 *
 * Designed to be the content of the right panel in EditorLayout.
 * Uses useAIAssistantSessions for localStorage-persisted sessions.
 */
export function AIAssistantSidebar({
  mundo,
  section,
  filePath,
  onProposeEdit,
}: AIAssistantSidebarProps) {
  const [screen, setScreen] = useState<Screen>("chat");

  const sessions = useAIAssistantSessions(mundo, section, filePath);

  const whisper = useWhisper({
    onTranscribed: useCallback(
      (text: string) => {
        sessions.sendMessage(text);
      },
      // eslint-disable-next-line react-hooks/exhaustive-deps
      [sessions.sendMessage],
    ),
  });

  const switchToChat = useCallback(() => setScreen("chat"), []);
  const switchToHistory = useCallback(() => setScreen("history"), []);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {screen === "chat" ? (
        <ChatScreen
          mundo={mundo}
          section={section}
          filePath={filePath}
          activeSession={sessions.activeSession}
          isSending={sessions.isSending}
          error={sessions.error}
          sendMessage={sessions.sendMessage}
          whisperStatus={whisper.status}
          whisperIsRecording={whisper.isRecording}
          whisperIsTranscribing={whisper.isTranscribing}
          whisperStartRecording={whisper.startRecording}
          whisperStopRecording={whisper.stopRecording}
          whisperError={whisper.error}
          onHistoryClick={switchToHistory}
          onProposeEdit={onProposeEdit}
        />
      ) : (
        <HistoryScreen
          sessions={sessions.sessions}
          activeSessionId={sessions.activeSessionId}
          switchSession={sessions.switchSession}
          createSession={sessions.createSession}
          onChatClick={switchToChat}
        />
      )}
    </div>
  );
}
