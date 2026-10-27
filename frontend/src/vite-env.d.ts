/// <reference types="vite/client" />

// Build identity injected by Vite's `define` (see `vite.config.ts`). Declared
// here so `tsc --noEmit` sees them; at runtime they are plain constants that
// Vite replaces during `vite build`.
declare const __BUILD_SHA__: string;
declare const __BUILD_TIME__: string;
declare const __BUILD_DIRTY__: boolean;
