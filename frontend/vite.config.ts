import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { execFileSync } from "node:child_process";
import { porcelainIsDirty } from "./src/lib/buildInfo";

/** Build identity (plan A): the served bundle must identify itself, because
 *  the API serves the gitignored `dist` and a stale bundle is otherwise
 *  invisible. Runs once per `vite build`; a missing git binary degrades to an
 *  empty sha (the UI then shows `dev`). */
function gitValue(args: string[]): string {
  try {
    return execFileSync("git", args, { cwd: __dirname, encoding: "utf8" }).trim();
  } catch {
    return "";
  }
}

const BUILD_SHA = gitValue(["rev-parse", "--short", "HEAD"]);
const BUILD_TIME = new Date().toISOString();
// Vite writes its temporary config bundle inside the project before this file
// is evaluated, so the porcelain output is filtered: a clean tree must NOT be
// stamped "uncommitted".
const BUILD_DIRTY = porcelainIsDirty(gitValue(["status", "--porcelain"]));

export default defineConfig({
  define: {
    __BUILD_SHA__: JSON.stringify(BUILD_SHA),
    __BUILD_TIME__: JSON.stringify(BUILD_TIME),
    __BUILD_DIRTY__: JSON.stringify(BUILD_DIRTY),
  },
  // Same-origin SPA (S1): the backend catch-all serves the built app from
  // /, so the bundle must never assume a sub-path base or a non-default
  // output dir. Explicit pins (S1-7), not functional changes.
  base: "/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "dist",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
