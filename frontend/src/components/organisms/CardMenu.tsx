import { useEffect, useRef } from "react";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";
import type { FileNode } from "@/api/types";

/**
 * Discriminated action union emitted by the card ⋯ menu (S7).
 * WikiEditor's onAction handler routes each action to its flow.
 */
export type CardAction =
  | "open"
  | "set-cover"
  | "rename"
  | "move"
  | "duplicate"
  | "trash";

interface CardMenuItem {
  action: CardAction;
  label: string;
}

/** File actions (S3): Open, Set cover…, Rename, Move to…, Duplicate, Delete. */
const FILE_ACTIONS: CardMenuItem[] = [
  { action: "open", label: "Abrir" },
  { action: "set-cover", label: "Establecer portada…" },
  { action: "rename", label: "Renombrar" },
  { action: "move", label: "Mover a…" },
  { action: "duplicate", label: "Duplicar" },
  { action: "trash", label: "Eliminar" },
];

/**
 * Folder actions (S3/S14): Open, Rename, Delete. Creation actions moved to
 * the file bar ("Nuevo archivo" / "Nueva carpeta") — a card menu suggests
 * "create inside this card", which is not how the directory scope works.
 */
const DIR_ACTIONS: CardMenuItem[] = [
  { action: "open", label: "Abrir" },
  { action: "rename", label: "Renombrar" },
  { action: "trash", label: "Eliminar" },
];

interface CardMenuProps {
  node: FileNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAction: (action: CardAction, node: FileNode) => void;
  /** S14: actions of the node whose request is in flight are disabled. */
  busyPath?: string | null;
  /** S34/S36: API error detail shown inline inside the open menu. */
  error?: string | null;
}

/**
 * Per-card ⋯ action menu (S2-S7, S14).
 *
 * Controlled by the parent (`open`/`onOpenChange`): SectionCards owns the
 * single-open state (S5). The ⋯ trigger and the menu are rendered inside a
 * `div.relative` wrapper as a SIBLING of the card button (never nested — S1)
 * and every click inside stopPropagation so the card's `onSelect` never
 * fires (S4).
 *
 * Closes on document `mousedown` outside (ignoring mousedowns inside the
 * wrapper so a menu click registers) and on Escape (S6).
 */
export function CardMenu({
  node,
  open,
  onOpenChange,
  onAction,
  busyPath,
  error,
}: CardMenuProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const actions = node.is_dir ? DIR_ACTIONS : FILE_ACTIONS;
  const disabled = busyPath === node.path;

  // Global close: document mousedown outside the wrapper + Escape (S6).
  useEffect(() => {
    if (!open) return;

    const handleMousedown = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        onOpenChange(false);
      }
    };
    const handleKeydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };

    document.addEventListener("mousedown", handleMousedown);
    document.addEventListener("keydown", handleKeydown);
    return () => {
      document.removeEventListener("mousedown", handleMousedown);
      document.removeEventListener("keydown", handleKeydown);
    };
  }, [open, onOpenChange]);

  const handleTriggerClick = (e: React.MouseEvent) => {
    // S4: the ⋯ click must never reach the card button underneath.
    e.stopPropagation();
    onOpenChange(!open);
  };

  const handleAction = (e: React.MouseEvent, action: CardAction) => {
    // S4: menu clicks never fire the card's onSelect.
    e.stopPropagation();
    onAction(action, node);
    onOpenChange(false);
  };

  return (
    <div ref={containerRef} className="relative inline-block">
      <button
        type="button"
        aria-label={`Acciones de ${node.name}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={handleTriggerClick}
        className={cn(
          "flex h-6 w-6 items-center justify-center rounded-md bg-llamita text-cripta transition-colors",
          "hover:bg-llama-alta focus-visible:outline-none",
          "focus-visible:ring-2 focus-visible:ring-llamita/50",
          open && "bg-llama-alta",
        )}
      >
        <Icon name="dots" size={12} />
      </button>

      {open && (
        <div
          role="menu"
          aria-label={`Acciones de ${node.name}`}
          className={cn(
            "absolute bottom-9 right-0 z-20 min-w-48 overflow-hidden rounded-lg",
            "border border-filio bg-madero shadow-xl",
          )}
        >
          {error && (
            <div
              role="alert"
              className="border-b border-filio px-3 py-2 text-small text-sangre"
            >
              {error}
            </div>
          )}
          {actions.map(({ action, label }) => (
            <button
              key={action}
              type="button"
              role="menuitem"
              disabled={disabled}
              onClick={(e) => handleAction(e, action)}
              className={cn(
                "block w-full px-3 py-2 text-left text-small text-pergamino transition-colors",
                "hover:bg-piedra hover:text-llamita focus-visible:outline-none",
                "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-llamita/50",
                "disabled:cursor-not-allowed disabled:opacity-40",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
