import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "@/components/atoms/Icon";
import type { WorldInfo } from "@/api/types";

interface WorldSelectorProps {
  worlds: WorldInfo[];
  currentWorld?: string;
  onWorldChange?: (world: string) => void;
}

/**
 * Dropdown for selecting a world.
 *
 * Can be used standalone (inside Navbar or any other context).
 * When `onWorldChange` is provided, it's called on selection.
 * Falls back to navigation `/wiki/{world}/lore` when omitted.
 */
export function WorldSelector({
  worlds,
  currentWorld,
  onWorldChange,
}: WorldSelectorProps) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const handleSelect = (world: string) => {
    setOpen(false);
    if (onWorldChange) {
      onWorldChange(world);
    } else {
      navigate(`/wiki/${encodeURIComponent(world)}/lore`);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex items-center gap-1.5 rounded-lg border border-filio bg-piedra px-3 py-1.5 text-small text-pergamino transition-colors hover:bg-filio"
      >
        <Icon name="world" size={14} />
        <span className="max-w-[100px] truncate">
          {currentWorld ?? "Mundos"}
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
                  className={`block w-full px-3 py-2 text-left text-small transition-colors hover:bg-piedra ${
                    w.name === currentWorld ? "text-llamita" : "text-pergamino"
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
  );
}
