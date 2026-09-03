import {
  ACTIVE_TALLER_STORAGE_KEY,
  DEFAULT_TALLER,
} from "@/lib/constants";

const ACTIVE_TALLER_EVENT = "demiurgos:active-taller";

/** Returns the persisted active Taller, or DEFAULT_TALLER when nothing has
 *  been selected yet (taller-selector-tree-states spec REQ-TRE-1/REQ-TRE-2). */
export function getCurrentTaller(): string {
  if (typeof window === "undefined") return DEFAULT_TALLER;
  return window.localStorage.getItem(ACTIVE_TALLER_STORAGE_KEY) ?? DEFAULT_TALLER;
}

export function setCurrentTaller(taller: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ACTIVE_TALLER_STORAGE_KEY, taller);
  window.dispatchEvent(new Event(ACTIVE_TALLER_EVENT));
}

export function clearCurrentTaller(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACTIVE_TALLER_STORAGE_KEY);
  window.dispatchEvent(new Event(ACTIVE_TALLER_EVENT));
}

/** Subscribes to active-taller changes: the local custom event plus the
 *  cross-tab `storage` event (REQ-TRE-2 S2). Returns an unsubscribe fn. */
export function subscribeCurrentTaller(listener: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(ACTIVE_TALLER_EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(ACTIVE_TALLER_EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}