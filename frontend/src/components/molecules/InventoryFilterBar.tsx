import type { InventoryFilters } from "@/api/methodologies";

interface InventoryFilterBarProps {
  filters: InventoryFilters;
  onChange: (filters: InventoryFilters) => void;
}

/** Clasificación values (REQ-LIB-5 / TW5). "Fundacional" is a UI convenience
 *  for the server-seeded trust facet: it maps to the `fundacional` query param,
 *  not to a `clasificacion` origin value. */
const CLASIFICACION_OPTIONS = [
  "Oficiales",
  "Fundacional",
  "Personalizadas",
  "Comunitarias",
];

/** Functional-category values. Mirrors the backend allow-list
 *  (`methodology_compiler.CATEGORIA_FUNCIONAL_ALLOWED`): the field is a closed
 *  set, so it filters through a select — never a free-text search box. */
const CATEGORIA_FUNCIONAL_OPTIONS = [
  "Creación",
  "Investigación",
  "Diseño",
  "Análisis",
  "Organización",
  "Visualización",
];

/**
 * Filter controls for the global inventory (REQ-LIB-4). Server-side
 * conjunctive: every control emits a full `InventoryFilters` object upward,
 * and a cleared control drops its key (undefined) so the backend re-queries
 * without it.
 *
 * Both controls are closed-set selects (clasificación, categoría funcional).
 * The Clasificación select carries the origin facet plus the "Fundacional"
 * trust facet (server-seeded skills), mapping to two distinct query params:
 * `clasificacion` (origin enum) and `fundacional` (trust attribute). They are
 * mutually exclusive in the emitted filters object.
 * Free-text search lives in the single "Buscar" field owned by the parent
 * (name / description / skill_id / etiquetas), so there is deliberately no
 * third text box here. There is also deliberately NO taller filter: the
 * catalog is the global view across all talleres, and the sidebar header
 * already carries the taller selector for scoped ("Mi mundo") exploration.
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
          value={filters.fundacional ? "Fundacional" : filters.clasificacion ?? ""}
          onChange={(event) => {
            if (event.target.value === "Fundacional") {
              update({ clasificacion: undefined, fundacional: true });
            } else {
              update({
                clasificacion: event.target.value || undefined,
                fundacional: undefined,
              });
            }
          }}
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
        <select
          className={inputClass}
          value={filters.categoria_funcional ?? ""}
          onChange={(event) =>
            update({ categoria_funcional: event.target.value || undefined })
          }
        >
          <option value="">Todas</option>
          {CATEGORIA_FUNCIONAL_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
