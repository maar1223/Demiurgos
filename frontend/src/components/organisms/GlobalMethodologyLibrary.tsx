import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getMethodologyInventory,
  type InventoryFilters,
} from "@/api/methodologies";
import type { MethodologyInventoryItem } from "@/api/types";
import { Spinner } from "@/components/atoms/Spinner";
import { Icon } from "@/components/atoms/Icon";
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

/** Spanish pluralized version count for the group header (TW7). */
function versionCountLabel(count: number): string {
  return count === 1 ? "1 versión" : `${count} versiones`;
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
  /** skill_ids whose multi-version disclosure group is collapsed. Absent ⇒
   *  expanded by default so nothing is hidden on arrival (TW7). */
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());

  const toggleGroup = useCallback((skillId: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(skillId)) {
        next.delete(skillId);
      } else {
        next.add(skillId);
      }
      return next;
    });
  }, []);

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

  // Presentation-only grouping (TW7): filter first, THEN group the survivors by
  // skill_id, preserving the incoming order for both the groups and the
  // versions inside each group. The inventory stays complete and per-version —
  // TW7/TW18's "comparar" still needs version-level entries (REQ-LIB-7).
  const groups = useMemo(() => {
    const ordered = new Map<string, MethodologyInventoryItem[]>();
    for (const item of visibleItems) {
      const versions = ordered.get(item.skill_id);
      if (versions) {
        versions.push(item);
      } else {
        ordered.set(item.skill_id, [item]);
      }
    }
    return ordered;
  }, [visibleItems]);

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
          {Array.from(groups.entries()).map(([skillId, versions]) =>
            versions.length === 1 ? (
              // Exactly one surviving version → the plain flat row, exactly as
              // before (no group chrome, no disclosure control).
              <li key={`${skillId}@${versions[0].version}`}>
                <InventoryRow
                  item={versions[0]}
                  onSelect={(clicked) => onSelect?.(clicked)}
                  selected={compareSelection.some((candidate) =>
                    sameVersion(candidate, versions[0]),
                  )}
                />
              </li>
            ) : (
              // Two or more surviving versions → a group: a disclosure header
              // followed by its version rows (TW7).
              <li key={skillId}>
                <div className="rounded-lg border border-edge bg-surface-raised p-3">
                  <button
                    type="button"
                    aria-expanded={!collapsed.has(skillId)}
                    aria-controls={`catalog-group-${skillId}`}
                    onClick={() => toggleGroup(skillId)}
                    className="flex w-full items-start gap-2 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
                  >
                    <Icon
                      name={
                        collapsed.has(skillId)
                          ? "chevron-right"
                          : "chevron-down"
                      }
                      size={16}
                      className="mt-0.5 shrink-0 text-muted"
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block break-words text-small font-medium text-primary">
                        {versions[0].name}
                      </span>
                      <span className="block break-words text-xs text-muted">
                        {versions[0].skill_id} ·{" "}
                        {versions[0].taller ?? "Sin taller"} ·{" "}
                        {versionCountLabel(versions.length)}
                      </span>
                    </span>
                  </button>
                  {!collapsed.has(skillId) && (
                    <div
                      id={`catalog-group-${skillId}`}
                      className="mt-2 space-y-2"
                    >
                      {versions.map((item) => (
                        <InventoryRow
                          key={`${item.skill_id}@${item.version}`}
                          item={item}
                          variant="version"
                          onSelect={(clicked) => onSelect?.(clicked)}
                          selected={compareSelection.some((candidate) =>
                            sameVersion(candidate, item),
                          )}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </li>
            ),
          )}
        </ul>
      )}
    </section>
  );
}
