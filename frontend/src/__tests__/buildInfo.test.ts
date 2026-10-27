import { afterEach, describe, expect, it } from "vitest";
import { porcelainIsDirty, readFrontendBuildInfo } from "@/lib/buildInfo";

/** The build stamp is injected by Vite's `define` at build time; under vitest
 *  (and `vite dev`) those globals do not exist, so the reader must degrade
 *  instead of throwing. */
const globals = globalThis as unknown as Record<string, unknown>;

afterEach(() => {
  delete globals.__BUILD_SHA__;
  delete globals.__BUILD_TIME__;
  delete globals.__BUILD_DIRTY__;
});

describe("readFrontendBuildInfo", () => {
  it("degrades to an explicit empty stamp when the build globals are absent", () => {
    expect(readFrontendBuildInfo()).toEqual({
      sha: "",
      time: "",
      dirty: false,
    });
  });

  it("reads the injected sha, time and dirty flag", () => {
    globals.__BUILD_SHA__ = "abc1234";
    globals.__BUILD_TIME__ = "2026-10-26T18:40:00.000Z";
    globals.__BUILD_DIRTY__ = true;

    expect(readFrontendBuildInfo()).toEqual({
      sha: "abc1234",
      time: "2026-10-26T18:40:00.000Z",
      dirty: true,
    });
  });

  it("ignores a malformed stamp instead of rendering garbage", () => {
    globals.__BUILD_SHA__ = 42;
    globals.__BUILD_TIME__ = null;
    globals.__BUILD_DIRTY__ = "yes";

    expect(readFrontendBuildInfo()).toEqual({
      sha: "",
      time: "",
      dirty: false,
    });
  });
});

describe("porcelainIsDirty", () => {
  it("is clean for empty output", () => {
    expect(porcelainIsDirty("")).toBe(false);
  });

  it("flags a real uncommitted change", () => {
    expect(porcelainIsDirty(" M frontend/src/App.tsx\n")).toBe(true);
    expect(porcelainIsDirty("?? frontend/src/lib/newThing.ts\n")).toBe(true);
  });

  it("ignores Vite's own timestamped config bundle", () => {
    // Vite writes this inside the project BEFORE evaluating vite.config.ts, so
    // a clean tree would otherwise be stamped "uncommitted" on every build.
    expect(
      porcelainIsDirty(
        "?? vite.config.ts.timestamp-1793055135956-0563c17a3b19a.mjs\n",
      ),
    ).toBe(false);
  });

  it("still flags a real change next to Vite's temp file", () => {
    expect(
      porcelainIsDirty(
        "?? vite.config.ts.timestamp-1793055135956-0563c17a3b19a.mjs\n M src/App.tsx\n",
      ),
    ).toBe(true);
  });
});
