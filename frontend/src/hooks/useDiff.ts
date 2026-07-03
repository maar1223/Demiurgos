import useSWR from "swr";
import { getDiff } from "@/api/wiki";
import type { DiffPreview } from "@/api/types";

/**
 * Provides a manual trigger for fetching a diff preview.
 *
 * Unlike useFileTree / useFileContent, this hook does NOT auto-fetch.
 * The caller must call `triggerDiff(mundo, section, path, newContent)`
 * to request a diff. This matches the spec requirement (R3, S20-S27):
 * the diff is only generated when the user explicitly asks for it.
 */
export function useDiff() {
  const { data, error, isLoading, isValidating, mutate } = useSWR<
    DiffPreview | null,
    Error
  >(null, null, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    shouldRetryOnError: false,
  });

  /**
   * Triggers a diff fetch by manually calling the API and updating SWR's cache.
   * Returns the DiffPreview or throws an ApiError.
   */
  const triggerDiff = async (
    mundo: string,
    section: string,
    path: string,
    newContent: string,
  ): Promise<DiffPreview> => {
    const result = await getDiff(mundo, section, path, newContent);
    // Store the result in SWR's cache so `data` reflects it
    await mutate(result, false);
    return result;
  };

  return {
    diff: data,
    isLoading,
    isValidating,
    error,
    triggerDiff,
    reset: () => mutate(null, false),
  };
}
