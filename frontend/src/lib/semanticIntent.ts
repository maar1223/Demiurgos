import type { AppLanguage, EditProposal, GuidedCharacterSession } from "@/api/types";

/**
 * Client-side semantic intent mapping.
 *
 * The server emits a validated decision envelope (state/response/action plus
 * continuation data) or a legacy chat answer. This module maps ONLY what the
 * server actually emits into deterministic client outcomes, failing closed to
 * a blocked-safe explanation for unknown or malformed states. It NEVER infers
 * permission: unsupported states can never become an answer, a confirmation,
 * a review, or a guided handoff. The blocked copy follows the configured UI
 * language (Spanish default) and never exposes provider/internal terms.
 */

export const SEMANTIC_BLOCKED_BY_LANGUAGE: Record<AppLanguage, string> = {
  es: "El Asistente IA no pudo completar la solicitud en este momento. No se realizó ninguna acción ni escritura.",
  en: "The AI Assistant could not complete the request right now. No action or write was made.",
};

/** Localized fail-closed copy; Spanish by default. Never provider/internal terms. */
export function semanticBlockedText(language: AppLanguage = "es"): string {
  return SEMANTIC_BLOCKED_BY_LANGUAGE[language];
}

/** Spanish-default blocked copy (backward-compatible constant). */
export const SEMANTIC_BLOCKED_TEXT: string = SEMANTIC_BLOCKED_BY_LANGUAGE.es;

export type SemanticClientOutcome =
  | { kind: "answer"; text: string; guided?: GuidedCharacterSession }
  | { kind: "question"; text: string }
  | { kind: "confirmation"; text: string; guided: GuidedCharacterSession }
  | { kind: "review"; text: string; proposal: EditProposal; guided?: GuidedCharacterSession }
  | { kind: "blocked"; text: string };

const KNOWN_STATES = new Set([
  "allow",
  "clarify",
  "require_confirmation",
  "proposal_ready",
  "blocked",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isGuidedSession(value: unknown): value is GuidedCharacterSession {
  if (!isRecord(value)) return false;
  return (
    typeof value.session_id === "string" &&
    typeof value.revision === "number" &&
    typeof value.phase === "string"
  );
}

function toEditProposal(value: Record<string, unknown>): EditProposal | null {
  if (
    typeof value.proposal_id !== "string" ||
    !value.proposal_id ||
    typeof value.target !== "string" ||
    !value.target ||
    typeof value.base_revision !== "string" ||
    typeof value.proposed_content !== "string" ||
    !value.proposed_content ||
    typeof value.proposed_digest !== "string" ||
    !value.proposed_digest ||
    typeof value.rationale !== "string" ||
    typeof value.is_new_file !== "boolean"
  ) {
    return null;
  }
  const proposal: EditProposal = {
    proposal_id: value.proposal_id,
    target: value.target,
    base_revision: value.base_revision,
    proposed_content: value.proposed_content,
    proposed_digest: value.proposed_digest,
    rationale: value.rationale,
    is_new_file: value.is_new_file,
  };
  if (typeof value.guided_session_id === "string") {
    proposal.guided_session_id = value.guided_session_id;
  }
  if (typeof value.guided_revision === "number") {
    proposal.guided_revision = value.guided_revision;
  }
  return proposal;
}

export function mapSemanticDecision(
  value: unknown,
  language: AppLanguage = "es",
): SemanticClientOutcome {
  if (!isRecord(value)) return { kind: "blocked", text: semanticBlockedText(language) };

  if (typeof value.state === "string") {
    if (!KNOWN_STATES.has(value.state)) {
      // Unsupported client state: blocked-safe outcome, never infer permission.
      return { kind: "blocked", text: semanticBlockedText(language) };
    }
    const response = typeof value.response === "string" ? value.response : "";
    // A fail-closed server envelope is authoritative: block regardless of the
    // reported state, using the server-safe copy when present.
    if (value.unavailable === true) {
      return { kind: "blocked", text: response || semanticBlockedText(language) };
    }
    switch (value.state) {
      case "allow":
        return { kind: "answer", text: response };
      case "clarify":
        return { kind: "question", text: response };
      case "blocked":
        return { kind: "blocked", text: response || semanticBlockedText(language) };
      case "require_confirmation": {
        const guided = isGuidedSession(value.guided_state) ? value.guided_state : null;
        if (!guided) return { kind: "blocked", text: semanticBlockedText(language) };
        return { kind: "confirmation", text: response, guided };
      }
      case "proposal_ready": {
        const proposal = toEditProposal(value);
        if (!proposal) return { kind: "blocked", text: semanticBlockedText(language) };
        const guided = isGuidedSession(value.guided_state) ? value.guided_state : undefined;
        return { kind: "review", text: response, proposal, ...(guided ? { guided } : {}) };
      }
    }
  }

  // No state field: legacy chat answer / guided handoff envelope.
  if (typeof value.response === "string") {
    const guided = isGuidedSession(value.guided_state) ? value.guided_state : undefined;
    return { kind: "answer", text: value.response, ...(guided ? { guided } : {}) };
  }
  return { kind: "blocked", text: semanticBlockedText(language) };
}
