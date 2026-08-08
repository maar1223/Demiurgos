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

describe("AIAssistantSidebar edit action", () => {
  beforeEach(() => {
    useSessionsMock.mockReturnValue({
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
      createSession: vi.fn(),
      switchSession: vi.fn(),
      deleteSession: vi.fn(),
      sendMessage: vi.fn(),
    });
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
      ...useSessionsMock.mock.results[0].value,
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
