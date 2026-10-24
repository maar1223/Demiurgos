import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import {
  useAIAssistantSessions,
  GLOBAL_ASSISTANT_CONTEXT,
  type Session,
} from "@/hooks/useAIAssistantSessions";
import { AssistantActivityUnavailable, streamAssistantActivity } from "@/api/assistantActivity";
import { acceptGuidedConsent, declineGuidedConsent } from "@/api/guidedCharacter";
import { askAssistant } from "@/api/wiki";
import { uploadChatAttachment } from "@/api/chatAttachments";
import { CATALOGUE } from "@/i18n/messages";
import { ApiError } from "@/api/types";
import type { AppLanguage, GuidedCharacterSession, SemanticDecisionEnvelope } from "@/api/types";

const mockUseAppLanguage = vi.fn();
vi.mock("@/hooks/useAppLanguage", () => ({
  useAppLanguage: () => mockUseAppLanguage(),
}));

/** Real catalogue-backed `t` so default titles are the actual localized copy. */
function mockLanguage(language: AppLanguage): void {
  const es = CATALOGUE.es as Record<string, string>;
  const en = CATALOGUE.en as Record<string, string>;
  mockUseAppLanguage.mockReturnValue({
    language,
    t: (key: string) => (language === "en" ? en : es)[key] ?? key,
  });
}

vi.mock("@/api/assistantActivity", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/assistantActivity")>();
  return { ...actual, streamAssistantActivity: vi.fn() };
});

vi.mock("@/api/wiki", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/wiki")>();
  return { ...actual, askAssistant: vi.fn() };
});

vi.mock("@/api/guidedCharacter", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/guidedCharacter")>();
  return { ...actual, acceptGuidedConsent: vi.fn(), declineGuidedConsent: vi.fn() };
});

vi.mock("@/api/chatAttachments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/chatAttachments")>();
  return { ...actual, uploadChatAttachment: vi.fn() };
});

const SESSIONS_KEY = "demiurgos-ai-sessions";
const ACTIVE_KEY = "demiurgos-ai-sessions-active";

beforeEach(() => {
  mockLanguage("es");
});

function makeSession(id: string, title = "Session title"): Session {
  return { id, title, messages: [], createdAt: Date.now() };
}

function seedSessions(sessions: Session[]): void {
  window.localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

describe("useAIAssistantSessions active session persistence", () => {
  it("persists the active session id and restores it on a fresh mount", () => {
    seedSessions([makeSession("s1"), makeSession("s2")]);

    const first = renderHook(() => useAIAssistantSessions("mundo"));
    expect(first.result.current.activeSessionId).toBeNull();

    act(() => {
      first.result.current.switchSession("s2");
    });
    expect(first.result.current.activeSessionId).toBe("s2");

    const stored = window.localStorage.getItem(ACTIVE_KEY);
    expect(stored).toBe(JSON.stringify("s2"));

    first.unmount();

    // Fresh mount — simulates the sidebar remounting after a tab switch
    const second = renderHook(() => useAIAssistantSessions("mundo"));
    expect(second.result.current.activeSessionId).toBe("s2");
    expect(second.result.current.activeSession?.id).toBe("s2");
  });

  it("falls back to null when the persisted id no longer exists", () => {
    seedSessions([makeSession("s1")]);
    window.localStorage.setItem(ACTIVE_KEY, JSON.stringify("ghost-id"));

    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    expect(result.current.activeSessionId).toBeNull();
    expect(result.current.activeSession).toBeNull();
  });

  it("does not auto-select a session when nothing was active", () => {
    seedSessions([makeSession("s1"), makeSession("s2")]);

    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    expect(result.current.activeSessionId).toBeNull();
    expect(result.current.activeSession).toBeNull();
  });

  it("clears the persisted id when the active session is deleted", () => {
    seedSessions([makeSession("s1"), makeSession("s2")]);

    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    act(() => {
      result.current.switchSession("s2");
    });
    expect(result.current.activeSessionId).toBe("s2");

    act(() => {
      result.current.deleteSession("s2");
    });
    expect(result.current.activeSessionId).toBeNull();
    expect(window.localStorage.getItem(ACTIVE_KEY)).toBeNull();
  });

  it("persists a newly created session as active", () => {
    seedSessions([makeSession("s1")]);

    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    act(() => {
      result.current.createSession();
    });

    const createdId = result.current.activeSessionId;
    expect(createdId).not.toBeNull();
    expect(window.localStorage.getItem(ACTIVE_KEY)).toBe(JSON.stringify(createdId));

    // A fresh mount restores the newly created session
    const second = renderHook(() => useAIAssistantSessions("mundo"));
    expect(second.result.current.activeSessionId).toBe(createdId);
  });
});

describe("useAIAssistantSessions empty-draft reuse", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("does not stack an empty draft when the active session is already empty", () => {
    seedSessions([makeSession("s1"), makeSession("s2")]);
    window.localStorage.setItem(ACTIVE_KEY, JSON.stringify("s1"));

    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    expect(result.current.sessions).toHaveLength(2);

    act(() => {
      result.current.createSession();
    });

    // The active empty draft is reused and the other empty draft is pruned.
    expect(result.current.sessions).toHaveLength(1);
    expect(result.current.sessions[0].id).toBe("s1");
    expect(result.current.activeSessionId).toBe("s1");
  });

  it("reuses an existing empty draft instead of creating another empty one", () => {
    const withMessages: Session = {
      id: "real",
      title: "Real chat",
      messages: [{ role: "user", content: "Hola" }],
      createdAt: Date.now(),
    };
    seedSessions([withMessages, makeSession("empty")]);

    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    expect(result.current.sessions).toHaveLength(2);

    act(() => {
      result.current.createSession();
    });

    // No new session was added: the existing empty draft is focused and the
    // conversation with messages is preserved.
    expect(result.current.sessions).toHaveLength(2);
    expect(result.current.activeSessionId).toBe("empty");
    expect(result.current.sessions.map((s) => s.id).sort()).toEqual(["empty", "real"]);
  });
});

