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
import {
  INCOMPLETE_EVIDENCE_WARNING,
  NEUTRAL_EVIDENCE_WARNING,
} from "@/api/assistantActivity";
import { useAIAssistantSessions } from "@/hooks/useAIAssistantSessions";
import { GLOBAL_ASSISTANT_CONTEXT } from "@/hooks/useAIAssistantSessions";
import { chatAttachmentThumbnailUrl } from "@/api/chatAttachments";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { TFunction } from "@/i18n/messages";
import { semanticBlockedText } from "@/lib/semanticIntent";
import type {
  EditProposal,
  GuidedFlowEcho,
  GuidedMethodOption,
} from "@/api/types";
import type { GuidedMethodChoice } from "@/api/guidedCharacter";
import { getGuidedMethods } from "@/api/methodologies";
import { useWhisper } from "@/hooks/useWhisper";

/* ------------------------------------------------------------------ */
/*  Types & Constants                                                  */
/* ------------------------------------------------------------------ */

export interface AssistantEditRequest {
  prompt: string;
  sessionId: string;
}

interface AIAssistantSidebarProps {
  /** World-scoped context. Omit (or pass null/undefined) for world-agnostic
   *  sessions such as the Taller de Ideas — the hook then uses the stable
   *  global context key `ideas-global`. */
  mundo?: string;
  section?: string;
  filePath?: string;
  onProposeEdit?: (request: AssistantEditRequest) => void | Promise<void>;
  onGuidedReview?: (proposal: EditProposal) => void | Promise<void>;
}

type Screen = "chat" | "history";

const SAFE_SOURCE_ROOTS = new Set([
  "lore",
  "personajes",
  "referencias",
  "media",
]);
const SAFE_ACTIVITY_WARNINGS = new Set([
  INCOMPLETE_EVIDENCE_WARNING,
  NEUTRAL_EVIDENCE_WARNING,
]);

// Keep the activity/evidence integration intact, but hide its presentation
// until the provider exposes reliable structured consulted-file evidence.
const ACTIVITY_EVIDENCE_UI_ENABLED = false;

function isSafeEvidencePath(value: string): boolean {
  if (!value || value.includes("\\") || value.startsWith("/")) return false;
  const parts = value.split("/");
  return (
    SAFE_SOURCE_ROOTS.has(parts[0]) &&
    parts.every((part) => part && part !== "." && part !== ".." && !part.startsWith("."))
  );
}

function safeActivityWarning(value: string | undefined): string | null {
  return value && SAFE_ACTIVITY_WARNINGS.has(value) ? value : null;
}

function activityStatusLabel(
  status: "running" | "succeeded" | "failed",
  t: TFunction,
): string {
  if (status === "running") return t("assistant.activity.status.running");
  if (status === "succeeded") return t("assistant.activity.status.succeeded");
  return t("assistant.activity.status.failed");
}

function activityOperationLabel(
  operation: "Search world" | "Read world",
  t: TFunction,
): string {
  if (operation === "Search world") return t("assistant.activity.operation.searchWorld");
  if (operation === "Read world") return t("assistant.activity.operation.readWorld");
  return t("assistant.activity.operation.worldActivity");
}

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
  mundo?: string;
  section?: string;
  filePath?: string;
  activeSession: ReturnType<typeof useAIAssistantSessions>["activeSession"];
  isSending: boolean;
  error: string | null;
  activity: ReturnType<typeof useAIAssistantSessions>["activity"];
  evidence: ReturnType<typeof useAIAssistantSessions>["evidence"];
  sendMessage: (prompt: string) => void;
  attachDocument: (file: File) => Promise<void>;
  removeAttachment: (attachmentId: string) => void;
  attaching: ReturnType<typeof useAIAssistantSessions>["attaching"];
  whisperStatus: ReturnType<typeof useWhisper>["status"];
  whisperIsRecording: boolean;
  whisperIsTranscribing: boolean;
  whisperStartRecording: () => void;
  whisperStopRecording: () => void;
  whisperError: string | null;
  onHistoryClick: () => void;
  onNewChat: () => void;
  onProposeEdit?: (request: AssistantEditRequest) => void | Promise<void>;
  resolveGuidedProposal: (accept: boolean) => Promise<void>;
  resolveGuidedConsent: (
    accept: boolean,
    method?: GuidedMethodChoice,
  ) => Promise<void>;
  /** Eligible character-creation methods for THIS session (S4/S6). */
  guidedMethods: GuidedMethodOption[];
  /** The world's eligible legacy activation, preselected; null = factory. */
  guidedMethodDefault: { skill_id: string; version: string } | null;
  /** Server-resolved flow for the pending consent card (S1). */
  consentFlow?: GuidedFlowEcho;
  requestGuidedReview?: () => Promise<EditProposal | null>;
  onGuidedReview?: (proposal: EditProposal) => void | Promise<void>;
}

