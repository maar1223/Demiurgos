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
}

/**
 * The assistant is waiting on a decision the server owns (creation path,
 * confirmation). One card, one visual language: an action-tinted panel with
 * real buttons, never a question that expects the author to type a token.
 */
export function GuidedChoiceCard({
  title,
  body,
  options,
  stacked = false,
}: GuidedChoiceCardProps) {
  return (
    <section
      aria-label={title}
      className="rounded-lg border border-action/40 bg-action/10 px-3 py-3 text-sm text-primary"
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
                : "rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition-colors hover:border-action/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
            }
          >
            {option.label}
          </button>
        ))}
      </div>
    </section>
  );
}
