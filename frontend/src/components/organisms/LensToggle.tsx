import { cn } from "@/lib/utils";

/** Internal lens of the "Taller" tab (REQ-LEN-1): operational "Mi mundo" vs
 *  read-only "Catálogo total". */
export type Lens = "mi-mundo" | "catalogo-total";

interface LensToggleProps {
  lens: Lens;
  onChange: (lens: Lens) => void;
}

const LENS_OPTIONS: { value: Lens; label: string }[] = [
  { value: "mi-mundo", label: "Mi mundo" },
  { value: "catalogo-total", label: "Catálogo total" },
];

/**
 * Segmented control for the two lenses of the "Taller" tab (REQ-LEN-1). It is
 * an INTERNAL toggle, not a top-level tab (SC-LEN-1.5): switching never
 * changes the active tab or the URL. Buttons use `role="tab"` + `aria-selected`
 * matching the page's tab pattern; the segmented-control styling distinguishes
 * it visually from the top-level tablist.
 */
export function LensToggle({ lens, onChange }: LensToggleProps) {
  return (
    <div
      role="tablist"
      aria-label="Lente del taller"
      className="inline-flex gap-1 rounded-lg border border-edge bg-surface-raised p-1"
    >
      {LENS_OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={lens === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-md px-3 py-1.5 text-small transition-colors",
            lens === option.value
              ? "bg-action text-action-text"
              : "text-muted hover:bg-surface-hover hover:text-primary",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}