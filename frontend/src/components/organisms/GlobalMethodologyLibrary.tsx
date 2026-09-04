import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getMethodologyInventory,
  type InventoryFilters,
} from "@/api/methodologies";
import type { MethodologyInventoryItem } from "@/api/types";
import { Spinner } from "@/components/atoms/Spinner";
import { Button } from "@/components/atoms/Button";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { InventoryRow } from "@/components/molecules/InventoryRow";
import { InventoryDetailPanel } from "@/components/molecules/InventoryDetailPanel";
import { InventoryFilterBar } from "@/components/molecules/InventoryFilterBar";
import { MethodologyComparePanel } from "@/components/molecules/MethodologyComparePanel";

const EMPTY_INVENTORY_MESSAGE = "No hay metodologías publicadas";
const NO_RESULTS_MESSAGE = "Sin resultados";
const LOAD_ERROR_MESSAGE =
  "No se pudo cargar el inventario global de metodologías.";

/** Two catalog entries are the same published version. */
function sameVersion(
  a: MethodologyInventoryItem,
  b: MethodologyInventoryItem,
): boolean {
  return a.skill_id === b.skill_id && a.version === b.version;
}

/**
 * Read-only query view over the complete published-skills inventory,
 * activated or not (REQ-LIB-2…7 / TW7).
 *
 * The only stateful prop is `onAdaptar` (TW13): when the parent wires it, each
 * published row offers "Adaptar" — derive an editable draft from that version
 * (the `clasificacion="Oficiales"` gate is enforced server-side; published
 * versions are immutable, REQ-CC-16). The organism itself stays read-only:
 * it renders list payloads and forwards the Author action upward.
 */
interface GlobalMethodologyLibraryProps {
  /** TW13 adaptation entry on published rows. When omitted, rows render
   *  without "Adaptar" (keeps the view read-only by default). */
  onAdaptar?: (item: MethodologyInventoryItem) => void;
}

export function GlobalMethodologyLibrary({
  onAdaptar,
}: GlobalMethodologyLibraryProps) {
  const [items, setItems] = useState<MethodologyInventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<InventoryFilters>({});
  const [detail, setDetail] = useState<MethodologyInventoryItem | null>(null);
  const [compareSelection, setCompareSelection] = useState<
    MethodologyInventoryItem[]
  >([]);

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
  useEffect(() => {
    void load(filters);
  }, [load, filters]);

  // Client-side substring search over the loaded list (REQ-LIB-3) — an empty
  // query shows the full list.
  const query = search.trim().toLowerCase();
  const visibleItems = useMemo(() => {
    if (!query) return items;
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(query) ||
        item.description.toLowerCase().includes(query) ||
        item.skill_id.toLowerCase().includes(query),
    );
  }, [items, query]);

  const toggleCompare = (item: MethodologyInventoryItem) => {
    setCompareSelection((prev) => {
      const existing = prev.findIndex((candidate) => sameVersion(candidate, item));
      if (existing >= 0) {
        return prev.filter((_, index) => index !== existing);
      }
      // Third selection replaces the oldest one (REQ-LIB-7).
      if (prev.length >= 2) {
        return [prev[1], item];
      }
      return [...prev, item];
    });
  };

  const clearCompare = () => setCompareSelection([]);

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner size="lg" />
      </div>
    );
  }

  if (error) {
    return <ErrorBanner message={error} onRetry={() => void load(filters)} />;
  }

  const comparing =
    compareSelection.length === 2
      ? { a: compareSelection[0], b: compareSelection[1] }
      : null;

  return (
    <section
      aria-label="Biblioteca global de metodologías"
      className="space-y-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-heading text-h4 text-primary">
            Biblioteca global
          </h2>
          <p className="mt-1 text-small text-muted">
            Inventario completo de metodologías publicadas, activadas o no.
            Vista de solo lectura: no modifica el taller activo ni los mundos.
          </p>
        </div>
        {compareSelection.length > 0 && (
          <Button variant="ghost" size="sm" onClick={clearCompare}>
            Limpiar
          </Button>
        )}
      </div>

      <InventoryFilterBar filters={filters} onChange={setFilters} />

      <label className="flex flex-col gap-1 text-small text-muted">
        Buscar
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Buscar por nombre, descripción o skill_id"
          className="rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50"
        />
      </label>

      {items.length === 0 ? (
        <EmptyState icon="empty" message={EMPTY_INVENTORY_MESSAGE} />
      ) : visibleItems.length === 0 ? (
        <EmptyState icon="search" message={NO_RESULTS_MESSAGE} />
      ) : (
        <ul className="space-y-2">
          {visibleItems.map((item) => (
            <li key={`${item.skill_id}@${item.version}`}>
              <InventoryRow
                item={item}
                onSelect={setDetail}
                onToggleCompare={toggleCompare}
                onAdaptar={onAdaptar}
                selected={compareSelection.some((candidate) =>
                  sameVersion(candidate, item),
                )}
              />
            </li>
          ))}
        </ul>
      )}

      {detail && (
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1">
            <InventoryDetailPanel item={detail} />
          </div>
          <Button variant="ghost" size="sm" onClick={() => setDetail(null)}>
            Cerrar
          </Button>
        </div>
      )}

      {comparing && (
        <MethodologyComparePanel a={comparing.a} b={comparing.b} />
      )}
    </section>
  );
}