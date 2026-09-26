import { useState, useCallback, useRef, useEffect, type ReactNode } from "react";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";
import { useAppLanguage } from "@/hooks/useAppLanguage";

interface EditorLayoutProps {
  /** Optional in-page header slot. The global Navbar is hoisted to the shared
   *  AppLayout, so pages no longer pass it here. */
  header?: ReactNode;
  sidebar: ReactNode;
  children: ReactNode;
  /** Right panel content (Asistente IA / Contexto). When provided, a resizable
   *  right panel is rendered with a draggable divider. */
  rightPanel?: ReactNode;
  /** Focus mode: hides both side panels (and their dividers). Optional — defaults
   *  to false so existing pages keep their current layout. */
  focusMode?: boolean;
}

const RIGHT_DEFAULT = 280;
const LEFT_DEFAULT = 240;

/** Proportional panel limits (1/5–2/5 of the viewport width) — computed live so
 *  drag/resize behavior adapts to the current window size. */
const panelLimits = () => {
  const vw = window.innerWidth || 1200;
  return { min: Math.round(vw * 0.2), max: Math.round(vw * 0.4) };
};

const clampPanel = (w: number) => {
  const { min, max } = panelLimits();
  return Math.min(max, Math.max(min, Math.round(w)));
};

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
  focusMode = false,
}: EditorLayoutProps) {
  const { t } = useAppLanguage();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const [rightWidth, setRightWidth] = useState<number>(() =>
    clampPanel(RIGHT_DEFAULT),
  );
  const [leftWidth, setLeftWidth] = useState<number>(() =>
    clampPanel(LEFT_DEFAULT),
  );
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{
    startX: number;
    startW: number;
    side: "left" | "right";
  } | null>(null);

  // Resize drag handlers — only active on desktop (`md:`+)
  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = { startX: e.clientX, startW: rightWidth, side: "right" };
      setDragging(true);
    },
    [rightWidth],
  );

  const onMouseDownLeft = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = { startX: e.clientX, startW: leftWidth, side: "left" };
      setDragging(true);
    },
    [leftWidth],
  );

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      if (!dragRef.current) return;
      const { startX, startW, side } = dragRef.current;
      const next =
        side === "right"
          ? startW + (startX - e.clientX)
          : startW + (e.clientX - startX);
      const clamped = clampPanel(next);
      if (side === "right") setRightWidth(clamped);
      else setLeftWidth(clamped);
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

  // Re-clamp both panel widths when the viewport resizes (proportional limits)
  useEffect(() => {
    const onResize = () => {
      setRightWidth((w) => clampPanel(w));
      setLeftWidth((w) => clampPanel(w));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return (
    <div className="flex h-[calc(100vh-3.5rem)] supports-[height:100dvh]:h-[calc(100dvh-3.5rem)] flex-col overflow-hidden bg-surface">
      {header}

      <div className="relative flex flex-1 overflow-hidden">
        {/* ── Left Sidebar ────────────────────────────────────────────── */}
        {/* Mobile overlay toggle */}
        <button
          type="button"
          onClick={() => setSidebarOpen((prev) => !prev)}
          className="fixed bottom-4 left-4 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-action text-action-text shadow-lg hover:bg-action-hover md:hidden"
          aria-label={sidebarOpen ? t("editorLayout.closePanel") : t("editorLayout.openPanel")}
          aria-expanded={sidebarOpen}
        >
          <Icon name={sidebarOpen ? "close" : "menu"} size={20} />
        </button>

        <aside
          style={{ "--left-w": `${leftWidth}px` } as React.CSSProperties}
          className={cn(
            "border-r border-edge bg-surface-raised",
            // Desktop: always visible, resizable width, full viewport height.
            // Focus mode hides the aside at ALL breakpoints (display:none wins
            // over the mobile overlay positioning — deliberate behavior).
            focusMode
              ? "hidden"
              : "hidden md:block md:w-[var(--left-w,240px)] lg:w-[var(--left-w,240px)] md:overflow-hidden",
            // Mobile: overlay with transition
            "fixed inset-y-0 left-0 z-30 w-[240px] translate-x-0 transition-transform duration-200 ease-in-out md:relative md:inset-auto md:translate-x-0",
            !sidebarOpen && "-translate-x-full md:translate-x-0",
          )}
        >
          {/* Mobile close button */}
          <div className="flex items-center justify-between border-b border-edge px-4 py-3 md:hidden">
            <span className="text-small text-muted">{t("editorLayout.files")}</span>
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              className="text-icon-muted hover:text-primary"
              aria-label={t("editorLayout.closePanel")}
            >
              <Icon name="close" size={16} />
            </button>
          </div>
          <div className="h-full overflow-y-auto py-2">{sidebar}</div>
        </aside>

        {/* Mobile backdrop for left sidebar */}
        {sidebarOpen && (
          <div
className="fixed inset-0 z-20 bg-surface/60 backdrop-blur-sm md:hidden"
                onClick={() => setRightOpen(false)}
              />
        )}

        {/* ── Left divider (desktop: resizable) ─────────────────────────── */}
        {sidebar && !focusMode && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label={t("editorLayout.resizeFiles")}
            tabIndex={0}
            onMouseDown={onMouseDownLeft}
            onKeyDown={(e) => {
              const { min, max } = panelLimits();
              const step = 40;
              if (e.key === "ArrowLeft")
                setLeftWidth((w) => Math.max(min, w - step));
              if (e.key === "ArrowRight")
                setLeftWidth((w) => Math.min(max, w + step));
            }}
            className={cn(
              "hidden md:flex w-2 cursor-col-resize items-center justify-center border-r border-edge bg-surface-raised hover:bg-surface-hover active:bg-surface-hover transition-colors",
              dragging && "bg-surface-hover select-none",
            )}
          >
            <Icon name="grip" size={14} className="text-muted" />
          </div>
        )}

        {/* ── Main Content ───────────────────────────────────────────── */}
        <main className="min-w-0 flex-1 overflow-y-auto px-4 py-6 md:px-8 lg:px-12">
          {children}
        </main>

        {/* ── Right Panel (desktop: resizable) ────────────────────────── */}
        {rightPanel && !focusMode && (
          <>
            {/* Resize handle — desktop only */}
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label={t("editorLayout.resizePanel")}
              tabIndex={0}
              onMouseDown={onMouseDown}
              onKeyDown={(e) => {
                const { min, max } = panelLimits();
                const step = 40;
                if (e.key === "ArrowLeft")
                  setRightWidth((w) => Math.min(max, w + step));
                if (e.key === "ArrowRight")
                  setRightWidth((w) => Math.max(min, w - step));
              }}
              className={cn(
                "hidden md:flex",
                "w-2 cursor-col-resize items-center justify-center",
                "border-l border-edge bg-surface-raised",
                "hover:bg-surface-hover active:bg-surface-hover transition-colors",
                dragging && "bg-surface-hover",
                // Prevent text selection while dragging
                dragging && "select-none",
              )}
            >
<Icon name="grip" size={14} className="text-muted" />
            </div>

            {/* Right panel — desktop: resizable static, mobile: overlay */}
            <aside
              className={cn(
                "border-l border-edge bg-surface-raised",
                // Desktop
                "hidden md:flex md:flex-col",
                // Mobile: overlay
                "fixed inset-y-0 right-0 z-30 w-[280px] flex flex-col translate-x-0 transition-transform duration-200 ease-in-out md:relative md:inset-auto md:w-auto md:translate-x-0",
                !rightOpen && "translate-x-full md:translate-x-0",
              )}
              style={{ width: rightWidth }}
            >
              {/* Mobile close button */}
              <div className="flex items-center justify-between border-b border-edge px-4 py-3 md:hidden">
                <span className="text-small text-muted">{t("editorLayout.panel")}</span>
                <button
                  type="button"
                  onClick={() => setRightOpen(false)}
                  className="text-icon-muted hover:text-primary"
                  aria-label={t("editorLayout.closePanel")}
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
className="fixed inset-0 z-20 bg-surface/60 backdrop-blur-sm md:hidden"
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
                  ? "bg-status-error text-action-text hover:bg-status-error/80"
                  : "bg-action text-action-text hover:bg-action-hover",
              )}
              aria-label={rightOpen ? t("editorLayout.closeRightPanel") : t("editorLayout.openRightPanel")}
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
