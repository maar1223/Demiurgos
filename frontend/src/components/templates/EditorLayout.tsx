import { useState, useCallback, useRef, useEffect, type ReactNode } from "react";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

interface EditorLayoutProps {
  header: ReactNode;
  sidebar: ReactNode;
  children: ReactNode;
  /** Right panel content (Asistente IA / Contexto). When provided, a resizable
   *  right panel is rendered with a draggable divider. */
  rightPanel?: ReactNode;
}

const PANEL_MIN = 200;
const PANEL_MAX = 500;
const PANEL_DEFAULT = 280;

/**
 * Layout for the Wiki Editor and Entity pages.
 *
 * Desktop: left sidebar (240px) + content area + optional resizable right panel.
 * Mobile: left sidebar collapses to overlay. Right panel toggles via FAB.
 *
 * Uses a native mousedown/mousemove/mouseup resize loop rather than
 * a library dependency to keep the bundle trim.
 */
export function EditorLayout({
  header,
  sidebar,
  children,
  rightPanel,
}: EditorLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const [rightWidth, setRightWidth] = useState(PANEL_DEFAULT);
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  // Resize drag handlers — only active on desktop (`md:`+)
  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = { startX: e.clientX, startW: rightWidth };
      setDragging(true);
    },
    [rightWidth],
  );

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      if (!dragRef.current) return;
      const delta = dragRef.current.startX - e.clientX;
      const next = Math.min(PANEL_MAX, Math.max(PANEL_MIN, dragRef.current.startW + delta));
      setRightWidth(next);
    };
    const onUp = () => {
      dragRef.current = null;
      setDragging(false);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [dragging]);

  return (
    <div className="flex h-screen supports-[height:100dvh]:h-dvh flex-col overflow-hidden bg-cripta">
      {header}

      <div className="relative flex flex-1 overflow-hidden">
        {/* ── Left Sidebar ────────────────────────────────────────────── */}
        {/* Mobile overlay toggle */}
        <button
          type="button"
          onClick={() => setSidebarOpen((prev) => !prev)}
          className="fixed bottom-4 left-4 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-llamita text-cripta shadow-lg hover:bg-llama-alta md:hidden"
          aria-label={sidebarOpen ? "Cerrar panel" : "Abrir panel"}
          aria-expanded={sidebarOpen}
        >
          <Icon name={sidebarOpen ? "close" : "menu"} size={20} />
        </button>

        <aside
          className={cn(
            "border-r border-filio bg-madero",
            // Desktop: always visible, fixed width, full viewport height
            "hidden md:block md:w-[240px] lg:w-[240px] md:overflow-hidden",
            // Mobile: overlay with transition
            "fixed inset-y-0 left-0 z-30 w-[240px] translate-x-0 transition-transform duration-200 ease-in-out md:relative md:inset-auto md:translate-x-0",
            !sidebarOpen && "-translate-x-full md:translate-x-0",
          )}
        >
          {/* Mobile close button */}
          <div className="flex items-center justify-between border-b border-filio px-4 py-3 md:hidden">
            <span className="text-small text-tinta-desvaida">Archivos</span>
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              className="text-plata hover:text-pergamino"
              aria-label="Cerrar panel"
            >
              <Icon name="close" size={16} />
            </button>
          </div>
          <div className="h-full overflow-y-auto py-2">{sidebar}</div>
        </aside>

        {/* Mobile backdrop for left sidebar */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-20 bg-cripta/60 backdrop-blur-sm md:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* ── Main Content ───────────────────────────────────────────── */}
        <main className="min-w-0 flex-1 overflow-y-auto px-4 py-6 md:px-8 lg:px-12">
          {children}
        </main>

        {/* ── Right Panel (desktop: resizable) ────────────────────────── */}
        {rightPanel && (
          <>
            {/* Resize handle — desktop only */}
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="Redimensionar panel"
              tabIndex={0}
              onMouseDown={onMouseDown}
              onKeyDown={(e) => {
                const step = 40;
                if (e.key === "ArrowLeft") setRightWidth((w) => Math.min(PANEL_MAX, w + step));
                if (e.key === "ArrowRight") setRightWidth((w) => Math.max(PANEL_MIN, w - step));
              }}
              className={cn(
                "hidden md:flex",
                "w-2 cursor-col-resize items-center justify-center",
                "border-l border-filio bg-madero",
                "hover:bg-filio active:bg-filio transition-colors",
                dragging && "bg-filio",
                // Prevent text selection while dragging
                dragging && "select-none",
              )}
            >
              <Icon name="grip" size={14} className="text-sombra" />
            </div>

            {/* Right panel — desktop: resizable static, mobile: overlay */}
            <aside
              className={cn(
                "border-l border-filio bg-madero",
                // Desktop
                "hidden md:flex md:flex-col",
                // Mobile: overlay
                "fixed inset-y-0 right-0 z-30 w-[280px] flex flex-col translate-x-0 transition-transform duration-200 ease-in-out md:relative md:inset-auto md:w-auto md:translate-x-0",
                !rightOpen && "translate-x-full md:translate-x-0",
              )}
              style={{ width: rightWidth }}
            >
              {/* Mobile close button */}
              <div className="flex items-center justify-between border-b border-filio px-4 py-3 md:hidden">
                <span className="text-small text-tinta-desvaida">Panel</span>
                <button
                  type="button"
                  onClick={() => setRightOpen(false)}
                  className="text-plata hover:text-pergamino"
                  aria-label="Cerrar panel"
                >
                  <Icon name="close" size={16} />
                </button>
              </div>
              <div className="flex flex-1 flex-col overflow-hidden">
                {rightPanel}
              </div>
            </aside>

            {/* Mobile backdrop for right panel */}
            {rightOpen && (
              <div
                className="fixed inset-0 z-20 bg-cripta/60 backdrop-blur-sm md:hidden"
                onClick={() => setRightOpen(false)}
              />
            )}

            {/* Mobile toggle FAB for right panel */}
            <button
              type="button"
              onClick={() => setRightOpen((prev) => !prev)}
              className={cn(
                "fixed bottom-4 right-4 z-40 flex h-12 w-12 items-center justify-center rounded-full shadow-lg md:hidden",
                rightOpen
                  ? "bg-sangre text-cripta hover:bg-sangre/80"
                  : "bg-llamita text-cripta hover:bg-llama-alta",
              )}
              aria-label={rightOpen ? "Cerrar panel derecho" : "Abrir panel derecho"}
              aria-expanded={rightOpen}
            >
              <Icon name={rightOpen ? "close" : "lightbulb"} size={20} />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
