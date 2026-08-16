export const ACTIVE_WORLD_STORAGE_KEY = "demiurgos-active-world";

const ACTIVE_WORLD_EVENT = "demiurgos:active-world";

export function getCurrentWorld(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACTIVE_WORLD_STORAGE_KEY);
}

export function setCurrentWorld(world: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ACTIVE_WORLD_STORAGE_KEY, world);
  window.dispatchEvent(new Event(ACTIVE_WORLD_EVENT));
}

export function clearCurrentWorld(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACTIVE_WORLD_STORAGE_KEY);
  window.dispatchEvent(new Event(ACTIVE_WORLD_EVENT));
}

export function subscribeCurrentWorld(listener: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(ACTIVE_WORLD_EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(ACTIVE_WORLD_EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}