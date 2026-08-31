import { Icon } from "@/components/atoms/Icon";
import { Badge } from "@/components/atoms/Badge";
import type { WorldInfo } from "@/api/types";

interface CategoryCardProps {
  world: WorldInfo;
  fileCount: number;
  onClick: (world: WorldInfo) => void;
}

/**
 * Notion-style world card shown on the Wiki Home page.
 * Displays the world name, description (derived from sections), and file count.
 */
export function CategoryCard({ world, fileCount, onClick }: CategoryCardProps) {
  const sectionLabels: string[] = [];
  if (world.lore_count > 0) sectionLabels.push("Lore");
  if (world.character_count > 0) sectionLabels.push("Personajes");
  if (world.reference_count > 0) sectionLabels.push("Referencias");

  return (
    <button
      type="button"
      onClick={() => onClick(world)}
      className="group flex w-full flex-col gap-3 rounded-xl border border-edge bg-surface-raised p-5 text-left transition-all hover:border-action/40 hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50 focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
    >
      {/* Header: icon + file count */}
      <div className="flex items-center justify-between">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-raised/50 text-action transition-colors group-hover:bg-surface-hover">
          <Icon name="world" size={20} />
        </div>
        <Badge variant="info">{fileCount} archivos</Badge>
      </div>

      {/* World name */}
      <h3 className="font-heading text-h4 text-primary transition-colors group-hover:text-action">
        {world.name}
      </h3>

      {/* Section labels */}
      {sectionLabels.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {sectionLabels.map((label) => (
            <span
              key={label}
              className="rounded-md bg-surface-raised/30 px-2 py-0.5 text-xs text-muted"
            >
              {label}
            </span>
          ))}
        </div>
      )}

      {/* Chevron hint */}
      <div className="mt-auto flex items-center justify-end text-icon-muted/50 transition-colors group-hover:text-action">
        <Icon name="chevron-right" size={16} />
      </div>
    </button>
  );
}
