import { useState } from "react";
import { useGuidedCharacter } from "@/hooks/useGuidedCharacter";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { Spinner } from "@/components/atoms/Spinner";

interface GuidedCharacterPanelProps {
  world: string;
}

const SUPPORTED_PHASES = new Set([
  "confirmation",
  "conversation",
  "review",
  "complete",
]);

/** Compact guided creation surface; metadata and provenance never render here. */
export function GuidedCharacterPanel({ world }: GuidedCharacterPanelProps) {
  const [input, setInput] = useState("");
  const guided = useGuidedCharacter(world);
  const appLanguage = useAppLanguage();
  const isSpanish = appLanguage === "es";
  const session = guided.session;
  const messages = session?.messages ?? [];
  const unsupportedPhase =
    session !== null && !SUPPORTED_PHASES.has(session.phase);

  const submit = () => {
    if (!input.trim() || guided.isLoading) return;
    void guided.send(input);
    setInput("");
  };

  if (unsupportedPhase) {
    return (
      <section aria-label="Guided character creation" className="flex min-h-0 flex-1 flex-col">
        <div className="border-b border-edge px-4 py-3">
          <h2 className="text-body font-medium text-primary">
            {isSpanish ? "Crear un personaje" : "Create a character"}
          </h2>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3">
          <div role="alert" className="rounded-md border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error">
            {isSpanish
              ? "No se puede actuar sobre esta solicitud. No se guardó nada."
              : "I cannot safely act on this request. Nothing was saved."}
          </div>
        </div>
<div className="border-t border-edge px-4 py-3">
          <textarea aria-label="Character creation response" value={input} onChange={(event) => setInput(event.target.value)} disabled rows={2} placeholder={isSpanish ? "Describí el personaje..." : "Describe the character..."} className="w-full resize-none rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-action focus:outline-none disabled:opacity-50" />
        </div>
      </section>
    );
  }

  return (
    <section aria-label="Guided character creation" className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-edge px-4 py-3">
        <h2 className="text-body font-medium text-primary">
          {isSpanish ? "Crear un personaje" : "Create a character"}
        </h2>
        <p className="mt-1 text-xs text-muted">
          {isSpanish
            ? "Una pregunta por vez. Vos aprobás cada detalle."
            : "One question at a time. You approve every detail."}
        </p>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {messages.map((message, index) => (
          <div key={`${message.role}-${index}`} className="mb-2 rounded-lg bg-surface px-3 py-2 text-sm text-primary">
            {message.content}
          </div>
        ))}
        {session?.pending_question && (
          <p className="mb-3 rounded-lg border border-action/30 bg-action/10 px-3 py-2 text-sm text-primary">
            {session.pending_question}
          </p>
        )}
        {session?.proposal && (
          <div className="rounded-lg border border-edge bg-surface p-3">
            <p className="text-xs text-muted">
              {isSpanish ? "Detalle sugerido" : "Suggested detail"}
            </p>
            <p className="mt-1 text-sm text-primary">{session.proposal.label}: {session.proposal.value}</p>
            <div className="mt-3 flex gap-2">
              <button type="button" onClick={() => void guided.reject()} disabled={guided.isLoading} className="rounded-md border border-edge px-2.5 py-1.5 text-xs text-muted disabled:opacity-50">{isSpanish ? "Rechazar" : "Reject"}</button>
              <button type="button" onClick={() => void guided.accept()} disabled={guided.isLoading} className="rounded-md bg-action px-2.5 py-1.5 text-xs text-action-text disabled:opacity-50">{isSpanish ? "Aceptar" : "Accept"}</button>
            </div>
          </div>
        )}
        {session?.index_status && session.index_status !== "indexed" && (
          <div role="status" className="mt-3 rounded-md border border-edge px-3 py-2 text-xs text-muted">
            {isSpanish
              ? `Personaje creado; la indexación del grafo está ${session.index_status}.`
              : `Character created; graph indexing is ${session.index_status}.`}
            <button type="button" onClick={() => void guided.retryIndex()} disabled={guided.isLoading} className="ml-2 text-action underline disabled:opacity-50">{isSpanish ? "Reintentar" : "Retry"}</button>
          </div>
        )}
        {guided.error && (
          <div role="alert" className="mt-3 rounded-md border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error">
            {guided.error} {isSpanish ? "No se guardó nada. Reintentá cuando quieras." : "Nothing was saved. Retry when ready."}
          </div>
        )}
      </div>
      <div className="border-t border-edge px-4 py-3">
        <div className="flex items-end gap-2">
          <textarea aria-label="Character creation response" value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }} disabled={guided.isLoading || Boolean(session?.proposal)} rows={2} placeholder={isSpanish ? "Describí el personaje..." : "Describe the character..."} className="min-w-0 flex-1 resize-none rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-action focus:outline-none" />
          <button type="button" onClick={submit} disabled={guided.isLoading || !input.trim() || Boolean(session?.proposal)} className="h-9 rounded-lg bg-action px-3 text-xs text-action-text disabled:opacity-50">{guided.isLoading ? <Spinner size="sm" /> : isSpanish ? "Enviar" : "Send"}</button>
        </div>
      </div>
    </section>
  );
}
