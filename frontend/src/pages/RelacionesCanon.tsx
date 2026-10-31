import { useState } from "react";
import { useParams } from "react-router-dom";
import { WikiHomeLayout } from "@/components/templates/WikiHomeLayout";
import GraphView from "@/components/GraphView";
import ProposalsPanel from "@/components/organisms/ProposalsPanel";
import { EmptyState } from "@/components/organisms/EmptyState";
import { Icon } from "@/components/atoms/Icon";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { MessageKey } from "@/i18n/messages";
import { cn } from "@/lib/utils";

type TabKey = "grafo" | "conflictos" | "propuestas";

const TABS: readonly { key: TabKey; label: MessageKey }[] = [
  { key: "grafo", label: "relaciones.tab.grafo" },
  { key: "conflictos", label: "relaciones.tab.conflictos" },
  { key: "propuestas", label: "relaciones.tab.propuestas" },
];

/**
 * Relaciones y Canon page (`/taller-mundo/:mundo/relaciones-canon`) — W9/W12.
 *
 * Three-tab shell (BLOQUE 4 · Slice A): "Grafo" is active by default and
 * renders the GraphView; "Propuestas" renders the on-demand semantic sweep;
 * "Conflictos" is still a follow-up slice and renders a placeholder.
 */
export default function RelacionesCanon() {
  const { t } = useAppLanguage();
  const { mundo } = useParams<{ mundo: string }>();
  const [activeTab, setActiveTab] = useState<TabKey>("grafo");

  return (
    <WikiHomeLayout>
      <div className="col-span-full">
        <h1 className="font-heading text-h3 text-primary">
          {t("relaciones.title")}
        </h1>
        <p className="mt-2 text-body text-muted">{t("relaciones.intro")}</p>
      </div>

      <div className="col-span-full">
        <div
          role="tablist"
          aria-label={t("relaciones.tabsAria")}
          className="mb-4 flex gap-2 border-b border-edge"
        >
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                "border-b-2 px-4 py-2 text-small font-medium transition-colors",
                activeTab === tab.key
                  ? "border-action text-action"
                  : "border-transparent text-muted hover:text-primary",
              )}
            >
              {t(tab.label)}
            </button>
          ))}
        </div>

        {activeTab === "grafo" ? (
          mundo ? (
            <GraphView mundo={mundo} />
          ) : (
            <EmptyState
              icon="error"
              message={t("relaciones.missingParams")}
            />
          )
        ) : activeTab === "propuestas" ? (
          mundo ? (
            <ProposalsPanel mundo={mundo} />
          ) : (
            <EmptyState
              icon="error"
              message={t("relaciones.missingParams")}
            />
          )
        ) : (
          <div
            data-testid="placeholder-panel"
            className="flex flex-col items-center justify-center gap-2 rounded-xl border border-edge bg-surface-raised py-24"
          >
            <Icon name="lightbulb" size={32} className="text-muted" />
            <p className="text-body text-muted">{t("nav.soon")}</p>
          </div>
        )}
      </div>
    </WikiHomeLayout>
  );
}