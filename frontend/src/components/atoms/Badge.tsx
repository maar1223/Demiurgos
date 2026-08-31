import { cn } from "@/lib/utils";

type BadgeVariant = "default" | "success" | "error" | "warning" | "info";

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: "bg-surface-raised text-primary border-edge",
  success: "bg-status-success/20 text-status-success border-status-success/30",
  error: "bg-status-error/20 text-status-error border-status-error/30",
  warning: "bg-action/20 text-action border-action/30",
  info: "bg-icon-muted/20 text-icon-muted border-icon-muted/30",
};

/**
 * Small badge/label for file counts, status indicators, etc.
 */
export function Badge({
  children,
  variant = "default",
  className,
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium",
        variantStyles[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}