describe("useAIAssistantSessions null-mundo (global context)", () => {
  const streamMock = vi.mocked(streamAssistantActivity);
  const askMock = vi.mocked(askAssistant);

  const allowedDecision = {
    accepted: true,
    events: [],
    answer: "Hola",
    terminalStatus: "succeeded" as const,
    semanticDecision: {
      kind: "semantic_decision" as const,
      request_id: "r1",
      state: "allow" as const,
      action: "answer" as const,
      unavailable: false,
      continuation: null,
    },
  };

  beforeEach(() => {
    streamMock.mockReset();
    askMock.mockReset();
    window.localStorage.clear();
  });

  it("exposes the stable ideas-global context key", () => {
    expect(GLOBAL_ASSISTANT_CONTEXT).toBe("ideas-global");
  });

  it("uses the stable ideas-global key when mundo is null/undefined", async () => {
    streamMock.mockResolvedValue(allowedDecision);

    const { result } = renderHook(() =>
      useAIAssistantSessions(undefined, undefined, undefined),
    );

    await act(async () => {
      await result.current.sendMessage("Dame una idea de personaje");
    });

    expect(streamMock).toHaveBeenCalledWith(
      "ideas-global",
      expect.objectContaining({ prompt: "Dame una idea de personaje" }),
      expect.any(Object),
    );
    // World-scoped context fields are omitted in the global context.
    const body = streamMock.mock.calls[0][1] as unknown as Record<string, unknown>;
    expect(body.section).toBeUndefined();
    expect(body.file_path).toBeUndefined();
    // The assistant answer is appended to the session.
    expect(result.current.activeSession?.messages).toContainEqual(
      expect.objectContaining({ role: "assistant", content: "Hola" }),
    );
  });

  it("keeps mundo-scoped sessions using the world key and world context", async () => {
    streamMock.mockResolvedValue(allowedDecision);

    const { result } = renderHook(() =>
      useAIAssistantSessions("vibrantes", "lore", "cap1.md"),
    );

    await act(async () => {
      await result.current.sendMessage("¿Quién es Rhyz?");
    });

    expect(streamMock).toHaveBeenCalledWith(
      "vibrantes",
      expect.objectContaining({
        prompt: "¿Quién es Rhyz?",
        section: "lore",
        file_path: "cap1.md",
      }),
      expect.any(Object),
    );
  });

  it("tolerates null-mundo for the session persistence flows", () => {
    seedSessions([makeSession("s1")]);

    const { result } = renderHook(() => useAIAssistantSessions(null as unknown as string));

    expect(result.current.activeSessionId).toBeNull();
    act(() => {
      result.current.switchSession("s1");
    });
    expect(result.current.activeSessionId).toBe("s1");

    act(() => {
      result.current.deleteSession("s1");
    });
    expect(result.current.activeSessionId).toBeNull();
  });
});

