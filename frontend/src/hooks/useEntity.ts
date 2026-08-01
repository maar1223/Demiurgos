import useSWR from "swr";
import { getEntity } from "@/api/graph";
import type { GraphEntity } from "@/api/types";

/**
 * Fetches a single entity from the knowledge graph via SWR.
 *
 * Cache key: `["entity", mundo, name]`
 * Auto-fetches when mundo and name are provided. Revalidates on focus
 * to keep entity data fresh.
 */
export function useEntity(
  mundo: string | undefined,
  name: string | undefined,
) {
  const key =
    mundo && name ? (["entity", mundo, name] as const) : null;

  const { data, error, isLoading, isValidating, mutate } = useSWR<
    GraphEntity,
    Error
  >(key, () => getEntity(mundo!, name!), {
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    errorRetryCount: 2,
  });

  return {
    entity: data ?? null,
    isLoading,
    isValidating,
    error,
    mutate,
  };
}
