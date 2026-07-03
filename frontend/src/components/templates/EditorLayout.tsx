import { useState, type ReactNode } from "react";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

interface EditorLayoutProps {
  header: ReactNode;
  sidebar: ReactNode;
  children: ReactNode;
}

/**
 * Layout for the Wiki Editor page.
 *
 * Desktop: sidebar (280px) + content area side-by-side.
 * Mobile: sidebar collapses to overlay with hamburger toggle.
 *
 * The sidebar slot receives the FileTree. The children slot receives the
 * MarkdownViewer (or breadcrumb + content).
 */
export function EditorLayout({ header, sidebar, children }: EditorLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-col bg-cripta">
      {header}

      <div className="relative flex flex-1">
        {/* Mobile sidebar overlay toggle */}
        <button
          type="button"
          onClick={() => setSidebarOpen((prev) => !prev)}
          className="fixed bottom-4 right-4 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-llamita text-cripta shadow-lg hover:bg-llama-alta md:hidden"
          aria-label={sidebarOpen ? "Cerrar panel" : "Abrir panel"}
          aria-expanded={sidebarOpen}
        >
          <Icon name={sidebarOpen ? "close" : "menu"} size={20} />
        </button>

        {/* Sidebar — desktop: static 280px, mobile: overlay */}
        <aside
          className={cn(
            "border-r border-filio bg-madero",
            // Desktop: always visible, fixed width
            "hidden md:block md:w-[280px] lg:w-[280px]",
            // Mobile: overlay with transition
            "fixed inset-y-0 left-0 z-30 w-[280px] translate-x-0 transition-transform duration-200 ease-in-out md:relative md:inset-auto md:translate-x-0",
            !sidebarOpen && "-translate-x-full md:translate-x-0",
          )}
        >
          {/* Mobile close button inside sidebar */}
          <div className="flex items-center justify-between border-b border-filio px-4 py-3 md:hidden">
            <span className="text-small text-tinta-desvaida">Archivos</span>
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              className="text-plata hover:text-pergamino"
              aria-label="Cerrar panel"
            >
              <Icon name="close" size={16} />
            </button>
          </div>

          {/* Sidebar content */}
          <div className="overflow-y-auto py-2">
            {sidebar}
          </div>
        </aside>

        {/* Mobile backdrop */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-20 bg-cripta/60 backdrop-blur-sm md:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Main content area */}
        <main className="min-w-0 flex-1 overflow-y-auto px-4 py-6 md:px-8 lg:px-12">
          {children}
        </main>
      </div>
    </div>
  );
}
