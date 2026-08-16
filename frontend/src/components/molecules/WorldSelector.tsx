import { useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { getCurrentWorld, setCurrentWorld } from "@/lib/currentWorld";
import type { WorldInfo } from "@/api/types";

interface WorldSelectorProps {
  worlds: WorldInfo[];
  currentWorld?: string;
  onWorldChange?: (world: string) => void;
}

/**
 * Dropdown for selecting the active working world.
 *
 * Selection never navigates. When the picked world differs from the current
 * one, a ConfirmDialog asks for confirmation: Cancel keeps the previous
 * world; Confirm persists the new active world (localStorage) and calls
 * `onWorldChange` when provided. Same-tab subscribers are notified through
 * the shared currentWorld util, so the Navbar label updates in place.
 */
export function WorldSelector({
  worlds,
  currentWorld,
  onWorldChange,
}: WorldSelectorProps) {
  const [open, setOpen] = useState(false);
  const [pendingWorld, setPendingWorld] = useState<string | null>(null);

  const effectiveCurrent = currentWorld ?? getCurrentWorld() ?? undefined;

  const handleSelect = (world: string) => {
    setOpen(false);
    if (world === effectiveCurrent) return;
    setPendingWorld(world);
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
          className="flex items-center gap-1.5 rounded-lg border border-filio bg-piedra px-3 py-1.5 text-small text-pergamino transition-colors hover:bg-filio"
          aria-expanded={open}
          aria-haspopup="listbox"
        >
          <Icon name="world" size={14} />
          <span className="max-w-[100px] truncate">
            {effectiveCurrent ?? "Mundos"}
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
            <div className="absolute right-0 z-20 mt-1 w-48 rounded-lg border border-filio bg-madero py-1 shadow-xl">
              {worlds.length === 0 ? (
                <span className="block px-3 py-2 text-small text-sombra">
                  No hay mundos
                </span>
              ) : (
                worlds.map((w) => (
                  <button
                    key={w.name}
                    type="button"
                    onClick={() => handleSelect(w.name)}
                    role="option"
                    aria-selected={w.name === effectiveCurrent}
                    className={`block w-full px-3 py-2 text-left text-small transition-colors hover:bg-piedra ${
                      w.name === effectiveCurrent
                        ? "text-llamita"
                        : "text-pergamino"
                    }`}
                  >
                    {w.name}
                  </button>
                ))
              )}
            </div>
          </>
        )}
      </div>

      {pendingWorld && (
        <ConfirmDialog
          title="Cambiar mundo activo"
          message={`¿Querés cambiar el mundo activo a «${pendingWorld}»?`}
          confirmLabel="Cambiar"
          onConfirm={confirmChange}
          onClose={() => setPendingWorld(null)}
        />
      )}
    </>
  );
}