describe("useAIAssistantSessions guided consent wiring", () => {
  const streamMock = vi.mocked(streamAssistantActivity);
  const askMock = vi.mocked(askAssistant);
  const acceptMock = vi.mocked(acceptGuidedConsent);
  const declineMock = vi.mocked(declineGuidedConsent);

  const suggestionEnvelope: SemanticDecisionEnvelope = {
    state: "require_confirmation",
    action: "request_confirmation",
    response: "Parece que querés crear un personaje. ¿Abrimos el flujo guiado?",
    request_id: "r1",
    attempts: 1,
    guided: true,
    consent: "required",
    consent_token: "ct-1",
  };

  const guidedSession: GuidedCharacterSession = {
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

  /**
   * The real `/consent/accept` response: a semantic decision envelope whose
   * bare session lives in `guided_state`. Mocking the bare session directly
   * (the old shape) masked the unwrap bug.
   */
  const consentAcceptEnvelope: SemanticDecisionEnvelope = {
    state: "require_confirmation",
    action: "request_confirmation",
    response: "¿Creo este personaje?",
    request_id: "r-consent",
    attempts: 1,
    fallback: false,
    guided: true,
    guided_explicitness: "imperative",
    session_id: "guided-42",
    guided_session_id: "guided-42",
    guided_revision: 1,
    guided_state: guidedSession,
  };

  beforeEach(() => {
    streamMock.mockReset();
    askMock.mockReset();
    acceptMock.mockReset();
    declineMock.mockReset();
    window.localStorage.clear();
  });

  it("persists the consent token from a musing suggestion", async () => {
    streamMock.mockRejectedValue(new AssistantActivityUnavailable(503, "guided_handoff"));
    askMock.mockResolvedValue(suggestionEnvelope);

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));

    await act(async () => {
      await result.current.sendMessage("Quiero crear un personaje");
    });

    expect(result.current.activeSession?.consentToken).toBe("ct-1");
    expect(result.current.activeSession?.guided).toBeUndefined();
  });

  it("opens the guided flow on accept and clears the suggestion", async () => {
    streamMock.mockRejectedValue(new AssistantActivityUnavailable(503, "guided_handoff"));
    askMock.mockResolvedValue(suggestionEnvelope);
    acceptMock.mockResolvedValue(consentAcceptEnvelope);

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));

    await act(async () => {
      await result.current.sendMessage("Quiero crear un personaje");
    });
    await act(async () => {
      await result.current.resolveGuidedConsent(true);
    });

    expect(acceptMock).toHaveBeenCalledWith("Vibrantes", "ct-1");
    expect(result.current.activeSession?.guided).toEqual(guidedSession);
    expect(result.current.activeSession?.consentToken).toBeUndefined();
  });

  it("unwraps a real consent envelope into a usable bare guided session", async () => {
    streamMock.mockRejectedValue(new AssistantActivityUnavailable(503, "guided_handoff"));
    askMock.mockResolvedValue(suggestionEnvelope);
    acceptMock.mockResolvedValue(consentAcceptEnvelope);

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));

    await act(async () => {
      await result.current.sendMessage("Quiero crear un personaje");
    });
    await act(async () => {
      await result.current.resolveGuidedConsent(true);
    });

    const guided = result.current.activeSession?.guided;
    // The stored value is the bare session, never the envelope wrapper.
    expect(guided).not.toHaveProperty("guided_state");
    expect(guided?.candidate).toBeDefined();
    expect(guided?.candidate?.proposals).toEqual(expect.any(Object));
    expect(guided?.candidate?.accepted_canon).toEqual(expect.any(Object));
    expect(guided?.phase).toBe("confirmation");
    expect(guided?.revision).toBe(1);
  });

  it("drops a present but malformed guided_state instead of storing it", async () => {
    streamMock.mockRejectedValue(new AssistantActivityUnavailable(503, "guided_handoff"));
    askMock.mockResolvedValue(suggestionEnvelope);
    acceptMock.mockResolvedValue({
      ...consentAcceptEnvelope,
      guided_state: {
        session_id: "guided-42",
        revision: 1,
        phase: "confirmation",
      } as GuidedCharacterSession,
    });

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));

    await act(async () => {
      await result.current.sendMessage("Quiero crear un personaje");
    });
    await act(async () => {
      await result.current.resolveGuidedConsent(true);
    });

    // A handle without a candidate would crash the sidebar, so the boundary
    // drops it; the session itself survives with the consent token cleared.
    expect(result.current.activeSession?.guided).toBeUndefined();
    expect(result.current.activeSession?.consentToken).toBeUndefined();
  });

  it("dismisses the suggestion on decline without opening the flow", async () => {
    streamMock.mockRejectedValue(new AssistantActivityUnavailable(503, "guided_handoff"));
    askMock.mockResolvedValue(suggestionEnvelope);
    declineMock.mockResolvedValue({ consent: "declined" });

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));

    await act(async () => {
      await result.current.sendMessage("Quiero crear un personaje");
    });
    await act(async () => {
      await result.current.resolveGuidedConsent(false);
    });

    expect(declineMock).toHaveBeenCalledWith("Vibrantes", "ct-1");
    expect(result.current.activeSession?.consentToken).toBeUndefined();
    expect(result.current.activeSession?.guided).toBeUndefined();
  });

  it("dismisses a pending suggestion when the user keeps chatting", async () => {
    streamMock.mockRejectedValue(new AssistantActivityUnavailable(503, "guided_handoff"));
    askMock.mockResolvedValue(suggestionEnvelope);

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));

    await act(async () => {
      await result.current.sendMessage("Quiero crear un personaje");
    });
    expect(result.current.activeSession?.consentToken).toBe("ct-1");

    // The next turn is a plain answer: the stale suggestion is dismissed.
    streamMock.mockResolvedValue({
      accepted: true,
      events: [],
      answer: "Seguimos charlando",
      terminalStatus: "succeeded" as const,
      semanticDecision: {
        kind: "semantic_decision" as const,
        request_id: "r2",
        state: "allow" as const,
        action: "answer" as const,
        unavailable: false,
        continuation: null,
      },
    });

    await act(async () => {
      await result.current.sendMessage("Mejor hablemos de otra cosa");
    });

    expect(result.current.activeSession?.consentToken).toBeUndefined();
  });
});

