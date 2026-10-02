import { describe, it, expect, beforeEach, afterEach } from "vitest";
import {
  completeFirstValueHandoff,
  getFirstValueHandoffPending,
  isFirstValueHandoffPending,
  markFirstValueHandoffPending,
} from "@/lib/firstValueHandoff";
import { FIRST_VALUE_HANDOFF_PENDING_KEY } from "@/lib/constants";

describe("firstValueHandoff pending flag", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("reads [] when nothing is stored", () => {
    expect(getFirstValueHandoffPending()).toEqual([]);
  });

  it("marks a world pending and reads it back", () => {
    markFirstValueHandoffPending("mi-mundo");
    expect(getFirstValueHandoffPending()).toEqual(["mi-mundo"]);
    expect(isFirstValueHandoffPending("mi-mundo")).toBe(true);
    expect(
      window.localStorage.getItem(FIRST_VALUE_HANDOFF_PENDING_KEY),
    ).toBe('["mi-mundo"]');
  });

  it("marking is idempotent (at-most-once add)", () => {
    markFirstValueHandoffPending("a");
    markFirstValueHandoffPending("a");
    expect(getFirstValueHandoffPending()).toEqual(["a"]);
  });

  it("an unknown world is never pending", () => {
    expect(isFirstValueHandoffPending("fantasma")).toBe(false);
  });

  it("completes a world and removes it from the list", () => {
    markFirstValueHandoffPending("a");
    markFirstValueHandoffPending("b");
    completeFirstValueHandoff("a");
    expect(getFirstValueHandoffPending()).toEqual(["b"]);
    expect(isFirstValueHandoffPending("a")).toBe(false);
  });

  it("completing is idempotent and keeps unrelated worlds", () => {
    markFirstValueHandoffPending("a");
    completeFirstValueHandoff("a");
    completeFirstValueHandoff("a");
    expect(getFirstValueHandoffPending()).toEqual([]);
  });

  it("reads [] for malformed storage", () => {
    window.localStorage.setItem(
      FIRST_VALUE_HANDOFF_PENDING_KEY,
      "{not-json",
    );
    expect(getFirstValueHandoffPending()).toEqual([]);

    window.localStorage.setItem(
      FIRST_VALUE_HANDOFF_PENDING_KEY,
      JSON.stringify({ nope: true }),
    );
    expect(getFirstValueHandoffPending()).toEqual([]);

    // Non-string entries are filtered out.
    window.localStorage.setItem(
      FIRST_VALUE_HANDOFF_PENDING_KEY,
      JSON.stringify(["ok", 42, null]),
    );
    expect(getFirstValueHandoffPending()).toEqual(["ok"]);
  });
});