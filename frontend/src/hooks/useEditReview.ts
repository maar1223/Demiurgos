import { useCallback, useState } from "react";
import {
  requestConfirmation as requestConfirmationApi,
  suggestEdit,
} from "@/api/wiki";
import type {
  EditConfirmation,
  EditKind,
  EditProposal,
  EditSuggestionResponse,
} from "@/api/types";

export type EditReviewStatus =
  | "draft"
  | "reviewing"
  | "confirmed"
  | "rejected";

export type EditProposalUpdate =
  | EditProposal
  | ((current: EditProposal) => EditProposal);

export interface UseEditReviewOptions {
  mundo: string | undefined;
  section: string | undefined;
  path: string | undefined;
}

export interface UseEditReviewResult {
  status: EditReviewStatus;
  proposal: EditProposal | null;
  confirmation: EditConfirmation | null;
  isLoading: boolean;
  error: Error | null;
  suggest: (
    prompt: string,
    sessionId?: string,
  ) => Promise<EditSuggestionResponse>;
  startReview: (proposal: EditProposal) => void;
  updateProposal: (proposal: EditProposalUpdate) => void;
  requestConfirmation: (
    editId: string,
    kind?: EditKind,
    snapshotId?: string,
  ) => Promise<EditConfirmation>;
  reject: () => void;
  reset: () => void;
}

/** Owns proposal review and confirmation-token state without rendering UI. */
export function useEditReview({
  mundo,
  section,
  path,
}: UseEditReviewOptions): UseEditReviewResult {
  const [status, setStatus] = useState<EditReviewStatus>("draft");
  const [proposal, setProposal] = useState<EditProposal | null>(null);
  const [confirmation, setConfirmation] = useState<EditConfirmation | null>(
    null,
  );
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const suggest = useCallback(
    async (prompt: string, sessionId?: string) => {
      if (!mundo || !section || !path) {
        throw new Error("A world, section, and path are required");
      }
      setIsLoading(true);
      setError(null);
      setConfirmation(null);
      try {
        const result = await suggestEdit(mundo, {
          section,
          path,
          prompt,
          session_id: sessionId,
        });
        setProposal(result.proposal);
        setStatus(result.proposal ? "reviewing" : "draft");
        return result;
      } catch (err) {
        const nextError = err instanceof Error ? err : new Error(String(err));
        setError(nextError);
        throw nextError;
      } finally {
        setIsLoading(false);
      }
    },
    [mundo, path, section],
  );

  const startReview = useCallback((nextProposal: EditProposal) => {
    setProposal(nextProposal);
    setConfirmation(null);
    setError(null);
    setStatus("reviewing");
  }, []);

  const updateProposal = useCallback((nextProposal: EditProposalUpdate) => {
    setProposal((current) => {
      if (!current) return current;
      return typeof nextProposal === "function"
        ? nextProposal(current)
        : nextProposal;
    });
    setConfirmation(null);
    setError(null);
    setStatus("reviewing");
  }, []);

  const requestConfirmation = useCallback(
    async (
      editId: string,
      kind: EditKind = "edit",
      snapshotId?: string,
    ) => {
      if (!mundo || !section || !path || !proposal) {
        throw new Error("A reviewed proposal is required");
      }
      setIsLoading(true);
      setError(null);
      try {
        const result = await requestConfirmationApi(mundo, section, path, {
          edit_id: editId,
          base_revision: proposal.base_revision,
          proposed_content: proposal.proposed_content,
          kind,
          snapshot_id: snapshotId,
        });
        setConfirmation(result);
        setStatus("confirmed");
        return result;
      } catch (err) {
        const nextError = err instanceof Error ? err : new Error(String(err));
        setError(nextError);
        throw nextError;
      } finally {
        setIsLoading(false);
      }
    },
    [mundo, path, proposal, section],
  );

  const reset = useCallback(() => {
    setStatus("draft");
    setProposal(null);
    setConfirmation(null);
    setError(null);
    setIsLoading(false);
  }, []);

  const reject = useCallback(() => {
    setStatus("rejected");
    setProposal(null);
    setConfirmation(null);
    setError(null);
    setIsLoading(false);
  }, []);

  return {
    status,
    proposal,
    confirmation,
    isLoading,
    error,
    suggest,
    startReview,
    updateProposal,
    requestConfirmation,
    reject,
    reset,
  };
}
