import { useEffect, useState } from "react";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { deleteWorld } from "@/api/worlds";
import type { ApiError, WorldInfo } from "@/api/types";
import { getErrorMessage } from "@/lib/utils";

type Step = 1 | 2 | 3;

interface DeleteWorldModalProps {
  /** The world targeted for deletion; `null` keeps the modal closed. */
  world: WorldInfo | null;
  /** Called after a successful delete — parent refreshes worlds + trash. */
  onDeleted: () => void;
  /** Closes the modal — cancels the current step. */
  onClose: () => void;
}

/** Step 2 — the three scope acknowledgements (REQ-009). */
const SCOPE_LABELS = [
  "Entiendo que se elimina TODO el contenido de este mundo.",
  "Sé que el mundo queda recuperable durante 30 días en la papelera y luego se elimina permanentemente.",
  "Acepto que los datos asociados (grafo, importaciones, sesiones guiadas e ideas) se ocultan y se limpian al purgar.",
] as const;

/**
 * 3-step world delete confirmation (REQ-009):
 * 1. Consequence warning — world name, ficha counts, 30-day recycle-bin notice.
 * 2. Three scope checkboxes — "Continuar" only enables with all three checked.
 * 3. Case-insensitive name gate — "Borrar definitivamente" only enables when
 *    the typed name matches the world name exactly (case-insensitive).
 *
 * On confirm calls `deleteWorld(name, confirmName)`; the typed value is sent
 * as `confirm_name` exactly as written (the backend compares case-insensitively).
 */
export function DeleteWorldModal({ world, onDeleted, onClose }: DeleteWorldModalProps) {
  const [step, setStep] = useState<Step>(1);
  const [checked, setChecked] = useState<[boolean, boolean, boolean]>([false, false, false]);
  const [typedName, setTypedName] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset the whole flow every time the modal opens for a (new) world.
  useEffect(() => {
    setStep(1);
    setChecked([false, false, false]);
    setTypedName("");
    setError(null);
    setIsBusy(false);
  }, [world?.name]);

  // Escape closes the modal — cancel at any step.
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  if (!world) return null;

  const allScopesChecked = checked.every(Boolean);
  const nameMatches = typedName.toUpperCase() === world.name.toUpperCase();

  const toggleScope = (index: 0 | 1 | 2) => {
    setChecked((prev) =>
      prev.map((value, i) => (i === index ? !value : value)) as [boolean, boolean, boolean],
    );
  };

  const handleConfirmDelete = async () => {
    setIsBusy(true);
    setError(null);
    try {
      await deleteWorld(world.name, typedName);
      onDeleted();
    } catch (err) {
      const apiErr = err as ApiError;
      setError(getErrorMessage(apiErr.status, apiErr.detail));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-surface/80 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="mx-4 w-full max-w-lg rounded-xl border border-edge bg-surface-raised shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-world-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-edge px-6 py-4">
          <h2
            id="delete-world-title"
            className="flex items-center gap-2 font-heading text-h4 text-status-error"
          >
            <Icon name="trash" size={20} />
            Eliminar mundo
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

        {/* Body */}
        <div className="px-6 py-4">
          {step === 1 && (
            <div className="flex flex-col gap-3">
              <p className="text-small text-muted">Estás por eliminar el mundo:</p>
              <p className="font-mono text-body text-primary">{world.name}</p>
              <div className="flex flex-wrap gap-2">
                <Badge>Lore {world.lore_count}</Badge>
                <Badge>Personajes {world.character_count}</Badge>
              </div>
              <div className="rounded-lg border border-action/30 bg-action/10 px-3 py-2 text-small text-action">
                El mundo se moverá a la papelera y quedará recuperable durante 30 días. Pasado ese
                plazo se eliminará permanentemente junto con sus datos asociados.
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="flex flex-col gap-3">
              <p className="text-small text-muted">
                Para continuar, confirmá el alcance de la eliminación:
              </p>
              {SCOPE_LABELS.map((label, index) => (
                <label
                  key={label}
                  className="flex items-start gap-3 rounded-lg border border-edge bg-surface/50 px-3 py-2 text-small text-primary"
                >
                  <input
                    type="checkbox"
                    checked={checked[index]}
                    onChange={() => toggleScope(index as 0 | 1 | 2)}
                    className="mt-0.5"
                  />
                  {label}
                </label>
              ))}
            </div>
          )}

          {step === 3 && (
            <div className="flex flex-col gap-3">
              <p className="text-small text-muted">
                Escribí el nombre del mundo con su ortografía exacta para confirmar:
              </p>
              <p className="font-mono text-body text-primary">{world.name}</p>
              <input
                type="text"
                value={typedName}
                onChange={(e) => setTypedName(e.target.value)}
                placeholder={world.name}
                aria-label="Nombre del mundo a eliminar"
                className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary placeholder:text-muted focus:border-action focus:outline-none"
              />
              {typedName && !nameMatches && (
                <p className="text-small text-status-error">El nombre no coincide.</p>
              )}
            </div>
          )}

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
        <div className="flex items-center justify-between gap-2 border-t border-edge px-6 py-4">
          {step > 1 ? (
            <Button variant="ghost" size="sm" onClick={() => setStep((s) => (s - 1) as Step)} disabled={isBusy}>
              Atrás
            </Button>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onClose} disabled={isBusy}>
              Cancelar
            </Button>
            {step === 1 && (
              <Button variant="primary" size="sm" onClick={() => setStep(2)}>
                Entiendo, continuar
              </Button>
            )}
            {step === 2 && (
              <Button variant="primary" size="sm" onClick={() => setStep(3)} disabled={!allScopesChecked}>
                Continuar
              </Button>
            )}
            {step === 3 && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => void handleConfirmDelete()}
                disabled={!nameMatches || isBusy}
              >
                {isBusy ? "Eliminando…" : "Borrar definitivamente"}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}