import { cn } from "@/lib/utils";
import { VALID_SECTIONS, SECTION_LABELS, type Section } from "@/lib/constants";

interface SectionTabsProps {
  /** Current section from the URL (`lore` | `personajes`) */
  activeSection: string;
  /** Called with the newly selected section */
  onSelect: (section: Section) => void;
}

/**
 * Horizontal tab row for switching world sections above the file tree.
 * Active tab is driven by the current URL section; clicking navigates
 * to the section root. Visual pattern mirrors TabBar (right panel).
 */
export function SectionTabs({ activeSection, onSelect }: SectionTabsProps) {
  return (
    <div
      role="tablist"
      aria-label="Secciones del mundo"
      className="flex shrink-0 border-b border-edge"
    >
      {VALID_SECTIONS.map((section) => (
        <button
          key={section}
          type="button"
          role="tab"
          aria-selected={activeSection === section}
          onClick={() => onSelect(section)}
          className={cn(
            "flex-1 px-3 py-2 text-small font-medium transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-action/50",
            activeSection === section
              ? "border-b-2 border-action text-primary"
              : "text-muted hover:text-primary hover:bg-surface-hover/50",
          )}
        >
          {SECTION_LABELS[section]}
        </button>
      ))}
    </div>
  );
}
