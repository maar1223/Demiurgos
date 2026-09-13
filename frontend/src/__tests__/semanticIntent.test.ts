import { describe, expect, it } from "vitest";
import {
  SEMANTIC_BLOCKED_BY_LANGUAGE,
  SEMANTIC_BLOCKED_TEXT,
  mapSemanticDecision,
  semanticBlockedText,
} from "@/lib/semanticIntent";
import type { GuidedCharacterSession } from "@/api/types";

const FORBIDDEN_TERMS = [
  "hermes",
  "provider",
  "gateway",
  "http",
  "timeout",
  "quota",
  "credits",
  "credential",
  "model",
  "internal",
  "error",
];

const guidedConfirmation: GuidedCharacterSession = {
  protocol_version: "guided-character-v1",
  session_id: "guided-42",
  world: "Vibrantes",
  phase: "confirmation",
  mode: "full",
  depth: "standard",
  revision: 1,
  pending_question: "¿Creo este personaje?",
  messages: [],
  candidate: { accepted_canon: {}, proposals: {}, unresolved_references: [], conflicts: [] },
  proposal: null,
};

function envelope(state: string, overrides: Record<string, unknown> = {}) {
  return {
    state,
    response: "Hermes semantic answer.",
    request_id: "request-1",
    attempts: 1,
    fallback: false,
    guided: true,
    ...overrides,
  };
}

describe("semantic intent client mapping", () => {
  it("maps allow to a normal answer", () => {
    expect(mapSemanticDecision(envelope("allow", { action: "answer" }))).toEqual({
      kind: "answer",
      text: "Hermes semantic answer.",
    });
  });

  it("maps clarify to a question", () => {
    expect(mapSemanticDecision(envelope("clarify", { action: "ask_question" }))).toEqual({
      kind: "question",
      text: "Hermes semantic answer.",
    });
  });

  it("maps require_confirmation to an explicit confirmation with continuation data", () => {
    const result = mapSemanticDecision(envelope("require_confirmation", {
      action: "request_confirmation",
      guided_session_id: "guided-42",
      guided_revision: 1,
      guided_state: guidedConfirmation,
    }));
    expect(result.kind).toBe("confirmation");
    if (result.kind !== "confirmation") return;
    expect(result.text).toBe("Hermes semantic answer.");
    expect(result.guided).toEqual(guidedConfirmation);
    expect(result.guided.pending_question).toBe("¿Creo este personaje?");
  });

  it("maps proposal_ready to a review with server-owned proposal data", () => {
    const result = mapSemanticDecision(envelope("proposal_ready", {
      action: "show_proposal",
      proposal_id: "guided-proposal-1",
      target: "personajes/rhyz-s-wife.md",
      base_revision: "1",
      proposed_content: "# Rhyz's Wife\n",
      proposed_digest: "abc123",
      rationale: "Review the guided character before creating the file.",
      is_new_file: true,
      guided_session_id: "guided-42",
      guided_revision: 1,
      guided_state: guidedConfirmation,
    }));
    expect(result.kind).toBe("review");
    if (result.kind !== "review") return;
    expect(result.proposal.proposal_id).toBe("guided-proposal-1");
    expect(result.proposal.target).toBe("personajes/rhyz-s-wife.md");
    expect(result.proposal.base_revision).toBe("1");
    expect(result.proposal.proposed_content).toBe("# Rhyz's Wife\n");
    expect(result.proposal.proposed_digest).toBe("abc123");
    expect(result.proposal.rationale).toBe("Review the guided character before creating the file.");
    expect(result.proposal.is_new_file).toBe(true);
    expect(result.proposal.guided_session_id).toBe("guided-42");
    expect(result.proposal.guided_revision).toBe(1);
    expect(result.guided).toEqual(guidedConfirmation);
  });

  it("maps blocked to a safe explanation", () => {
    expect(mapSemanticDecision(envelope("blocked", {
      action: "blocked_explanation",
      response: "No canon, proposal, or write was made.",
    }))).toEqual({
      kind: "blocked",
      text: "No canon, proposal, or write was made.",
    });
  });

  it("fails an unknown state closed to blocked without inferring permission", () => {
    const result = mapSemanticDecision(envelope("approve", {
      action: "answer",
      proposal_id: "guided-proposal-1",
      proposed_content: "# X\n",
      proposed_digest: "abc",
      target: "lore/x.md",
      base_revision: "1",
      rationale: "r",
      is_new_file: false,
      guided_state: guidedConfirmation,
    }));
    expect(result).toEqual({ kind: "blocked", text: SEMANTIC_BLOCKED_TEXT });
  });

  it("fails require_confirmation without continuation data closed to blocked", () => {
    expect(mapSemanticDecision(envelope("require_confirmation", { guided: true }))).toEqual({
      kind: "blocked",
      text: SEMANTIC_BLOCKED_TEXT,
    });
  });

  it("fails proposal_ready without server-owned proposal fields closed to blocked", () => {
    expect(mapSemanticDecision(envelope("proposal_ready", { guided: true }))).toEqual({
      kind: "blocked",
      text: SEMANTIC_BLOCKED_TEXT,
    });
  });

  it("fails malformed and non-envelope values closed to blocked", () => {
    expect(mapSemanticDecision(null)).toEqual({ kind: "blocked", text: SEMANTIC_BLOCKED_TEXT });
    expect(mapSemanticDecision("string")).toEqual({ kind: "blocked", text: SEMANTIC_BLOCKED_TEXT });
    expect(mapSemanticDecision({ response: "legacy answer" })).toEqual({
      kind: "answer",
      text: "legacy answer",
    });
    expect(mapSemanticDecision({ response: "handoff", guided_state: guidedConfirmation })).toEqual({
      kind: "answer",
      text: "handoff",
      guided: guidedConfirmation,
    });
  });
});

