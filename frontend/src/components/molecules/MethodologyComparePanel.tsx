import type { ReactNode } from "react";
import type { MethodologyInventoryItem } from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { CLASIFICACION_VARIANT } from "./InventoryRow";

interface MethodologyComparePanelProps {
  a: MethodologyInventoryItem;
  b: MethodologyInventoryItem;
}

interface CompareField {
  label: string;
  render: (item: MethodologyInventoryItem) => ReactNode;
}

const FIELDS: CompareField[] = [
  { label: "Nombre", render: (item) => item.name },
  { label: "Versión", render: (item) => item.version },
  { label: "Taller", render: (item) => item.taller ?? "—" },
  {
    label: "Categoría funcional",
    render: (item) => item.categoria_funcional ?? "—",
  },
  {
    label: "Etiquetas",
    render: (item) =>
      item.etiquetas && item.etiquetas.length > 0
        ? item.etiquetas.join(", ")
        : "—",
  },
  {
    label: "Descripción",
    render: (item) => (item.description ? item.description : "—"),
  },
  {
    label: "Clasificación",
    render: (item) => {
      const clasificacion = item.clasificacion ?? null;
      const variant = clasificacion
        ? (CLASIFICACION_VARIANT[clasificacion] ?? "default")
        : "default";
      return (
        <Badge variant={variant}>
          {clasificacion ?? "Sin clasificación"}
        </Badge>
      );
    },
  },
];

/**
 * Lightweight side-by-side compare of two inventory items across seven
 * fields (REQ-LIB-7 / TW18). Pure presentational — no diff editor, no
 * selection logic; the parent decides which items to pass.
 */
export function MethodologyComparePanel({
  a,
  b,
}: MethodologyComparePanelProps) {
  return (
    <section className="overflow-hidden rounded-lg border border-edge bg-surface-raised">
      <h3 className="border-b border-edge px-4 py-2 font-heading text-h4 text-primary">
        Comparación
      </h3>
      <table className="w-full text-small">
        <thead>
          <tr className="border-b border-edge text-left text-xs text-muted">
            <th className="w-36 px-4 py-2 font-medium">Campo</th>
            <th className="px-4 py-2 font-medium">{a.name}</th>
            <th className="px-4 py-2 font-medium">{b.name}</th>
          </tr>
        </thead>
        <tbody>
          {FIELDS.map((field) => (
            <tr
              key={field.label}
              className="border-b border-edge/50 last:border-0"
            >
              <th
                scope="row"
                className="px-4 py-2 align-top text-left text-xs font-medium text-muted"
              >
                {field.label}
              </th>
              <td className="px-4 py-2 align-top text-primary">
                {field.render(a)}
              </td>
              <td className="px-4 py-2 align-top text-primary">
                {field.render(b)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}