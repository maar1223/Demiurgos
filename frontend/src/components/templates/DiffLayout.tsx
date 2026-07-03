import type { ReactNode } from "react";

interface DiffLayoutProps {
  /** Navigation header (Navbar). */
  header: ReactNode;
  /** Content rendered inside the diff layout. Expected to be DiffViewer. */
  children: ReactNode;
}

/**
 * Layout for the Diff view page.
 *
 * Desktop: side-by-side diff panels (handled by DiffViewer).
 * Mobile: stacks to single-column (handled by DiffViewer's singleColumn prop).
 *
 * The layout provides the overall page structure: header + content area.
 */
export function DiffLayout({ header, children }: DiffLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-cripta">
      {header}

      <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col px-4 py-6 md:px-8 lg:px-12">
        {children}
      </div>
    </div>
  );
}