describe("semantic intent consent suggestion mapping", () => {
  it("maps a musing consent suggestion with no guided session", () => {
    const result = mapSemanticDecision(envelope("require_confirmation", {
      action: "request_confirmation",
      response: "Parece que querés crear un personaje. ¿Abrimos el flujo guiado?",
      consent: "required",
      consent_token: "ct-1",
    }));
    expect(result).toEqual({
      kind: "suggestion",
      text: "Parece que querés crear un personaje. ¿Abrimos el flujo guiado?",
      consentToken: "ct-1",
    });
  });

  it("maps a proposal_ready consent suggestion when no proposal is present", () => {
    const result = mapSemanticDecision(envelope("proposal_ready", {
      action: "show_proposal",
      consent: "required",
      consent_token: "ct-2",
    }));
    expect(result).toEqual({
      kind: "suggestion",
      text: "Hermes semantic answer.",
      consentToken: "ct-2",
    });
  });

  it("prefers the guided session over a consent marker", () => {
    const result = mapSemanticDecision(envelope("require_confirmation", {
      action: "request_confirmation",
      consent: "required",
      consent_token: "ct-1",
      guided_state: guidedConfirmation,
    }));
    expect(result.kind).toBe("confirmation");
    if (result.kind !== "confirmation") return;
    expect(result.guided).toEqual(guidedConfirmation);
  });

  it("fails a consent marker without a token closed to blocked", () => {
    expect(mapSemanticDecision(envelope("require_confirmation", {
      action: "request_confirmation",
      consent: "required",
    }))).toEqual({ kind: "blocked", text: SEMANTIC_BLOCKED_TEXT });
  });

  it("fails an empty consent token closed to blocked", () => {
    expect(mapSemanticDecision(envelope("require_confirmation", {
      action: "request_confirmation",
      consent: "required",
      consent_token: "",
    }))).toEqual({ kind: "blocked", text: SEMANTIC_BLOCKED_TEXT });
  });

  it("fails a token without consent:required closed to blocked", () => {
    expect(mapSemanticDecision(envelope("require_confirmation", {
      action: "request_confirmation",
      consent_token: "ct-1",
    }))).toEqual({ kind: "blocked", text: SEMANTIC_BLOCKED_TEXT });
  });

  it("never infers a suggestion from an unknown state", () => {
    expect(mapSemanticDecision(envelope("approve", {
      action: "request_confirmation",
      consent: "required",
      consent_token: "ct-1",
    }))).toEqual({ kind: "blocked", text: SEMANTIC_BLOCKED_TEXT });
  });
});

describe("semantic intent localized unavailable copy", () => {
  it("localizes the blocked copy with a Spanish default", () => {
    expect(SEMANTIC_BLOCKED_BY_LANGUAGE.es).toBe(
      "El Asistente IA no pudo completar la solicitud en este momento. No se realizó ninguna acción ni escritura.",
    );
    expect(SEMANTIC_BLOCKED_BY_LANGUAGE.en).toBe(
      "The AI Assistant could not complete the request right now. No action or write was made.",
    );
    expect(semanticBlockedText()).toBe(SEMANTIC_BLOCKED_BY_LANGUAGE.es);
    expect(semanticBlockedText("es")).toBe(SEMANTIC_BLOCKED_BY_LANGUAGE.es);
    expect(semanticBlockedText("en")).toBe(SEMANTIC_BLOCKED_BY_LANGUAGE.en);
  });

  it("keeps the localized copy free of provider/internal terms", () => {
    for (const language of ["es", "en"] as const) {
      const text = semanticBlockedText(language).toLowerCase();
      for (const term of FORBIDDEN_TERMS) {
        expect(text).not.toContain(term);
      }
    }
  });

  it("localizes the unknown-state blocked outcome via the configured language", () => {
    const unknown = { state: "approve", action: "answer", response: "x" };
    expect(mapSemanticDecision(unknown, "es")).toEqual({
      kind: "blocked",
      text: SEMANTIC_BLOCKED_BY_LANGUAGE.es,
    });
    expect(mapSemanticDecision(unknown, "en")).toEqual({
      kind: "blocked",
      text: SEMANTIC_BLOCKED_BY_LANGUAGE.en,
    });
  });

  it("fails an unavailable envelope closed without inferring permission or action", () => {
    const unavailable = {
      state: "allow",
      action: "answer",
      response: "",
      unavailable: true,
    };
    expect(mapSemanticDecision(unavailable, "es")).toEqual({
      kind: "blocked",
      text: SEMANTIC_BLOCKED_BY_LANGUAGE.es,
    });
  });

  it("keeps the server-safe blocked copy when present on an unavailable envelope", () => {
    expect(mapSemanticDecision({
      state: "blocked",
      action: "blocked_explanation",
      response: "El Asistente IA no pudo completar la solicitud en este momento. No se realizó ninguna acción ni escritura.",
      unavailable: true,
    }, "es")).toEqual({
      kind: "blocked",
      text: "El Asistente IA no pudo completar la solicitud en este momento. No se realizó ninguna acción ni escritura.",
    });
  });
});
