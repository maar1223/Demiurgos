import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { requestConfirmation, suggestEdit } from "@/api/wiki";
import { useEditReview } from "@/hooks/useEditReview";
import type {
  EditConfirmation,
  EditProposal,
  FileContent,
} from "@/api/types";

vi.mock("@/api/wiki", () => ({
  requestConfirmation: vi.fn(),
  suggestEdit: vi.fn(),
}));

const requestConfirmationMock = vi.mocked(requestConfirmation);
const suggestEditMock = vi.mocked(suggestEdit);

const proposal: EditProposal = {
  proposal_id: "proposal-1",
  target: "lore/draft.md",
  base_revision: "base-revision",
  proposed_content: "# Revised draft",
  proposed_digest: "proposed-digest",
  rationale: "Clarify the opening paragraph",
  is_new_file: false,
};

const confirmation: EditConfirmation = {
  token: "single-use-token",
  expires_at: "2026-08-07T20:00:00Z",
  proposed_digest: proposal.proposed_digest,
};

const options = {
  mundo: "vibrantes",
  section: "lore",
  path: "draft.md",
};

describe("useEditReview", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("moves from draft through reviewing to confirmed", async () => {
    suggestEditMock.mockResolvedValue({
      proposal,
      attempts: 1,
      outcome: "proposal",
    });
    requestConfirmationMock.mockResolvedValue(confirmation);

    const { result } = renderHook(() => useEditReview(options));
    expect(result.current.status).toBe("draft");

    await act(async () => {
      await result.current.suggest("Revise the draft");
    });
    expect(result.current.status).toBe("reviewing");
    expect(result.current.proposal).toEqual(proposal);

    await act(async () => {
      await result.current.requestConfirmation(proposal.proposal_id);
    });
    expect(result.current.status).toBe("confirmed");
    expect(result.current.confirmation).toEqual(confirmation);
  });

  it("represents rejection and clears the confirmation token", async () => {
    requestConfirmationMock.mockResolvedValue(confirmation);
    const { result } = renderHook(() => useEditReview(options));

    act(() => result.current.startReview(proposal));
    await act(async () => {
      await result.current.requestConfirmation(proposal.proposal_id);
    });
    expect(result.current.confirmation?.token).toBe(confirmation.token);

    act(() => result.current.reject());
    expect(result.current.status).toBe("rejected");
    expect(result.current.proposal).toBeNull();
    expect(result.current.confirmation).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("resets a rejected review to a clean draft", () => {
    const { result } = renderHook(() => useEditReview(options));

    act(() => result.current.startReview(proposal));
    act(() => result.current.reject());
    act(() => result.current.reset());

    expect(result.current.status).toBe("draft");
    expect(result.current.proposal).toBeNull();
    expect(result.current.confirmation).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it("clears an old token when a new suggestion starts", async () => {
    requestConfirmationMock.mockResolvedValue(confirmation);
    suggestEditMock.mockResolvedValue({
      proposal,
      attempts: 1,
      outcome: "proposal",
    });
    const { result } = renderHook(() => useEditReview(options));

    act(() => result.current.startReview(proposal));
    await act(async () => {
      await result.current.requestConfirmation(proposal.proposal_id);
    });
    expect(result.current.confirmation).toEqual(confirmation);

    await act(async () => {
      await result.current.suggest("Start a fresh review");
    });
    expect(result.current.status).toBe("reviewing");
    expect(result.current.confirmation).toBeNull();
  });

  it("keeps the review unconfirmed when suggestion fails", async () => {
    const error = new Error("proposal service unavailable");
    suggestEditMock.mockRejectedValue(error);
    const { result } = renderHook(() => useEditReview(options));

    await act(async () => {
      await expect(result.current.suggest("Revise the draft")).rejects.toThrow(
        error,
      );
    });

    expect(result.current.status).toBe("draft");
    expect(result.current.confirmation).toBeNull();
    expect(result.current.error).toBe(error);
    expect(result.current.isLoading).toBe(false);
  });

  it("keeps the review pending when confirmation fails", async () => {
    const error = new Error("confirmation rejected");
    requestConfirmationMock.mockRejectedValue(error);
    const { result } = renderHook(() => useEditReview(options));

    act(() => result.current.startReview(proposal));
    await act(async () => {
      await expect(
        result.current.requestConfirmation(proposal.proposal_id),
      ).rejects.toThrow(error);
    });

    expect(result.current.status).toBe("reviewing");
    expect(result.current.confirmation).toBeNull();
    expect(result.current.error).toBe(error);
    expect(result.current.isLoading).toBe(false);
  });

  it("types the current file size without removing legacy metadata", () => {
    const file: FileContent = {
      path: "lore/draft.md",
      name: "draft.md",
      content: "# Draft",
      size: 7,
      size_bytes: 7,
      modified: "2026-08-07T19:00:00Z",
      extension: ".md",
      revision: "revision",
    };

    expect(file.size).toBe(7);
    expect(file.size_bytes).toBe(7);
  });
});
