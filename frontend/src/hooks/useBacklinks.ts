import useSWR from "swr";
import { getLinks } from "@/api/graph";
import type { EntityLink } from "@/api/types";

/**
 * Fetches entity connections (forward links, backlinks, relations) via SWR.
 *
 * Cache key: `["backlinks", mundo, name, kind]`
 * The optional `kind` parameter filters links by relationship type.
 * Revalidates on focus for fresh data.
 */
export function useBacklinks(
  mundo: string | undefined,
  name: string | undefined,
  kind?: string,
) {
  const key =
    mundo && name
      ? (["backlinks", mundo, name, kind] as const)
      : null;

  const { data, error, isLoading, isValidating, mutate } = useSWR<
    EntityLink[],
    Error
  >(key, () => getLinks(mundo!, name!, kind), {
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    errorRetryCount: 2,
  });

  return {
    links: data ?? [],
    isLoading,
    isValidating,
    error,
    mutate,
  };
}
