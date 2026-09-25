import { useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { MessageKey } from "@/i18n/messages";

const STORAGE_KEY = "sidebar-tab";

export type SidebarTab = "asistente" | "contexto";

const TABS: { id: SidebarTab; labelKey: MessageKey }[] = [
  { id: "asistente", labelKey: "tab.asistente" },
  { id: "contexto", labelKey: "tab.contexto" },
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
  const { t } = useAppLanguage();
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
      className="flex border-b border-edge"
      role="tablist"
      aria-label={t("tab.aria")}
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
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-action/50",
            active === tab.id
              ? "border-b-2 border-action text-primary"
              : "text-muted hover:text-primary hover:bg-surface-hover/50",
          )}
        >
          {t(tab.labelKey)}
        </button>
      ))}
    </div>
  );
}
