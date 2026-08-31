import { type ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const variantStyles: Record<Variant, string> = {
  primary:
    "bg-action text-action-text hover:bg-action-hover active:bg-action/90 focus-visible:ring-action/50",
  secondary:
    "bg-surface-raised text-primary hover:bg-surface-hover active:bg-surface-raised/80 focus-visible:ring-edge/50",
  ghost:
    "bg-transparent text-primary hover:bg-surface-hover active:bg-surface-raised/30 focus-visible:ring-edge/50",
};

const sizeStyles: Record<Size, string> = {
  sm: "px-3 py-1.5 text-small",
  md: "px-4 py-2 text-body",
  lg: "px-6 py-3 text-h4",
};

/**
 * Demiurgos-styled button with primary/secondary/ghost variants.
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
          "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors",
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
