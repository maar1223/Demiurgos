/** Build-time stamp injected by Vite's `define` (see `frontend/vite.config.ts`).
 *
 *  The backend serves the prebuilt, gitignored `frontend/dist`, so the UI must
 *  be able to identify the bundle it is actually running: `vitest` and `tsc`
 *  can be green while the served `dist` lags behind `frontend/src`. Every value
 *  is read defensively — under `vite dev` and vitest the globals do not exist,
 *  and a missing stamp must degrade to `dev` instead of throwing.
 */
export interface FrontendBuildInfo {
  sha: string;
  time: string;
  dirty: boolean;
}

export function readFrontendBuildInfo(): FrontendBuildInfo {
  return {
    sha: typeof __BUILD_SHA__ === "string" ? __BUILD_SHA__ : "",
    time: typeof __BUILD_TIME__ === "string" ? __BUILD_TIME__ : "",
    dirty: typeof __BUILD_DIRTY__ === "boolean" ? __BUILD_DIRTY__ : false,
  };
}

/** Vite's own temporary config bundle, written INSIDE the project directory
 *  before `vite.config.ts` is evaluated. `git status --porcelain` therefore
 *  always reports it as untracked, which would stamp every clean build as
 *  "uncommitted". It is a build artifact, never a source change. */
const VITE_TEMP_CONFIG = /vite\.config\.ts\.timestamp-[0-9A-Za-z-]+\.m?js$/;

/** True when `git status --porcelain` output holds a real change. */
export function porcelainIsDirty(output: string): boolean {
  return output
    .split("\n")
    .map((line) => line.trimEnd())
    .some((line) => line !== "" && !VITE_TEMP_CONFIG.test(line));
}

/** `sha · time [· dirtyLabel]`, or the `dev` marker when nothing was injected. */
export function formatFrontendBuild(
  info: FrontendBuildInfo,
  dirtyLabel: string,
): string {
  if (!info.sha) return "dev";
  return [info.sha, info.time, info.dirty ? dirtyLabel : ""]
    .filter(Boolean)
    .join(" · ");
}
