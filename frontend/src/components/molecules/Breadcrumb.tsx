import { useEffect, useRef, useState } from "react";
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

// No truncate/max-width on purpose: every chip — especially the active
// file chip — must show its full name. Space is governed by the dynamic
// measurement + "…" collapse, not by cutting text.
const chipBase =
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors";

// Number of real chips kept on each side of the "…" when collapsed.
const COLLAPSE_KEEP_HEAD = 2;
const COLLAPSE_KEEP_TAIL = 2;

/**
 * Navigation breadcrumb rendered as chip segments (targetitas) per spec
 * R2 (S17-S18).
 *
 * Each non-last segment is a clickable chip that navigates to that
 * directory level. The last segment is styled as the active current-file
 * chip and is not clickable. A chevron separator is shown between chips.
 *
 * The central editor panel is user-resizable (sidebars + focus mode), so a
 * fixed chip budget would be arbitrary. Instead the component measures the
 * natural width of ALL chips (an invisible measurement layer) against the
 * real container width via ResizeObserver: when everything fits, every
 * segment is shown; when it overflows AND there are enough segments to make
 * collapsing worthwhile (>= 5), it collapses to
 * `[head…] · "…" · […tail]` with an expandable "…" chip. Expanding shows
 * the full list (which wraps to extra lines if needed). Growing the panel
 * re-measures and reveals more chips automatically.
 */
export function Breadcrumb({ segments, onSegmentClick }: BreadcrumbProps) {
  const navRef = useRef<HTMLElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);

  /** True when the full chip list does not fit the container width. */
  const [overflow, setOverflow] = useState(false);
  /** User-expanded ("…" clicked) — show every segment regardless of fit. */
  const [expanded, setExpanded] = useState(false);

  // Re-measure whenever the segments change or the container resizes (the
  // central panel is user-resizable). jsdom has no ResizeObserver — guard
  // so the component safely renders the full list in tests.
  useEffect(() => {
    const nav = navRef.current;
    if (!nav || typeof ResizeObserver === "undefined") return;

    const check = () => {
      const total = measureRef.current?.scrollWidth ?? 0;
      setOverflow(total > nav.clientWidth);
    };
    check();
    const ro = new ResizeObserver(check);
    ro.observe(nav);
    return () => ro.disconnect();
  }, [segments]);

  const canCollapse = segments.length >= COLLAPSE_KEEP_HEAD + COLLAPSE_KEEP_TAIL + 1;
  const collapseMode = overflow && canCollapse;

  // Collapsed: head + "…" + tail. Expanded: the full list plus a trailing
  // "…" chip that collapses back — the toggle stays reachable in both modes.
  const visibleSegments = collapseMode
    ? expanded
      ? [
          ...segments.map((s, i) => ({ segment: s, index: i })),
          { segment: "…", index: "collapse" as const },
        ]
      : [
          ...segments.slice(0, COLLAPSE_KEEP_HEAD).map((s, i) => ({ segment: s, index: i })),
          { segment: "…", index: "ellipsis" as const },
          ...segments.slice(-COLLAPSE_KEEP_TAIL).map((s, i) => ({
            segment: s,
            index: segments.length - COLLAPSE_KEEP_TAIL + i,
          })),
        ]
    : segments.map((s, i) => ({ segment: s, index: i }));

  if (segments.length === 0) return null;

  return (
    <>
      {/* Invisible measurement layer: every chip at its natural width.
          Always mounted — overflow is derived from it, so it cannot be
          conditionally rendered. */}
      <div
        ref={measureRef}
        data-testid="breadcrumb-measure"
        aria-hidden
        className="invisible absolute left-0 top-0 flex items-center gap-1.5"
      >
        {segments.map((segment, index) => (
          <span
            key={`${index}-${segment}`}
            className="flex min-w-0 items-center gap-1.5"
          >
            {index > 0 && (
              <Icon name="chevron-right" size={12} className="shrink-0 text-sombra" />
            )}
            <span
              className={cn(
                chipBase,
                "border-filio bg-piedra text-tinta-desvaida",
              )}
            >
              {segment}
            </span>
          </span>
        ))}
      </div>

      <nav
        ref={navRef}
        data-testid="breadcrumb-nav"
        aria-label="Breadcrumb"
        className="flex flex-wrap items-center justify-center gap-1.5"
      >
        {visibleSegments.map(({ segment, index }) => {
          const isEllipsis = index === "ellipsis" || index === "collapse";
          const isLast = !isEllipsis && index === segments.length - 1;
          // Separator between consecutive chips — the ellipsis chips are
          // chips too (they continue the path), so they get a separator.
          const showSeparator = index !== 0;

          return (
            <span
              key={isEllipsis ? index : `${index}-${segment}`}
              className="flex min-w-0 items-center gap-1.5"
            >
              {showSeparator && (
                <Icon
                  name="chevron-right"
                  size={12}
                  className="shrink-0 text-sombra"
                />
              )}

              {isEllipsis ? (
                <button
                  type="button"
                  onClick={() => setExpanded((prev) => !prev)}
                  aria-expanded={expanded}
                  aria-label={
                    expanded ? "Ocultar niveles intermedios" : "Mostrar todos los niveles"
                  }
                  className={cn(
                    chipBase,
                    "border-llamita/40 bg-llamita/10 text-llamita hover:border-llamita/70 hover:bg-llamita/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-llamita/50",
                  )}
                >
                  {"…"}
                </button>
              ) : isLast ? (
                <span
                  className={cn(
                    chipBase,
                    "border-llamita/40 bg-llamita/10 text-llamita",
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
                    "border-filio bg-piedra text-tinta-desvaida hover:border-llamita/50 hover:bg-filio hover:text-pergamino focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-llamita/50",
                  )}
                >
                  {segment}
                </button>
              )}
            </span>
          );
        })}
      </nav>
    </>
  );
}
