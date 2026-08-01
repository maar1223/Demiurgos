import { useState, useCallback } from "react";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "sidebar-tab";

export type SidebarTab = "asistente" | "contexto";

const TABS: { id: SidebarTab; label: string }[] = [
  { id: "asistente", label: "Asistente" },
  { id: "contexto", label: "Contexto" },
];

interface TabBarProps {
  /** Optional externally-controlled active tab (defaults to sessionStorage) */
  activeTab?: SidebarTab;
  /** Called when the active tab changes */
  onTabChange?: (tab: SidebarTab) => void;
}

/**
 * Two-button tab bar for sidebar panels: [Asistente] | [Contexto].
 *
 * Reads initial active state from `sessionStorage` key `sidebar-tab`,
 * falling back to `"asistente"`. Persists tab changes to sessionStorage
 * for cross-navigation persistence (spec EB3).
 *
 * Used in WikiEditor and EntityPage sidebars to switch between
 * the AI Assistant panel and the entity context panel.
 */
export function TabBar({
  activeTab: controlledTab,
  onTabChange,
}: TabBarProps) {
  const [internalTab, setInternalTab] = useState<SidebarTab>(() => {
    if (typeof window === "undefined") return "asistente";
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored === "asistente" || stored === "contexto") return stored;
    return "asistente";
  });

  const active = controlledTab ?? internalTab;

  const handleClick = useCallback(
    (tab: SidebarTab) => {
      if (typeof window !== "undefined") {
        sessionStorage.setItem(STORAGE_KEY, tab);
      }
      setInternalTab(tab);
      onTabChange?.(tab);
    },
    [onTabChange],
  );

  return (
    <div
      className="flex border-b border-filio"
      role="tablist"
      aria-label="Panel lateral"
    >
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          onClick={() => handleClick(tab.id)}
          className={cn(
            "flex-1 px-3 py-2 text-small font-medium transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-llamita/50",
            active === tab.id
              ? "border-b-2 border-llamita text-pergamino"
              : "text-sombra hover:text-tinta-desvaida hover:bg-piedra/50",
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
