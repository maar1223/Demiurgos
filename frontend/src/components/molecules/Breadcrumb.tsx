import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

interface BreadcrumbProps {
  /**
   * Ordered path segments, e.g. `["vibrantes", "lore", "cap1", "historia.md"]`
   */
  segments: string[];
  /**
   * Called when a segment at the given index is clicked.
   * The index corresponds to the position in `segments`.
   */
  onSegmentClick?: (index: number) => void;
}

const chipBase =
  "inline-flex items-center truncate rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors";

/**
 * Navigation breadcrumb rendered as chip segments (targetitas) per spec
 * R2 (S17-S18).
 *
 * Each non-last segment is a clickable chip that navigates to that
 * directory level. The last segment is styled as the active current-file
 * chip and is not clickable. A chevron separator is shown between chips.
 */
export function Breadcrumb({ segments, onSegmentClick }: BreadcrumbProps) {
  if (segments.length === 0) return null;

  return (
    <nav
      aria-label="Breadcrumb"
      className="flex flex-wrap items-center justify-center gap-1.5"
    >
      {segments.map((segment, index) => {
        const isLast = index === segments.length - 1;

        return (
          <span
            key={`${index}-${segment}`}
            className="flex min-w-0 items-center gap-1.5"
          >
            {/* Separator between segments */}
            {index > 0 && (
              <Icon
                name="chevron-right"
                size={12}
                className="shrink-0 text-sombra"
              />
            )}

            {isLast ? (
              <span
                className={cn(
                  chipBase,
                  "max-w-[120px] border-llamita/40 bg-llamita/10 text-llamita mobile:max-w-[80px]",
                )}
              >
                {segment}
              </span>
            ) : (
              <button
                type="button"
                onClick={() => onSegmentClick?.(index)}
                className={cn(
                  chipBase,
                  "max-w-[120px] border-filio bg-piedra text-tinta-desvaida hover:border-llamita/50 hover:bg-filio hover:text-pergamino focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-llamita/50 mobile:max-w-[80px]",
                )}
              >
                {segment}
              </button>
            )}
          </span>
        );
      })}
    </nav>
  );
}
