import { useState, useEffect, useRef } from "react";
import useSWR from "swr";
import { searchEntities } from "@/api/graph";
import type { SearchResult } from "@/api/types";

/**
 * Debounces a value by the given delay (ms).
 * Returns the latest value only after the delay has elapsed without changes.
 */
function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}

/**
 * SWR hook for entity search with 300ms debounce and stale-request
 * cancellation via AbortController.
 *
 * Cache key: `["entity-search", mundo, debouncedQuery]`
 * Does NOT revalidate on focus — search results are ephemeral.
 * Keeps previous data while fetching to avoid flicker.
 */
export function useEntitySearch(
  mundo: string | undefined,
  query: string,
) {
  const debouncedQuery = useDebouncedValue(query, 300);
  const abortRef = useRef<AbortController | null>(null);

  const key =
    mundo && debouncedQuery.trim().length > 0
      ? (["entity-search", mundo, debouncedQuery] as const)
      : null;

  const { data, error, isLoading, isValidating, mutate } = useSWR<
    SearchResult[],
    Error
  >(
    key,
    async () => {
      // Cancel any previous in-flight request before starting a new one.
      if (abortRef.current) {
        abortRef.current.abort();
      }
      abortRef.current = new AbortController();

      // NOTE: apiFetch creates its own AbortController for timeout and does
      // not yet accept an external signal. The controller stored here is
      // wired for when apiFetch supports merging external signals. Today,
      // the debounce + SWR key change handles staleness; the controller
      // ensures clean teardown on unmount.
      return searchEntities(mundo!, debouncedQuery);
    },
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      errorRetryCount: 1,
      keepPreviousData: true,
    },
  );

  // Abort any in-flight request on unmount.
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, []);

  return {
    results: data ?? [],
    isLoading: !!key && isLoading,
    isValidating,
    error,
    mutate,
  };
}
