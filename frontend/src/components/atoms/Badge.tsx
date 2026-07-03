import { cn } from "@/lib/utils";

type BadgeVariant = "default" | "success" | "error" | "warning" | "info";

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: "bg-piedra text-pergamino border-filio",
  success: "bg-musgo/20 text-musgo border-musgo/30",
  error: "bg-sangre/20 text-sangre border-sangre/30",
  warning: "bg-llamita/20 text-llamita border-llamita/30",
  info: "bg-plata/20 text-plata border-plata/30",
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
