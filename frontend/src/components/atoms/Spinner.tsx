import { cn } from "@/lib/utils";
import { useAppLanguage } from "@/hooks/useAppLanguage";

interface SpinnerProps {
  size?: "sm" | "md" | "lg";
  className?: string;
}

const sizeStyles = {
  sm: "h-4 w-4 border-2",
  md: "h-8 w-8 border-2",
  lg: "h-12 w-12 border-3",
};

/**
 * Loading spinner using the icon-muted color from the Demiurgos palette.
 */
export function Spinner({ size = "md", className }: SpinnerProps) {
  const { t } = useAppLanguage();
  return (
    <div
      className={cn(
        "animate-spin rounded-full border-icon-muted/30 border-t-icon-muted",
        sizeStyles[size],
        className,
      )}
      role="status"
      aria-label={t("spinner.loading")}
    >
      <span className="sr-only">{t("spinner.loadingDots")}</span>
    </div>
  );
}
