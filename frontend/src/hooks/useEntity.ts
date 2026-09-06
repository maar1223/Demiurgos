import useSWR from "swr";
import { getEntity } from "@/api/graph";
import { ApiError, type GraphEntity } from "@/api/types";

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
  >(
    key,
    async () => {
      const result = await getEntity(mundo!, name!);
      // The backend returns a 200 with an `{error}` body when the name is
      // unresolved (e.g. a path passed as a name). Treat that as a 404 so
      // EntityDetail renders the "not found" state instead of crashing on a
      // malformed entity (undefined forward_links → `.length` TypeError).
      const errorField = (result as unknown as { error?: unknown }).error;
      if (typeof errorField === "string") {
        throw new ApiError(404, errorField, errorField);
      }
      return result;
    },
    {
      revalidateOnFocus: true,
      revalidateOnReconnect: true,
      errorRetryCount: 2,
    },
  );

  return {
    entity: data ?? null,
    isLoading,
    isValidating,
    error,
    mutate,
  };
}
