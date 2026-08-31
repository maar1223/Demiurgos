import { useState, useCallback, type ChangeEvent } from "react";
import { useEntitySearch } from "@/hooks/useEntitySearch";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { cn } from "@/lib/utils";
import type { SearchResult } from "@/api/types";

interface EntitySearchPanelProps {
  /** Current world name for scoping search and wikilinks */
  mundo: string;
  /** Callback fired when a search result is clicked. Receives the entity name. */
  onInsert?: (name: string) => void;
}

/**
 * Entity search panel for the "Contexto" sidebar tab.
 *
 * Features:
 * - Debounced search input using `useEntitySearch` (300ms via the hook)
 * - Result list showing entity name, type badge, and description excerpt
 * - Click a result to insert `[[Name]]` wikilink via `onInsert` callback
 * - Loading state: `Spinner` centered in results area
 * - Empty state: "Sin resultados" message with search icon
 * - Error state: `ErrorBanner` with "Reintentar" button
 */
export function EntitySearchPanel({
  mundo,
  onInsert,
}: EntitySearchPanelProps) {
  const [query, setQuery] = useState("");
  const { results, isLoading, error, mutate } = useEntitySearch(mundo, query);

  const handleInput = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      setQuery(e.target.value);
    },
    [],
  );

  const handleResultClick = useCallback(
    (name: string) => {
      onInsert?.(name);
    },
    [onInsert],
  );

  const hasQuery = query.trim().length > 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Search input */}
      <div className="px-3 py-2">
        <div className="relative">
          <Icon
            name="search"
            size={14}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted"
          />
          <input
            type="text"
            value={query}
            onChange={handleInput}
            placeholder="Buscar entidad…"
            className={cn(
              "w-full rounded-md border border-edge bg-surface-raised",
              "py-1.5 pl-8 pr-3",
              "text-small text-primary placeholder:text-muted",
              "focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50",
              "transition-colors",
            )}
            aria-label="Buscar entidad"
          />
          {/* Inline spinner while loading */}
          {isLoading && (
            <div className="absolute right-2.5 top-1/2 -translate-y-1/2">
              <Spinner size="sm" />
            </div>
          )}
        </div>
      </div>

      {/* Results panel */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* Error state */}
        {error && !isLoading && (
          <div className="px-3 py-2">
            <ErrorBanner
              message={error.message || "Error al buscar entidades."}
              onRetry={() => mutate()}
            />
          </div>
        )}

        {/* Loading state (standalone, when no previous results) */}
        {isLoading && results.length === 0 && hasQuery && (
          <div className="flex items-center justify-center py-8">
            <Spinner size="sm" />
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !error && hasQuery && results.length === 0 && (
          <EmptyState
            icon="search"
            message="Sin resultados"
          />
        )}

        {/* No query — idle state */}
        {!hasQuery && !isLoading && !error && (
          <div className="px-3 py-6 text-center text-small text-muted">
            <p>Escribí para buscar entidades del mundo.</p>
            <p className="mt-1 text-xs">
              Hacé clic en un resultado para insertar un wikilink.
            </p>
          </div>
        )}

        {/* Results list */}
        {results.length > 0 && (
          <ul className="flex flex-col" role="listbox" aria-label="Resultados de búsqueda">
            {results.map((r) => (
              <SearchResultItem
                key={r.path}
                result={r}
                onClick={() => handleResultClick(r.name)}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Internal sub-component
// ---------------------------------------------------------------------------

interface SearchResultItemProps {
  result: SearchResult;
  onClick: () => void;
}

function SearchResultItem({ result, onClick }: SearchResultItemProps) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={false}
      onClick={onClick}
      className={cn(
        "flex flex-col gap-0.5 px-3 py-2 text-left",
        "border-b border-edge/50 last:border-b-0",
        "hover:bg-surface-hover transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-action/50",
      )}
    >
      {/* Name row */}
      <div className="flex items-center gap-2">
        <span className="text-small font-medium text-primary truncate">
          {result.name}
        </span>
        {result.type && (
          <span className="shrink-0 rounded bg-surface-raised px-1.5 py-0.5 text-xs text-muted">
            {result.type}
          </span>
        )}
      </div>
      {/* Description excerpt */}
      {result.description && (
        <p className="text-xs text-muted line-clamp-2">
          {result.description}
        </p>
      )}
      {/* Link count hint */}
      {result.link_count > 0 && (
        <span className="text-xs text-icon-muted">
          {result.link_count} {result.link_count === 1 ? "conexión" : "conexiones"}
        </span>
      )}
    </button>
  );
}
