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
    "bg-llamita text-cripta hover:bg-llama-alta active:bg-llamita/90 focus-visible:ring-llamita/50",
  secondary:
    "bg-piedra text-pergamino hover:bg-filio active:bg-filio/80 focus-visible:ring-filio/50",
  ghost:
    "bg-transparent text-pergamino hover:bg-piedra active:bg-filio/30 focus-visible:ring-filio/50",
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
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-cripta",
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
