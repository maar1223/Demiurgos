import { useEffect, useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { cn } from "@/lib/utils";
import {
  MOVE_DESTINATION_SECTIONS,
  MOVE_DESTINATION_LABELS,
  type MoveDestinationSection,
} from "@/lib/constants";
import { useAppLanguage } from "@/hooks/useAppLanguage";

interface MoveToSectionDialogProps {
  /** The node being moved: section is where it lives, path is section-relative. */
  source: { section: string; path: string };
  /** Called with the chosen destination section — the caller builds the
   *  mundo-relative destination path (`{section}/{path}`). */
  onConfirm: (destSection: MoveDestinationSection) => void;
  onClose: () => void;
}

/**
 * "Mover a sección…" dialog (card ⋯ menu flow): pick a destination section
 * of the world workshop and confirm.
 *
 * Deliberately different from the MoveModal: it lists sections, not folders
 * (no tree fetch), warns that a section change is irreversible (the backend
 * has no undo for cross-section moves), and keeps Confirm disabled until a
 * section is chosen. Overlay pattern mirrors ConfirmDialog (fixed inset-0
 * z-50, role dialog, aria-modal, Escape/overlay click).
 */
export function MoveToSectionDialog({
  source,
  onConfirm,
  onClose,
}: MoveToSectionDialogProps) {
  const { t } = useAppLanguage();
  const [selected, setSelected] = useState<MoveDestinationSection | null>(
    null,
  );
  const destinations = MOVE_DESTINATION_SECTIONS.filter(
    (s) => s !== source.section,
  );

  // Close on Escape key
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const nodeName = source.path.split("/").pop() ?? source.path;

  return (
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
        aria-labelledby="move-section-dialog-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-edge px-6 py-4">
          <h2
            id="move-section-dialog-title"
            className="font-heading text-h4 text-primary"
          >
            {t("move.section.title")}
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
          <p className="text-body text-primary">
            <span className="font-medium text-action">{nodeName}</span>{" "}
            {t("move.section.body")}
          </p>

          {/* Irreversibility warning — cross-section moves have no undo */}
          <div
            role="alert"
            className="mt-3 flex items-start gap-2 rounded-lg border border-status-error/30 bg-status-error/10 p-3 text-small text-status-error"
          >
            <Icon name="error" size={16} className="mt-0.5 shrink-0" />
            <span>{t("move.section.warning")}</span>
          </div>

          {/* Destination sections — every workshop section except the current */}
          <div
            role="radiogroup"
            aria-label={t("move.destSectionAria")}
            className="mt-4 flex flex-col gap-2"
          >
            {destinations.map((sec) => {
              const isSelected = selected === sec;
              return (
                <button
                  key={sec}
                  type="button"
                  role="radio"
                  aria-checked={isSelected}
                  onClick={() => setSelected(sec)}
                  className={cn(
                    "flex items-center gap-2 rounded-lg border px-3 py-2.5 text-left text-body transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50",
                    isSelected
                      ? "border-action bg-surface-raised text-primary"
                      : "border-edge bg-surface text-muted hover:border-action/40 hover:text-primary",
                  )}
                >
                  <Icon
                    name="folder"
                    size={16}
                    className={isSelected ? "text-action" : "text-muted"}
                  />
                  <span>{t(MOVE_DESTINATION_LABELS[sec])}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-edge px-6 py-4">
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!selected}
            onClick={() => selected && onConfirm(selected)}
          >
            {t("common.confirm")}
          </Button>
        </div>
      </div>
    </div>
  );
}
