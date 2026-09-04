import { useMemo, type ReactNode } from "react";
import { Badge } from "@/components/atoms/Badge";
import { Icon } from "@/components/atoms/Icon";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";
import { ProvenanceBadge } from "@/components/organisms/CoCreation/ProvenanceBadge";
import { diffLines, mergeChangedRows, splitLines } from "@/lib/diff";
import { cn } from "@/lib/utils";
import type {
  DerivedFrom,
  DraftPayload,
  PublishedMethodologyDetail,
  SectionClassification,
} from "@/api/types";

/** TW13 compare sections — the typed canvas keys (REQ-CC-18). */
export const COMPARE_SECTIONS: { key: keyof DraftPayload; label: string }[] = [
  { key: "name", label: "Nombre" },
  { key: "description", label: "Descripción" },
  { key: "purpose", label: "Propósito" },
  { key: "scope", label: "Alcance" },
  { key: "main_flow", label: "Flujo principal" },
  { key: "branches", label: "Ramas" },
  { key: "rules", label: "Reglas" },
];

/** Classify one section against the original: conservado | modificado |
 *  añadido | eliminado (REQ-CC-18). List sections compare as newline-joined
 *  text through the shared LCS diff (`lib/diff.ts`). */
export function classifySection(
  original: string,
  derived: string,
): SectionClassification {
  const left = splitLines(original ?? "");
  const right = splitLines(derived ?? "");
  if (left.length === 0 && right.length === 0) return "conservado";
  if (left.length === 0) return "añadido";
  if (right.length === 0) return "eliminado";
  const rows = mergeChangedRows(diffLines(left, right));
  return rows.every((row) => row.status === "same")
    ? "conservado"
    : "modificado";
}

/** Extract one section value (lists join as newlines for comparison). */
function sectionValue(
  payload: DraftPayload | null,
  key: keyof DraftPayload,
): string {
  if (!payload) return "";
  const value = payload[key];
  if (Array.isArray(value)) return (value as string[]).join("\n");
  return typeof value === "string" ? value : "";
}

/** Best-effort frontend reverse of the deterministic template — mirrors the
 *  backend `parse_rendered_source` boundary: the template renders
 *  `branches`/`rules` as two adjacent bullet lists with NO separator, so
 *  their combined bullets classify into `branches` only and `rules` starts
 *  empty for the Author to reclassify in the canvas (documented lossiness). */
export function parseSourceSections(source: string): Partial<DraftPayload> {
  const parsed: Partial<DraftPayload> = {};
  if (!source || !source.trim()) return parsed;
  const lines = source.split("\n");
  const indexOf = (header: string): number =>
    lines.findIndex((line) => line.trim() === header);

  const first = lines[0]?.trim() ?? "";
  if (first.startsWith("# ")) parsed.name = first.slice(2);

  const propositoIdx = indexOf("## Propósito");
  if (propositoIdx !== -1) {
    if (first.startsWith("# ")) {
      const description = lines
        .slice(1, propositoIdx)
        .join("\n")
        .trim();
      if (description) parsed.description = description;
    }
    const alcanceIdx = indexOf("## Alcance");
    const purpose =
      alcanceIdx !== -1
        ? lines.slice(propositoIdx + 1, alcanceIdx).join("\n").trim()
        : lines.slice(propositoIdx + 1).join("\n").trim();
    if (purpose) parsed.purpose = purpose;

    if (alcanceIdx !== -1) {
      const flujoIdx = indexOf("## Flujo principal");
      const scope =
        flujoIdx !== -1
          ? lines.slice(alcanceIdx + 1, flujoIdx).join("\n").trim()
          : lines.slice(alcanceIdx + 1).join("\n").trim();
      // Drop the deterministic world-binding marker `(mundo: X)` /
      // `(transversal)` so the scope compares content-only (REQ-CC-18).
      if (scope) {
        parsed.scope = scope
          .replace(/\(mundo: [^)]*\)/g, "")
          .replace(/\(transversal\)/g, "")
          .trim();
      }

      if (flujoIdx !== -1) {
        const ramasIdx = indexOf("## Ramas y reglas");
        const mainFlow =
          ramasIdx !== -1
            ? lines.slice(flujoIdx + 1, ramasIdx).join("\n").trim()
            : lines.slice(flujoIdx + 1).join("\n").trim();
        if (mainFlow) parsed.main_flow = mainFlow;

        if (ramasIdx !== -1) {
          const bullets = lines
            .slice(ramasIdx + 1)
            .filter((line) => line.trim().startsWith("- "))
            .map((line) => line.trim().slice(2));
          if (bullets.length > 0) parsed.branches = bullets;
        }
      }
    }
  }
  return parsed;
}

