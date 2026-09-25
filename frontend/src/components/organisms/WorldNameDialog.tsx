import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { useAppLanguage } from "@/hooks/useAppLanguage";

interface WorldNameDialogProps {
  title: string;
  message: string;
  initialValue?: string;
  confirmLabel?: string;
  confirmBusy?: boolean;
  error?: string | null;
  onConfirm: (name: string) => void;
  onClose: () => void;
}

/**
 * Centered dialog (ConfirmDialog shell) that asks for a world name. Used for
 * renaming an active world and for "restore as" (conflict resolution), so the
 * UX looks the same everywhere. Local empty/whitespace validation never calls
 * the API.
 */
export function WorldNameDialog({
  title,
  message,
  initialValue = "",
  confirmLabel,
  confirmBusy = false,
  error = null,
  onConfirm,
  onClose,
}: WorldNameDialogProps) {
  const { t } = useAppLanguage();
  const [name, setName] = useState(initialValue);
  const inputRef = useRef<HTMLInputElement>(null);
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    if (!inputRef.current) return;
    inputRef.current.focus();
  }, []);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const trimmed = name.trim();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!trimmed) {
      setInvalid(true);
      return;
    }
    onConfirm(trimmed);
  };

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
        aria-labelledby="world-name-dialog-title"
      >
        <div className="flex items-center justify-between border-b border-edge px-6 py-4">
          <h2
            id="world-name-dialog-title"
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

        <form onSubmit={handleSubmit} noValidate>
          <div className="flex flex-col gap-4 px-6 py-4">
            <p className="text-body text-muted">{message}</p>
            <label className="flex flex-col gap-1 text-small text-primary">
              {t("worlds.name.label")}
              <input
                ref={inputRef}
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  if (invalid) setInvalid(false);
                  if (error) return; // server-side error shown below
                }}
                placeholder={t("worlds.name.placeholder")}
                aria-invalid={invalid || Boolean(error)}
                className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
              />
            </label>
            {(invalid || error) && (
              <div
                role="alert"
                className="rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-small text-status-error"
              >
                {invalid ? t("worlds.name.empty") : error}
              </div>
            )}
          </div>
          <div className="flex items-center justify-end gap-2 border-t border-edge px-6 py-4">
            <Button type="button" variant="ghost" size="sm" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="primary" size="sm" disabled={confirmBusy}>
              {confirmBusy ? t("worlds.name.saving") : (confirmLabel ?? t("common.confirm"))}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  );
}
