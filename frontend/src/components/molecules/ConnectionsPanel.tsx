import { Badge } from "@/components/atoms/Badge";
import { Icon, type IconName } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";
import { useAppLanguage } from "@/hooks/useAppLanguage";

/** Short status summary for a connection row: a label plus a Badge variant. */
export interface ConnectionStatusSummary {
  label: string;
  variant: "default" | "success" | "error" | "warning" | "info";
}

/** One connection entry: its index row and the body shown in the detail region. */
export interface ConnectionDef {
  id: string;
  icon: IconName;
  title: string;
  subtitle: string;
  status?: ConnectionStatusSummary;
  body: React.ReactNode;
}

interface ConnectionsPanelProps {
  connections: ConnectionDef[];
  activeId: string;
  onSelect: (id: string) => void;
}

/**
 * Conexiones — one connection-card family: a `role="group"` index of toggle
 * rows plus a single detail region. This is NOT a tablist (the page's section
 * rail owns the only `role="tablist"`) and NOT a pure accordion (an expanded
 * first card would push the second below the fold).
 *
 * Both bodies stay mounted and the inactive one is `hidden`, so each wizard
 * keeps its step state and its status reads stay warm. The shared row anatomy
 * is a leading `Icon`, an `h3` whose accessible name is EXACTLY the title
 * (subtitle and status `Badge` live outside the heading, chevron is
 * `aria-hidden`), a one-line subtitle and the trailing status badge.
 */
export function ConnectionsPanel({
  connections,
  activeId,
  onSelect,
}: ConnectionsPanelProps) {
  const { t } = useAppLanguage();
  return (
    <div className="space-y-4">
      <div
        role="group"
        aria-label={t("connections.aria")}
        className="overflow-hidden rounded-lg border border-edge bg-surface-raised"
      >
        {connections.map((connection, index) => {
          const active = activeId === connection.id;
          return (
            <div
              key={connection.id}
              className={cn(
                "flex items-start gap-3 p-4",
                index > 0 && "border-t border-edge",
              )}
            >
              <Icon
                name={connection.icon}
                size={18}
                className="mt-0.5 text-icon-muted"
              />
              <div className="min-w-0 flex-1">
                <h3
                  id={`connection-${connection.id}-heading`}
                  className="font-heading text-body text-primary"
                >
                  <button
                    type="button"
                    aria-expanded={active}
                    aria-controls={`connection-${connection.id}-body`}
                    onClick={() => onSelect(connection.id)}
                    className="flex w-full items-center justify-between gap-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-icon-muted/50"
                  >
                    <span>{connection.title}</span>
                    <Icon
                      name={active ? "chevron-down" : "chevron-right"}
                      size={16}
                      aria-hidden="true"
                      className="text-icon-muted"
                    />
                  </button>
                </h3>
                <p className="mt-0.5 text-small text-muted">
                  {connection.subtitle}
                </p>
              </div>
              {connection.status && (
                <Badge variant={connection.status.variant}>
                  {connection.status.label}
                </Badge>
              )}
            </div>
          );
        })}
      </div>

      {connections.map((connection) => (
        <section
          key={connection.id}
          id={`connection-${connection.id}-body`}
          hidden={activeId !== connection.id}
          aria-labelledby={`connection-${connection.id}-heading`}
          className="rounded-lg border border-edge bg-surface-raised p-4"
        >
          {connection.body}
        </section>
      ))}
    </div>
  );
}
