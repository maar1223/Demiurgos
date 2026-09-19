import { type ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const variantStyles: Record<Variant, string> = {
  primary:
    "bg-action text-action-text hover:bg-action-hover active:bg-action/90 focus-visible:ring-action/50",
  secondary:
    "bg-surface-raised text-primary border border-edge hover:bg-surface-hover active:bg-surface-raised/80 focus-visible:ring-edge/50",
  ghost:
    "bg-surface-raised/40 text-primary border border-edge/70 hover:bg-surface-hover active:bg-surface-raised/30 focus-visible:ring-edge/50",
  danger:
    "bg-status-error text-action-text hover:bg-status-error/80 active:bg-status-error/90 focus-visible:ring-status-error/50",
};

const sizeStyles: Record<Size, string> = {
  sm: "px-3 py-1.5 text-small",
  md: "px-4 py-2 text-body",
  lg: "px-6 py-3 text-h4",
};

/**
 * Demiurgos-styled button with primary/secondary/ghost/danger variants.
 * `danger` is the destructive treatment (REQ-PIA-08); use it only for
 * irreversible actions.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "primary",
      size = "md",
      disabled,
      children,
      ...props
    },
    ref,
  ) => {
    return (
      <button
        ref={ref}
        disabled={disabled}
        className={cn(
          "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors shadow-sm",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-surface",
          "disabled:cursor-not-allowed disabled:opacity-50",
          variantStyles[variant],
          sizeStyles[size],
          className,
        )}
        {...props}
      >
        {children}
      </button>
    );
  },
);

Button.displayName = "Button";
