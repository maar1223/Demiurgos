import { useState, useCallback, useRef, useEffect, type ReactNode } from "react";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import {
  activeRightPanelWidth,
  collapsedRightPanelWidth,
  restingRightPanelWidth,
  rightPanelBounds,
  setAutoWidenPreference,
  supportsAutoWiden,
  useAutoWidenPreference,
} from "@/lib/panelAutoWiden";

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
  /** The right panel currently hosts the AI assistant (Asistente tab active).
   *  Only then does interacting with it widen the panel. */
  assistantPanel?: boolean;
  /** The assistant is producing a response. The expanded width is held until
   *  it finishes, so a stray click cannot hide the answer being written. */
  assistantBusy?: boolean;
}

const LEFT_DEFAULT = 240;

/** Tailwind `md` breakpoint: below it the panels are overlays, not columns. */
const DESKTOP_MIN_VIEWPORT = 768;

/** Proportional panel limits (1/5–2/5 of the viewport width) — computed live so
 *  drag/resize behavior adapts to the current window size. Used by the left
 *  panel; the right panel geometry lives in `panelAutoWiden`. */
const panelLimits = () => {
  const vw = currentViewportWidth();
  return { min: Math.round(vw * 0.2), max: Math.round(vw * 0.4) };
};

const currentViewportWidth = () =>
  typeof window === "undefined" ? 1200 : window.innerWidth || 1200;

const clampPanel = (w: number) => {
  const { min, max } = panelLimits();
  return Math.min(max, Math.max(min, Math.round(w)));
};

