/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  // Theme is driven by the `.dark` class on <html> (set by the anti-FOUC
  // inline script in index.html and by hooks/useTheme).
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Brand role tokens (PR-1 theme infrastructure). Flat keys backed by
        // CSS variables holding "R G B" channels; <alpha-value> makes the
        // /opacity modifiers work. Light values live in :root, dark in
        // :root.dark (see src/styles/globals.css).
        surface: "rgb(var(--color-surface) / <alpha-value>)",
        "surface-raised": "rgb(var(--color-surface-raised) / <alpha-value>)",
        "surface-hover": "rgb(var(--color-surface-hover) / <alpha-value>)",
        "surface-active": "rgb(var(--color-surface-active) / <alpha-value>)",
        primary: "rgb(var(--color-primary) / <alpha-value>)",
        detail: "rgb(var(--color-detail) / <alpha-value>)",
        muted: "rgb(var(--color-muted) / <alpha-value>)",
        edge: "rgb(var(--color-edge) / <alpha-value>)",
        action: "rgb(var(--color-action) / <alpha-value>)",
        "action-hover": "rgb(var(--color-action-hover) / <alpha-value>)",
        "action-text": "rgb(var(--color-action-text) / <alpha-value>)",
        "status-success": "rgb(var(--color-status-success) / <alpha-value>)",
        "status-error": "rgb(var(--color-status-error) / <alpha-value>)",
        "diff-gutter": "rgb(var(--color-diff-gutter) / <alpha-value>)",
        "icon-muted": "rgb(var(--color-icon-muted) / <alpha-value>)",
      },
      fontFamily: {
        heading: ["Space Grotesk", "sans-serif"],
        body: ["Inter", "sans-serif"],
      },
      fontSize: {
        // Tool-density type scale (~12% tighter than the previous content
        // scale): dense UIs read better at 14px body with compact headings.
        display: ["2.25rem", { lineHeight: "1.1", fontWeight: "700" }], // 36px
        h1: ["2rem", { lineHeight: "1.2", fontWeight: "700" }], // 32px
        h2: ["1.625rem", { lineHeight: "1.3", fontWeight: "600" }], // 26px
        h3: ["1.25rem", { lineHeight: "1.4", fontWeight: "600" }], // 20px
        h4: ["1.0625rem", { lineHeight: "1.4", fontWeight: "600" }], // 17px
        body: ["0.875rem", { lineHeight: "1.6", fontWeight: "400" }], // 14px
        small: ["0.8125rem", { lineHeight: "1.5", fontWeight: "400" }], // 13px
        xs: ["0.6875rem", { lineHeight: "1.4", fontWeight: "400" }], // 11px
      },
      screens: {
        mobile: { max: "767px" },
        tablet: { min: "768px", max: "1199px" },
        desktop: "1200px",
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};
