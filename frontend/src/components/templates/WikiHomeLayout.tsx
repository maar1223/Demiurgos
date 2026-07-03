import type { ReactNode } from "react";

interface WikiHomeLayoutProps {
  header: ReactNode;
  children: ReactNode;
}

/**
 * Layout for the Wiki Home page.
 * Renders the global header and a responsive card grid.
 */
export function WikiHomeLayout({ header, children }: WikiHomeLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-cripta">
      {header}
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">
        <div className="grid grid-cols-1 gap-4 tablet:grid-cols-2 desktop:grid-cols-3">
          {children}
        </div>
      </main>
    </div>
  );
}
