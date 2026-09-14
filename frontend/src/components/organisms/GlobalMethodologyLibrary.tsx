import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getMethodologyInventory,
  type InventoryFilters,
} from "@/api/methodologies";
import type { MethodologyInventoryItem } from "@/api/types";
import { Spinner } from "@/components/atoms/Spinner";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { InventoryRow } from "@/components/molecules/InventoryRow";
import { InventoryFilterBar } from "@/components/molecules/InventoryFilterBar";

const EMPTY_INVENTORY_MESSAGE = "No hay metodologías publicadas";
const NO_RESULTS_MESSAGE = "Sin resultados";
const LOAD_ERROR_MESSAGE =
  "No se pudo cargar el inventario global de metodologías.";
/** Server-side filter re-query debounce (ms). Keeps the filter bar mounted
 *  and focused while the user types (one request after the last keystroke). */
const FILTER_DEBOUNCE_MS = 300;

/** Two catalog entries are the same published version. */
function sameVersion(
  a: MethodologyInventoryItem,
  b: MethodologyInventoryItem,
): boolean {
  return a.skill_id === b.skill_id && a.version === b.version;
}

/** Compare-selection reducer shared with the page (the right panel's
 *  "Comparar" action toggles the same catalog selection). Dedupes by version;
 *  a third selection replaces the oldest one (REQ-LIB-7). */
export function toggleCompareSelection(
  prev: MethodologyInventoryItem[],
  item: MethodologyInventoryItem,
): MethodologyInventoryItem[] {
  const existing = prev.findIndex((candidate) => sameVersion(candidate, item));
  if (existing >= 0) {
    return prev.filter((_, index) => index !== existing);
  }
  // Third selection replaces the oldest one (REQ-LIB-7).
  if (prev.length >= 2) {
    return [prev[1], item];
  }
  return [...prev, item];
}

interface GlobalMethodologyLibraryProps {
  /** SC-SB-2.2: page-level selection — fired on row click; the page renders
   *  the detail in the center view (`MethodologyDetailView`), never inline. */
  onSelect?: (item: MethodologyInventoryItem) => void;
  /** Controlled compare selection shared with the right state panel's
   *  "Comparar" action — used only to highlight rows in the compare queue. */
  compareSelection?: MethodologyInventoryItem[];
}

/**
 * Read-only query view over the complete published-skills inventory,
 * activated or not (REQ-LIB-2…7 / TW7). Re-slotted into the "Taller" sidebar
 * as the catalogo explorer (task 2.4): the internal heading was removed and
 * rows report page-level selection via `onSelect` (SC-SB-2.2).
 *
 * The only stateful prop is `onSelect` (SC-SB-2.2): the parent wires clicks
 * upward — the page renders the detail in the center `MethodologyDetailView`,
 * so this list never repeats it inline. Rows are selection + information
 * only — every action (Adaptar, Comparar, Exportar) lives in the right
 * MethodologyStatePanel. The organism itself stays read-only: it renders list
 * payloads and reports selection upward.
 */
export function GlobalMethodologyLibrary({
  onSelect,
  compareSelection = [],
}: GlobalMethodologyLibraryProps) {
  const [items, setItems] = useState<MethodologyInventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<InventoryFilters>({});

  const load = useCallback(async (activeFilters: InventoryFilters) => {
    setLoading(true);
    setError(null);
    try {
      const { items: nextItems } =
        await getMethodologyInventory(activeFilters);
      setItems(nextItems);
    } catch {
      setError(LOAD_ERROR_MESSAGE);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch on mount and whenever the server-side filters change (REQ-LIB-4).
  // Debounced so typing does not fire one request per keystroke; the cleanup
  // cancels the pending request when a newer filter value arrives.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      void load(filters);
    }, FILTER_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [load, filters]);

  // Single client-side substring search over the loaded list (REQ-LIB-3): the
  // one free-text entry point covers every textual field — name, description,
  // skill_id, functional category and tags. The two closed-set facets
  // (clasificación, categoría funcional) keep their own selects. An empty query
  // shows the full list.
  const query = search.trim().toLowerCase();
  const visibleItems = useMemo(() => {
    if (!query) return items;
    return items.filter((item) => {
      const haystack = [
        item.name,
        item.description,
        item.skill_id,
        item.categoria_funcional ?? "",
        ...(item.etiquetas ?? []),
      ];
      return haystack.some((value) => value.toLowerCase().includes(query));
    });
  }, [items, query]);

  return (
    <section
      aria-label="Biblioteca global de metodologías"
      className="space-y-4"
    >
      <InventoryFilterBar filters={filters} onChange={setFilters} />

      <label className="flex flex-col gap-1 text-small text-muted">
        Buscar
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Buscar por nombre, descripción, skill_id o etiqueta"
          className="rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50"
        />
      </label>

      {/* Only the results region swaps while a request is in flight: the
          filter bar and the client-side "Buscar" input stay mounted so the
          user never loses focus mid-typing. */}
      {loading ? (
        <div className="flex justify-center py-16">
          <Spinner size="lg" />
        </div>
      ) : error ? (
        <ErrorBanner message={error} onRetry={() => void load(filters)} />
      ) : items.length === 0 ? (
        <EmptyState icon="empty" message={EMPTY_INVENTORY_MESSAGE} />
      ) : visibleItems.length === 0 ? (
        <EmptyState icon="search" message={NO_RESULTS_MESSAGE} />
      ) : (
        <ul className="space-y-2">
          {visibleItems.map((item) => (
            <li key={`${item.skill_id}@${item.version}`}>
              <InventoryRow
                item={item}
                onSelect={(clicked) => onSelect?.(clicked)}
                selected={compareSelection.some((candidate) =>
                  sameVersion(candidate, item),
                )}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
