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
import type { GuidedCharacterSession, SemanticDecisionEnvelope } from "@/api/types";

vi.mock("@/hooks/useAppLanguage", () => ({
  useAppLanguage: vi.fn(() => "es"),
}));

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

const SESSIONS_KEY = "demiurgos-ai-sessions";
const ACTIVE_KEY = "demiurgos-ai-sessions-active";

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