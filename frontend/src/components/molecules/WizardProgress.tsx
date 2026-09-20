import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

export type WizardStepState = "done" | "current" | "todo";

export interface WizardProgressStep {
  id: string;
  label: string;
}

export interface WizardProgressProps {
  steps: readonly WizardProgressStep[];
  /** Zero-based index of the current step. */
  current: number;
  /** Landmark name. Default "Progreso de la configuración". */
  ariaLabel?: string;
  /**
   * Enables revisiting. Only indices where `canSelect` returns true are
   * rendered as clickable buttons; the rest stay static. Omit `onSelect`
   * entirely and the whole indicator is non-interactive (the idea-capture
   * behaviour).
   */
  onSelect?: (index: number) => void;
  /**
   * Per-step selector for revisiting. Defaults to every step when omitted.
   */
  canSelect?: (index: number) => boolean;
  /**
   * Explicit per-step states, taking precedence over the derived
   * `current`-relative state when provided. Lets a wizard whose completion is
   * real data (not "how far the user walked") mark a revisited step honestly
   * as `done`. Omit it and the state is derived from `current` exactly as
   * before.
   */
  states?: readonly WizardStepState[];
  className?: string;
}

/**
 * Numbered wizard progress indicator shared by the idea-capture and assistant
 * configuration wizards. Mirrors the idea-capture rendering: a circle showing a
 * check when done and the 1-based number otherwise, a state-tinted label,
 * painted connectors between steps, and `aria-current="step"` on the active
 * step.
 */
export function WizardProgress({
  steps,
  current,
  ariaLabel = "Progreso de la configuración",
  onSelect,
  canSelect,
  states,
  className,
}: WizardProgressProps) {
  return (
    <nav
      aria-label={ariaLabel}
      className={cn("flex items-center gap-1", className)}
    >
      {steps.map((entry, index) => {
        const state: WizardStepState =
          states?.[index] ??
          (index < current ? "done" : index === current ? "current" : "todo");
        const columnClassName = cn(
          "flex min-w-0 flex-1 flex-col items-center gap-1 text-center",
          index > 0 && "ml-1",
        );
        const ariaCurrent = index === current ? "step" : undefined;
        const selectable = onSelect !== undefined && (canSelect?.(index) ?? true);

        const content = (
          <>
            <span
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-medium",
                state === "done" &&
                  "border-status-success bg-status-success/15 text-status-success",
                state === "current" && "border-action bg-action/15 text-action",
                state === "todo" && "border-edge bg-surface-raised text-muted",
              )}
            >
              {state === "done" ? <Icon name="check" size={14} /> : index + 1}
            </span>
            <span
              className={cn(
                "text-xs leading-tight",
                state === "current"
                  ? "text-primary"
                  : state === "done"
                    ? "text-status-success"
                    : "text-muted",
              )}
            >
              {entry.label}
            </span>
          </>
        );

        return (
          <div key={entry.id} className="flex flex-1 items-center gap-1">
            {selectable ? (
              // Bare <button> on purpose: the Button atom defaults to the primary
              // variant and this indicator lives in the Conexiones primary-action
              // budget. The extra resets reproduce the static column exactly.
              // Non-selectable steps stay static so they are not focusable and
              // never read as actionable.
              <button
                type="button"
                aria-current={ariaCurrent}
                onClick={() => onSelect?.(index)}
                className={cn(
                  columnClassName,
                  "cursor-pointer appearance-none border-0 bg-transparent p-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50",
                )}
              >
                {content}
              </button>
            ) : (
              <div className={columnClassName} aria-current={ariaCurrent}>
                {content}
              </div>
            )}
            {index < steps.length - 1 && (
              <div
                aria-hidden="true"
                className={cn(
                  "mb-5 h-px w-3 shrink-0",
                  // A connector is painted once the step before it is done, so
                  // explicit states (not the walked index) drive the trail too.
                  state === "done" ? "bg-status-success/50" : "bg-surface-raised",
                )}
              />
            )}
          </div>
        );
      })}
    </nav>
  );
}
