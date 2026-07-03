import useSWR from "swr";
import { getFileTree } from "@/api/wiki";
import type { FileNode } from "@/api/types";

/**
 * Fetches the recursive file tree for a world section via SWR.
 *
 * Cache key: `["file-tree", mundo, section]`
 * Auto-fetches when mundo and section are provided, revalidates on focus.
 */
export function useFileTree(mundo: string | undefined, section: string | undefined) {
  const key =
    mundo && section ? (["file-tree", mundo, section] as const) : null;

  const { data, error, isLoading, isValidating, mutate } = useSWR<
    FileNode[],
    Error
  >(key, () => getFileTree(mundo!, section!), {
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    errorRetryCount: 2,
  });

  return {
    nodes: data ?? [],
    isLoading,
    isValidating,
    error,
    mutate,
  };
}
