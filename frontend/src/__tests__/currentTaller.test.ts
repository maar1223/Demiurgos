import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearCurrentTaller,
  getCurrentTaller,
  setCurrentTaller,
  subscribeCurrentTaller,
} from "@/lib/currentTaller";
import {
  ACTIVE_TALLER_STORAGE_KEY,
  DEFAULT_TALLER,
} from "@/lib/constants";

describe("currentTaller", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("returns DEFAULT_TALLER when nothing is persisted", () => {
    expect(getCurrentTaller()).toBe(DEFAULT_TALLER);
  });

  it("reads a taller persisted under ACTIVE_TALLER_STORAGE_KEY", () => {
    window.localStorage.setItem(ACTIVE_TALLER_STORAGE_KEY, "Mundo");
    expect(getCurrentTaller()).toBe("Mundo");
  });

  it("resolves a stale legacy 'Herramientas' value to DEFAULT_TALLER without writing through (OC-2 S1)", () => {
    window.localStorage.setItem(ACTIVE_TALLER_STORAGE_KEY, "Herramientas");
    expect(getCurrentTaller()).toBe(DEFAULT_TALLER);
    // No write-through: the stale key stays untouched until an explicit set.
    expect(window.localStorage.getItem(ACTIVE_TALLER_STORAGE_KEY)).toBe(
      "Herramientas",
    );
  });

  it("resolves a corrupted stored value to DEFAULT_TALLER without writing through (OC-2 S2)", () => {
    window.localStorage.setItem(ACTIVE_TALLER_STORAGE_KEY, "mundo/");
    expect(getCurrentTaller()).toBe(DEFAULT_TALLER);
    expect(window.localStorage.getItem(ACTIVE_TALLER_STORAGE_KEY)).toBe(
      "mundo/",
    );
  });

  it("preserves a valid stored 'Ideas' value across reads (OC-3 S2)", () => {
    window.localStorage.setItem(ACTIVE_TALLER_STORAGE_KEY, "Ideas");
    expect(getCurrentTaller()).toBe("Ideas");
    expect(window.localStorage.getItem(ACTIVE_TALLER_STORAGE_KEY)).toBe(
      "Ideas",
    );
  });

  it("persists the taller and round-trips through getCurrentTaller", () => {
    setCurrentTaller("Mundo");
    expect(window.localStorage.getItem(ACTIVE_TALLER_STORAGE_KEY)).toBe(
      "Mundo",
    );
    expect(getCurrentTaller()).toBe("Mundo");
  });

  it("clears the persisted taller and falls back to DEFAULT_TALLER", () => {
    setCurrentTaller("Mundo");
    clearCurrentTaller();
    expect(window.localStorage.getItem(ACTIVE_TALLER_STORAGE_KEY)).toBeNull();
    expect(getCurrentTaller()).toBe(DEFAULT_TALLER);
  });

  it("notifies subscribers on set and clear", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeCurrentTaller(listener);

    setCurrentTaller("Mundo");
    expect(listener).toHaveBeenCalledTimes(1);

    clearCurrentTaller();
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
  });

  it("stops notifying subscribers after unsubscribe", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeCurrentTaller(listener);
    unsubscribe();

    setCurrentTaller("Mundo");
    expect(listener).not.toHaveBeenCalled();
  });

  it("notifies subscribers on a cross-tab storage event", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeCurrentTaller(listener);

    window.dispatchEvent(
      new StorageEvent("storage", {
        key: ACTIVE_TALLER_STORAGE_KEY,
        newValue: "Taller de Mundo",
      }),
    );

    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });
});