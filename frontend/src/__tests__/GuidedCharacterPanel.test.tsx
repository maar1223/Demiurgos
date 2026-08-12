import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GuidedCharacterPanel } from "@/components/organisms/GuidedCharacterPanel";
import { useGuidedCharacter } from "@/hooks/useGuidedCharacter";

vi.mock("@/hooks/useGuidedCharacter", () => ({ useGuidedCharacter: vi.fn() }));

const useGuidedCharacterMock = vi.mocked(useGuidedCharacter);

const baseState = () => ({
  session: {
    protocol_version: "guided-character-v1",
    session_id: "session-1",
    world: "Vibrantes",
    phase: "review" as const,
    revision: 2,
    pending_question: null,
    messages: [{ role: "assistant" as const, content: "What drives them?" }],
    candidate: {
      accepted_canon: {},
      proposals: { desire: { value: "Protect the village", provenance: ["secret"] } },
      unresolved_references: [],
      conflicts: [],
    },
    proposal: {
      key: "desire",
      label: "Desire",
      value: "Protect the village",
      rationale: "A focused starting point",
    },
  },
  isLoading: false,
  error: null,
  send: vi.fn(),
  accept: vi.fn(),
  reject: vi.fn(),
  retryIndex: vi.fn(),
});

describe("GuidedCharacterPanel", () => {
  beforeEach(() => useGuidedCharacterMock.mockReturnValue(baseState()));

  it("renders one focused prompt and hides provider provenance", () => {
    render(<GuidedCharacterPanel world="Vibrantes" />);

    expect(screen.getByText("What drives them?")).toBeInTheDocument();
    expect(screen.getByText(/Protect the village/)).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
    expect(screen.queryByText(/workflow|provenance/i)).not.toBeInTheDocument();
  });

  it("delegates rejection and acceptance without a client-side write", async () => {
    const user = userEvent.setup();
    const state = baseState();
    useGuidedCharacterMock.mockReturnValue(state);
    render(<GuidedCharacterPanel world="Vibrantes" />);

    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.click(screen.getByRole("button", { name: "Accept" }));

    expect(state.reject).toHaveBeenCalledTimes(1);
    expect(state.accept).toHaveBeenCalledTimes(1);
  });

  it("offers retry for non-indexed durable creation status", async () => {
    const user = userEvent.setup();
    const state = {
      ...baseState(),
      session: { ...baseState().session, proposal: null, phase: "complete" as const, index_status: "pending" as const },
    };
    useGuidedCharacterMock.mockReturnValue(state);
    render(<GuidedCharacterPanel world="Vibrantes" />);

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(screen.getByRole("status")).toHaveTextContent("graph indexing is pending");
    expect(state.retryIndex).toHaveBeenCalledTimes(1);
  });
});
