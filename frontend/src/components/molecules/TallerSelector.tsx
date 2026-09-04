import { useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";
import {
  CORE_TALLERES,
  CORE_TALLER_LABELS,
  type CoreTaller,
} from "@/lib/constants";

interface TallerSelectorProps {
  /** Currently active Taller SHORT KEY (Herramientas | Mundo | Ideas). */
  activeTaller: string;
  /** Called with the selected Taller SHORT KEY — display labels live in
   *  CORE_TALLER_LABELS (taller-selector-tree-states spec REQ-TRE-1). */
  onTallerChange: (taller: string) => void;
  /** Stretch the trigger and dropdown to the full width of their container.
   *  Used inside the narrow sidebar filter bar (REQ-LIB-4) where a compact
   *  inline button would let the dropdown overflow and clip. */
  fullWidth?: boolean;
}

function isCoreTaller(taller: string): taller is CoreTaller {
  return (CORE_TALLERES as readonly string[]).includes(taller);
}

/**
 * Dropdown for selecting the active Taller (spec REQ-TRE-1).
 *
 * Mirrors the WorldSelector shape (button + listbox + chevron +
 * close-on-outside-click) over the curated CORE_TALLERES list. Switching is
 * cheap — no confirmation dialog and no "+ Nuevo" entry (REQ-TRE-1). The
 * value passed to `onTallerChange` and persisted is the SHORT KEY; the
 * trigger and the options display the CORE_TALLER_LABELS label.
 */
export function TallerSelector({
  activeTaller,
  onTallerChange,
  fullWidth = false,
}: TallerSelectorProps) {
  const [open, setOpen] = useState(false);

  const triggerLabel = isCoreTaller(activeTaller)
    ? CORE_TALLER_LABELS[activeTaller]
    : activeTaller;

  const handleSelect = (taller: CoreTaller) => {
    setOpen(false);
    if (taller === activeTaller) return;
    onTallerChange(taller);
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          "flex items-center gap-1.5 rounded-lg border border-edge bg-surface-raised px-3 py-1.5 text-small text-primary transition-colors hover:bg-surface-hover",
          fullWidth && "w-full justify-between",
        )}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className={cn("truncate", !fullWidth && "max-w-[180px]")}>
          {triggerLabel}
        </span>
        <Icon
          name="chevron-down"
          size={12}
          className={`transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div
            className={cn(
              "absolute z-20 mt-1 rounded-lg border border-edge bg-surface-raised py-1 shadow-xl",
              fullWidth ? "left-0 right-0" : "right-0 w-48",
            )}
          >
            {CORE_TALLERES.map((taller) => (
              <button
                key={taller}
                type="button"
                onClick={() => handleSelect(taller)}
                role="option"
                aria-selected={taller === activeTaller}
                className={`block w-full px-3 py-2 text-left text-small transition-colors hover:bg-surface-hover ${
                  taller === activeTaller ? "text-action" : "text-primary"
                }`}
              >
                {CORE_TALLER_LABELS[taller]}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}