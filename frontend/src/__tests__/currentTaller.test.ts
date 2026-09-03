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
    window.localStorage.setItem(ACTIVE_TALLER_STORAGE_KEY, "Taller de Mundo");
    expect(getCurrentTaller()).toBe("Taller de Mundo");
  });

  it("persists the taller and round-trips through getCurrentTaller", () => {
    setCurrentTaller("Taller de Mundo");
    expect(window.localStorage.getItem(ACTIVE_TALLER_STORAGE_KEY)).toBe(
      "Taller de Mundo",
    );
    expect(getCurrentTaller()).toBe("Taller de Mundo");
  });

  it("clears the persisted taller and falls back to DEFAULT_TALLER", () => {
    setCurrentTaller("Taller de Mundo");
    clearCurrentTaller();
    expect(window.localStorage.getItem(ACTIVE_TALLER_STORAGE_KEY)).toBeNull();
    expect(getCurrentTaller()).toBe(DEFAULT_TALLER);
  });

  it("notifies subscribers on set and clear", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeCurrentTaller(listener);

    setCurrentTaller("Taller de Mundo");
    expect(listener).toHaveBeenCalledTimes(1);

    clearCurrentTaller();
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
  });

  it("stops notifying subscribers after unsubscribe", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeCurrentTaller(listener);
    unsubscribe();

    setCurrentTaller("Taller de Mundo");
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