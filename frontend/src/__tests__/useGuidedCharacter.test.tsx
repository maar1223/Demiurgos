import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  continueGuidedCharacter,
  recoverGuidedCharacter,
  startGuidedCharacter,
} from "@/api/guidedCharacter";
import { useGuidedCharacter } from "@/hooks/useGuidedCharacter";

vi.mock("@/api/guidedCharacter", () => ({
  acceptGuidedCharacterProposal: vi.fn(),
  continueGuidedCharacter: vi.fn(),
  recoverGuidedCharacter: vi.fn(),
  rejectGuidedCharacterProposal: vi.fn(),
  retryGuidedCharacterIndex: vi.fn(),
  startGuidedCharacter: vi.fn(),
}));

const recovered = {
  protocol_version: "guided-character-v1",
  session_id: "server-session",
  world: "Vibrantes",
  phase: "conversation" as const,
  revision: 4,
  pending_question: "What do they fear?",
  messages: [],
  candidate: { accepted_canon: {}, proposals: {}, unresolved_references: [], conflicts: [] },
  proposal: null,
};

describe("useGuidedCharacter", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetAllMocks();
  });

  it("uses backend recovery state instead of a cached candidate", async () => {
    localStorage.setItem("demiurgos-guided-character-session", JSON.stringify({ world: "Vibrantes", sessionId: "server-session" }));
    vi.mocked(recoverGuidedCharacter).mockResolvedValue(recovered);

    const { result } = renderHook(() => useGuidedCharacter("Vibrantes"));

    await waitFor(() => expect(result.current.session).toEqual(recovered));
    expect(recoverGuidedCharacter).toHaveBeenCalledWith("Vibrantes", "server-session");
  });

  it("sends the current backend revision and does not persist on failure", async () => {
    vi.mocked(startGuidedCharacter).mockRejectedValue(new Error("provider unavailable"));
    const { result } = renderHook(() => useGuidedCharacter("Vibrantes"));

    await act(async () => {
      await expect(result.current.send("Create a character")).rejects.toThrow("provider unavailable");
    });

    expect(result.current.error).toBe("provider unavailable");
    expect(localStorage.getItem("demiurgos-guided-character-session")).toBeNull();
    expect(continueGuidedCharacter).not.toHaveBeenCalled();
  });
});
