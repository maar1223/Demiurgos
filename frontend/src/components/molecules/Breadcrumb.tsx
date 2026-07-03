import { Icon } from "@/components/atoms/Icon";

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

/**
 * Navigation breadcrumb with clickable segments per spec R2 (S17-S18).
 *
 * Each segment is clickable. The last segment is rendered as plain text
 * (current location). A chevron separator is shown between segments.
 */
export function Breadcrumb({ segments, onSegmentClick }: BreadcrumbProps) {
  if (segments.length === 0) return null;

  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-small">
      {segments.map((segment, index) => {
        const isLast = index === segments.length - 1;

        return (
          <span key={`${index}-${segment}`} className="flex items-center gap-1">
            {/* Separator between segments */}
            {index > 0 && (
              <Icon
                name="chevron-right"
                size={12}
                className="text-sombra shrink-0"
              />
            )}

            {isLast ? (
              <span className="truncate text-pergamino max-w-[120px] mobile:max-w-[80px]">
                {segment}
              </span>
            ) : (
              <button
                type="button"
                onClick={() => onSegmentClick?.(index)}
                className="truncate text-tinta-desvaida transition-colors hover:text-pergamino max-w-[120px] mobile:max-w-[80px]"
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
