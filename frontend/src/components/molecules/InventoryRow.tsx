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
  /** Marks the row as part of the compare selection. */
  selected?: boolean;
}

/**
 * Single inventory row: name, version, taller, clasificacion badge and
 * trust-attribute chips. Presentational — the parent owns all selection
 * state. Missing or unknown `clasificacion` renders a neutral
 * "Sin clasificación" badge and never hides the row (REQ-LIB-5).
 *
 * The clasificacion badge is suppressed when a trust chip already implies it
 * (`fundacional`/`verified` ⇒ `Oficiales`), so each row shows one origin label.
 */
export function InventoryRow({
  item,
  onSelect,
  selected = false,
}: InventoryRowProps) {
  const clasificacion = item.clasificacion ?? null;
  const clasificacionVariant = clasificacion
    ? (CLASIFICACION_VARIANT[clasificacion] ?? "default")
    : "default";
  const trust = item.trust_attributes ?? [];

  /** A trust chip can already imply the classification: `fundacional` and
   *  `verified` both imply `Oficiales` (server-derived — the seed path and the
   *  official signature respectively; invariant G14). Showing both would say
   *  the same thing twice, so the row renders the more specific label only. */
  const classificationImpliedByTrust =
    clasificacion === "Oficiales" &&
    (trust.includes("fundacional") || trust.includes("verified"));

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
          <span className="block break-words text-small font-medium text-primary">
            {item.name}
          </span>
          <span className="block break-words text-xs text-muted">
            v{item.version} · {item.taller ?? "Sin taller"} · {item.skill_id}
          </span>
        </button>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {!classificationImpliedByTrust && (
          <Badge variant={clasificacionVariant}>
            {clasificacion ?? "Sin clasificación"}
          </Badge>
        )}
        {trust.map((attr) => (
          <Badge key={attr} variant={TRUST_VARIANT[attr] ?? "default"}>
            {TRUST_LABEL[attr] ?? attr}
          </Badge>
        ))}
      </div>
    </div>
  );
}