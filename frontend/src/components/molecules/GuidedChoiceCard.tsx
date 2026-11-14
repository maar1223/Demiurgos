import type { ReactNode } from "react";

export interface GuidedChoiceOption {
  label: string;
  onClick: () => void;
  /** The recommended/default option, rendered as the primary action. */
  primary?: boolean;
  disabled?: boolean;
}

interface GuidedChoiceCardProps {
  title: string;
  body?: ReactNode;
  options: GuidedChoiceOption[];
  /** Long labels read better stacked; short ones fit in a row. */
  stacked?: boolean;
  /**
   * `action` (default) tints the panel for a pending confirmation. `neutral`
   * keeps equal-rank decisions (the creation path) on the surface, so no
   * option reads as more important than the other.
   */
  variant?: "action" | "neutral";
}

/**
 * The assistant is waiting on a decision the server owns (creation path,
 * confirmation). One card, one visual language: real buttons, never a question
 * that expects the author to type a token.
 */
export function GuidedChoiceCard({
  title,
  body,
  options,
  stacked = false,
  variant = "action",
}: GuidedChoiceCardProps) {
  return (
    <section
      aria-label={title}
      className={
        variant === "neutral"
          ? "rounded-lg border border-edge bg-surface-raised px-3 py-3 text-sm text-primary"
          : "rounded-lg border border-action/40 bg-action/10 px-3 py-3 text-sm text-primary"
      }
    >
      <h3 className="font-medium">{title}</h3>
      {body ? (
        <p className="mt-1 text-xs leading-relaxed text-muted">{body}</p>
      ) : null}
      <div
        className={
          stacked ? "mt-3 flex flex-col gap-2" : "mt-3 flex flex-wrap gap-2"
        }
      >
        {options.map((option) => (
          <button
            key={option.label}
            type="button"
            onClick={option.onClick}
            disabled={option.disabled}
            className={
              option.primary
                ? "rounded-md bg-action px-3 py-1.5 text-xs font-medium text-action-text transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
                : "rounded-md border border-action/40 bg-surface px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:border-action hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50"
            }
          >
            {option.label}
          </button>
        ))}
      </div>
    </section>
  );
}
