import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { WikiHomeLayout } from "@/components/templates/WikiHomeLayout";
import GraphView from "@/components/GraphView";
import ProposalsPanel from "@/components/organisms/ProposalsPanel";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { EmptyState } from "@/components/organisms/EmptyState";
import { Icon } from "@/components/atoms/Icon";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { applyRelationReconcile, fetchRelationReconcilePreview } from "@/api/graph";
import type { RelationReconcilePreview } from "@/api/types";
import type { MessageKey } from "@/i18n/messages";
import { cn } from "@/lib/utils";

type TabKey = "grafo" | "conflictos" | "propuestas";

const REASON_MESSAGES: Record<string, MessageKey> = {
  "redundant-folder": "relaciones.reconcile.reason.redundant-folder",
  ungrounded: "relaciones.reconcile.reason.ungrounded",
  unresolved: "relaciones.reconcile.reason.unresolved",
  rejected: "relaciones.reconcile.reason.rejected",
};

const TABS: readonly { key: TabKey; label: MessageKey }[] = [
  { key: "grafo", label: "relaciones.tab.grafo" },
  { key: "conflictos", label: "relaciones.tab.conflictos" },
  { key: "propuestas", label: "relaciones.tab.propuestas" },
];

/**
 * Relaciones y Canon page (`/taller-mundo/:mundo/relaciones-canon`) — W9/W12.
 *
 * The header carries the world-wide "Sincronizar relaciones" action, visible in
 * every tab because it belongs to the world, not to one panel: it aligns the
 * graph with what the text says (adds what is missing, removes what no text
 * backs) behind a preview and a pre-image backup.
 *
 * Tabs: "Grafo" renders the GraphView, "Propuestas" the on-demand semantic
 * sweep, and "Conflictos" is still a follow-up slice.
 */
