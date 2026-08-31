import { Icon, type IconName } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

/** Per-section icon and description shown on the card. */
const SECTION_CARD_META: Record<string, { icon: IconName; description: string }> = {
  lore: {
    icon: "markdown",
    description: "Ambientación, reglas del mundo e historia",
  },
  personajes: {
    icon: "avatar",
    description: "Fichas de personajes y desarrollo",
  },
  referencias: {
    icon: "folder-open",
    description: "Material de apoyo e investigaciones",
  },
};

interface SectionCardProps {
  section: string;
  label: string;
  fileCount: number;
  onClick: () => void;
}

/**
 * Card for a world section (lore, personajes) shown on the
 * WikiWorld page. Icon-based visual (no image), file count, description
 * and a chevron hint. Clicking navigates to the section.
 */
export function SectionCard({
  section,
  label,
  fileCount,
  onClick,
}: SectionCardProps) {
  const meta = SECTION_CARD_META[section] ?? {
    icon: "file" as const,
    description: "",
  };

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group flex w-full flex-col gap-3 rounded-xl border border-edge bg-surface-raised p-5 text-left transition-all",
        "hover:border-action/40 hover:bg-surface-hover",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50",
        "focus-visible:ring-offset-2 focus-visible:ring-offset-surface",
      )}
    >
      {/* Icon area */}
      <div className="flex h-32 items-center justify-center rounded-lg bg-surface-raised/50 text-action transition-colors group-hover:bg-surface-hover">
        <Icon name={meta.icon} size={48} />
      </div>

      {/* Label + chevron hint */}
      <div className="flex items-center justify-between">
        <h3 className="font-heading text-h4 text-primary transition-colors group-hover:text-action">
          {label}
        </h3>
        <Icon
          name="chevron-right"
          size={16}
          className="text-icon-muted/50 transition-colors group-hover:text-action"
        />
      </div>

      {/* Description */}
      <p className="text-small text-muted">{meta.description}</p>

      {/* File count */}
      <span className="text-xs text-muted">
        {fileCount > 0 ? `${fileCount} archivos` : "vacío"}
      </span>
    </button>
  );
}
