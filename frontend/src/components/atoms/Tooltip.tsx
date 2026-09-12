import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface TooltipProps {
  /** Stable id linking the trigger to the accessible copy via
   *  aria-describedby. */
  id: string;
  /** Tooltip copy — rendered twice: the visible bubble (pure-CSS hover /
   *  focus-visible reveal) and an sr-only duplicate exposed to assistive
   *  tech. */
  content: ReactNode;
  /** The trigger surface (icon, button, text). */
  children: ReactNode;
  className?: string;
}

/**
 * Pure-CSS tooltip atom (axis-binding-ui spec R5 — "Keyboard-only conflict
 *  access"): hover AND focus-visible reveal, no portal, no JS state. The
 *  trigger exposes the copy through `aria-describedby` pointing at the sr-only
 *  duplicate (role="tooltip"), so assistive tech reads it regardless of the
 *  CSS reveal state; the visible bubble is an aria-hidden visual duplicate —
 *  the same pattern as the SectionCards status-dot tooltip.
 */
export function Tooltip({ id, content, children, className }: TooltipProps) {
  return (
    <span className={cn("group relative inline-flex", className)}>
      <span
        aria-describedby={id}
        tabIndex={0}
        className="inline-flex focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
      >
        {children}
      </span>
      <span
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-full z-20 mt-1.5 w-max max-w-xs -translate-x-1/2 rounded-md border border-edge bg-surface-raised px-2 py-1 text-xs text-primary opacity-0 shadow-lg transition-opacity duration-75 group-hover:opacity-100 group-focus-within:opacity-100"
      >
        {content}
      </span>
      <span id={id} role="tooltip" className="sr-only">
        {content}
      </span>
    </span>
  );
}