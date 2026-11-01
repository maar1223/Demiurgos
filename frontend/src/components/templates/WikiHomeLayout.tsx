import type { ReactNode } from "react";

interface WikiHomeLayoutProps {
  /** Optional in-page header slot. The global Navbar is hoisted to the shared
   *  AppLayout, so pages no longer pass it here. */
  header?: ReactNode;
  children: ReactNode;
  /** Drop the max-width container and the page padding: the page manages its
   *  own full-bleed area (the graph canvas needs the whole viewport). */
  bleed?: boolean;
}

/**
 * Layout for the Wiki Home page.
 * Renders the optional global header slot and a responsive card grid.
 */
export function WikiHomeLayout({ header, children, bleed }: WikiHomeLayoutProps) {
  return (
    <div
      className={
        bleed
          ? // The Navbar is 3.5rem + 1px tall and lives outside this layout,
            // so a full-viewport page must subtract it (EditorLayout does the
            // same) or the document always scrolls by the header height.
            // A definite HEIGHT, not min-height: everything below uses
            // ``h-full``/``flex-1`` and a percentage height needs a resolved
            // ancestor, otherwise the canvas collapses to zero.
            "flex h-[calc(100vh-3.5rem-1px)] flex-col overflow-hidden bg-surface supports-[height:100dvh]:h-[calc(100dvh-3.5rem-1px)]"
          : "flex min-h-screen flex-col bg-surface"
      }
    >
      {header}
      <main
        className={
          bleed
            ? "flex w-full flex-1 flex-col"
            : "mx-auto w-full max-w-7xl flex-1 px-4 py-8"
        }
      >
        <div
          className={
            bleed
              ? "flex min-h-0 flex-1 flex-col"
              : "grid grid-cols-1 gap-4 tablet:grid-cols-2 desktop:grid-cols-3"
          }
        >
          {children}
        </div>
      </main>
    </div>
  );
}
