import type {
  AppLanguage,
  EditProposal,
  GuidedCharacterSession,
  GuidedFlowEcho,
} from "@/api/types";
import { translate } from "@/i18n/messages";

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

/** Localized fail-closed copy, sourced from the catalogue (UI-REQ-2). */
export const SEMANTIC_BLOCKED_BY_LANGUAGE: Record<AppLanguage, string> = {
  es: translate("es", "assistant.blocked"),
  en: translate("en", "assistant.blocked"),
};

/** Localized fail-closed copy; Spanish by default. Never provider/internal terms. */
export function semanticBlockedText(language: AppLanguage = "es"): string {
  return translate(language, "assistant.blocked");
}

/** Spanish-default blocked copy (backward-compatible constant). */
export const SEMANTIC_BLOCKED_TEXT: string = SEMANTIC_BLOCKED_BY_LANGUAGE.es;

export type SemanticClientOutcome =
  | { kind: "answer"; text: string; guided?: GuidedCharacterSession }
  | { kind: "question"; text: string }
  | { kind: "confirmation"; text: string; guided: GuidedCharacterSession }
  | { kind: "review"; text: string; proposal: EditProposal; guided?: GuidedCharacterSession }
  | { kind: "suggestion"; text: string; consentToken: string; flow?: GuidedFlowEcho }
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

/**
 * Structural guard for a bare guided session. Shared by the semantic mapper
 * (which admits `guided_state` from the `/ai/ask` envelope) and the
 * consent-envelope unwrap at the assistant boundary.
 */
export function isGuidedSession(value: unknown): value is GuidedCharacterSession {
  if (!isRecord(value)) return false;
  return (
    typeof value.session_id === "string" &&
    typeof value.revision === "number" &&
    typeof value.phase === "string"
  );
}

/** A candidate the sidebar can safely enumerate (proposals + accepted canon). */
function isGuidedCandidate(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return isRecord(value.proposals) && isRecord(value.accepted_canon);
}

/**
 * Strict usability guard for a guided session the UI is about to keep or
 * persist. The sidebar dereferences `candidate.proposals` /
 * `candidate.accepted_canon`, so a handle without a well-formed candidate can
 * never be rendered or stored safely.
 *
 * Deliberately stricter than `isGuidedSession`: the live `/ai/ask` mapping
 * keeps its exact semantics, while the persisted-session loader and the
 * consent unwrap drop a shape that would crash on mount.
 */
export function isUsableGuidedSession(value: unknown): value is GuidedCharacterSession {
  return isGuidedSession(value) && isGuidedCandidate(value.candidate);
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

/**
 * A consent suggestion is admitted ONLY when the server explicitly marks
 * `consent: "required"` with a non-empty `consent_token` AND the envelope
 * carries no guided session. The absence of `guided_state` is what
 * discriminates a musing suggestion from an imperative auto-open; any other
 * shape stays fail-closed, so a malformed or legacy envelope can never be
 * read as permission to open the guided surface.
 */
function toFlowEcho(value: unknown): GuidedFlowEcho | undefined {
  if (!isRecord(value)) return undefined;
  const { flow_id, entity_type, target_section, ui_copy_key } = value;
  if (
    typeof flow_id !== "string" || !flow_id ||
    typeof entity_type !== "string" || !entity_type ||
    typeof target_section !== "string" || !target_section ||
    (ui_copy_key !== "character" && ui_copy_key !== "system")
  ) {
    return undefined;
  }
  return { flow_id, entity_type, target_section, ui_copy_key };
}

function toConsentSuggestion(
  value: Record<string, unknown>,
): SemanticClientOutcome | null {
  if (value.consent !== "required") return null;
  if (isGuidedSession(value.guided_state)) return null;
  if (typeof value.consent_token !== "string" || !value.consent_token) return null;
  const text = typeof value.response === "string" ? value.response : "";
  return {
    kind: "suggestion",
    text,
    consentToken: value.consent_token,
    flow: toFlowEcho(value.flow),
  };
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
        if (guided) return { kind: "confirmation", text: response, guided };
        // No guided session: the server may have issued a musing consent
        // suggestion instead of an imperative auto-open.
        const suggestion = toConsentSuggestion(value);
        if (suggestion) return suggestion;
        return { kind: "blocked", text: semanticBlockedText(language) };
      }
      case "proposal_ready": {
        const proposal = toEditProposal(value);
        if (proposal) {
          const guided = isGuidedSession(value.guided_state) ? value.guided_state : undefined;
          return { kind: "review", text: response, proposal, ...(guided ? { guided } : {}) };
        }
        // No server-owned proposal: a consent suggestion is the only other
        // admitted shape; anything else fails closed.
        const suggestion = toConsentSuggestion(value);
        if (suggestion) return suggestion;
        return { kind: "blocked", text: semanticBlockedText(language) };
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
