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
        "group flex w-full flex-col gap-3 rounded-xl border border-filio bg-madero p-5 text-left transition-all",
        "hover:border-llamita/40 hover:bg-piedra",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-llamita/50",
        "focus-visible:ring-offset-2 focus-visible:ring-offset-cripta",
      )}
    >
      {/* Icon area */}
      <div className="flex h-32 items-center justify-center rounded-lg bg-filio/50 text-llamita transition-colors group-hover:bg-filio">
        <Icon name={meta.icon} size={48} />
      </div>

      {/* Label + chevron hint */}
      <div className="flex items-center justify-between">
        <h3 className="font-heading text-h4 text-pergamino transition-colors group-hover:text-llamita">
          {label}
        </h3>
        <Icon
          name="chevron-right"
          size={16}
          className="text-plata/50 transition-colors group-hover:text-llamita"
        />
      </div>

      {/* Description */}
      <p className="text-small text-tinta-desvaida">{meta.description}</p>

      {/* File count */}
      <span className="text-xs text-tinta-desvaida">
        {fileCount > 0 ? `${fileCount} archivos` : "vacío"}
      </span>
    </button>
  );
}
