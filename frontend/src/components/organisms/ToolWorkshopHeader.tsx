import type { ReactNode } from "react";

interface ToolWorkshopHeaderProps {
  /** Descriptive subtitle — the page intentionally renders NO `<h1>` here
   *  (REQ-TAB-2 / SC-TAB-2.1); the Navbar owns the page label. */
  subtitle: string;
  /** Top-level tab buttons, right-aligned (REQ-TAB-2). */
  tablist: ReactNode;
}

/**
 * Shared header for both render sites of the Taller de Herramientas shell
 * (REQ-TAB-2): the flowing "Taller" view and the EditorLayout header of the
 * "Crear skill" view. Single source of truth for the subtitle + tablist
 * layout — `flex justify-between` puts the subtitle left, tabs right.
 */
export function ToolWorkshopHeader({
  subtitle,
  tablist,
}: ToolWorkshopHeaderProps) {
  return (
    <div className="border-b border-edge px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-body text-muted">{subtitle}</p>
        {tablist}
      </div>
    </div>
  );
}