describe("useAIAssistantSessions persisted session sanitization", () => {
  it("drops a malformed guided handle from a stored session without losing the conversation", () => {
    const oldShape = {
      id: "s1",
      title: "Old session",
      messages: [{ role: "user", content: "Hola" }],
      createdAt: 1,
      guided: {
        // The pre-unwrap envelope era: a guided handle with no candidate.
        protocol_version: "guided-character-v1",
        session_id: "guided-1",
        world: "Vibrantes",
        phase: "conversation",
        revision: 3,
        pending_question: null,
        messages: [],
        proposal: null,
      },
    };
    seedSessions([oldShape] as unknown as Session[]);

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));

    expect(result.current.sessions).toHaveLength(1);
    expect(result.current.sessions[0].id).toBe("s1");
    // The conversation survives; only the unsafe guided handle is dropped.
    expect(result.current.sessions[0].messages).toHaveLength(1);
    expect(result.current.sessions[0].guided).toBeUndefined();
  });

  it("keeps a stored session whose guided handle carries a candidate", () => {
    const validGuided = {
      protocol_version: "guided-character-v1",
      session_id: "guided-1",
      world: "Vibrantes",
      phase: "conversation",
      mode: "full",
      depth: "standard",
      revision: 3,
      pending_question: null,
      messages: [],
      candidate: { accepted_canon: {}, proposals: {}, unresolved_references: [], conflicts: [] },
      proposal: null,
    };
    seedSessions([
      {
        id: "s1",
        title: "Valid session",
        messages: [{ role: "user", content: "Hola" }],
        createdAt: 1,
        guided: validGuided,
      } as unknown as Session,
    ]);

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));

    expect(result.current.sessions[0].guided).toEqual(validGuided);
  });

  it("ignores a stored payload that is not an array", () => {
    window.localStorage.setItem(SESSIONS_KEY, JSON.stringify({ nope: true }));

    expect(() => renderHook(() => useAIAssistantSessions("Vibrantes"))).not.toThrow();
  });
});

