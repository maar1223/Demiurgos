import type { MethodologyInventoryItem } from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { cn } from "@/lib/utils";

/** Badge variant union — mirrors the internal type in Badge.tsx. */
type BadgeVariant = "default" | "success" | "error" | "warning" | "info";

/** clasificacion value → Badge variant (REQ-LIB-5 / TW5). */
export const CLASIFICACION_VARIANT: Record<string, BadgeVariant> = {
  Oficiales: "success",
  Personalizadas: "warning",
  Comunitarias: "info",
};

/** trust_attributes value → Badge variant (REQ-LIB-5 / TW5). */
export const TRUST_VARIANT: Record<string, BadgeVariant> = {
  fundacional: "success",
  verified: "success",
  derived: "info",
  "co-created": "warning",
  quarantined: "error",
};

/** trust_attributes value → Spanish display label (spec UC-4). */
export const TRUST_LABEL: Record<string, string> = {
  fundacional: "Fundacional",
  verified: "Verificado",
  derived: "Derivado",
  "co-created": "Co-creado",
  quarantined: "En cuarentena",
};

interface InventoryRowProps {
  item: MethodologyInventoryItem;
  /** Opens the detail panel for this item. */
  onSelect?: (item: MethodologyInventoryItem) => void;
  /** Toggles this item in the compare selection (max 2). */
  onToggleCompare?: (item: MethodologyInventoryItem) => void;
  /** Marks the row as part of the compare selection. */
  selected?: boolean;
  /** TW13 "Adaptar": derive an editable draft from this published version.
   *  The gate (`clasificacion === "Oficiales"` => derivation is the ONLY path,
   *  REQ-CC-16) is enforced server-side — published versions are immutable —
   *  so the entry is offered on every published row; the title hints at the
   *  required case. */
  onAdaptar?: (item: MethodologyInventoryItem) => void;
  /** REQ-IMP-1: export this published version as a `.zip` methodology
   *  package. Offered on every published row (the inventory only lists
   *  published skills); the parent owns the download. */
  onExport?: (item: MethodologyInventoryItem) => void;
}

/**
 * Single inventory row: name, version, taller, clasificacion badge and
 * trust-attribute chips. Presentational — the parent owns all selection
 * state. Missing or unknown `clasificacion` renders a neutral
 * "Sin clasificación" badge and never hides the row (REQ-LIB-5).
 */
export function InventoryRow({
  item,
  onSelect,
  onToggleCompare,
  selected = false,
  onAdaptar,
  onExport,
}: InventoryRowProps) {
  const clasificacion = item.clasificacion ?? null;
  const clasificacionVariant = clasificacion
    ? (CLASIFICACION_VARIANT[clasificacion] ?? "default")
    : "default";
  const trust = item.trust_attributes ?? [];
  const oficiales = clasificacion === "Oficiales";

  return (
    <div
      className={cn(
        "rounded-lg border border-edge bg-surface-raised p-3 transition-colors",
        selected && "border-action/50",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={() => onSelect?.(item)}
          className="min-w-0 flex-1 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
        >
          <span className="block truncate text-small font-medium text-primary">
            {item.name}
          </span>
          <span className="block truncate text-xs text-muted">
            v{item.version} · {item.taller ?? "Sin taller"} · {item.skill_id}
          </span>
        </button>
        <div className="flex shrink-0 items-center gap-2">
          {onExport && (
            <button
              type="button"
              onClick={() => onExport(item)}
              title="Descargar esta versión publicada como paquete .zip"
              className="rounded-md border border-edge px-2.5 py-1 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary"
            >
              Exportar
            </button>
          )}
          {onAdaptar && (
            <button
              type="button"
              onClick={() => onAdaptar(item)}
              title={
                oficiales
                  ? "Las skills oficiales se adaptan creando una versión derivada (no se editan en el lugar)."
                  : "Derivar una versión editable de esta publicación"
              }
              className={cn(
                "rounded-md border px-2.5 py-1 text-xs transition-colors",
                oficiales
                  ? "border-action/40 bg-action/10 text-action hover:bg-action/20"
                  : "border-edge text-muted hover:border-action/40 hover:text-primary",
              )}
            >
              Adaptar
            </button>
          )}
          {onToggleCompare && (
            <button
              type="button"
              aria-pressed={selected}
              onClick={() => onToggleCompare(item)}
              className={cn(
                "rounded-md border px-2.5 py-1 text-xs transition-colors",
                selected
                  ? "border-action/40 bg-surface-hover text-action"
                  : "border-edge text-muted hover:border-action/40 hover:text-primary",
              )}
            >
              {selected ? "Quitar" : "Comparar"}
            </button>
          )}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge variant={clasificacionVariant}>
          {clasificacion ?? "Sin clasificación"}
        </Badge>
        {trust.map((attr) => (
          <Badge key={attr} variant={TRUST_VARIANT[attr] ?? "default"}>
            {TRUST_LABEL[attr] ?? attr}
          </Badge>
        ))}
      </div>
    </div>
  );
}