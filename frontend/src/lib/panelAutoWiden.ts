import { useSyncExternalStore } from "react";

/**
 * Auto-widen for the right panel that hosts the AI assistant.
 *
 * The preference is user-owned and opt-out: it lives in `localStorage` so it
 * survives restarts and applies to every page with an assistant panel. The
 * panel geometry is derived from the live viewport instead of being a stored
 * pixel value, so it adapts to the window without the user re-dragging.
 */

export const PANEL_AUTO_WIDEN_STORAGE_KEY = "demiurgos-panel-auto-widen";

const STORED_ON = "on";
const STORED_OFF = "off";

/** Collapsed width target: a quarter of the viewport, capped so wide monitors
 *  do not turn the resting panel into a second article column. */
const RIGHT_PANEL_COLLAPSED_RATIO = 0.25;
const RIGHT_PANEL_COLLAPSED_MAX_PX = 420;

/** Expanded width target: a third of the viewport (the reading width the
 *  assistant needs for cards and diffs). */
const RIGHT_PANEL_ACTIVE_RATIO = 1 / 3;

/** Hard ceiling regardless of viewport: wider chat lines hurt readability. */
const RIGHT_PANEL_MAX_PX = 640;

/** Floor: the panel never gets thinner than this unless the viewport itself
 *  forces a smaller proportional bound. */
const RIGHT_PANEL_MIN_PX = 280;

/** Existing proportional drag bounds (kept so a manual resize behaves as
 *  before on normal screens). */
const RIGHT_PANEL_MIN_RATIO = 0.2;
const RIGHT_PANEL_MAX_RATIO = 0.4;

/** The article keeps at least this much room before the assistant expands. */
export const MAIN_CONTENT_MIN_PX = 480;

/** Approximate space taken by both dividers (2×8px handle + 2×1px borders). */
const DIVIDER_PX = 20;

/** Below this viewport the expanded chat is too narrow to be worth the
 *  article space it takes (at 1024 the article floor eats almost the whole
 *  third), so the automatic behavior is off and the toggle is hidden. */
export const AUTO_WIDEN_MIN_VIEWPORT = 1280;

const listeners = new Set<() => void>();

/** Reads the persisted preference. Unset or unreadable means enabled: the
 *  feature is opt-out, never opt-in. */
export function readAutoWidenPreference(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return (
      window.localStorage.getItem(PANEL_AUTO_WIDEN_STORAGE_KEY) !== STORED_OFF
    );
  } catch {
    return true;
  }
}

/** Persists the preference and notifies every mounted consumer. */
export function setAutoWidenPreference(enabled: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      PANEL_AUTO_WIDEN_STORAGE_KEY,
      enabled ? STORED_ON : STORED_OFF,
    );
  } catch {
    // Storage unavailable: still notify so the UI reflects the attempt.
  }
  for (const listener of listeners) listener();
}

function subscribeAutoWiden(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React binding for the shared preference (EditorLayout + TabBar toggle). */
export function useAutoWidenPreference(): boolean {
  return useSyncExternalStore(
    subscribeAutoWiden,
    readAutoWidenPreference,
    () => true,
  );
}

export interface RightPanelBounds {
  min: number;
  max: number;
}

/** Width range for the right panel, derived from the viewport and the current
 *  left panel width so the article never drops below `MAIN_CONTENT_MIN_PX`. */
export function rightPanelBounds(
  viewportWidth: number,
  leftWidth: number,
): RightPanelBounds {
  const viewport = viewportWidth > 0 ? viewportWidth : 1200;
  const proportionalMin = Math.round(viewport * RIGHT_PANEL_MIN_RATIO);
  const proportionalMax = Math.round(viewport * RIGHT_PANEL_MAX_RATIO);
  const contentMax = viewport - leftWidth - MAIN_CONTENT_MIN_PX - DIVIDER_PX;
  const min = Math.min(proportionalMin, RIGHT_PANEL_MIN_PX);
  const max = Math.max(
    min,
    Math.min(RIGHT_PANEL_MAX_PX, proportionalMax, contentMax),
  );
  return { min, max };
}

function clampToBounds(width: number, bounds: RightPanelBounds): number {
  return Math.min(bounds.max, Math.max(bounds.min, Math.round(width)));
}

/** Existing proportional default for a right panel that does not host the
 *  assistant (a fifth of the viewport) — unchanged behavior for the other
 *  pages that use `EditorLayout`. */
const RIGHT_PANEL_RESTING_RATIO = 0.2;

/** Resting width for a right panel without the assistant (one fifth of the
 *  viewport), so unrelated panels keep their previous resting size. */
export function restingRightPanelWidth(
  viewportWidth: number,
  leftWidth: number,
): number {
  const viewport = viewportWidth > 0 ? viewportWidth : 1200;
  return clampToBounds(
    Math.round(viewport * RIGHT_PANEL_RESTING_RATIO),
    rightPanelBounds(viewport, leftWidth),
  );
}

/** Resting width: the panel the author returns to when they leave the chat. */
export function collapsedRightPanelWidth(
  viewportWidth: number,
  leftWidth: number,
): number {
  const viewport = viewportWidth > 0 ? viewportWidth : 1200;
  const target = Math.min(
    Math.round(viewport * RIGHT_PANEL_COLLAPSED_RATIO),
    RIGHT_PANEL_COLLAPSED_MAX_PX,
  );
  return clampToBounds(target, rightPanelBounds(viewport, leftWidth));
}

/** Expanded width: the panel the assistant gets while it is being used. */
export function activeRightPanelWidth(
  viewportWidth: number,
  leftWidth: number,
): number {
  const viewport = viewportWidth > 0 ? viewportWidth : 1200;
  return clampToBounds(
    Math.round(viewport * RIGHT_PANEL_ACTIVE_RATIO),
    rightPanelBounds(viewport, leftWidth),
  );
}

/** Whether this viewport is wide enough for the automatic behavior. */
export function supportsAutoWiden(viewportWidth: number): boolean {
  return viewportWidth >= AUTO_WIDEN_MIN_VIEWPORT;
}