const CLASSIFICATION_LABELS: Record<SectionClassification, string> = {
  conservado: "Conservado",
  modificado: "Modificado",
  añadido: "Añadido",
  eliminado: "Eliminado",
};

const CLASSIFICATION_VARIANT: Record<
  SectionClassification,
  "default" | "success" | "error" | "warning" | "info"
> = {
  conservado: "success",
  modificado: "warning",
  añadido: "info",
  eliminado: "error",
};

interface AdaptationComparePanelProps {
  /** The published original (TW13 original render, read-only). */
  original: PublishedMethodologyDetail | null;
  /** The derived draft payload (live, editable side). */
  derivedPayload: DraftPayload | null;
  /** Server-injected provenance (TW14). */
  derivedFrom: DerivedFrom | null;
  isOpen: boolean;
  onClose: () => void;
  /** The editable derived side — the full CoCreationCanvas wired to the
   *  shared hook (REQ-CC-18: original read-only, derived editable). */
  canvas: ReactNode;
}

/**
 * TW13 side-by-side adaptation compare (REQ-CC-18).
 *
 * Per-section classification (conservado/modificado/añadido/eliminado) is
 * computed with the shared LCS diff over each typed section; the ORIGINAL
 * renders read-only via MarkdownViewer and the DERIVED side is the editable
 * CoCreationCanvas. The provenance badge (TW14) anchors the derivation.
 */
export function AdaptationComparePanel({
  original,
  derivedPayload,
  derivedFrom,
  isOpen,
  onClose,
  canvas,
}: AdaptationComparePanelProps) {
  const originalSections = useMemo(
    () => parseSourceSections(original?.source ?? ""),
    [original],
  );

  if (!isOpen) return null;

  const classifications = COMPARE_SECTIONS.map((section) => {
    const original = sectionValue(
      originalSections as DraftPayload | null,
      section.key,
    );
    const derived = sectionValue(derivedPayload, section.key);
    return {
      ...section,
      original,
      derived,
      classification: classifySection(original, derived),
    };
  });

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-surface/80 backdrop-blur-sm"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="mx-4 flex max-h-[90vh] w-full max-w-5xl flex-col rounded-xl border border-edge bg-surface-raised shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="adaptation-compare-title"
      >
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-edge px-6 py-4">
          <div className="min-w-0">
            <h2
              id="adaptation-compare-title"
              className="font-heading text-h4 text-primary"
            >
              Comparar adaptación
            </h2>
            <p className="mt-0.5 truncate text-small text-muted">
              Original {original?.skill_id}@{original?.version} vs borrador
              derivado
            </p>
          </div>
          <div className="flex items-center gap-2">
            <ProvenanceBadge derivedFrom={derivedFrom} />
            <button
              type="button"
              onClick={onClose}
              aria-label="Cerrar comparación"
              className="rounded-md p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary"
            >
              <Icon name="close" size={20} />
            </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
          {/* Per-section classification (REQ-CC-18). */}
          <section aria-label="Clasificación por sección">
            <h3 className="text-xs font-medium uppercase tracking-wide text-muted">
              Clasificación por sección
            </h3>
            <ul className="mt-2 flex flex-wrap gap-2">
              {classifications.map((section) => (
                <li
                  key={section.key}
                  className="flex items-center gap-1.5 rounded-md border border-edge bg-surface px-2.5 py-1.5"
                >
                  <span className="text-xs text-primary">{section.label}</span>
                  <Badge
                    variant={CLASSIFICATION_VARIANT[section.classification]}
                  >
                    {CLASSIFICATION_LABELS[section.classification]}
                  </Badge>
                </li>
              ))}
            </ul>
          </section>

          {/* Original read-only vs derived editable (REQ-CC-18). */}
          <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-2">
            <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-edge bg-surface">
              <div className="flex items-center justify-between border-b border-edge px-3 py-2">
                <h3 className="text-xs font-medium text-muted">
                  Original (solo lectura)
                </h3>
                <Icon name="diff" size={14} className="text-icon-muted" />
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
                {original ? (
                  <MarkdownViewer content={original.source} />
                ) : (
                  <p className="text-sm text-muted">
                    No se pudo cargar el original publicado.
                  </p>
                )}
              </div>
            </div>
            <div
              className={cn(
                "flex min-h-0 flex-col overflow-hidden rounded-lg border border-edge bg-surface",
              )}
            >
              <div className="flex items-center justify-between border-b border-edge px-3 py-2">
                <h3 className="text-xs font-medium text-muted">
                  Derivado (editable)
                </h3>
                <Icon name="edit" size={14} className="text-icon-muted" />
              </div>
              <div className="min-h-0 flex-1 overflow-hidden">{canvas}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default AdaptationComparePanel;