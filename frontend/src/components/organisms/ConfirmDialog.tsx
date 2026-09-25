import { useEffect } from "react";
import { createPortal } from "react-dom";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { useAppLanguage } from "@/hooks/useAppLanguage";

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel?: string;
  /**
   * Variant for the confirm action. Defaults to `primary`, so every existing
   * caller keeps its current appearance. Destructive flows opt into `danger`
   * (REQ-PIA-08).
   */
  confirmVariant?: "primary" | "danger";
  isBusy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onClose: () => void;
}

/**
 * Minimal confirmation dialog (S12): shows the target name, Confirm aborts
 * nothing, Cancel aborts. Overlay pattern mirrors ImagePicker (fixed inset-0
 * z-50, role dialog, aria-modal, Escape/overlay click). Used for Delete —
 * the target name is shown in `message`, so the user always sees what is
 * about to be moved to the trash. Destructive callers pass
 * `confirmVariant="danger"` so the confirm action carries the danger
 * treatment instead of the primary style (REQ-PIA-08).
 */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  confirmVariant = "primary",
  isBusy = false,
  error = null,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const { t } = useAppLanguage();
  // Close on Escape key
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-surface/80 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="mx-4 w-full max-w-md rounded-xl border border-edge bg-surface-raised shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-edge px-6 py-4">
          <h2
            id="confirm-dialog-title"
            className="font-heading text-h4 text-primary"
          >
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary"
            aria-label={t("common.close")}
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4">
          <p className="text-body text-primary">{message}</p>
          {error && (
            <div
              role="alert"
              className="mt-3 rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-small text-status-error"
            >
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-edge px-6 py-4">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={isBusy}>
            {t("common.cancel")}
          </Button>
          <Button
            variant={confirmVariant}
            size="sm"
            onClick={onConfirm}
            disabled={isBusy}
          >
            {confirmLabel ?? t("common.confirm")}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
