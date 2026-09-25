import { useEffect, useState } from "react";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { deleteWorld } from "@/api/worlds";
import type { ApiError, WorldInfo } from "@/api/types";
import { getErrorMessage } from "@/lib/utils";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { MessageKey } from "@/i18n/messages";

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
const SCOPE_LABELS: readonly MessageKey[] = [
  "worlds.delete.scope1",
  "worlds.delete.scope2",
  "worlds.delete.scope3",
];

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
  const { t } = useAppLanguage();
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
            {t("worlds.delete.title")}
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
          {step === 1 && (
            <div className="flex flex-col gap-3">
              <p className="text-small text-muted">{t("worlds.delete.intro")}</p>
              <p className="font-mono text-body text-primary">{world.name}</p>
              <div className="flex flex-wrap gap-2">
                <Badge>{t("worlds.count.lore", { count: world.lore_count })}</Badge>
                <Badge>{t("worlds.count.personajes", { count: world.character_count })}</Badge>
              </div>
              <div className="rounded-lg border border-action/30 bg-action/10 px-3 py-2 text-small text-action">
                {t("worlds.delete.warning")}
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="flex flex-col gap-3">
              <p className="text-small text-muted">
                {t("worlds.delete.scopeIntro")}
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
                  {t(label)}
                </label>
              ))}
            </div>
          )}

          {step === 3 && (
            <div className="flex flex-col gap-3">
              <p className="text-small text-muted">
                {t("worlds.delete.confirmIntro")}
              </p>
              <p className="font-mono text-body text-primary">{world.name}</p>
              <input
                type="text"
                value={typedName}
                onChange={(e) => setTypedName(e.target.value)}
                placeholder={world.name}
                aria-label={t("worlds.delete.nameAria")}
                className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary placeholder:text-muted focus:border-action focus:outline-none"
              />
              {typedName && !nameMatches && (
                <p className="text-small text-status-error">{t("worlds.delete.mismatch")}</p>
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
              {t("common.back")}
            </Button>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onClose} disabled={isBusy}>
              {t("common.cancel")}
            </Button>
            {step === 1 && (
              <Button variant="primary" size="sm" onClick={() => setStep(2)}>
                {t("worlds.delete.understand")}
              </Button>
            )}
            {step === 2 && (
              <Button variant="primary" size="sm" onClick={() => setStep(3)} disabled={!allScopesChecked}>
                {t("common.continue")}
              </Button>
            )}
            {step === 3 && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => void handleConfirmDelete()}
                disabled={!nameMatches || isBusy}
              >
                {isBusy ? t("worlds.delete.deleting") : t("worlds.delete.confirm")}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}