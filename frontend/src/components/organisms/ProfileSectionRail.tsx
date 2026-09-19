import { useRef, type KeyboardEvent } from "react";
import { Icon, type IconName } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

/** One entry of the Perfil section rail: id, user-facing label and glyph. */
export interface ProfileSectionDef {
  id: string;
  label: string;
  icon: IconName;
}

interface ProfileSectionRailProps {
  sections: ProfileSectionDef[];
  /** Currently active section id. */
  activeId: string;
  /**
   * Called with the newly selected section id. `focusPanel` distinguishes a
   * click (the panel heading takes focus after the change) from an arrow-key
   * rove (focus stays in the rail).
   */
  onSelect: (id: string, options?: { focusPanel?: boolean }) => void;
}

/**
 * Perfil section rail — the page-owned ARIA tablist (REQ-PIA-04). Implements
 * the full tab contract the shared TabBar/SectionTabs stop short of:
 * `role=tablist`/`tab`, `aria-selected` on the active tab only, and
 * `aria-controls` pointing at the owning panel. Focus roves (one tab stop,
 * ArrowLeft/Right/Home/End move focus AND select). On small widths the rail
 * scrolls horizontally instead of overflowing (REQ-PIA-11). Each section
 * exposes exactly one icon (REQ-PIA-06).
 */
export function ProfileSectionRail({
  sections,
  activeId,
  onSelect,
}: ProfileSectionRailProps) {
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next: number | null = null;
    switch (event.key) {
      case "ArrowRight":
        next = (index + 1) % sections.length;
        break;
      case "ArrowLeft":
        next = (index - 1 + sections.length) % sections.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = sections.length - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    const target = tabRefs.current[next];
    if (target) target.focus();
    onSelect(sections[next].id, { focusPanel: false });
  };

  return (
    <div
      role="tablist"
      aria-label="Secciones del perfil"
      className="flex gap-1 overflow-x-auto md:w-56 md:flex-col md:gap-1 md:overflow-visible"
    >
      {sections.map((section, index) => {
        const active = section.id === activeId;
        return (
          <button
            key={section.id}
            ref={(node) => {
              tabRefs.current[index] = node;
            }}
            type="button"
            role="tab"
            id={`profile-tab-${section.id}`}
            aria-selected={active}
            aria-controls={`profile-panel-${section.id}`}
            tabIndex={active ? 0 : -1}
            onClick={() => onSelect(section.id, { focusPanel: true })}
            onKeyDown={(event) => handleKeyDown(event, index)}
            className={cn(
              "flex shrink-0 items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-left text-body transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-action/50",
              active
                ? "bg-surface-raised text-primary"
                : "text-muted hover:bg-surface-raised hover:text-primary",
            )}
          >
            <Icon name={section.icon} size={16} className="shrink-0" />
            {section.label}
          </button>
        );
      })}
    </div>
  );
}