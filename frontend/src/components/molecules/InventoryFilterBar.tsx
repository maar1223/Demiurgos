import type { InventoryFilters } from "@/api/methodologies";
import { TallerSelector } from "./TallerSelector";

interface InventoryFilterBarProps {
  filters: InventoryFilters;
  onChange: (filters: InventoryFilters) => void;
}

const CLASIFICACION_OPTIONS = ["Oficiales", "Personalizadas", "Comunitarias"];

/**
 * Filter controls for the global inventory (REQ-LIB-4). Server-side
 * conjunctive: every control emits a full `InventoryFilters` object upward,
 * and a cleared control drops its key (undefined) so the backend re-queries
 * without it. The `TallerSelector` here is a FILTER ONLY — it never drives
 * `activeTaller` or world state (REQ-LIB-4, design decision).
 */
export function InventoryFilterBar({
  filters,
  onChange,
}: InventoryFilterBarProps) {
  const update = (patch: Partial<InventoryFilters>) =>
    onChange({ ...filters, ...patch });

  const inputClass =
    "w-full rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50";

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-small text-muted">
        Clasificación
        <select
          className={inputClass}
          value={filters.clasificacion ?? ""}
          onChange={(event) =>
            update({ clasificacion: event.target.value || undefined })
          }
        >
          <option value="">Todas</option>
          {CLASIFICACION_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-small text-muted">
        Categoría funcional
        <input
          type="text"
          className={inputClass}
          value={filters.categoria_funcional ?? ""}
          onChange={(event) =>
            update({ categoria_funcional: event.target.value || undefined })
          }
          placeholder="Ej. Generación de ideas"
        />
      </label>

      <div className="flex w-full flex-col gap-1 text-small text-muted">
        Taller
        <TallerSelector
          activeTaller={filters.taller ?? ""}
          onTallerChange={(taller) => update({ taller })}
          fullWidth
        />
      </div>

      <label className="flex flex-col gap-1 text-small text-muted">
        Etiquetas
        <input
          type="text"
          className={inputClass}
          value={filters.etiquetas ?? ""}
          onChange={(event) =>
            update({ etiquetas: event.target.value || undefined })
          }
          placeholder="Separadas por coma"
        />
      </label>
    </div>
  );
}