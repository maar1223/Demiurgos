import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AIAssistantSidebar } from "@/components/organisms/AIAssistantSidebar";
import { useAIAssistantSessions } from "@/hooks/useAIAssistantSessions";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { translate } from "@/i18n/messages";
import { tEs } from "@/__tests__/i18nTestUtils";
import { getGuidedMethods } from "@/api/methodologies";
import type { GuidedCharacterSession } from "@/api/types";

vi.mock("@/hooks/useAIAssistantSessions", () => ({
  useAIAssistantSessions: vi.fn(),
  GLOBAL_ASSISTANT_CONTEXT: "ideas-global",
}));

vi.mock("@/hooks/useAppLanguage", () => ({
  useAppLanguage: vi.fn(),
}));

vi.mock("@/api/methodologies", () => ({
  getGuidedMethods: vi.fn(() =>
    Promise.resolve({ methods: [], default: null }),
  ),
}));

vi.mock("@/hooks/useWhisper", () => ({
  useWhisper: vi.fn(() => ({
    status: "idle",
    isRecording: false,
    isTranscribing: false,
    startRecording: vi.fn(),
    stopRecording: vi.fn(),
    error: null,
  })),
}));

const useSessionsMock = vi.mocked(useAIAssistantSessions);
const getGuidedMethodsMock = vi.mocked(getGuidedMethods);
const useAppLanguageMock = vi.mocked(useAppLanguage);

/** The hook returns `{ language, t }` (AD-3); `t` resolves the real catalogue. */
const lang = (language: "es" | "en") => ({
  language,
  t: (key: Parameters<typeof translate>[1], params?: Parameters<typeof translate>[2]) =>
    translate(language, key, params),
});

type SessionsState = ReturnType<typeof useAIAssistantSessions>;

const createSessionsState = (
  overrides: Partial<SessionsState> = {},
): SessionsState => ({
  sessions: [],
  activeSession: {
    id: "session-42",
    title: "Revise the opening",
    messages: [
      { role: "user", content: "Revise the opening" },
      { role: "assistant", content: "I found an opportunity to clarify it." },
    ],
    createdAt: 1,
  },
  activeSessionId: "session-42",
  isSending: false,
  error: null,
  activity: {
    accepted: false,
    items: [],
    status: "neutral",
    warning: null,
    availability: "unknown",
  },
  evidence: { sources: [], warnings: [], status: "neutral" },
  createSession: vi.fn(),
  switchSession: vi.fn(),
  deleteSession: vi.fn(),
  sendMessage: vi.fn(),
  attachDocument: vi.fn(async () => {}),
  removeAttachment: vi.fn(),
  attaching: null,
  cancelSend: vi.fn(),
  resolveGuidedProposal: vi.fn(),
  resolveGuidedConsent: vi.fn(),
  ...overrides,
});