interface ActivityEvidenceProps {
  activity: ReturnType<typeof useAIAssistantSessions>["activity"];
  evidence: ReturnType<typeof useAIAssistantSessions>["evidence"];
  isSending: boolean;
}

function ActivityEvidence({ activity, evidence, isSending }: ActivityEvidenceProps) {
  const { t } = useAppLanguage();
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const sources = evidence.sources.filter(isSafeEvidencePath);
  const warnings = Array.from(
    new Set([
      ...evidence.warnings.map(safeActivityWarning),
      ...activity.items.map((item) => safeActivityWarning(item.warning)),
    ]),
  ).filter((warning): warning is string => Boolean(warning));

  return (
    <section
      aria-label={t("assistant.activity.sectionAria")}
      className="mb-3 rounded-lg border border-edge bg-surface/70 px-3 py-2.5 text-xs"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-medium text-primary">{t("assistant.activity.title")}</h3>
        {activity.status === "running" && (
          <span className="text-action">{t("assistant.activity.queryingSources")}</span>
        )}
      </div>

      {activity.items.length > 0 && (
        <ul aria-label={t("assistant.activity.listAria")} className="mt-2 space-y-1.5">
          {activity.items.map((item) => (
            <li key={item.item_id} className="flex items-center justify-between gap-2">
              <span className="text-muted">
                {activityOperationLabel(item.operation, t)}
              </span>
              <span
                className={cn(
                  item.status === "failed" ? "text-status-error" : "text-muted",
                )}
              >
                {activityStatusLabel(item.status, t)}
              </span>
            </li>
          ))}
        </ul>
      )}

      {warnings.length > 0 && (
        <div role="alert" className="mt-2 text-status-error">
          {warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      )}

      {sources.length > 0 ? (
        <div className="mt-2 border-t border-edge pt-2">
          <button
            type="button"
            aria-expanded={sourcesOpen}
            onClick={() => setSourcesOpen((open) => !open)}
            className="text-left text-muted hover:text-primary"
          >
            {t("assistant.activity.confirmedSources", { count: sources.length })}
          </button>
          {sourcesOpen && (
            <ul className="mt-1.5 space-y-1 pl-3 text-muted">
              {sources.map((source) => (
                <li key={source} className="break-words">
                  {source}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="mt-2 border-t border-edge pt-2 text-muted">
          {activity.availability === "unavailable"
            ? activity.availabilityReason === "file_evidence_contract_unverified"
              ? t("assistant.activity.unavailableContract")
              : t("assistant.activity.unavailable")
            : isSending
              ? t("assistant.activity.safeChannel")
            : activity.status === "running"
              ? t("assistant.activity.waiting")
              : t("assistant.activity.noSources")}
        </p>
      )}
    </section>
  );
}

function ChatScreen({
  mundo,
  section,
  filePath,
  activeSession,
  isSending,
  error,
  activity,
  evidence,
  sendMessage,
  attachDocument,
  removeAttachment,
  attaching,
  whisperStatus,
  whisperIsRecording,
  whisperIsTranscribing,
  whisperStartRecording,
  whisperStopRecording,
  whisperError,
  onHistoryClick,
  onNewChat,
  onProposeEdit,
  onGuidedReview,
  resolveGuidedProposal,
  resolveGuidedConsent,
  guidedMethods,
  guidedMethodDefault,
  consentFlow,
  requestGuidedReview,
}: ChatScreenProps) {
  const [input, setInput] = useState("");
  const [consentMethodId, setConsentMethodId] = useState("factory");
  const [consentMethodTouched, setConsentMethodTouched] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      messagesEndRef.current?.scrollIntoView?.({ behavior: "smooth" });
    } catch { /* jsdom */ }
  }, [activeSession?.messages, isSending]);

  const { language: appLanguage, t } = useAppLanguage();
  const attachments = activeSession?.attachments ?? [];
  const attachmentMundo = mundo ?? GLOBAL_ASSISTANT_CONTEXT;
  const messages = activeSession?.messages ?? [];
  const confirmationPending = activeSession?.guided?.phase === "confirmation";
  const consentToken = activeSession?.consentToken;
  const guidedMethodology = activeSession?.guided?.methodology ?? null;

  const handleSend = useCallback(() => {
    const trimmed = input.trim();
    if (isSending) return;
    // An attachment is a complete turn on its own: ask for a summary (or the
    // image question) with the localized default when nothing was typed (S6).
    const onlyImages =
      attachments.length > 0 && attachments.every((item) => item.kind === "image");
    const fallback = onlyImages
      ? t("assistant.attach.defaultPromptImage")
      : t("assistant.attach.defaultPrompt");
    const prompt = trimmed || (attachments.length > 0 ? fallback : "");
    if (!prompt) return;
    sendMessage(prompt);
    setInput("");
  }, [attachments, input, isSending, sendMessage, t]);

  const handleAttachClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      // Reset first: picking the same file twice must still fire a change.
      event.target.value = "";
      if (file) void attachDocument(file);
    },
    [attachDocument],
  );

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
    const prompt = mundo
      ? `Estoy en la sección ${section}${filePath ? `, archivo ${filePath}` : ""}. Dame ideas sobre qué puedo trabajar o profundizar aquí.`
      : "Dame ideas sobre qué puedo trabajar en el banco global de ideas.";
    sendMessage(prompt);
  }, [mundo, section, filePath, sendMessage]);

  const handleMicClick = useCallback(() => {
    if (whisperIsRecording) {
      whisperStopRecording();
    } else if (!whisperIsTranscribing) {
      whisperStartRecording();
    }
  }, [whisperIsRecording, whisperIsTranscribing, whisperStartRecording, whisperStopRecording]);

  const guidedMethodName = guidedMethodology
    ? guidedMethodology.factory
      ? t("guided.methodFactory")
      : guidedMethods.find(
          (method) => method.skill_id === guidedMethodology.skill_id,
        )?.name ?? guidedMethodology.skill_id ?? ""
    : null;

  const consentFlowKey =
    consentFlow?.ui_copy_key === "system"
      ? "system"
      : consentFlow?.ui_copy_key === "chronology"
        ? "chronology"
        : consentFlow?.ui_copy_key === "entity"
          ? "entity"
          : "character";

  /** Preselect the flow default when the consent card appears (S3/S6).
   *  The character flow keeps its factory fallback; a declared flow preselects
   *  its first eligible method (the server's foundational default). */
  useEffect(() => {
    if (!consentToken) {
      setConsentMethodTouched(false);
      return;
    }
    if (!consentMethodTouched) {
      setConsentMethodId(
        consentFlowKey === "character"
          ? (guidedMethodDefault?.skill_id ?? "factory")
          : (guidedMethodDefault?.skill_id ?? guidedMethods[0]?.skill_id ?? ""),
      );
    }
  }, [
    consentToken, consentFlowKey, guidedMethodDefault, guidedMethods,
    consentMethodTouched,
  ]);

  const consentChoice = (): GuidedMethodChoice | undefined => {
    if (consentMethodId === "factory" || !consentMethodId) {
      // Only the character flow has a builtin factory contract.
      return consentFlowKey === "character" ? { skill_id: "factory" } : undefined;
    }
    const chosen = guidedMethods.find(
      (method) => method.skill_id === consentMethodId,
    );
    if (chosen) return { skill_id: chosen.skill_id, version: chosen.version };
    return consentFlowKey === "character" ? { skill_id: "factory" } : undefined;
  };
  const isSpanish = appLanguage === "es";
  const latestUserPrompt = [...messages]
    .reverse()
    .find((message) => message.role === "user")?.content.trim();
  const suggestions = mundo
    ? [
        t("assistant.suggestion.rhyz"),
        t("assistant.suggestion.stal"),
        t("assistant.suggestion.flud"),
        t("assistant.suggestion.ekkor"),
      ]
    : [
        t("assistant.suggestion.global.character"),
        t("assistant.suggestion.global.plot"),
        t("assistant.suggestion.global.concept"),
      ];
  const canProposeEdit = Boolean(
    onProposeEdit &&
      section &&
      filePath &&
      activeSession?.id &&
      latestUserPrompt &&
      !isSending,
  );
  const proposeEditDisabledReason = !mundo
    ? t("assistant.propose.disabled.noWorld")
    : !section || !filePath
      ? t("assistant.propose.disabled.noFile")
      : !latestUserPrompt
        ? t("assistant.propose.disabled.noPrompt")
        : isSending
          ? t("assistant.propose.disabled.sending")
          : t("assistant.propose.enabled");
  const hasAssistantAnswer = messages.some((message) => message.role === "assistant");
  const hasGuidedCandidate = Boolean(
    activeSession?.guided && (
      Object.keys(activeSession.guided.candidate?.proposals ?? {}).length > 0 ||
      Object.keys(activeSession.guided.candidate?.accepted_canon ?? {}).length > 0 ||
      activeSession.guided.phase === "review" ||
      activeSession.guided.phase === "complete"
    ),
  );
  const showActivityEvidence =
    isSending ||
    hasAssistantAnswer ||
    activity.accepted ||
    activity.items.length > 0 ||
    evidence.status !== "neutral";

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

  const handleGuidedReview = useCallback(async () => {
    if (!onGuidedReview || isSending) return;
    if (activeSession?.pendingReview) {
      await onGuidedReview(activeSession.pendingReview);
      return;
    }
    if (!requestGuidedReview || !activeSession?.guided) return;
    const proposal = await requestGuidedReview();
    if (proposal) await onGuidedReview(proposal);
  }, [activeSession?.guided, activeSession?.pendingReview, isSending, onGuidedReview, requestGuidedReview]);

  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-edge px-4 py-3 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <button
            type="button"
            onClick={handleLightbulb}
            disabled={confirmationPending || isSending}
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted hover:text-primary hover:bg-surface-hover transition-colors shrink-0 disabled:opacity-40"
            title={t("assistant.header.ideasTitle")}
            aria-label={t("assistant.header.ideasTitle")}
          >
            <Icon name="lightbulb" size={14} />
          </button>
          <div className="min-w-0">
            <h2 className="text-body font-medium text-primary truncate">
              {t("assistant.header.title")}
            </h2>
            <p className="text-xs text-muted truncate">
              {mundo ?? t("assistant.header.globalContext")}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={onNewChat}
            disabled={confirmationPending}
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted hover:text-primary hover:bg-surface-hover transition-colors shrink-0 disabled:opacity-40"
            title={t("assistant.header.newChat")}
            aria-label={t("assistant.header.newChat")}
          >
            <Icon name="plus" size={14} />
          </button>
          <button
            type="button"
            onClick={onHistoryClick}
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted hover:text-primary hover:bg-surface-hover transition-colors shrink-0"
            title={t("assistant.header.history")}
            aria-label={t("assistant.header.history")}
          >
            <Icon name="history" size={14} />
          </button>
        </div>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {messages.length === 0 && !isSending && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-action/10 text-action">
              <Icon name="lightbulb" size={24} />
            </div>
            {mundo ? (
              <>
                <h3 className="mb-1 text-body font-medium text-primary">
                  {t("assistant.empty.worldTitle")}
                </h3>
                <p className="mb-4 text-xs text-muted max-w-[200px]">
                  {t("assistant.empty.worldBody", { world: mundo })}
                </p>
              </>
            ) : (
              <>
                <h3 className="mb-1 text-body font-medium text-primary">
                  {t("assistant.empty.globalTitle")}
                </h3>
                <p className="mb-4 text-xs text-muted max-w-[200px]">
                  {t("assistant.empty.globalBody")}
                </p>
              </>
            )}
            <div className="flex flex-wrap justify-center gap-1.5">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => handleSuggestion(suggestion)}
                  className="rounded-md border border-edge bg-surface px-2.5 py-1 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary"
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
                    ? "bg-action text-action-text"
                    : "bg-surface text-primary",
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

           {guidedMethodName && (
             <p className="mb-2 rounded-lg border border-edge bg-surface px-3 py-2 text-xs text-muted">
               {t("guided.methodCurrent", { name: guidedMethodName })}
             </p>
           )}

           {confirmationPending && (
             <section
               aria-labelledby="guided-confirmation-title"
               className="rounded-lg border border-action/40 bg-action/10 px-3 py-3 text-sm text-primary"
             >
               <h3 id="guided-confirmation-title" className="font-medium">
                 {t("assistant.confirm.title")}
               </h3>
               <p className="mt-1 text-xs leading-relaxed text-muted">
                 {t("assistant.confirm.body")}
               </p>
               <div className="mt-3 flex flex-wrap gap-2">
                 <button
                   type="button"
                   onClick={() => void sendMessage(isSpanish ? "sí" : "yes")}
                   disabled={isSending}
                   className="rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
                 >
                   {t("assistant.confirm.yes")}
                 </button>
                 <button
                   type="button"
                   onClick={() => void sendMessage("no")}
                   disabled={isSending}
                   className="rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                 >
                   {t("assistant.confirm.no")}
                 </button>
               </div>
             </section>
           )}

           {consentToken && (
             <section
               aria-labelledby="guided-consent-title"
               className="rounded-lg border border-action/40 bg-action/10 px-3 py-3 text-sm text-primary"
             >
                <h3 id="guided-consent-title" className="font-medium">
                  {t("assistant.consent.title")}
                </h3>
                <p className="mt-1 text-xs leading-relaxed text-muted">
                  {consentFlowKey === "system"
                    ? t("assistant.consent.body.system")
                    : consentFlowKey === "chronology"
                      ? t("assistant.consent.body.chronology")
                      : consentFlowKey === "entity"
                        ? t("assistant.consent.body.entity")
                        : t("assistant.consent.body.character")}
                </p>
                <label className="mt-2 flex flex-col gap-1 text-xs text-muted">
                  {t("guided.methodTitle")}
                  <select
                    value={consentMethodId}
                    onChange={(event) => {
                      setConsentMethodTouched(true);
                      setConsentMethodId(event.target.value);
                    }}
                    disabled={isSending}
                    className="rounded-lg border border-edge bg-surface px-2 py-1.5 text-sm text-primary focus:border-action focus:outline-none disabled:opacity-50"
                  >
                    {consentFlowKey === "character" && (
                      <option value="factory">{t("guided.methodFactory")}</option>
                    )}
                    {guidedMethods.map((method) => (
                      <option key={method.skill_id} value={method.skill_id}>
                        {method.name} (v{method.version})
                      </option>
                    ))}
                  </select>
                </label>
               <div className="mt-3 flex flex-wrap gap-2">
                 <button
                   type="button"
                   onClick={() => void resolveGuidedConsent(true, consentChoice())}
                   disabled={isSending}
                    className="rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {t("assistant.consent.yes")}
                  </button>
                  <button
                    type="button"
                    onClick={() => void resolveGuidedConsent(false)}
                    disabled={isSending}
                    className="rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {t("assistant.consent.no")}
                  </button>
               </div>
             </section>
           )}

           {activeSession?.guided?.proposal && (
            <div className="rounded-lg border border-edge bg-surface px-3 py-2 text-sm text-primary">
              <p className="text-xs text-muted">
                {t("assistant.proposal.title")}
              </p>
              <p className="mt-1">{activeSession.guided.proposal.label}: {activeSession.guided.proposal.value}</p>
              <div className="mt-3 flex gap-2">
                <button type="button" onClick={() => void resolveGuidedProposal(false)} disabled={isSending} className="rounded-md border border-edge px-2.5 py-1.5 text-xs text-muted disabled:opacity-50">{t("assistant.proposal.reject")}</button>
                <button type="button" onClick={() => void resolveGuidedProposal(true)} disabled={isSending} className="rounded-md bg-action px-2.5 py-1.5 text-xs text-action-text disabled:opacity-50">{t("assistant.proposal.accept")}</button>
              </div>
            </div>
          )}

          {(hasGuidedCandidate || Boolean(activeSession?.pendingReview)) && onGuidedReview && !isSending && (
            <button
              type="button"
              onClick={() => void handleGuidedReview()}
              aria-label={t("assistant.review.action")}
              className="flex w-full items-center gap-2 rounded-lg border border-action/50 bg-action/10 px-3 py-2 text-left text-sm font-medium text-primary transition-colors hover:border-action hover:bg-action/20 focus:outline-none focus:ring-2 focus:ring-action/60 active:bg-action/25 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Icon name="edit" size={16} />
              <span>{t("assistant.review.action")}</span>
            </button>
          )}

          {isSending && (
            <div className="flex justify-start">
              <div className="rounded-lg bg-surface px-4 py-2.5">
                <Spinner size="sm" />
              </div>
            </div>
          )}

          {ACTIVITY_EVIDENCE_UI_ENABLED && showActivityEvidence && (
            <ActivityEvidence activity={activity} evidence={evidence} isSending={isSending} />
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {(error || whisperError) && (
        <div className="mx-4 mb-2 rounded-md border border-status-error/30 bg-status-error/10 px-3 py-1.5 text-xs text-status-error">
          {error || whisperError}
        </div>
      )}

      {activity.blocked && !isSending && (
        <div
          role="alert"
          aria-label={t("assistant.blocked.aria")}
          className="mx-4 mb-2 rounded-md border border-action/30 bg-action/10 px-3 py-1.5 text-xs leading-relaxed text-primary"
        >
          {semanticBlockedText(isSpanish ? "es" : "en")}
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-edge px-4 py-3 shrink-0">
        {attaching && (
          <div
            role="status"
            aria-live="polite"
            className="mb-2 flex max-w-full items-center gap-2 rounded-md border border-edge bg-surface px-2 py-1 text-xs text-primary"
          >
            <span aria-hidden="true">
              <Spinner size="sm" />
            </span>
            <span className="max-w-[12rem] truncate">{attaching.name}</span>
            <span className="text-muted">
              {attaching.kind === "image"
                ? t("assistant.attach.analyzingImage")
                : t("assistant.attach.extracting")}
            </span>
          </div>
        )}
        {attachments.length > 0 && (
          <ul
            aria-label={t("assistant.attach.list.aria")}
            className="mb-2 flex flex-wrap gap-1.5"
          >
            {attachments.map((attachment) => (
              <li
                key={attachment.id}
                className="flex max-w-full items-center gap-2 rounded-md border border-edge bg-surface px-2 py-1 text-xs text-primary"
              >
                {attachment.kind === "image" ? (
                  <span className="relative flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded border border-edge bg-surface">
                    <Icon name="image" size={14} className="text-muted" />
                    <img
                      src={chatAttachmentThumbnailUrl(attachmentMundo, attachment.id)}
                      alt=""
                      className="absolute inset-0 h-full w-full object-cover"
                      onError={(event) => {
                        event.currentTarget.style.display = "none";
                      }}
                    />
                  </span>
                ) : (
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded border border-edge bg-surface text-[9px] font-semibold uppercase tracking-wide text-muted">
                    {attachment.kind}
                  </span>
                )}
                <span
                  className="max-w-[12rem] truncate"
                  title={
                    attachment.truncated
                      ? t("assistant.attach.truncated", { chars: attachment.chars })
                      : attachment.name
                  }
                >
                  {attachment.name}
                </span>
                <span className="text-muted">{attachment.chars}</span>
                <button
                  type="button"
                  onClick={() => removeAttachment(attachment.id)}
                  disabled={isSending}
                  aria-label={t("assistant.attach.remove.aria", { name: attachment.name })}
                  className="flex h-5 w-5 items-center justify-center rounded text-muted hover:text-primary disabled:opacity-50"
                >
                  <Icon name="close" size={12} />
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("assistant.composer.placeholder")}
            rows={2}
            className="min-w-0 flex-1 resize-none rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50"
            disabled={confirmationPending || isSending}
          />
          <div className="flex shrink-0 items-center gap-1">
            <input
              ref={fileInputRef}
              type="file"
              accept=".docx,.pdf,.png,.jpg,.jpeg,.webp,.gif"
              onChange={handleFileChange}
              className="hidden"
              tabIndex={-1}
              aria-hidden="true"
              data-testid="assistant-attachment-input"
            />
            <button
              type="button"
              onClick={handleAttachClick}
              disabled={confirmationPending || isSending || Boolean(attaching)}
              title={t("assistant.attach.hint")}
              className="flex h-9 w-9 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-hover hover:text-primary disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
              aria-label={t("assistant.attach.aria")}
            >
              <Icon name="upload" size={16} />
            </button>
            <button
              type="button"
              onClick={handleMicClick}
              disabled={confirmationPending || whisperIsTranscribing}
              className={cn(
                "flex h-9 w-9 items-center justify-center rounded-lg transition-colors shrink-0",
                whisperStatus === "recording"
                  ? "bg-status-error text-primary animate-pulse"
                  : whisperStatus === "transcribing"
                    ? "text-action"
                    : "text-muted hover:text-primary hover:bg-surface-hover",
              )}
              aria-label={
                whisperIsRecording
                  ? t("assistant.mic.stop")
                  : whisperIsTranscribing
                    ? t("assistant.mic.transcribing")
                    : t("assistant.mic.record")
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
              disabled={
                confirmationPending ||
                isSending ||
                Boolean(attaching) ||
                (!input.trim() && attachments.length === 0)
              }
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-action text-action-text hover:bg-action-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
              aria-label={t("assistant.send.aria")}
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
            aria-label={t("assistant.propose.aria")}
            className="flex items-center gap-1.5 rounded-md border border-edge px-2.5 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Icon name="edit" size={13} />
            {t("assistant.propose.label")}
          </button>
          {!canProposeEdit && (
            <span className="text-xs text-muted">{proposeEditDisabledReason}</span>
          )}
        </div>
        <p className="mt-1 text-xs text-muted">
          {t("assistant.composer.hint")}
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
  const { t } = useAppLanguage();
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
      <div className="flex items-center justify-between border-b border-edge px-4 py-3 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex h-7 w-7 items-center justify-center rounded-md text-action shrink-0">
            <Icon name="history" size={16} />
          </div>
          <h2 className="text-body font-medium text-primary truncate">
            {t("assistant.history.title")}
          </h2>
        </div>
        <button
          type="button"
          onClick={handleNewSession}
          className="flex items-center gap-1 rounded-md bg-action px-2.5 py-1.5 text-xs font-medium text-action-text hover:bg-action-hover transition-colors shrink-0"
          aria-label={t("assistant.history.newAria")}
        >
          <Icon name="plus" size={12} />
          {t("assistant.history.new")}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        {sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <p className="text-xs text-muted">
              {t("assistant.history.empty")}
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
                    ? "bg-action/10 text-action"
                    : "text-muted hover:bg-surface-hover hover:text-primary",
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
                    {session.messages.length}{" "}
                    {session.messages.length === 1
                      ? t("assistant.count.messageOne")
                      : t("assistant.count.messageMany")}
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

      <div className="border-t border-edge px-4 py-2 shrink-0">
        <p className="text-xs text-muted text-center">
          {t("assistant.history.footer", {
            sessions: sessions.length,
            sessionWord:
              sessions.length === 1
                ? t("assistant.count.sessionOne")
                : t("assistant.count.sessionMany"),
            messages: totalMessages,
            messageWord:
              totalMessages === 1
                ? t("assistant.count.messageOne")
                : t("assistant.count.messageMany"),
          })}
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
  onGuidedReview,
}: AIAssistantSidebarProps) {
  const [screen, setScreen] = useState<Screen>("chat");
  const sessions = useAIAssistantSessions(mundo, section, filePath);
  const [guidedMethods, setGuidedMethods] = useState<GuidedMethodOption[]>([]);
  const [guidedMethodDefault, setGuidedMethodDefault] = useState<
    { skill_id: string; version: string } | null
  >(null);
  const consentToken = sessions.activeSession?.consentToken;
  const consentFlow = sessions.activeSession?.consentFlow;
  const guidedMethodSkillId =
    sessions.activeSession?.guided?.methodology?.skill_id ?? null;
  const guidedFlowId =
    consentFlow?.flow_id ??
    sessions.activeSession?.guided?.flow?.flow_id ??
    "guided-character";

  /** Eligible methods are fetched when the consent card or a running guided
   *  session needs to render the method, scoped to the session's flow. */
  useEffect(() => {
    if (!consentToken && !guidedMethodSkillId) return;
    let cancelled = false;
    getGuidedMethods(mundo, guidedFlowId)
      .then((response) => {
        if (cancelled) return;
        setGuidedMethods(response.methods);
        setGuidedMethodDefault(response.default);
      })
      .catch(() => {
        /* The factory option stays; the server validates the choice. */
      });
    return () => {
      cancelled = true;
    };
  }, [consentToken, guidedMethodSkillId, guidedFlowId, mundo]);

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
          activity={sessions.activity}
          evidence={sessions.evidence}
          sendMessage={sessions.sendMessage}
          attachDocument={sessions.attachDocument}
          removeAttachment={sessions.removeAttachment}
          attaching={sessions.attaching}
          whisperStatus={whisper.status}
          whisperIsRecording={whisper.isRecording}
          whisperIsTranscribing={whisper.isTranscribing}
          whisperStartRecording={whisper.startRecording}
          whisperStopRecording={whisper.stopRecording}
          whisperError={whisper.error}
          onHistoryClick={switchToHistory}
          onNewChat={sessions.createSession}
          onProposeEdit={onProposeEdit}
          onGuidedReview={onGuidedReview}
          resolveGuidedProposal={sessions.resolveGuidedProposal}
          resolveGuidedConsent={sessions.resolveGuidedConsent}
          guidedMethods={guidedMethods}
          guidedMethodDefault={guidedMethodDefault}
          consentFlow={consentFlow}
          requestGuidedReview={sessions.requestGuidedReview}
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