const clampRightPanel = (w: number, viewportWidth: number, leftWidth: number) => {
  const { min, max } = rightPanelBounds(viewportWidth, leftWidth);
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
 *
 * The right panel also auto-widens while the assistant panel is being used and
 * returns to its resting width when the author touches another section. The
 * behavior is user-owned (`panelAutoWiden`): the Asistente tab bar exposes the
 * toggle, and dragging the divider turns it off instead of fighting the drag.
 */
export function EditorLayout({
  header,
  sidebar,
  children,
  rightPanel,
  focusMode = false,
  assistantPanel = false,
  assistantBusy = false,
}: EditorLayoutProps) {
  const { t } = useAppLanguage();
  const autoWiden = useAutoWidenPreference();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const [viewportWidth, setViewportWidth] = useState(currentViewportWidth);
  const [leftWidth, setLeftWidth] = useState<number>(() =>
    clampPanel(LEFT_DEFAULT),
  );
  const [rightWidth, setRightWidth] = useState<number>(() =>
    assistantPanel
      ? collapsedRightPanelWidth(currentViewportWidth(), clampPanel(LEFT_DEFAULT))
      : restingRightPanelWidth(currentViewportWidth(), clampPanel(LEFT_DEFAULT)),
  );
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{
    startX: number;
    startW: number;
    side: "left" | "right";
    changed: boolean;
  } | null>(null);

  /** Expanded state of the assistant panel, driven by real interaction. */
  const [engaged, setEngaged] = useState(false);
  const rightPanelRef = useRef<HTMLElement | null>(null);
  /** An outside interaction arrived while the assistant was answering: honor it
   *  as soon as the answer finishes instead of dropping it. */
  const pendingCollapse = useRef(false);

  // ── Assistant engagement (document-level, capture phase) ────────────────
  // Capture phase so a child stopping propagation cannot hide the gesture.
  // Expansion and contraction use the same rule: the panel widens while the
  // author interacts with the assistant and returns as soon as the next
  // interaction lands outside it. A delay made the same gesture collapse
  // immediately or ten seconds later depending on recent typing, which read as
  // inconsistent.
  useEffect(() => {
    const autoApplies =
      autoWiden &&
      Boolean(rightPanel) &&
      !focusMode &&
      assistantPanel &&
      supportsAutoWiden(viewportWidth);
    if (!autoApplies) {
      pendingCollapse.current = false;
      setEngaged(false);
      return;
    }

    const isIgnored = (node: Node | null): boolean =>
      node instanceof Element && Boolean(node.closest("[data-auto-widen-ignore]"));

    const engage = () => {
      pendingCollapse.current = false;
      setEngaged(true);
    };

    const release = () => {
      if (assistantBusy) {
        pendingCollapse.current = true;
        return;
      }
      pendingCollapse.current = false;
      setEngaged(false);
    };

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (isIgnored(target instanceof Node ? target : null)) return;
      if (target instanceof Node && rightPanelRef.current?.contains(target)) {
        engage();
        return;
      }
      release();
    };

    const onFocusIn = (event: FocusEvent) => {
      const target = event.target;
      if (target instanceof Node && rightPanelRef.current?.contains(target)) {
        engage();
      }
    };

    const onFocusOut = (event: FocusEvent) => {
      const next = event.relatedTarget;
      // Pointer navigation is owned by `pointerdown`; only a real focus move
      // (keyboard Tab) contracts here.
      if (!(next instanceof Node)) return;
      if (isIgnored(next)) return;
      if (rightPanelRef.current?.contains(next)) return;
      release();
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("focusin", onFocusIn, true);
    document.addEventListener("focusout", onFocusOut, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("focusin", onFocusIn, true);
      document.removeEventListener("focusout", onFocusOut, true);
    };
  }, [
    assistantBusy,
    assistantPanel,
    autoWiden,
    focusMode,
    rightPanel,
    viewportWidth,
  ]);

  // The answer starts: hold the panel open. The answer ends: honor a click
  // that arrived mid-stream, if there was one.
  useEffect(() => {
    if (assistantBusy) {
      pendingCollapse.current = false;
      setEngaged(true);
      return;
    }
    if (pendingCollapse.current) {
      pendingCollapse.current = false;
      setEngaged(false);
    }
  }, [assistantBusy]);

  // ── Width policy ────────────────────────────────────────────────────────
  // The automatic behavior owns the width only while enabled. A manual drag
  // turns it off (see `onMouseDown`), so the two never fight.
  useEffect(() => {
    if (!rightPanel || focusMode || !autoWiden) return;
    if (!assistantPanel || !supportsAutoWiden(viewportWidth)) {
      // No assistant in the panel (Contexto tab, other pages) or a viewport
      // too narrow: keep the previous resting size.
      setRightWidth(restingRightPanelWidth(viewportWidth, leftWidth));
      return;
    }
    setRightWidth(
      engaged
        ? activeRightPanelWidth(viewportWidth, leftWidth)
        : collapsedRightPanelWidth(viewportWidth, leftWidth),
    );
  }, [
    assistantPanel,
    autoWiden,
    engaged,
    focusMode,
    leftWidth,
    rightPanel,
    viewportWidth,
  ]);

  // Resize drag handlers — only active on desktop (`md:`+)
  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = {
        startX: e.clientX,
        startW: rightWidth,
        side: "right",
        changed: false,
      };
      setDragging(true);
    },
    [rightWidth],
  );

  const onMouseDownLeft = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = {
        startX: e.clientX,
        startW: leftWidth,
        side: "left",
        changed: false,
      };
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
      const clamped =
        side === "right"
          ? clampRightPanel(next, currentViewportWidth(), leftWidth)
          : clampPanel(next);
      if (clamped !== startW) dragRef.current.changed = true;
      if (side === "right") setRightWidth(clamped);
      else setLeftWidth(clamped);
    };
    const onUp = () => {
      const moved = dragRef.current?.changed ?? false;
      const side = dragRef.current?.side;
      dragRef.current = null;
      setDragging(false);
      // A real resize is a manual decision: stop the automatic behavior so it
      // never snaps the panel back under the author's hands. A plain click on
      // the grip changes nothing.
      if (moved && side === "right") setAutoWidenPreference(false);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [dragging, leftWidth]);

  // Re-clamp both panel widths when the viewport resizes (proportional limits)
  useEffect(() => {
    const onResize = () => {
      const next = currentViewportWidth();
      setViewportWidth(next);
      setLeftWidth((w) => clampPanel(w));
      setRightWidth((w) => clampRightPanel(w, next, leftWidth));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [leftWidth]);

  return (
    // Height = viewport minus the global Navbar: `h-14` (3.5rem) PLUS its 1px
    // bottom border. Without the 1px the shell is 1px taller than the viewport,
    // so the document scrolls and reveals a strip under the panels.
    <div className="flex h-[calc(100vh-3.5rem-1px)] supports-[height:100dvh]:h-[calc(100dvh-3.5rem-1px)] flex-col overflow-hidden bg-surface">
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
              data-auto-widen-ignore
              onMouseDown={onMouseDown}
              onKeyDown={(e) => {
                const { min, max } = rightPanelBounds(
                  viewportWidth,
                  leftWidth,
                );
                const step = 40;
                if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                  setAutoWidenPreference(false);
                  setRightWidth((w) =>
                    e.key === "ArrowLeft"
                      ? Math.min(max, w + step)
                      : Math.max(min, w - step),
                  );
                }
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
              ref={rightPanelRef}
              className={cn(
                "border-l border-edge bg-surface-raised",
                // Desktop
                "hidden md:flex md:flex-col",
                // Mobile: overlay
                "fixed inset-y-0 right-0 z-30 w-[280px] flex-col translate-x-0 transition-transform duration-200 ease-in-out md:relative md:inset-auto md:w-auto md:translate-x-0",
                !rightOpen && "translate-x-full md:translate-x-0",
              )}
              // Inline width only in the desktop column layout: on mobile the
              // panel is a fixed 280px overlay and a computed width would
              // shrink it below usability.
              style={
                viewportWidth >= DESKTOP_MIN_VIEWPORT
                  ? { width: rightWidth }
                  : undefined
              }
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
