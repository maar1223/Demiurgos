import type { ReactNode } from "react";
import type { MethodologyInventoryItem } from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { MessageKey } from "@/i18n/messages";
import { CLASIFICACION_VARIANT } from "./InventoryRow";

interface MethodologyComparePanelProps {
  a: MethodologyInventoryItem;
  b: MethodologyInventoryItem;
}

interface CompareField {
  label: MessageKey;
  render: (item: MethodologyInventoryItem, t: ReturnType<typeof useAppLanguage>["t"]) => ReactNode;
}

const FIELDS: CompareField[] = [
  { label: "methodology.compare.name", render: (item) => item.name },
  { label: "methodology.compare.version", render: (item) => item.version },
  {
    label: "methodology.compare.taller",
    render: (item, t) => item.taller ?? t("methodology.compare.dash"),
  },
  {
    label: "methodology.compare.category",
    render: (item, t) =>
      item.categoria_funcional ?? t("methodology.compare.dash"),
  },
  {
    label: "methodology.compare.tags",
    render: (item, t) =>
      item.etiquetas && item.etiquetas.length > 0
        ? item.etiquetas.join(", ")
        : t("methodology.compare.dash"),
  },
  {
    label: "methodology.compare.description",
    render: (item, t) =>
      item.description ? item.description : t("methodology.compare.dash"),
  },
  {
    label: "methodology.compare.classification",
    render: (item, t) => {
      const clasificacion = item.clasificacion ?? null;
      const variant = clasificacion
        ? (CLASIFICACION_VARIANT[clasificacion] ?? "default")
        : "default";
      return (
        <Badge variant={variant}>
          {clasificacion ?? t("methodology.compare.unclassified")}
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
  const { t } = useAppLanguage();
  return (
    <section className="overflow-hidden rounded-lg border border-edge bg-surface-raised">
      <h3 className="border-b border-edge px-4 py-2 font-heading text-h4 text-primary">
        {t("methodology.compare.title")}
      </h3>
      <table className="w-full text-small">
        <thead>
          <tr className="border-b border-edge text-left text-xs text-muted">
            <th className="w-36 px-4 py-2 font-medium">
              {t("methodology.compare.field")}
            </th>
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
                {t(field.label)}
              </th>
              <td className="px-4 py-2 align-top text-primary">
                {field.render(a, t)}
              </td>
              <td className="px-4 py-2 align-top text-primary">
                {field.render(b, t)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}