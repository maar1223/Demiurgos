import { useEffect, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { createWorld } from "@/api/onboarding";
import { ApiError, type WorldCreateResult, type WorldInfo } from "@/api/types";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { TFunction } from "@/i18n/messages";

interface CreateWorldModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (world: WorldInfo) => void;
}

/**
 * The 401 guidance matching Onboarding's fail-closed auth hint: creation is a
 * gated write, so a missing session surfaces the exact remediation instead of
 * retrying.
 */
function authHint(error: unknown, t: TFunction): string | null {
  if (error instanceof ApiError && error.status === 401) {
    return t("common.sessionExpired");
  }
  return null;
}

/** Projection of the create response into the selector's WorldInfo shape. */
function toWorldInfo(result: WorldCreateResult): WorldInfo {
  return {
    name: result.name,
    path: result.path ?? "",
    lore_count: 0,
    character_count: 0,
    reference_count: 0,
  };
}

/**
 * Modal form for creating an additional world without re-entering onboarding
 * (`+ Nuevo mundo` entry in WorldSelector). Overlay pattern mirrors
 * ImportImageModal/ConfirmDialog (fixed inset-0 z-50, role dialog, aria-modal,
 * Escape/overlay dismissal) plus autofocus and a minimal local Tab/Shift+Tab
 * focus trap — no focus-trap dependency.
 *
 * Lifecycle: client validation (empty/whitespace name) never calls the API;
 * `created`/`already_exists` deliver the world via `onCreated` and close;
 * `collision`/`invalid_name`/`io_error` stay inline and keep the dialog open;
 * HTTP 401 closes and surfaces the auth hint without retrying.
 */
export function CreateWorldModal({ isOpen, onClose, onCreated }: CreateWorldModalProps) {
  const { t } = useAppLanguage();
  const [name, setName] = useState("");
  const [loreSkeleton, setLoreSkeleton] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Reset the form and autofocus each time the dialog opens.
  useEffect(() => {
    if (!isOpen) return;
    setName("");
    setLoreSkeleton(false);
    setError(null);
    setBusy(false);
    inputRef.current?.focus();
  }, [isOpen]);

  // Escape closes; Tab/Shift+Tab cycle through the dialog's focusables only.
  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusables = dialog.querySelectorAll<HTMLElement>(
        "input, button, [href], select, textarea, [tabindex]:not([tabindex='-1'])",
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === dialog)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [isOpen, onClose]);

  const handleOverlayClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) onClose();
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError(t("worlds.create.emptyName"));
      return;
    }
    setBusy(true);
    setError(null);
    void createWorld(trimmed, loreSkeleton)
      .then((result) => {
        setBusy(false);
        if (
          result.kind === "collision" ||
          result.kind === "invalid_name" ||
          result.kind === "io_error"
        ) {
          setError(result.message);
          return;
        }
        onCreated(toWorldInfo(result));
        onClose();
      })
      .catch((cause: unknown) => {
        setBusy(false);
        const hint = authHint(cause, t);
        if (hint) {
          setError(hint);
          onClose();
          return;
        }
        setError(
          cause instanceof Error
            ? cause.message
            : t("worlds.create.failed"),
        );
      });
  };

  if (!isOpen) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-surface/80 backdrop-blur-sm"
      onClick={handleOverlayClick}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-world-title"
        className="mx-4 w-full max-w-md rounded-xl border border-edge bg-surface-raised shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-edge px-6 py-4">
          <h2
            id="create-world-title"
            className="font-heading text-h4 text-primary"
          >
            {t("worlds.create.title")}
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

        {/* Form */}
        <form onSubmit={handleSubmit} noValidate>
          <div className="flex flex-col gap-4 px-6 py-4">
            <label
              htmlFor="create-world-name"
              className="flex flex-col gap-1 text-small text-primary"
            >
              {t("worlds.create.nameLabel")}
              <input
                id="create-world-name"
                ref={inputRef}
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  if (error) setError(null);
                }}
                placeholder={t("worlds.create.namePlaceholder")}
                className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
              />
            </label>

            <label className="flex items-center gap-2 text-small text-primary">
              <input
                type="checkbox"
                checked={loreSkeleton}
                onChange={(event) => setLoreSkeleton(event.target.checked)}
                className="h-4 w-4"
              />
              {t("worlds.create.loreSkeleton")}
            </label>

            {error && (
              <div
                role="alert"
                className="rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-small text-status-error"
              >
                {error}
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-2 border-t border-edge px-6 py-4">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onClose}
              disabled={busy}
            >
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="primary" size="sm" disabled={busy}>
              {busy ? t("worlds.create.creating") : t("worlds.create.submit")}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  );
}