describe("useAIAssistantSessions default-title defect (AD-12, SES-REQ-1/2)", () => {
  const streamMock = vi.mocked(streamAssistantActivity);
  const allowedDecision = {
    accepted: true,
    events: [],
    answer: "Hola",
    terminalStatus: "succeeded" as const,
    semanticDecision: {
      kind: "semantic_decision" as const,
      request_id: "r1",
      state: "allow" as const,
      action: "answer" as const,
      unavailable: false,
      continuation: null,
    },
  };

  /** Legacy double-encoded mojibake title, built via escapes so the source
   *  mojibake guard never flags the test itself. */
  const MOJIBAKE_TITLE = "Nueva sesi\u251c\u2502n";

  beforeEach(() => {
    streamMock.mockReset();
    streamMock.mockResolvedValue(allowedDecision);
    window.localStorage.clear();
  });

  it("creates a session with the correct neutral-Spanish default title (SES-SCN-1.1)", () => {
    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    act(() => {
      result.current.createSession();
    });

    const created = result.current.sessions[0];
    expect(created.title).toBe("Nueva sesión");
    expect(created.title).not.toContain("\u251c");
    expect(created.titleIsDefault).toBe(true);
  });

  it("creates a session with the English default title from the catalogue (SES-SCN-1.2)", () => {
    mockLanguage("en");
    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    act(() => {
      result.current.createSession();
    });

    expect(result.current.sessions[0].title).toBe("New session");
    expect(result.current.sessions[0].titleIsDefault).toBe(true);
  });

  it("replaces the default title on the first message in Spanish (SES-SCN-2.1)", async () => {
    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    act(() => {
      result.current.createSession();
    });
    expect(result.current.sessions[0].title).toBe("Nueva sesión");

    await act(async () => {
      await result.current.sendMessage("cómo crear un personaje");
    });

    expect(result.current.sessions[0].title).toBe("cómo crear un personaje");
    expect(result.current.sessions[0].titleIsDefault).toBe(false);
    expect(result.current.sessions[0].title).not.toContain("Nueva sesión");
  });

  it("replaces the default title on the first message in English (SES-SCN-2.2)", async () => {
    mockLanguage("en");
    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    act(() => {
      result.current.createSession();
    });
    expect(result.current.sessions[0].title).toBe("New session");

    await act(async () => {
      await result.current.sendMessage("how to create a character");
    });

    expect(result.current.sessions[0].title).toBe("how to create a character");
    expect(result.current.sessions[0].titleIsDefault).toBe(false);
  });

  it("migrates a legacy mojibake draft and replaces it on first message (SES-SCN-2.3)", async () => {
    seedSessions([
      { id: "legacy", title: MOJIBAKE_TITLE, messages: [], createdAt: Date.now() },
    ]);
    window.localStorage.setItem(ACTIVE_KEY, JSON.stringify("legacy"));

    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    // The visible mojibake is migrated to the localized default + flagged.
    expect(result.current.sessions[0].title).toBe("Nueva sesión");
    expect(result.current.sessions[0].titleIsDefault).toBe(true);

    await act(async () => {
      await result.current.sendMessage("primer mensaje");
    });

    expect(result.current.sessions[0].title).toBe("primer mensaje");
    expect(result.current.sessions[0].title).not.toContain("\u251c");
  });

  it("preserves accented characters in derived titles (SES-SCN-2.4)", async () => {
    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    act(() => {
      result.current.createSession();
    });

    await act(async () => {
      await result.current.sendMessage("cómo crear un personaje ñato");
    });

    const title = result.current.sessions[0].title;
    expect(title).toBe("cómo crear un personaje ñato");
    expect(title).not.toContain("\u251c");
    expect(title).not.toContain("\ufffd");
  });

  it("never overwrites a manually re-titled session (SES-SCN-2.5)", async () => {
    seedSessions([
      {
        id: "titled",
        title: "Mi aventura",
        messages: [{ role: "user", content: "hola" }],
        createdAt: Date.now(),
      },
    ]);
    window.localStorage.setItem(ACTIVE_KEY, JSON.stringify("titled"));

    const { result } = renderHook(() => useAIAssistantSessions("mundo"));
    await act(async () => {
      await result.current.sendMessage("segundo mensaje");
    });

    expect(result.current.sessions[0].title).toBe("Mi aventura");
    expect(result.current.sessions[0].titleIsDefault).not.toBe(true);
  });
});
describe("useAIAssistantSessions document attachments", () => {
  const attachment = {
    id: "att-1",
    name: "Personaje.docx",
    kind: "docx" as const,
    chars: 1200,
    truncated: false,
  };

  it("attaches a document to the active session and clears it on removal", async () => {
    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));
    const uploadMock = vi.mocked(uploadChatAttachment);
    uploadMock.mockResolvedValue(attachment);

    await act(async () => {
      await result.current.attachDocument(new File(["x"], "Personaje.docx"));
    });

    expect(result.current.activeSession?.attachments).toEqual([attachment]);

    act(() => {
      result.current.removeAttachment("att-1");
    });
    expect(result.current.activeSession?.attachments).toEqual([]);
  });

  it("persists attachments with the session", async () => {
    const uploadMock = vi.mocked(uploadChatAttachment);
    uploadMock.mockResolvedValue(attachment);

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));
    await act(async () => {
      await result.current.attachDocument(new File(["x"], "Personaje.docx"));
    });

    const stored = JSON.parse(window.localStorage.getItem(SESSIONS_KEY) ?? "[]");
    expect(stored[0].attachments).toEqual([attachment]);
  });

  it("reports a rejected upload with localized copy and attaches nothing", async () => {
    const uploadMock = vi.mocked(uploadChatAttachment);
    uploadMock.mockRejectedValue(
      new ApiError(422, "unsupported", "unsupported", "attachment.unsupported_type"),
    );

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));
    await act(async () => {
      await result.current.attachDocument(new File(["x"], "notes.txt"));
    });

    expect(result.current.activeSession?.attachments ?? []).toEqual([]);
    expect(result.current.error).toBe(
      "Solo se admiten documentos .docx y .pdf.",
    );
  });

  it("sends the attachment ids with the turn", async () => {
    const streamMock = vi.mocked(streamAssistantActivity);
    const uploadMock = vi.mocked(uploadChatAttachment);
    uploadMock.mockResolvedValue(attachment);
    streamMock.mockResolvedValue({
      accepted: true,
      events: [],
      answer: "Listo",
      terminalStatus: "succeeded" as const,
      semanticDecision: {
        kind: "semantic_decision" as const,
        request_id: "r1",
        state: "allow" as const,
        action: "answer" as const,
        unavailable: false,
        continuation: null,
      },
    });

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));
    await act(async () => {
      await result.current.attachDocument(new File(["x"], "Personaje.docx"));
    });
    await act(async () => {
      await result.current.sendMessage("¿Quién es el personaje?");
    });

    const requests = streamMock.mock.calls;
    const request = requests[requests.length - 1]?.[1] as { attachment_ids?: string[] };
    expect(request.attachment_ids).toEqual(["att-1"]);
  });

  it("drops stale attachments when the server reports them expired", async () => {
    const streamMock = vi.mocked(streamAssistantActivity);
    const uploadMock = vi.mocked(uploadChatAttachment);
    uploadMock.mockResolvedValue(attachment);
    streamMock.mockRejectedValue(
      new ApiError(409, "expired", "expired", "attachment.expired"),
    );

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));
    await act(async () => {
      await result.current.attachDocument(new File(["x"], "Personaje.docx"));
    });
    await act(async () => {
      await result.current.sendMessage("¿Quién es el personaje?");
    });

    expect(result.current.activeSession?.attachments).toEqual([]);
    expect(result.current.error).toBe(
      "El documento adjunto ya no está disponible. Vuelve a adjuntarlo.",
    );
  });
});