export default function RelacionesCanon() {
  const { t } = useAppLanguage();
  const { mundo } = useParams<{ mundo: string }>();
  const [activeTab, setActiveTab] = useState<TabKey>("grafo");
  const [preview, setPreview] = useState<RelationReconcilePreview | null>(null);
  const [syncOpen, setSyncOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState("");
  const [syncNotice, setSyncNotice] = useState("");
  const [graphVersion, setGraphVersion] = useState(0);

  const refreshPreview = useCallback(async () => {
    if (!mundo) return;
    try {
      setPreview(await fetchRelationReconcilePreview(mundo));
    } catch {
      setPreview(null);
    }
  }, [mundo]);

  useEffect(() => {
    void refreshPreview();
  }, [refreshPreview]);

  const openSync = async () => {
    if (!mundo) return;
    if (preview === null) {
      await refreshPreview();
    }
    setSyncNotice("");
    setSyncOpen(true);
  };

  const applySync = async () => {
    if (!mundo) return;
    setSyncing(true);
    setSyncError("");
    try {
      const result = await applyRelationReconcile(mundo);
      setSyncOpen(false);
      setGraphVersion((version) => version + 1);
      await refreshPreview();
      setSyncNotice(
        t("relaciones.reconcile.applied", {
          files: result.applied,
          backup: result.backup,
        }),
      );
      if (result.failed.length > 0) {
        setSyncError(
          t("relaciones.reconcile.failed", { count: result.failed.length }),
        );
      }
    } catch {
      setSyncError(t("relaciones.propuestas.actionError"));
    } finally {
      setSyncing(false);
    }
  };

  const syncLabel = preview === null
    ? t("relaciones.reconcile.button.base")
    : preview.files === 0
      ? t("relaciones.reconcile.button.zero")
      : preview.files === 1
        ? t("relaciones.reconcile.button.one")
        : t("relaciones.reconcile.button.many", { count: preview.files });

  // The graph gets the whole viewport under the app header (3.5rem + 1px):
  // a fixed 1280px container and 18rem of reserved height wasted both axes.
  const isGraph = activeTab === "grafo";

  return (
    <WikiHomeLayout bleed={isGraph}>
      <div
        className={cn(
          "col-span-full flex flex-wrap items-start justify-between gap-3",
          isGraph && "border-b border-edge px-4 py-2",
        )}
      >
        <div className={cn(isGraph && "flex items-baseline gap-3")}>
          <h1 className="font-heading text-h3 text-primary">
            {t("relaciones.title")}
          </h1>
          <p className={cn("mt-2 text-body text-muted", isGraph && "mt-0 hidden md:block")}>
            {t("relaciones.intro")}
          </p>
        </div>
        <button
          type="button"
          data-testid="sync-button"
          title={t("relaciones.reconcile.button.title")}
          onClick={openSync}
          disabled={syncing || (preview !== null && preview.files === 0)}
          className="rounded-lg border border-edge px-4 py-2 text-small font-medium text-primary transition-colors hover:border-action hover:text-action disabled:cursor-not-allowed disabled:opacity-50"
        >
          {syncing ? t("relaciones.reconcile.checking") : syncLabel}
        </button>
      </div>

      {syncNotice ? (
        <p className="col-span-full text-small text-muted">{syncNotice}</p>
      ) : null}
      {syncError ? (
        <p role="alert" className="col-span-full text-small text-danger">
          {syncError}
        </p>
      ) : null}

      <div className={cn("col-span-full", isGraph && "flex min-h-0 flex-1 flex-col")}>
        <div
          role="tablist"
          aria-label={t("relaciones.tabsAria")}
          className={cn(
            "mb-4 flex gap-2 border-b border-edge",
            isGraph && "mb-0 px-4",
          )}
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
            <div className={cn(isGraph && "min-h-0 flex-1")}>
              <GraphView key={graphVersion} mundo={mundo} bleed={isGraph} />
            </div>
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

      {syncOpen && preview ? (
        <ConfirmDialog
          title={t("relaciones.reconcile.confirmTitle")}
          message={t("relaciones.reconcile.confirmMessage", {
            files: preview.files,
            additions: preview.additions,
            removals: preview.removals,
          })}
          confirmLabel={t("relaciones.reconcile.apply")}
          confirmVariant="danger"
          isBusy={syncing}
          onConfirm={applySync}
          onClose={() => setSyncOpen(false)}
        >
          <p className="text-small font-medium text-primary">
            {t("relaciones.reconcile.listTitle")}
          </p>
          <ul className="mt-1 flex max-h-64 flex-col gap-1 overflow-auto text-small text-muted">
            {preview.items.map((item) => (
              <li key={item.path}>
                <details>
                  <summary className="cursor-pointer select-none">
                    <span className="text-primary">{item.path}</span>
                    {" · "}
                    {t("relaciones.reconcile.additions", {
                      count: item.add.length,
                    })}
                    {" · "}
                    {t("relaciones.reconcile.removals", {
                      count: item.remove.length,
                    })}
                  </summary>
                  {item.add.length > 0 ? (
                    <div className="mt-1 pl-4">
                      <p className="text-primary">
                        {t("relaciones.reconcile.addList")}
                      </p>
                      <ul className="list-disc pl-4">
                        {item.add.map((target) => (
                          <li key={target}>{target}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {item.remove.length > 0 ? (
                    <div className="mt-1 pl-4">
                      <p className="text-primary">
                        {t("relaciones.reconcile.removeList")}
                      </p>
                      <ul className="list-disc pl-4">
                        {item.remove.map((removal) => (
                          <li key={removal.key}>
                            {removal.key}
                            {removal.target_id &&
                            removal.target_id !== removal.key
                              ? ` → ${removal.target_id}`
                              : ""}
                            {" · "}
                            {REASON_MESSAGES[removal.reason]
                              ? t(REASON_MESSAGES[removal.reason])
                              : removal.reason}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </details>
              </li>
            ))}
          </ul>
        </ConfirmDialog>
      ) : null}
    </WikiHomeLayout>
  );
}
