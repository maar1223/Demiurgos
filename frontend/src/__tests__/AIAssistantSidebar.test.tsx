import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AIAssistantSidebar } from "@/components/organisms/AIAssistantSidebar";
import { useAIAssistantSessions } from "@/hooks/useAIAssistantSessions";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { translate } from "@/i18n/messages";
import { tEs } from "@/__tests__/i18nTestUtils";
import type { GuidedCharacterSession } from "@/api/types";

vi.mock("@/hooks/useAIAssistantSessions", () => ({
  useAIAssistantSessions: vi.fn(),
}));

vi.mock("@/hooks/useAppLanguage", () => ({
  useAppLanguage: vi.fn(),
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
      screen.getByRole("button", { name: "Dame una idea de personaje" }),
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
    expect(resolveGuidedConsent).toHaveBeenCalledWith(true);
    await user.click(screen.getByRole("button", { name: "Seguir charlando" }));
    expect(resolveGuidedConsent).toHaveBeenCalledWith(false);
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
