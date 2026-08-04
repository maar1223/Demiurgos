import { useEffect } from "react";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel?: string;
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
 * about to be moved to the trash.
 */
export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Confirmar",
  isBusy = false,
  error = null,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  // Close on Escape key
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-cripta/80 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="mx-4 w-full max-w-md rounded-xl border border-filio bg-madero shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-filio px-6 py-4">
          <h2
            id="confirm-dialog-title"
            className="font-heading text-h4 text-pergamino"
          >
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-plata transition-colors hover:bg-piedra hover:text-pergamino"
            aria-label="Cerrar"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4">
          <p className="text-body text-pergamino">{message}</p>
          {error && (
            <div
              role="alert"
              className="mt-3 rounded-lg border border-sangre/30 bg-sangre/10 px-3 py-2 text-small text-sangre"
            >
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-filio px-6 py-4">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={isBusy}>
            Cancelar
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={onConfirm}
            disabled={isBusy}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
