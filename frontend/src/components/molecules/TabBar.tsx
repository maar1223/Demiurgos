import { useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { Icon } from "@/components/atoms/Icon";
import { Tooltip } from "@/components/atoms/Tooltip";
import {
  setAutoWidenPreference,
  useAutoWidenPreference,
} from "@/lib/panelAutoWiden";
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
  const autoWiden = useAutoWidenPreference();
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
    <div className="flex items-stretch border-b border-edge">
      <div
        role="tablist"
        aria-label={t("tab.aria")}
        className="flex min-w-0 flex-1"
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
      {/* The automatic behavior only applies from `xl` up (the same threshold
          `panelAutoWiden` uses): below it the extra width barely exists, so a
          toggle would promise something it cannot deliver. */}
      <span className="hidden shrink-0 xl:inline-flex">
        <Tooltip
          id="assistant-auto-widen-tip"
          content={t(autoWiden ? "tab.autoWiden.on" : "tab.autoWiden.off")}
          triggerTabIndex={-1}
        >
          <button
            type="button"
            // The toggle must not count as assistant interaction: clicking it
            // would otherwise widen the panel right before disabling the rule.
            data-auto-widen-ignore
            aria-pressed={autoWiden}
            aria-label={t("tab.autoWiden.aria")}
            aria-describedby="assistant-auto-widen-tip"
            onClick={() => setAutoWidenPreference(!autoWiden)}
            className={cn(
              "flex h-full items-center px-3 transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-action/50",
              autoWiden
                ? "text-action hover:bg-surface-hover/50"
                : "text-muted hover:text-primary hover:bg-surface-hover/50",
            )}
          >
            <Icon name={autoWiden ? "expand" : "minimize"} size={16} />
          </button>
        </Tooltip>
      </span>
    </div>
  );
}
