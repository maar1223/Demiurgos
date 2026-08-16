import { Icon } from "@/components/atoms/Icon";
import type { IconName } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";

interface EmptyStateProps {
  icon?: IconName;
  message: string;
  actionLabel?: string;
  onAction?: () => void;
}

/**
 * Reusable empty state with icon, message, and optional action button.
 */
export function EmptyState({
  icon = "empty",
  message,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-piedra text-plata/50">
        <Icon name={icon} size={32} />
      </div>
      <p className="text-body text-tinta-desvaida">{message}</p>
      {actionLabel && onAction && (
        <Button variant="secondary" size="sm" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
