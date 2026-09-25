import { useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { getCurrentWorld, setCurrentWorld } from "@/lib/currentWorld";
import type { WorldInfo } from "@/api/types";
import { useAppLanguage } from "@/hooks/useAppLanguage";

interface WorldSelectorProps {
  worlds: WorldInfo[];
  currentWorld?: string;
  onWorldChange?: (world: string) => void;
  /**
   * Optional callback fired when the user activates the bottom-of-dropdown
   * `+ Nuevo mundo` entry. Parents use it to render the
   * `CreateWorldModal`. The entry is only rendered when there is at least
   * one existing world (spec R9) — first-run onboarding owns the empty
   * path.
   */
  onRequestCreate?: () => void;
}

/**
 * Dropdown for selecting the active working world.
 *
 * Selection never navigates. When the picked world differs from the current
 * one, a ConfirmDialog asks for confirmation: Cancel keeps the previous
 * world; Confirm persists the new active world (localStorage) and calls
 * `onWorldChange` when provided. Same-tab subscribers are notified through
 * the shared currentWorld util, so the Navbar label updates in place.
 *
 * When `onRequestCreate` is provided AND `worlds.length > 0`, a divider
 * plus `+ Nuevo mundo` action appears at the bottom of the dropdown. The
 * action is a `menuitem` (never an `option`) and closes the dropdown
 * before invoking the callback, so the parent can mount the modal without
 * leaving the dropdown visible underneath.
 */
export function WorldSelector({
  worlds,
  currentWorld,
  onWorldChange,
  onRequestCreate,
}: WorldSelectorProps) {
  const { t } = useAppLanguage();
  const [open, setOpen] = useState(false);
  const [pendingWorld, setPendingWorld] = useState<string | null>(null);

  const effectiveCurrent = currentWorld ?? getCurrentWorld() ?? undefined;

  const handleSelect = (world: string) => {
    setOpen(false);
    if (world === effectiveCurrent) return;
    setPendingWorld(world);
  };

  const handleRequestCreate = () => {
    setOpen(false);
    onRequestCreate?.();
  };

  const confirmChange = () => {
    if (!pendingWorld) return;
    setCurrentWorld(pendingWorld);
    onWorldChange?.(pendingWorld);
    setPendingWorld(null);
  };

  return (
    <>
      <div className="relative">
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          className="flex items-center gap-1.5 rounded-lg border border-edge bg-surface-raised px-3 py-1.5 text-small text-primary transition-colors hover:bg-surface-hover"
          aria-expanded={open}
          aria-haspopup="listbox"
        >
          <Icon name="world" size={14} />
          <span className="max-w-[100px] truncate">
            {effectiveCurrent ?? t("worldSelector.fallback")}
          </span>
          <Icon
            name="chevron-down"
            size={12}
            className={`transition-transform ${open ? "rotate-180" : ""}`}
          />
        </button>

        {open && (
          <>
            <div
              className="fixed inset-0 z-10"
              onClick={() => setOpen(false)}
            />
            <div className="absolute right-0 z-20 mt-1 w-48 rounded-lg border border-edge bg-surface-raised py-1 shadow-xl">
              {worlds.length === 0 ? (
                <span className="block px-3 py-2 text-small text-muted">
                  {t("worldSelector.empty")}
                </span>
              ) : (
                <>
                  {worlds.map((w) => (
                    <button
                      key={w.name}
                      type="button"
                      onClick={() => handleSelect(w.name)}
                      role="option"
                      aria-selected={w.name === effectiveCurrent}
                      className={`block w-full px-3 py-2 text-left text-small transition-colors hover:bg-surface-hover ${
                        w.name === effectiveCurrent
                          ? "text-action"
                          : "text-primary"
                      }`}
                    >
                      {w.name}
                    </button>
                  ))}
                  {onRequestCreate && (
                    <>
                      <div
                        className="my-1 border-t border-edge"
                        role="separator"
                      />
                      <button
                        type="button"
                        role="menuitem"
                        onClick={handleRequestCreate}
                        className="block w-full px-3 py-2 text-left text-small text-action transition-colors hover:bg-surface-hover"
                      >
                        {t("worldSelector.create")}
                      </button>
                    </>
                  )}
                </>
              )}
            </div>
          </>
        )}
      </div>

      {pendingWorld && (
        <ConfirmDialog
          title={t("worldSelector.changeTitle")}
          message={t("worldSelector.changeMessage", { world: pendingWorld })}
          confirmLabel={t("worldSelector.changeConfirm")}
          onConfirm={confirmChange}
          onClose={() => setPendingWorld(null)}
        />
      )}
    </>
  );
}