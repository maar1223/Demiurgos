import { describe, expect, it } from "vitest";
import { API_BASE_URL } from "@/lib/constants";

describe("constants", () => {
  it("keeps API_BASE_URL empty (same-origin) for release builds (S1-7)", () => {
    // VITE_API_URL is a DEV-ONLY override (frontend/src/lib/constants.ts:3).
    // The release SPA is served same-origin by the backend catch-all (S1), so
    // a build that bakes an absolute http(s):// origin would call the wrong
    // host in production and appear broken. This assertion is the guard: it
    // fails the frontend suite the moment VITE_API_URL leaks into the
    // environment the tests/build run under.
    expect(API_BASE_URL).toBe("");
  });
});