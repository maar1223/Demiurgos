import { useEffect, useMemo, useState } from "react";
import { useFileTree } from "@/hooks/useFileTree";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { cn } from "@/lib/utils";
import {
  MOVE_DESTINATION_SECTIONS,
  MOVE_DESTINATION_LABELS,
  type MoveDestinationSection,
} from "@/lib/constants";
import type { FileNode } from "@/api/types";

interface MoveModalProps {
  mundo: string;
  /** The node being moved: section is where it lives, path is section-relative. */
  source: { section: string; path: string };
  /** Called with the mundo-relative destination (e.g. `lore/ciudades`). */
  onConfirm: (destPath: string) => void;
  onClose: () => void;
}

/**
 * "Mover a…" modal (S9): pick a destination section (lore/personajes/
 * referencias — decision (b)) and a folder inside it, then confirm.
 *
 * Owns a collapsible directory-only tree per active section built on
 * `useFileTree` (SWR cache reuses the already-loaded trees). The source
 * subtree is excluded so a folder cannot be moved into itself. The section
 * root is selectable. Overlay pattern mirrors ImagePicker (fixed inset-0
 * z-50, role dialog, aria-modal, Escape/overlay click).
 */
export function MoveModal({ mundo, source, onConfirm, onClose }: MoveModalProps) {
  const [activeSection, setActiveSection] =
    useState<MoveDestinationSection>("lore");
  const [selectedDir, setSelectedDir] = useState<string>("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const { nodes, isLoading, error } = useFileTree(mundo, activeSection);

  // Close on Escape key
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  // The source subtree only exists inside its own section; a same-named
  // folder in another section is a perfectly valid destination.
  const isExcluded = useMemo(
    () =>
      (path: string): boolean =>
        activeSection === source.section &&
        (path === source.path || path.startsWith(source.path + "/")),
    [activeSection, source.section, source.path],
  );

  const topDirs = useMemo(
    () => nodes.filter((n) => n.is_dir && !isExcluded(n.path)),
    [nodes, isExcluded],
  );

  const crumbParts = selectedDir ? selectedDir.split("/") : [];

  const selectDir = (path: string) => {
    setSelectedDir(path);
    // Auto-expand the newly selected folder so its contents stay visible.
    setExpanded((prev) => {
      if (prev.has(path)) return prev;
      const next = new Set(prev);
      next.add(path);
      return next;
    });
  };

  const handleTabChange = (sec: MoveDestinationSection) => {
    setActiveSection(sec);
    setSelectedDir("");
  };

  const renderDirs = (dirNodes: FileNode[]): React.ReactNode => (
    <ul className="list-none space-y-0.5">
      {dirNodes.map((dir) => {
        const isExpanded = expanded.has(dir.path);
        const isSelected = selectedDir === dir.path;
        const childDirs = (dir.children ?? []).filter(
          (c) => c.is_dir && !isExcluded(c.path),
        );
        return (
          <li key={dir.path}>
            <div
              className={cn(
                "flex items-center rounded-md transition-colors",
                isSelected && "bg-piedra",
              )}
            >
              <button
                type="button"
                aria-label={`Seleccionar ${dir.name}`}
                onClick={() => selectDir(dir.path)}
                className={cn(
                  "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left",
                  "text-small transition-colors",
                  isSelected
                    ? "text-llamita"
                    : "text-pergamino hover:bg-piedra/60 hover:text-llamita",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-llamita/50",
                )}
              >
                <Icon
                  name={isExpanded ? "chevron-down" : "chevron-right"}
                  size={14}
                  className="shrink-0 text-plata/50"
                />
                <Icon name="folder" size={16} className="shrink-0 text-llamita/50" />
                <span className="truncate">{dir.name}</span>
              </button>
            </div>
            {isExpanded && childDirs.length > 0 && (
              <div className="ml-3 border-l border-filio pl-2">
                {renderDirs(childDirs)}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );

  const handleConfirm = () => {
    onConfirm(selectedDir ? `${activeSection}/${selectedDir}` : activeSection);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-cripta/80 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="mx-4 flex max-h-[80vh] w-full max-w-lg flex-col rounded-xl border border-filio bg-madero shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="move-modal-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-filio px-6 py-4">
          <h2
            id="move-modal-title"
            className="font-heading text-h4 text-pergamino"
          >
            Mover a…
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-plata transition-colors hover:bg-piedra hover:text-pergamino"
            aria-label="Cerrar"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Destination section tabs */}
        <div
          role="tablist"
          aria-label="Sección de destino"
          className="flex shrink-0 border-b border-filio"
        >
          {MOVE_DESTINATION_SECTIONS.map((sec) => (
            <button
              key={sec}
              type="button"
              role="tab"
              aria-selected={activeSection === sec}
              onClick={() => handleTabChange(sec)}
              className={cn(
                "flex-1 px-2 py-2 text-small font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-llamita/50",
                activeSection === sec
                  ? "border-b-2 border-llamita text-pergamino"
                  : "text-sombra hover:bg-piedra/50 hover:text-tinta-desvaida",
              )}
            >
              {MOVE_DESTINATION_LABELS[sec]}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Spinner size="md" />
            </div>
          )}

          {error && !isLoading && (
            <ErrorBanner
              message="No se pudo cargar la sección de destino"
              className="mb-3"
            />
          )}

          {!isLoading && !error && (
            <>
              {/* Breadcrumb of the current folder path */}
              <div className="mb-3 flex flex-wrap items-center gap-1 text-small">
                <button
                  type="button"
                  onClick={() => setSelectedDir("")}
                  className={cn(
                    "rounded px-1.5 py-0.5 transition-colors hover:bg-piedra hover:text-llamita",
                    selectedDir === ""
                      ? "bg-piedra font-medium text-llamita"
                      : "text-tinta-desvaida",
                  )}
                >
                  {MOVE_DESTINATION_LABELS[activeSection]} (raíz)
                </button>
                {crumbParts.map((part, idx) => {
                  const path = crumbParts.slice(0, idx + 1).join("/");
                  const isLast = idx === crumbParts.length - 1;
                  return (
                    <span key={path} className="flex items-center gap-1">
                      <Icon name="chevron-right" size={12} className="text-plata/40" />
                      <button
                        type="button"
                        onClick={() => setSelectedDir(path)}
                        className={cn(
                          "rounded px-1.5 py-0.5 transition-colors hover:bg-piedra hover:text-llamita",
                          isLast
                            ? "bg-piedra font-medium text-llamita"
                            : "text-tinta-desvaida",
                        )}
                      >
                        {part}
                      </button>
                    </span>
                  );
                })}
              </div>

              {/* Directory tree (dirs only, source subtree excluded) */}
              {topDirs.length === 0 ? (
                <p className="py-8 text-center text-small text-tinta-desvaida">
                  No hay carpetas para elegir en esta sección.
                </p>
              ) : (
                renderDirs(topDirs)
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-filio px-6 py-4">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancelar
          </Button>
          <Button variant="primary" size="sm" onClick={handleConfirm}>
            Mover aquí
          </Button>
        </div>
      </div>
    </div>
  );
}
