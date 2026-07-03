import useSWR from "swr";
import { listWorlds } from "@/api/wiki";
import type { WorldInfo } from "@/api/types";

const WORLDS_KEY = "worlds";

/**
 * Fetches the list of available worlds via SWR.
 * Auto-fetches on mount and revalidates on window focus.
 */
export function useWorlds() {
  const { data, error, isLoading, isValidating, mutate } = useSWR<
    WorldInfo[],
    Error
  >(WORLDS_KEY, listWorlds, {
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    errorRetryCount: 2,
  });

  return {
    worlds: data ?? [],
    isLoading,
    isValidating,
    error,
    mutate,
  };
}
