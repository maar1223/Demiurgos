import { useCallback, useState } from "react";
import useSWR from "swr";
import { listHistory, restoreFile } from "@/api/wiki";
import type {
  HistoryEntry,
  HistoryListResponse,
  RestoreFileRequest,
  SuccessResponse,
} from "@/api/types";

export interface UseFileHistoryResult {
  target: string | null;
  entries: HistoryEntry[];
  isLoading: boolean;
  isValidating: boolean;
  isRestoring: boolean;
  error: Error | undefined;
  restoreError: Error | null;
  mutate: () => Promise<HistoryListResponse | undefined>;
  restore: (request: RestoreFileRequest) => Promise<SuccessResponse>;
}

/** Loads authorized snapshots and exposes the gated restore contract only. */
export function useFileHistory(
  mundo: string | undefined,
  path: string | undefined,
): UseFileHistoryResult {
  const key = mundo && path ? (["file-history", mundo, path] as const) : null;
  const { data, error, isLoading, isValidating, mutate } = useSWR<
    HistoryListResponse,
    Error
  >(key, () => listHistory(mundo!, path!), {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    errorRetryCount: 2,
    shouldRetryOnError: true,
  });
  const [isRestoring, setIsRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<Error | null>(null);

  const restore = useCallback(
    async (request: RestoreFileRequest) => {
      if (!mundo) {
        const nextError = new Error("A world is required to restore a file");
        setRestoreError(nextError);
        throw nextError;
      }
      setIsRestoring(true);
      setRestoreError(null);
      try {
        const result = await restoreFile(mundo, request);
        await mutate();
        return result;
      } catch (err) {
        const nextError = err instanceof Error ? err : new Error(String(err));
        setRestoreError(nextError);
        throw nextError;
      } finally {
        setIsRestoring(false);
      }
    },
    [mundo, mutate],
  );

  return {
    target: data?.target ?? null,
    entries: data?.entries ?? [],
    isLoading,
    isValidating,
    isRestoring,
    error,
    restoreError,
    mutate,
    restore,
  };
}
