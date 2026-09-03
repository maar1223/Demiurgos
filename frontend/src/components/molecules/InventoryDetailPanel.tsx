import type { MethodologyInventoryItem } from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { CLASIFICACION_VARIANT, TRUST_VARIANT } from "./InventoryRow";

interface InventoryDetailPanelProps {
  item: MethodologyInventoryItem;
}

/**
 * Full metadata panel for one inventory item, rendered entirely from the
 * list payload — no GET-by-id call (REQ-LIB-6). Presentational.
 */
export function InventoryDetailPanel({ item }: InventoryDetailPanelProps) {
  const clasificacion = item.clasificacion ?? null;
  const clasificacionVariant = clasificacion
    ? (CLASIFICACION_VARIANT[clasificacion] ?? "default")
    : "default";
  const trust = item.trust_attributes ?? [];
  const etiquetas = item.etiquetas ?? [];

  return (
    <section className="rounded-lg border border-edge bg-surface-raised p-4">
      <header>
        <h3 className="font-heading text-h4 text-primary">{item.name}</h3>
        <p className="mt-0.5 text-xs text-muted">
          v{item.version} · {item.skill_id}
        </p>
      </header>

      {item.description && (
        <p className="mt-3 text-small leading-relaxed text-primary">
          {item.description}
        </p>
      )}

      <dl className="mt-4 space-y-3 text-small">
        <div>
          <dt className="text-xs text-muted">Taller</dt>
          <dd className="text-primary">{item.taller ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Categoría funcional</dt>
          <dd className="text-primary">{item.categoria_funcional ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Etiquetas</dt>
          <dd className="flex flex-wrap gap-1 pt-1">
            {etiquetas.length > 0 ? (
              etiquetas.map((tag) => (
                <span
                  key={tag}
                  className="rounded-full bg-surface-raised px-2.5 py-0.5 text-xs text-muted"
                >
                  {tag}
                </span>
              ))
            ) : (
              <span className="text-muted">—</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Clasificación</dt>
          <dd className="pt-1">
            <Badge variant={clasificacionVariant}>
              {clasificacion ?? "Sin clasificación"}
            </Badge>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Atributos de confianza</dt>
          <dd className="flex flex-wrap gap-1 pt-1">
            {trust.length > 0 ? (
              trust.map((attr) => (
                <Badge key={attr} variant={TRUST_VARIANT[attr] ?? "default"}>
                  {attr}
                </Badge>
              ))
            ) : (
              <span className="text-muted">—</span>
            )}
          </dd>
        </div>
      </dl>
    </section>
  );
}