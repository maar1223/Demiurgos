import { useState } from "react";
import { useGuidedCharacter } from "@/hooks/useGuidedCharacter";
import { Spinner } from "@/components/atoms/Spinner";

interface GuidedCharacterPanelProps {
  world: string;
}

/** Compact guided creation surface; metadata and provenance never render here. */
export function GuidedCharacterPanel({ world }: GuidedCharacterPanelProps) {
  const [input, setInput] = useState("");
  const guided = useGuidedCharacter(world);
  const session = guided.session;
  const messages = session?.messages ?? [];

  const submit = () => {
    if (!input.trim() || guided.isLoading) return;
    void guided.send(input);
    setInput("");
  };

  return (
    <section aria-label="Guided character creation" className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-filio px-4 py-3">
        <h2 className="text-body font-medium text-pergamino">Create a character</h2>
        <p className="mt-1 text-xs text-tinta-desvaida">One question at a time. You approve every detail.</p>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {messages.map((message, index) => (
          <div key={`${message.role}-${index}`} className="mb-2 rounded-lg bg-cripta px-3 py-2 text-sm text-pergamino">
            {message.content}
          </div>
        ))}
        {session?.pending_question && (
          <p className="mb-3 rounded-lg border border-llamita/30 bg-llamita/10 px-3 py-2 text-sm text-pergamino">
            {session.pending_question}
          </p>
        )}
        {session?.proposal && (
          <div className="rounded-lg border border-filio bg-cripta p-3">
            <p className="text-xs text-tinta-desvaida">Suggested detail</p>
            <p className="mt-1 text-sm text-pergamino">{session.proposal.label}: {session.proposal.value}</p>
            <div className="mt-3 flex gap-2">
              <button type="button" onClick={() => void guided.reject()} disabled={guided.isLoading} className="rounded-md border border-filio px-2.5 py-1.5 text-xs text-tinta-desvaida disabled:opacity-50">Reject</button>
              <button type="button" onClick={() => void guided.accept()} disabled={guided.isLoading} className="rounded-md bg-llamita px-2.5 py-1.5 text-xs text-cripta disabled:opacity-50">Accept</button>
            </div>
          </div>
        )}
        {session?.index_status && session.index_status !== "indexed" && (
          <div role="status" className="mt-3 rounded-md border border-filio px-3 py-2 text-xs text-tinta-desvaida">
            Character created; graph indexing is {session.index_status}.
            <button type="button" onClick={() => void guided.retryIndex()} disabled={guided.isLoading} className="ml-2 text-llamita underline disabled:opacity-50">Retry</button>
          </div>
        )}
        {guided.error && (
          <div role="alert" className="mt-3 rounded-md border border-sangre/30 bg-sangre/10 px-3 py-2 text-xs text-sangre">
            {guided.error} Nothing was saved. Retry when ready.
          </div>
        )}
      </div>
      <div className="border-t border-filio px-4 py-3">
        <div className="flex items-end gap-2">
          <textarea aria-label="Character creation response" value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }} disabled={guided.isLoading || Boolean(session?.proposal)} rows={2} placeholder="Describe the character..." className="min-w-0 flex-1 resize-none rounded-lg border border-filio bg-cripta px-3 py-2 text-sm text-pergamino placeholder:text-sombra focus:border-llamita focus:outline-none" />
          <button type="button" onClick={submit} disabled={guided.isLoading || !input.trim() || Boolean(session?.proposal)} className="h-9 rounded-lg bg-llamita px-3 text-xs text-cripta disabled:opacity-50">{guided.isLoading ? <Spinner size="sm" /> : "Send"}</button>
        </div>
      </div>
    </section>
  );
}
