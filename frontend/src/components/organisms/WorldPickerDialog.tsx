import { useEffect } from "react";
import { createPortal } from "react-dom";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import type { WorldInfo } from "@/api/types";

interface WorldPickerDialogProps {
  /** The world that no longer exists (shown in the message). */
  missingWorld?: string;
  /** Worlds that DO exist and can be selected. */
  available: WorldInfo[];
  onPick: (name: string) => void;
  onCreate: () => void;
  onClose: () => void;
  /** Optional footer escape action (e.g. "Volver al inicio" / "Cancelar"). */
  footerAction?: { label: string; onAction: () => void };
}

/**
 * Centered overlay dialog (ConfirmDialog shell) listing the surviving worlds so
 * the user can jump straight into one, plus a "+ Nuevo mundo" option. Used both
 * when a world-scoped route points at a missing world (WorldNotFound) and when
 * the user deletes the currently-selected world from the Profile → Mundos tab,
 * so the selector is never left pointing at a world that no longer exists.
 */
export function WorldPickerDialog({
  missingWorld,
  available,
  onPick,
  onCreate,
  onClose,
  footerAction,
}: WorldPickerDialogProps) {
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
        aria-labelledby="world-picker-title"
      >
        <div className="flex items-center justify-between border-b border-edge px-6 py-4">
          <h2
            id="world-picker-title"
            className="font-heading text-h4 text-primary"
          >
            Elegí un mundo
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary"
            aria-label="Cerrar"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        <div className="px-6 py-4">
          {missingWorld ? (
            <p className="text-body text-primary">
              El mundo «{missingWorld}» ya no existe.
            </p>
          ) : (
            <p className="text-body text-primary">Elegí tu próximo mundo.</p>
          )}
          <p className="mt-1 text-small text-muted">
            Seleccioná otro mundo para continuar o creá uno nuevo.
          </p>

          <div className="mt-4 flex flex-col gap-2">
            {available.length > 0 ? (
              available.map((w) => (
                <button
                  key={w.name}
                  type="button"
                  onClick={() => onPick(w.name)}
                  className="flex items-center gap-2 rounded-lg border border-edge bg-surface px-3 py-2 text-left text-small text-primary transition-colors hover:border-action/40 hover:bg-surface-hover"
                >
                  <Icon name="world" size={14} />
                  {w.name}
                </button>
              ))
            ) : (
              <p className="text-small text-muted">
                No hay otros mundos creados todavía.
              </p>
            )}
            <button
              type="button"
              onClick={onCreate}
              className="flex items-center gap-2 rounded-lg border border-dashed border-action/40 px-3 py-2 text-left text-small text-action transition-colors hover:bg-action/10"
            >
              <Icon name="plus" size={14} />
              Nuevo mundo
            </button>
          </div>
        </div>

        {footerAction && (
          <div className="flex items-center justify-end gap-2 border-t border-edge px-6 py-4">
            <Button variant="ghost" size="sm" onClick={footerAction.onAction}>
              {footerAction.label}
            </Button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
