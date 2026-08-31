import type { ReactNode } from "react";

interface WikiHomeLayoutProps {
  /** Optional in-page header slot. The global Navbar is hoisted to the shared
   *  AppLayout, so pages no longer pass it here. */
  header?: ReactNode;
  children: ReactNode;
}

/**
 * Layout for the Wiki Home page.
 * Renders the optional global header slot and a responsive card grid.
 */
export function WikiHomeLayout({ header, children }: WikiHomeLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-surface">
      {header}
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">
        <div className="grid grid-cols-1 gap-4 tablet:grid-cols-2 desktop:grid-cols-3">
          {children}
        </div>
      </main>
    </div>
  );
}