describe("AIAssistantSidebar edit action", () => {
  beforeEach(() => {
    useSessionsMock.mockReturnValue(createSessionsState());
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("uses the latest user prompt, active session, and contextual file", async () => {
    const onProposeEdit = vi.fn();
    const user = userEvent.setup();

    render(
      <AIAssistantSidebar
        mundo="Vibrantes"
        section="lore"
        filePath="capitulos/cap1.md"
        onProposeEdit={onProposeEdit}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Proponer edición" }));

    expect(onProposeEdit).toHaveBeenCalledWith({
      prompt: "Revise the opening",
      sessionId: "session-42",
    });
  });

  it("disables the action with guidance when no user prompt exists", () => {
    useSessionsMock.mockReturnValue({
      ...createSessionsState(),
      activeSession: {
        id: "session-42",
        title: "Nueva sesión",
        messages: [],
        createdAt: 1,
      },
    });

    render(
      <AIAssistantSidebar
        mundo="Vibrantes"
        section="lore"
        filePath="capitulos/cap1.md"
        onProposeEdit={vi.fn()}
      />,
    );

    const action = screen.getByRole("button", { name: "Proponer edición" });
    expect(action).toBeDisabled();
    expect(action).toHaveAttribute(
      "title",
      tEs("assistant.propose.disabled.noPrompt"),
    );
  });
});

describe("AIAssistantSidebar activity and evidence", () => {
  beforeEach(() => {
    useSessionsMock.mockReturnValue(createSessionsState());
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("keeps the assistant answer while the activity panel is gated", () => {
    useSessionsMock.mockReturnValue(
      createSessionsState({
        activity: {
          accepted: true,
          status: "running",
          warning: null,
          availability: "available",
          items: [
            { item_id: "search-1", operation: "Search world", status: "running" },
            {
              item_id: "read-1",
              operation: "Read world",
              status: "succeeded",
              path: "lore/confirmed.md",
            },
            {
              item_id: "failed-1",
              operation: "Read world",
              status: "failed",
              warning: "Evidence incomplete.",
            },
          ],
        },
        evidence: {
          sources: ["lore/confirmed.md", "/etc/passwd"],
          warnings: ["Evidence incomplete.", "provider secret"],
          status: "incomplete",
        },
      }),
    );

    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(screen.getByText("I found an opportunity to clarify it.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Actividad y evidencia" })).not.toBeInTheDocument();
    expect(screen.queryByText("No hay fuentes del mundo confirmadas.")).not.toBeInTheDocument();
  });

  it("preserves the answer after a partial activity failure", () => {
    useSessionsMock.mockReturnValue(
      createSessionsState({
        activity: {
          accepted: true,
          status: "complete",
          warning: "Evidence incomplete.",
          availability: "available",
          items: [
            { item_id: "read-1", operation: "Read world", status: "succeeded", path: "lore/confirmed.md" },
            { item_id: "search-1", operation: "Search world", status: "failed", warning: "Evidence incomplete." },
          ],
        },
        evidence: {
          sources: ["lore/confirmed.md"],
          warnings: ["Evidence incomplete."],
          status: "incomplete",
        },
      }),
    );

    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(screen.getByText("I found an opportunity to clarify it.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Actividad y evidencia" })).not.toBeInTheDocument();
  });

  it("uses neutral evidence copy for an unchanged legacy answer", () => {
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(screen.getByText("I found an opportunity to clarify it.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Actividad y evidencia" })).not.toBeInTheDocument();
  });

  it("explains unavailable activity while the legacy request is thinking", () => {
    useSessionsMock.mockReturnValue(
      createSessionsState({
        activeSession: {
          id: "session-42",
          title: "Revise the opening",
          messages: [{ role: "user", content: "Revise the opening" }],
          createdAt: 1,
        },
        isSending: true,
      }),
    );

    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(screen.queryByRole("region", { name: "Actividad y evidencia" })).not.toBeInTheDocument();
  });

  it("explains when live activity is unavailable after the legacy fallback", () => {
    useSessionsMock.mockReturnValue(
      createSessionsState({
        activity: {
          accepted: false,
          items: [],
          status: "neutral",
          warning: null,
          availability: "unavailable",
          availabilityReason: "file_evidence_contract_unverified",
        },
      }),
    );

    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(screen.queryByRole("region", { name: "Actividad y evidencia" })).not.toBeInTheDocument();
  });
});

describe("AIAssistantSidebar single conversation", () => {
  beforeEach(() => {
    useSessionsMock.mockReturnValue(createSessionsState());
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("keeps the normal chat surface in the personajes section", () => {
    render(<AIAssistantSidebar mundo="Vibrantes" section="personajes" />);

    expect(screen.getByText("I found an opportunity to clarify it.")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Assistant chat" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Guided creation" })).not.toBeInTheDocument();
  });

  it.each([
    {
      language: "es" as const,
      prompt: "I want to create a character",
      yes: "Sí, comenzar",
      no: "No, cancelar",
      value: "sí",
      explanation: "no comenzará ninguna propuesta guiada",
    },
    {
      language: "en" as const,
      prompt: "Quiero crear un personaje",
      yes: "Yes, start",
      no: "No, cancel",
      value: "yes",
      explanation: "no guided proposal will start",
    },
  ])("uses the configured $language UI language, ignoring the $prompt prompt", async ({ language, prompt, yes, no, value, explanation }) => {
    useAppLanguageMock.mockReturnValue(lang(language));
    const sendMessage = vi.fn();
    useSessionsMock.mockReturnValue(createSessionsState({
      sendMessage,
      activeSession: {
        id: "session-42",
        title: "Create a character",
        messages: [{ role: "user", content: prompt }],
        createdAt: 1,
        guided: {
          protocol_version: "guided-character-v1",
          session_id: "guided-42",
          world: "Vibrantes",
          phase: "confirmation",
          mode: "full",
          depth: "standard",
          revision: 1,
          pending_question: "Continue?",
          messages: [],
          candidate: { accepted_canon: {}, proposals: {}, unresolved_references: [], conflicts: [] },
          proposal: null,
        },
      },
    }));

    const user = userEvent.setup();
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(screen.getByText(new RegExp(explanation))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: yes })).toBeEnabled();
    expect(screen.getByRole("button", { name: no })).toBeEnabled();
    expect(screen.getByRole("textbox")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: yes }));
    expect(sendMessage).toHaveBeenCalledWith(value);
    await user.click(screen.getByRole("button", { name: no }));
    expect(sendMessage).toHaveBeenCalledWith("no");
  });

  it("does not render confirmation controls outside the confirmation phase", () => {
    render(<AIAssistantSidebar mundo="Vibrantes" />);
    expect(screen.queryByRole("button", { name: "Yes, start" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sí, comenzar" })).not.toBeInTheDocument();
  });

  it("does not show character modes outside the personajes landing view", () => {
    render(<AIAssistantSidebar mundo="Vibrantes" section="lore" />);

    expect(screen.queryByRole("tablist", { name: "Assistant mode" })).not.toBeInTheDocument();
  });

  it("hides character review until the guided candidate is meaningful", () => {
    const onGuidedReview = vi.fn();
    useSessionsMock.mockReturnValue(createSessionsState({
      activeSession: {
        id: "session-42",
        title: "Create a character",
        messages: [],
        createdAt: 1,
        guided: {
          protocol_version: "guided-character-v1",
          session_id: "guided-42",
          world: "Vibrantes",
           phase: "conversation",
           mode: "full",
           depth: "standard",
          revision: 1,
          pending_question: "What drives them?",
          messages: [],
          candidate: { accepted_canon: {}, proposals: {}, unresolved_references: [], conflicts: [] },
          proposal: null,
        },
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" onGuidedReview={onGuidedReview} />);
    expect(screen.queryByRole("button", { name: "Review and approve character diff" })).not.toBeInTheDocument();
  });

  it("renders guided review as an explicit accessible action", async () => {
    const onGuidedReview = vi.fn();
    const requestGuidedReview = vi.fn().mockResolvedValue({} as never);
    useSessionsMock.mockReturnValue(createSessionsState({
      requestGuidedReview,
      activeSession: {
        id: "session-42",
        title: "Create a character",
        messages: [],
        createdAt: 1,
        guided: {
          protocol_version: "guided-character-v1",
          session_id: "guided-42",
          world: "Vibrantes",
           phase: "conversation",
           mode: "full",
           depth: "standard",
          revision: 1,
          pending_question: "What drives them?",
          messages: [],
          candidate: { accepted_canon: {}, proposals: { desire: "freedom" }, unresolved_references: [], conflicts: [] },
          proposal: null,
        },
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" onGuidedReview={onGuidedReview} />);
    const action = screen.getByRole("button", { name: "Revisar y aprobar el diff del personaje" });
    expect(action).toHaveAttribute("type", "button");
    await userEvent.setup().click(action);
    expect(requestGuidedReview).toHaveBeenCalled();
  });

  it("localizes the proposal detail actions and review button in the configured language", () => {
    const onGuidedReview = vi.fn();
    useAppLanguageMock.mockReturnValue(lang("es"));
    useSessionsMock.mockReturnValue(createSessionsState({
      activeSession: {
        id: "session-42",
        title: "Create a character",
        messages: [],
        createdAt: 1,
        guided: {
          protocol_version: "guided-character-v1",
          session_id: "guided-42",
          world: "Vibrantes",
          phase: "review",
          mode: "full",
          depth: "standard",
          revision: 1,
          pending_question: null,
          messages: [],
          candidate: { accepted_canon: {}, proposals: {}, unresolved_references: [], conflicts: [] },
          proposal: {
            key: "desire",
            label: "Desire",
            value: "freedom",
            rationale: "A starting point",
          },
        },
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" onGuidedReview={onGuidedReview} />);
    expect(screen.getByText("Detalle sugerido")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rechazar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aceptar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revisar y aprobar el diff del personaje" })).toBeInTheDocument();
    expect(screen.queryByText("Suggested detail")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review and approve character diff" })).not.toBeInTheDocument();
  });

  it("keeps English copy for the guided review surface when configured en", () => {
    useAppLanguageMock.mockReturnValue(lang("en"));
    useSessionsMock.mockReturnValue(createSessionsState({
      activeSession: {
        id: "session-42",
        title: "Create a character",
        messages: [],
        createdAt: 1,
        guided: {
          protocol_version: "guided-character-v1",
          session_id: "guided-42",
          world: "Vibrantes",
          phase: "review",
          mode: "full",
          depth: "standard",
          revision: 1,
          pending_question: null,
          messages: [],
          candidate: { accepted_canon: {}, proposals: {}, unresolved_references: [], conflicts: [] },
          proposal: {
            key: "desire",
            label: "Desire",
            value: "freedom",
          },
        },
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" onGuidedReview={vi.fn()} />);
    expect(screen.getByText("Suggested detail")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review and approve character diff" })).toBeInTheDocument();
  });

  it("renders Spanish confirmation actions and disables competing composer input", async () => {
    const sendMessage = vi.fn();
    useSessionsMock.mockReturnValue(createSessionsState({
      sendMessage,
      isSending: false,
      activeSession: {
        id: "session-42",
        title: "Crear personaje",
        messages: [
          { role: "user", content: "Quiero crear la esposa de Rhyz" },
          { role: "assistant", content: "¿Querés comenzar?" },
        ],
        createdAt: 1,
        guided: {
          protocol_version: "guided-character-v1",
          session_id: "guided-42",
          world: "Vibrantes",
          phase: "confirmation",
          mode: "full",
          depth: "standard",
          revision: 1,
          pending_question: null,
          messages: [],
          candidate: { accepted_canon: {}, proposals: {}, unresolved_references: [], conflicts: [] },
          proposal: null,
        },
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(screen.getByRole("region", { name: "Confirmación necesaria" })).toHaveTextContent(
      "no comenzará ninguna propuesta guiada",
    );
    expect(screen.getByRole("button", { name: "Sí, comenzar" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "No, cancelar" })).toBeEnabled();
    expect(
      screen.getByPlaceholderText(tEs("assistant.composer.placeholder")),
    ).toBeDisabled();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Sí, comenzar" }));
    await user.click(screen.getByRole("button", { name: "No, cancelar" }));
    expect(sendMessage).toHaveBeenNthCalledWith(1, "sí");
    expect(sendMessage).toHaveBeenNthCalledWith(2, "no");
  });

  it("uses Spanish confirmation labels from the configured language, not the prompt", () => {
    useAppLanguageMock.mockReturnValue(lang("es"));
    useSessionsMock.mockReturnValue(createSessionsState({
      activeSession: {
        id: "session-42",
        title: "Create character",
        messages: [
          { role: "user", content: "I want to create Rhyz's wife" },
          { role: "assistant", content: "Would you like to start?" },
        ],
        createdAt: 1,
        guided: {
          protocol_version: "guided-character-v1",
          session_id: "guided-42",
          world: "Vibrantes",
          phase: "confirmation",
          mode: "full",
          depth: "standard",
          revision: 1,
          pending_question: null,
          messages: [],
          candidate: { accepted_canon: {}, proposals: {}, unresolved_references: [], conflicts: [] },
          proposal: null,
        },
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(screen.getByRole("button", { name: "Sí, comenzar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "No, cancelar" })).toBeInTheDocument();
    expect(screen.getByText(/no comenzará ninguna propuesta guiada/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Yes, start" })).not.toBeInTheDocument();
  });
});

describe("AIAssistantSidebar null-mundo (global context)", () => {
  beforeEach(() => {
    useSessionsMock.mockReturnValue(
      createSessionsState({
        activeSession: {
          id: "session-42",
          title: "Nueva sesión",
          messages: [],
          createdAt: 1,
        },
      }),
    );
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("renders a world-agnostic context without a mundo prop", () => {
    render(<AIAssistantSidebar />);

    expect(screen.getByText("Banco global de ideas")).toBeInTheDocument();
    expect(screen.getByText(tEs("assistant.empty.globalTitle"))).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: tEs("assistant.suggestion.global.character"),
      }),
    ).toBeInTheDocument();
    // No file to edit in the global context — the edit action explains why.
    expect(
      screen.getByText("El asistente global no edita archivos de un mundo."),
    ).toBeInTheDocument();
  });

  it("forwards no world context to the sessions hook", () => {
    render(<AIAssistantSidebar />);

    expect(useSessionsMock).toHaveBeenCalledWith(undefined, undefined, undefined);
  });
});

describe("AIAssistantSidebar semantic decision UX", () => {
  beforeEach(() => {
    useSessionsMock.mockReturnValue(createSessionsState());
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("surfaces a server-owned proposal_ready review as an explicit action", async () => {
    const onGuidedReview = vi.fn();
    const requestGuidedReview = vi.fn();
    const proposal = {
      proposal_id: "guided-proposal-1",
      target: "personajes/rhyz-s-wife.md",
      base_revision: "1",
      proposed_content: "# Rhyz's Wife\n",
      proposed_digest: "abc123",
      rationale: "Review the guided character before creating the file.",
      is_new_file: true,
    };
    useSessionsMock.mockReturnValue(createSessionsState({
      requestGuidedReview,
      activeSession: {
        id: "session-42",
        title: "Semantic proposal",
        messages: [{ role: "user", content: "Propose a character" }],
        createdAt: 1,
        pendingReview: proposal,
      },
    }));

    const user = userEvent.setup();
    render(<AIAssistantSidebar mundo="Vibrantes" onGuidedReview={onGuidedReview} />);

    const action = screen.getByRole("button", { name: "Revisar y aprobar el diff del personaje" });
    await user.click(action);

    expect(onGuidedReview).toHaveBeenCalledWith(proposal);
    expect(requestGuidedReview).not.toHaveBeenCalled();
  });

  it("renders a blocked-safe message without inferring permission", () => {
    useSessionsMock.mockReturnValue(createSessionsState({
      activeSession: {
        id: "session-42",
        title: "Blocked",
        messages: [
          { role: "user", content: "Vuelca esto al canon" },
          { role: "assistant", content: "I cannot safely act on this request right now. No canon, proposal, or write was made." },
        ],
        createdAt: 1,
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" onGuidedReview={vi.fn()} />);

    expect(screen.getByText(/cannot safely act on this request/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revisar y aprobar el diff del personaje" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sí, comenzar" })).not.toBeInTheDocument();
  });

  it("renders a localized fail-closed alert without provider terms", () => {
    useSessionsMock.mockReturnValue(createSessionsState({
      activity: {
        accepted: true,
        items: [],
        status: "complete",
        warning: null,
        availability: "unavailable",
        blocked: true,
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" onGuidedReview={vi.fn()} />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "El Asistente IA no pudo completar la solicitud en este momento. No se realizó ninguna acción ni escritura.",
    );
    expect(screen.queryByText(/hermes|provider|gateway|http|timeout|quota|credential|model|internal/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revisar y aprobar el diff del personaje" })).not.toBeInTheDocument();
  });

  it("hides the fail-closed alert while the assistant is sending", () => {
    useSessionsMock.mockReturnValue(createSessionsState({
      isSending: true,
      activity: {
        accepted: true,
        items: [],
        status: "running",
        warning: null,
        availability: "unknown",
        blocked: true,
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("AIAssistantSidebar new conversation", () => {
  beforeEach(() => {
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("creates a new session from the chat header button", async () => {
    const createSession = vi.fn();
    useSessionsMock.mockReturnValue(createSessionsState({ createSession }));
    const user = userEvent.setup();

    render(<AIAssistantSidebar mundo="Vibrantes" />);

    await user.click(screen.getByRole("button", { name: "Nueva conversación" }));

    expect(createSession).toHaveBeenCalledTimes(1);
  });

  it("is disabled while a guided confirmation is pending", () => {
    const guided = {
      protocol_version: "1",
      session_id: "g-1",
      world: "Vibrantes",
      phase: "confirmation",
      mode: "full",
      depth: "standard",
      revision: 1,
      pending_question: null,
      messages: [],
      candidate: { proposals: {}, accepted_canon: {} },
      proposal: null,
    } as unknown as GuidedCharacterSession;

    useSessionsMock.mockReturnValue(createSessionsState({
      activeSession: {
        id: "session-42",
        title: "Nueva sesión",
        messages: [],
        createdAt: 1,
        guided,
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(
      screen.getByRole("button", { name: "Nueva conversación" }),
    ).toBeDisabled();
  });
});

describe("AIAssistantSidebar guided consent suggestion", () => {
  beforeEach(() => {
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("renders the in-chat consent card with the composer enabled", () => {
    useSessionsMock.mockReturnValue(createSessionsState({
      activeSession: {
        id: "session-42",
        title: "Crear personaje",
        messages: [{ role: "user", content: "Quiero crear un personaje" }],
        createdAt: 1,
        consentToken: "ct-1",
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(screen.getByText(tEs("assistant.consent.body"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sí, empecemos" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Seguir charlando" })).toBeEnabled();
    // The suggestion creates no guided session: the composer stays enabled.
    expect(
      screen.getByPlaceholderText(tEs("assistant.composer.placeholder")),
    ).toBeEnabled();
  });

  it("wires accept and decline through the sessions hook", async () => {
    const resolveGuidedConsent = vi.fn();
    useSessionsMock.mockReturnValue(createSessionsState({
      resolveGuidedConsent,
      activeSession: {
        id: "session-42",
        title: "Crear personaje",
        messages: [{ role: "user", content: "Quiero crear un personaje" }],
        createdAt: 1,
        consentToken: "ct-1",
      },
    }));

    const user = userEvent.setup();
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    await user.click(screen.getByRole("button", { name: "Sí, empecemos" }));
    expect(resolveGuidedConsent).toHaveBeenCalledWith(true, {
      skill_id: "factory",
    });
    await user.click(screen.getByRole("button", { name: "Seguir charlando" }));
    expect(resolveGuidedConsent).toHaveBeenCalledWith(false);
  });

  it("renders flow-specific copy and methods for a declared flow (S3)", async () => {
    const resolveGuidedConsent = vi.fn();
    getGuidedMethodsMock.mockResolvedValueOnce({
      methods: [
        {
          skill_id: "narrative-system-creation",
          version: "1.1",
          name: "Creación de Sistemas",
        },
      ],
      default: { skill_id: "narrative-system-creation", version: "1.1" },
      flow: "guided-system",
    });
    useSessionsMock.mockReturnValue(createSessionsState({
      resolveGuidedConsent,
      activeSession: {
        id: "session-42",
        title: "Crear sistema",
        messages: [{ role: "user", content: "Quiero crear un sistema" }],
        createdAt: 1,
        consentToken: "ct-sys",
        consentFlow: {
          flow_id: "guided-system",
          entity_type: "sistema",
          target_section: "lore",
          ui_copy_key: "system",
        },
      },
    }));

    const user = userEvent.setup();
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(
      await screen.findByText(tEs("assistant.consent.body.system")),
    ).toBeInTheDocument();
    const select = await screen.findByRole("combobox", {
      name: "Método de esta sesión",
    });
    expect(select).toHaveValue("narrative-system-creation");
    // A declared flow has no builtin factory contract.
    expect(
      screen.queryByRole("option", { name: /De fábrica/ }),
    ).not.toBeInTheDocument();
    expect(getGuidedMethodsMock).toHaveBeenLastCalledWith(
      "Vibrantes", "guided-system",
    );

    await user.click(screen.getByRole("button", { name: "Sí, empecemos" }));
    expect(resolveGuidedConsent).toHaveBeenCalledWith(true, {
      skill_id: "narrative-system-creation",
      version: "1.1",
    });
  });

  it("renders chronology copy and methods for the chronology flow (S3)", async () => {
    const resolveGuidedConsent = vi.fn();
    getGuidedMethodsMock.mockResolvedValueOnce({
      methods: [
        {
          skill_id: "narrative-chronology-creation",
          version: "1.1",
          name: "Creación de Cronologías",
        },
      ],
      default: { skill_id: "narrative-chronology-creation", version: "1.1" },
      flow: "guided-chronology",
    });
    useSessionsMock.mockReturnValue(createSessionsState({
      resolveGuidedConsent,
      activeSession: {
        id: "session-42",
        title: "Crear cronología",
        messages: [{ role: "user", content: "Quiero crear una cronología" }],
        createdAt: 1,
        consentToken: "ct-chron",
        consentFlow: {
          flow_id: "guided-chronology",
          entity_type: "cronologia",
          target_section: "lore",
          ui_copy_key: "chronology",
        },
      },
    }));

    const user = userEvent.setup();
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(
      await screen.findByText(tEs("assistant.consent.body.chronology")),
    ).toBeInTheDocument();
    const select = await screen.findByRole("combobox", {
      name: "Método de esta sesión",
    });
    expect(select).toHaveValue("narrative-chronology-creation");
    expect(
      screen.queryByRole("option", { name: /De fábrica/ }),
    ).not.toBeInTheDocument();
    expect(getGuidedMethodsMock).toHaveBeenLastCalledWith(
      "Vibrantes", "guided-chronology",
    );

    await user.click(screen.getByRole("button", { name: "Sí, empecemos" }));
    expect(resolveGuidedConsent).toHaveBeenCalledWith(true, {
      skill_id: "narrative-chronology-creation",
      version: "1.1",
    });
  });

  it("renders entity copy and methods for the entity flow (S3)", async () => {
    const resolveGuidedConsent = vi.fn();
    getGuidedMethodsMock.mockResolvedValueOnce({
      methods: [
        {
          skill_id: "narrative-entity-creation",
          version: "1.0",
          name: "Creación de Entidades",
        },
      ],
      default: { skill_id: "narrative-entity-creation", version: "1.0" },
      flow: "guided-entity",
    });
    useSessionsMock.mockReturnValue(createSessionsState({
      resolveGuidedConsent,
      activeSession: {
        id: "session-entity",
        title: "Crear entidad",
        messages: [{ role: "user", content: "Quiero crear un lugar" }],
        createdAt: 1,
        consentToken: "ct-entity",
        consentFlow: {
          flow_id: "guided-entity",
          entity_type: "entidad",
          target_section: "lore",
          ui_copy_key: "entity",
        },
      },
    }));

    const user = userEvent.setup();
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(
      await screen.findByText(tEs("assistant.consent.body.entity")),
    ).toBeInTheDocument();
    const select = await screen.findByRole("combobox", {
      name: "Método de esta sesión",
    });
    expect(select).toHaveValue("narrative-entity-creation");
    expect(
      screen.queryByRole("option", { name: /De fábrica/ }),
    ).not.toBeInTheDocument();
    expect(getGuidedMethodsMock).toHaveBeenLastCalledWith(
      "Vibrantes", "guided-entity",
    );

    await user.click(screen.getByRole("button", { name: "Sí, empecemos" }));
    expect(resolveGuidedConsent).toHaveBeenCalledWith(true, {
      skill_id: "narrative-entity-creation",
      version: "1.0",
    });
  });

  it("sends the method chosen on the consent card (S6)", async () => {
    const resolveGuidedConsent = vi.fn();
    getGuidedMethodsMock.mockResolvedValueOnce({
      methods: [
        {
          skill_id: "narrative-character-creation",
          version: "1.2",
          name: "Creación de Personajes",
        },
      ],
      default: null,
    });
    useSessionsMock.mockReturnValue(createSessionsState({
      resolveGuidedConsent,
      activeSession: {
        id: "session-42",
        title: "Crear personaje",
        messages: [{ role: "user", content: "Quiero crear un personaje" }],
        createdAt: 1,
        consentToken: "ct-1",
      },
    }));

    const user = userEvent.setup();
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    const select = await screen.findByRole("combobox", {
      name: "Método de esta sesión",
    });
    await user.selectOptions(select, "narrative-character-creation");
    await user.click(screen.getByRole("button", { name: "Sí, empecemos" }));

    expect(resolveGuidedConsent).toHaveBeenCalledWith(true, {
      skill_id: "narrative-character-creation",
      version: "1.2",
    });
  });

  it("shows the pinned method while a guided session runs (S1)", () => {
    useSessionsMock.mockReturnValue(createSessionsState({
      activeSession: {
        id: "session-42",
        title: "Crear personaje",
        createdAt: 1,
        messages: [{ role: "user", content: "Quiero crear un personaje" }],
        guided: {
          protocol_version: "guided-character-v1",
          session_id: "guided-42",
          world: "Vibrantes",
          phase: "confirmation",
          mode: "full",
          depth: "standard",
          revision: 1,
          pending_question: "Continue?",
          messages: [],
          candidate: {
            accepted_canon: {},
            proposals: {},
            unresolved_references: [],
            conflicts: [],
          },
          proposal: null,
          methodology: {
            skill_id: "narrative-character-creation",
            skill_version: "1.2",
            flow_type: "guided-character",
            factory: false,
          },
        },
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" />);
    expect(
      screen.getByText("Método: narrative-character-creation"),
    ).toBeInTheDocument();
  });

  it("shows the factory method while a factory guided session runs (S1)", () => {
    useSessionsMock.mockReturnValue(createSessionsState({
      activeSession: {
        id: "session-42",
        title: "Crear personaje",
        createdAt: 1,
        messages: [{ role: "user", content: "Quiero crear un personaje" }],
        guided: {
          protocol_version: "guided-character-v1",
          session_id: "guided-42",
          world: "Vibrantes",
          phase: "conversation",
          mode: "full",
          depth: "standard",
          revision: 1,
          pending_question: null,
          messages: [],
          candidate: {
            accepted_canon: {},
            proposals: {},
            unresolved_references: [],
            conflicts: [],
          },
          proposal: null,
          methodology: {
            skill_id: "guided-character-v1",
            skill_version: "builtin",
            flow_type: "guided-character",
            factory: true,
          },
        },
      },
    }));

    render(<AIAssistantSidebar mundo="Vibrantes" />);
    expect(
      screen.getByText("Método: De fábrica (Creación de Personajes)"),
    ).toBeInTheDocument();
  });

  it("renders no consent card without a pending token", () => {
    useSessionsMock.mockReturnValue(createSessionsState());

    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(screen.queryByRole("button", { name: "Sí, empecemos" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Seguir charlando" })).not.toBeInTheDocument();
  });
});

describe("AIAssistantSidebar malformed guided session", () => {
  beforeEach(() => {
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("renders the normal chat UI when guided lacks candidate", () => {
    const malformedGuided = {
      protocol_version: "guided-character-v1",
      session_id: "guided-42",
      world: "Vibrantes",
      phase: "conversation",
      mode: "full",
      depth: "standard",
      revision: 1,
      pending_question: null,
      messages: [],
      proposal: null,
    } as unknown as GuidedCharacterSession;

    useSessionsMock.mockReturnValue(createSessionsState({
      activeSession: {
        id: "session-42",
        title: "Create a character",
        messages: [
          { role: "user", content: "Quiero crear un personaje" },
          { role: "assistant", content: "I found an opportunity to clarify it." },
        ],
        createdAt: 1,
        guided: malformedGuided,
      },
    }));

    expect(() =>
      render(<AIAssistantSidebar mundo="Vibrantes" onGuidedReview={vi.fn()} />),
    ).not.toThrow();

    // The malformed handle is ignored: the normal chat surface still renders.
    expect(screen.getByText("I found an opportunity to clarify it.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Revisar y aprobar el diff del personaje" }),
    ).not.toBeInTheDocument();
  });
});

describe("AIAssistantSidebar document attachments", () => {
  const attachment = {
    id: "att-1",
    name: "Personaje.docx",
    kind: "docx" as const,
    chars: 1200,
    truncated: false,
  };

  beforeEach(() => {
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("renders the attach action and uploads the chosen file", async () => {
    const attachDocument = vi.fn(async () => {});
    useSessionsMock.mockReturnValue(createSessionsState({ attachDocument }));
    const user = userEvent.setup();
    const { container } = render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(
      screen.getByRole("button", { name: tEs("assistant.attach.aria") }),
    ).toBeInTheDocument();

    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    expect(input.accept).toBe(".docx,.pdf,.png,.jpg,.jpeg,.webp,.gif");
    const file = new File(["contenido"], "Personaje.docx");
    await user.upload(input, file);

    expect(attachDocument).toHaveBeenCalledWith(file);
  });

  it("shows one chip per attachment and removes it", async () => {
    const removeAttachment = vi.fn();
    useSessionsMock.mockReturnValue(
      createSessionsState({
        removeAttachment,
        activeSession: {
          id: "session-42",
          title: "Revise the opening",
          messages: [],
          createdAt: 1,
          attachments: [attachment],
        },
      }),
    );
    const user = userEvent.setup();
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(
      screen.getByRole("list", { name: tEs("assistant.attach.list.aria") }),
    ).toHaveTextContent("Personaje.docx");

    await user.click(
      screen.getByRole("button", {
        name: tEs("assistant.attach.remove.aria", { name: "Personaje.docx" }),
      }),
    );
    expect(removeAttachment).toHaveBeenCalledWith("att-1");
  });

  it("sends the default summary prompt when only an attachment is present", async () => {
    const sendMessage = vi.fn();
    useSessionsMock.mockReturnValue(
      createSessionsState({
        sendMessage,
        activeSession: {
          id: "session-42",
          title: "Revise the opening",
          messages: [],
          createdAt: 1,
          attachments: [attachment],
        },
      }),
    );
    const user = userEvent.setup();
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    const send = screen.getByRole("button", { name: tEs("assistant.send.aria") });
    expect(send).toBeEnabled();
    await user.click(send);

    expect(sendMessage).toHaveBeenCalledWith(tEs("assistant.attach.defaultPrompt"));
  });

  it("keeps the send action disabled with neither text nor attachments", () => {
    useSessionsMock.mockReturnValue(createSessionsState());
    render(<AIAssistantSidebar mundo="Vibrantes" />);
    expect(
      screen.getByRole("button", { name: tEs("assistant.send.aria") }),
    ).toBeDisabled();
  });

  it("disables the attach action while a turn is in flight", () => {
    useSessionsMock.mockReturnValue(createSessionsState({ isSending: true }));
    render(<AIAssistantSidebar mundo="Vibrantes" />);
    expect(
      screen.getByRole("button", { name: tEs("assistant.attach.aria") }),
    ).toBeDisabled();
  });
});

describe("AIAssistantSidebar attachment chip", () => {
  it("shows the extracted character count next to the name", () => {
    useAppLanguageMock.mockReturnValue(lang("es"));
    useSessionsMock.mockReturnValue(
      createSessionsState({
        activeSession: {
          id: "session-42",
          title: "Revise the opening",
          messages: [],
          createdAt: 1,
          attachments: [
            {
              id: "att-1",
              name: "Personaje.docx",
              kind: "docx",
              chars: 1200,
              truncated: false,
            },
          ],
        },
      }),
    );
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    const list = screen.getByRole("list", {
      name: tEs("assistant.attach.list.aria"),
    });
    expect(list).toHaveTextContent("Personaje.docx");
    expect(list).toHaveTextContent("1200");
  });
});

describe("AIAssistantSidebar image attachments", () => {
  const image = {
    id: "img-1",
    name: "faro.png",
    kind: "image" as const,
    chars: 240,
    truncated: false,
  };

  beforeEach(() => {
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("accepts images in the attach action", () => {
    useSessionsMock.mockReturnValue(createSessionsState());
    const { container } = render(<AIAssistantSidebar mundo="Vibrantes" />);
    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    expect(input.accept).toBe(".docx,.pdf,.png,.jpg,.jpeg,.webp,.gif");
  });

  it("sends the image question when only an image is attached", async () => {
    const sendMessage = vi.fn();
    useSessionsMock.mockReturnValue(
      createSessionsState({
        sendMessage,
        activeSession: {
          id: "session-42",
          title: "Look",
          messages: [],
          createdAt: 1,
          attachments: [image],
        },
      }),
    );
    const user = userEvent.setup();
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    await user.click(
      screen.getByRole("button", { name: tEs("assistant.send.aria") }),
    );

    expect(sendMessage).toHaveBeenCalledWith(
      tEs("assistant.attach.defaultPromptImage"),
    );
  });

  it("keeps the document summary prompt when a document is also attached", async () => {
    const sendMessage = vi.fn();
    useSessionsMock.mockReturnValue(
      createSessionsState({
        sendMessage,
        activeSession: {
          id: "session-42",
          title: "Mixed",
          messages: [],
          createdAt: 1,
          attachments: [
            image,
            {
              id: "doc-1",
              name: "Personaje.docx",
              kind: "docx",
              chars: 1200,
              truncated: false,
            },
          ],
        },
      }),
    );
    const user = userEvent.setup();
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    await user.click(
      screen.getByRole("button", { name: tEs("assistant.send.aria") }),
    );

    expect(sendMessage).toHaveBeenCalledWith(tEs("assistant.attach.defaultPrompt"));
  });
});

describe("AIAssistantSidebar attachment previews", () => {
  beforeEach(() => {
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  const baseSession = {
    id: "session-42",
    title: "Preview",
    messages: [],
    createdAt: 1,
  };

  it("renders the thumbnail image for an image attachment", () => {
    useSessionsMock.mockReturnValue(
      createSessionsState({
        activeSession: {
          ...baseSession,
          attachments: [
            {
              id: "img-1",
              name: "faro.png",
              kind: "image",
              chars: 240,
              truncated: false,
            },
          ],
        },
      }),
    );
    const { container } = render(<AIAssistantSidebar mundo="Vibrantes" />);
    const image = container.querySelector('img[src*="/thumbnail"]') as HTMLImageElement;
    expect(image).not.toBeNull();
    expect(image.getAttribute("src")).toBe(
      "/api/Vibrantes/ai/attachments/img-1/thumbnail",
    );
  });

  it("renders the type badge for a document attachment", () => {
    useSessionsMock.mockReturnValue(
      createSessionsState({
        activeSession: {
          ...baseSession,
          attachments: [
            {
              id: "doc-1",
              name: "Personaje.docx",
              kind: "docx",
              chars: 1200,
              truncated: false,
            },
          ],
        },
      }),
    );
    render(<AIAssistantSidebar mundo="Vibrantes" />);
    const list = screen.getByRole("list", {
      name: tEs("assistant.attach.list.aria"),
    });
    expect(list).toHaveTextContent("docx");
    expect(list.querySelector("img")).toBeNull();
  });

  it("uses the global context for thumbnails without a world", () => {
    useSessionsMock.mockReturnValue(
      createSessionsState({
        activeSession: {
          ...baseSession,
          attachments: [
            {
              id: "img-2",
              name: "idea.png",
              kind: "image",
              chars: 90,
              truncated: false,
            },
          ],
        },
      }),
    );
    const { container } = render(<AIAssistantSidebar />);
    const image = container.querySelector('img[src*="/thumbnail"]') as HTMLImageElement;
    expect(image.getAttribute("src")).toBe(
      "/api/ideas-global/ai/attachments/img-2/thumbnail",
    );
  });
});


describe("AIAssistantSidebar attachment progress", () => {
  beforeEach(() => {
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("names the accepted file types on the attach button", () => {
    useSessionsMock.mockReturnValue(createSessionsState());
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    const button = screen.getByRole("button", { name: tEs("assistant.attach.aria") });
    const hint = button.getAttribute("title") ?? "";
    for (const extension of [".docx", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"]) {
      expect(hint).toContain(extension);
    }
  });

  it("shows an indeterminate progress chip while an image is analyzed", () => {
    useSessionsMock.mockReturnValue(
      createSessionsState({ attaching: { name: "faro.png", kind: "image" } }),
    );
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("faro.png");
    expect(status).toHaveTextContent(tEs("assistant.attach.analyzingImage"));
    expect(
      screen.getByRole("button", { name: tEs("assistant.attach.aria") }),
    ).toBeDisabled();
  });

  it("shows the extraction copy for a document", () => {
    useSessionsMock.mockReturnValue(
      createSessionsState({ attaching: { name: "Personaje.docx", kind: "document" } }),
    );
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(screen.getByRole("status")).toHaveTextContent(
      tEs("assistant.attach.extracting"),
    );
  });

  it("blocks sending while a file is still processing", () => {
    useSessionsMock.mockReturnValue(
      createSessionsState({
        attaching: { name: "faro.png", kind: "image" },
        activeSession: {
          id: "session-42",
          title: "Busy",
          messages: [],
          createdAt: 1,
          attachments: [
            {
              id: "att-1",
              name: "Personaje.docx",
              kind: "docx",
              chars: 10,
              truncated: false,
            },
          ],
        },
      }),
    );
    render(<AIAssistantSidebar mundo="Vibrantes" />);

    expect(
      screen.getByRole("button", { name: tEs("assistant.send.aria") }),
    ).toBeDisabled();
  });
});
