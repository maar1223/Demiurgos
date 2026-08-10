import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AIAssistantSidebar } from "@/components/organisms/AIAssistantSidebar";
import { useAIAssistantSessions } from "@/hooks/useAIAssistantSessions";

vi.mock("@/hooks/useAIAssistantSessions", () => ({
  useAIAssistantSessions: vi.fn(),
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
  ...overrides,
});

describe("AIAssistantSidebar edit action", () => {
  beforeEach(() => {
    useSessionsMock.mockReturnValue(createSessionsState());
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
      "Escribí y enviá una solicitud al asistente primero.",
    );
  });
});

describe("AIAssistantSidebar activity and evidence", () => {
  beforeEach(() => {
    useSessionsMock.mockReturnValue(createSessionsState());
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
