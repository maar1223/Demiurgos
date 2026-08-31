import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { useWorlds } from "@/hooks/useWorlds";
import { CreateWorldModal } from "@/components/organisms/CreateWorldModal";
import type { WorldInfo } from "@/api/types";

interface WorldNotFoundProps {
  /** The world name that was in the route but no longer exists. */
  mundo: string;
}

/**
 * Friendly dead-end replacement for "Mundo no encontrado".
 *
 * When a world-scoped route points at a world that no longer exists (e.g. it
 * was deleted), instead of leaving the user on a "Volver al inicio" dead-end a
 * centered dialog (same shell as the restart/system ConfirmDialog) pops up with
 * the worlds that DO exist so they can jump straight into one, plus an option
 * to create a new world. Dismissing the dialog reveals a plain inline "not
 * found" state with a home action as fallback.
 */
export function WorldNotFound({ mundo }: WorldNotFoundProps) {
  const navigate = useNavigate();
  const { worlds } = useWorlds();
  const [open, setOpen] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const available = worlds.filter((w) => w.name !== mundo);

  const goHome = () => navigate("/wiki");
  const pick = (name: string) =>
    navigate(`/wiki/${encodeURIComponent(name)}`);

  const handleCreated = (world: WorldInfo) => {
    setCreateOpen(false);
    setOpen(false);
    navigate(`/wiki/${encodeURIComponent(world.name)}`);
  };

  return (
    <>
      {/* Inline fallback behind the dialog (visible if the user dismisses it). */}
      <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-raised text-status-error">
          <Icon name="error" size={32} />
        </div>
        <h2 className="font-heading text-h3 text-primary">Mundo no encontrado</h2>
        <p className="max-w-md text-body text-muted">
          No existe un mundo llamado «{mundo}» (fue borrado o el nombre cambió).
        </p>
        <Button variant="secondary" onClick={goHome}>
          <Icon name="chevron-left" size={16} />
          Volver al inicio
        </Button>
      </div>

      {open && (
        <WorldPickerDialog
          mundo={mundo}
          available={available}
          onPick={pick}
          onCreate={() => setCreateOpen(true)}
          onClose={() => setOpen(false)}
          onGoHome={() => {
            setOpen(false);
            goHome();
          }}
        />
      )}

      <CreateWorldModal
        isOpen={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={handleCreated}
      />
    </>
  );
}

interface WorldPickerDialogProps {
  mundo: string;
  available: WorldInfo[];
  onPick: (name: string) => void;
  onCreate: () => void;
  onClose: () => void;
  onGoHome: () => void;
}

/** Centered overlay dialog (ConfirmDialog shell) offering the surviving worlds. */
function WorldPickerDialog({
  mundo,
  available,
  onPick,
  onCreate,
  onClose,
  onGoHome,
}: WorldPickerDialogProps) {
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const dialog = (
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
          <p className="text-body text-primary">
            El mundo «{mundo}» ya no existe.
          </p>
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

        <div className="flex items-center justify-end gap-2 border-t border-edge px-6 py-4">
          <Button variant="ghost" size="sm" onClick={onGoHome}>
            <Icon name="chevron-left" size={14} />
            Volver al inicio
          </Button>
        </div>
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
}
