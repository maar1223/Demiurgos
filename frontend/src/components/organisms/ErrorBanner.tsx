import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
  className?: string;
}

/**
 * Error banner with message and optional retry button.
 */
export function ErrorBanner({ message, onRetry, className }: ErrorBannerProps) {
  return (
    <div
      className={`flex items-start gap-3 rounded-lg border border-status-error/30 bg-status-error/10 p-4 ${className ?? ""}`}
      role="alert"
    >
      <div className="mt-0.5 shrink-0 text-status-error">
        <Icon name="error" size={20} />
      </div>
      <div className="flex-1">
        <p className="text-small text-status-error">{message}</p>
      </div>
      {onRetry && (
        <Button variant="ghost" size="sm" onClick={onRetry}>
          Reintentar
        </Button>
      )}
    </div>
  );
}
