import useSWR from "swr";
import { getFileContent } from "@/api/wiki";
import type { FileContent } from "@/api/types";

/**
 * Fetches the content of a single file via SWR on demand.
 *
 * Cache key: `["file-content", mundo, section, path]`
 * Only fetches when mundo, section, AND path are all provided (no auto-fetch
 * without a selected file). Does NOT revalidate on focus — content is
 * immutable once loaded until a new file is selected or a manual mutation
 * occurs.
 */
export function useFileContent(
  mundo: string | undefined,
  section: string | undefined,
  path: string | undefined,
) {
  const key =
    mundo && section && path
      ? (["file-content", mundo, section, path] as const)
      : null;

  const { data, error, isLoading, isValidating, mutate } = useSWR<
    FileContent,
    Error
  >(key, () => getFileContent(mundo!, section!, path!), {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    errorRetryCount: 2,
    shouldRetryOnError: true,
  });

  return {
    file: data ?? null,
    revision: data?.revision ?? null,
    isLoading,
    isValidating,
    error,
    mutate,
  };
}
