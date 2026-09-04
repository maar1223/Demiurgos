import { useCallback, useEffect, useMemo, useState } from "react";
import {
  exportPublished,
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
const EXPORT_ERROR_MESSAGE = "No se pudo exportar la metodología.";

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
  /** TW13 adaptation entry on published rows. When omitted, rows render
   *  without "Adaptar" (keeps the view read-only by default). */
  onAdaptar?: (item: MethodologyInventoryItem) => void;
  /** SC-SB-2.2: page-level selection — fired on row click alongside the
   *  internal detail panel. */
  onSelect?: (item: MethodologyInventoryItem) => void;
  /** Controlled compare selection shared with the right state panel's
   *  "Comparar" action. When omitted, the organism owns its selection
   *  (backward compatible with standalone usage). */
  compareSelection?: MethodologyInventoryItem[];
  onCompareToggle?: (item: MethodologyInventoryItem) => void;
  onCompareClear?: () => void;
}

/**
 * Read-only query view over the complete published-skills inventory,
 * activated or not (REQ-LIB-2…7 / TW7). Re-slotted into the "Taller" sidebar
 * as the catalogo explorer (task 2.4): the internal heading was removed and
 * rows report page-level selection via `onSelect` (SC-SB-2.2).
 *
 * The only stateful props are `onAdaptar` (TW13) and `onSelect` (SC-SB-2.2):
 * when the parent wires them, each published row offers "Adaptar" — derive an
 * editable draft from that version (the `clasificacion="Oficiales"` gate is
 * enforced server-side; published versions are immutable, REQ-CC-16) — and
 * reports clicks upward. The organism itself stays read-only: it renders list
 * payloads and forwards the Author action upward.
 */
export function GlobalMethodologyLibrary({
  onAdaptar,
  onSelect,
  compareSelection: controlledCompare,
  onCompareToggle,
  onCompareClear,
}: GlobalMethodologyLibraryProps) {
  const [items, setItems] = useState<MethodologyInventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<InventoryFilters>({});
  const [detail, setDetail] = useState<MethodologyInventoryItem | null>(null);
  const [internalCompare, setInternalCompare] = useState<
    MethodologyInventoryItem[]
  >([]);

  const compareSelection = controlledCompare ?? internalCompare;
  const toggleCompare = (item: MethodologyInventoryItem) => {
    if (onCompareToggle) {
      onCompareToggle(item);
      return;
    }
    setInternalCompare((prev) => toggleCompareSelection(prev, item));
  };
  const clearCompare = () => {
    if (onCompareClear) {
      onCompareClear();
      return;
    }
    setInternalCompare([]);
  };

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

  /** REQ-IMP-1: export a published version as a `.zip` package and trigger the
   *  browser download. Read-only — the catalog is never mutated; the Author
   *  keeps the artifact. */
  const handleExport = async (item: MethodologyInventoryItem) => {
    setExportError(null);
    try {
      const blob = await exportPublished(item.skill_id, item.version);
      const objectUrl = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `${item.skill_id}-${item.version}.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(objectUrl);
    } catch {
      setExportError(EXPORT_ERROR_MESSAGE);
    }
  };

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
      className="space-y-4"
    >
      {compareSelection.length > 0 && (
        <div className="flex justify-end">
          <Button variant="ghost" size="sm" onClick={clearCompare}>
            Limpiar
          </Button>
        </div>
      )}

      <InventoryFilterBar filters={filters} onChange={setFilters} />

      {exportError && (
        <p
          role="alert"
          className="rounded-md border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error"
        >
          {exportError}
        </p>
      )}

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
                onSelect={(clicked) => {
                  setDetail(clicked);
                  onSelect?.(clicked);
                }}
                onToggleCompare={toggleCompare}
                onAdaptar={onAdaptar}
                onExport={handleExport}
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