describe("useAIAssistantSessions attachment cap", () => {
  it("stops at five attachments without calling the upload endpoint", async () => {
    const uploadMock = vi.mocked(uploadChatAttachment);
    uploadMock.mockClear();
    const existing = Array.from({ length: 5 }, (_, index) => ({
      id: `att-${index}`,
      name: `doc${index}.pdf`,
      kind: "pdf" as const,
      chars: 10,
      truncated: false,
    }));
    seedSessions([
      {
        id: "capped",
        title: "Capped",
        messages: [],
        createdAt: Date.now(),
        attachments: existing,
      },
    ]);
    window.localStorage.setItem(ACTIVE_KEY, JSON.stringify("capped"));

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));
    await act(async () => {
      await result.current.attachDocument(new File(["x"], "extra.pdf"));
    });

    expect(uploadMock).not.toHaveBeenCalled();
    expect(result.current.error).toBe(
      "Puedes adjuntar como máximo 5 documentos por mensaje.",
    );
    expect(result.current.activeSession?.attachments).toHaveLength(5);
  });
});

describe("useAIAssistantSessions image attachment errors", () => {
  it("localizes a vision-unavailable rejection", async () => {
    const uploadMock = vi.mocked(uploadChatAttachment);
    uploadMock.mockClear();
    uploadMock.mockRejectedValue(
      new ApiError(
        422,
        "vision unavailable",
        "vision unavailable",
        "attachment.vision_unavailable",
      ),
    );

    const { result } = renderHook(() => useAIAssistantSessions("Vibrantes"));
    await act(async () => {
      await result.current.attachDocument(new File(["x"], "faro.png"));
    });

    expect(result.current.error).toBe(
      "La visión no está disponible para el modelo del asistente.",
    );
    expect(result.current.activeSession?.attachments ?? []).toEqual([]);
  });
});
