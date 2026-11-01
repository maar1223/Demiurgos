import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { fetchConflicts, setConflictDecision } from "@/api/conflicts";
import type {
  ConflictCode,
  ConflictDecisionKind,
  ConflictsResponse,
  WorldConflict,
} from "@/api/conflicts";
import { EmptyState } from "@/components/organisms/EmptyState";
import type { MessageKey } from "@/i18n/messages";

interface ConflictsPanelProps {
  mundo: string;
}

/** One user-facing sentence per deterministic code (S8). */
const CODE_MESSAGES: Record<ConflictCode, MessageKey> = {
  version: "relaciones.conflictos.code.version",
  "missing-minimum": "relaciones.conflictos.code.missing-minimum",
  "unresolved-reference": "relaciones.conflictos.code.unresolved-reference",
  "ambiguous-reference": "relaciones.conflictos.code.ambiguous-reference",
  "duplicate-id": "relaciones.conflictos.code.duplicate-id",
  "dangling-relation": "relaciones.conflictos.code.dangling-relation",
  "self-relation": "relaciones.conflictos.code.self-relation",
  "canon-state-mismatch": "relaciones.conflictos.code.canon-state-mismatch",
};

const DECISION_ACTIONS: { kind: ConflictDecisionKind; label: MessageKey }[] = [
  { kind: "intentional", label: "relaciones.conflictos.decision.intentional" },
  { kind: "muted", label: "relaciones.conflictos.decision.muted" },
  { kind: "structural", label: "relaciones.conflictos.decision.structural" },
];

const itemClass =
  "w-full rounded-lg border border-edge bg-surface-raised p-3 text-left transition-colors hover:border-action";
const actionClass =
  "rounded-lg border border-edge px-2 py-1 text-small font-medium text-primary transition-colors hover:border-action hover:text-action disabled:cursor-not-allowed disabled:opacity-50";

/**
 * Conflictos — the deterministic conflict panel (S1) with the Author's
 * decisions (S2).
 *
 * It shows what the world's own structure contradicts and lets the Author
 * decide what each conflict means: intentional (known, never an error),
 * muted (grouped apart, recoverable) or a structural rupture. Nothing here
 * edits a ficha or calls a model: the panel records the decision and links to
 * the ficha.
 */
export default function ConflictsPanel({ mundo }: ConflictsPanelProps) {
  const { t } = useAppLanguage();
  const navigate = useNavigate();
  const [data, setData] = useState<ConflictsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      setData(await fetchConflicts(mundo));
    } catch {
      setLoadError(t("relaciones.conflictos.loadError"));
    } finally {
      setLoading(false);
    }
  }, [mundo, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = useMemo(() => {
    const items = data?.conflicts ?? [];
    const pending = (severity: string) => (conflict: WorldConflict) =>
      conflict.decision !== "intentional" &&
      conflict.decision !== "muted" &&
      conflict.severity === severity;
    return {
      errors: items.filter(pending("error")),
      warnings: items.filter(pending("warning")),
      known: items.filter((conflict) => conflict.decision === "intentional"),
      muted: items.filter((conflict) => conflict.decision === "muted"),
    };
  }, [data]);

  const decide = useCallback(
    async (conflict: WorldConflict, decision: ConflictDecisionKind | "clear") => {
      setBusy(true);
      setActionError("");
      try {
        setData(
          await setConflictDecision(mundo, {
            conflict_id: conflict.id,
            decision,
          }),
        );
      } catch {
        setActionError(t("relaciones.conflictos.actionError"));
      } finally {
        setBusy(false);
      }
    },
    [mundo, t],
  );

  const openFicha = useCallback(
    (conflict: WorldConflict) => {
      const name = encodeURIComponent(conflict.name);
      navigate(`/wiki/${encodeURIComponent(mundo)}/entity/${name}`);
    },
    [mundo, navigate],
  );

  const message = (conflict: WorldConflict): string => {
    const key = CODE_MESSAGES[conflict.code];
    if (!key) return conflict.message;
    const params: Record<string, string | number> = {};
    if (conflict.field) params.field = conflict.field;
    if (conflict.reference) params.reference = conflict.reference;
    return t(key, params);
  };

  const renderItem = (conflict: WorldConflict) => {
    const decided = conflict.decision !== null;
    return (
      <li key={conflict.id} data-testid="conflict-item">
        <div className="rounded-lg border border-edge bg-surface-raised p-3">
          <button
            type="button"
            className={itemClass}
            onClick={() => openFicha(conflict)}
            title={t("relaciones.conflictos.openFicha")}
          >
            <span className="block text-small font-medium text-primary">
              {conflict.name}
            </span>
            <span className="block truncate text-small text-muted">
              {conflict.path}
            </span>
            <span className="mt-1 block text-small text-secondary">
              {message(conflict)}
            </span>
            {conflict.decision === "structural" ? (
              <span
                data-testid="structural-badge"
                className="mt-1 inline-block rounded bg-danger/10 px-2 py-0.5 text-small font-medium text-danger"
              >
                {t("relaciones.conflictos.decision.structuralBadge")}
              </span>
            ) : null}
          </button>
          <div className="mt-2 flex flex-wrap gap-2">
            {decided ? (
              <button
                type="button"
                className={actionClass}
                disabled={busy}
                onClick={() => void decide(conflict, "clear")}
              >
                {t("relaciones.conflictos.decision.clear")}
              </button>
            ) : (
              DECISION_ACTIONS.map((action) => (
                <button
                  key={action.kind}
                  type="button"
                  className={actionClass}
                  disabled={busy}
                  onClick={() => void decide(conflict, action.kind)}
                >
                  {t(action.label)}
                </button>
              ))
            )}
          </div>
        </div>
      </li>
    );
  };

  const renderGroup = (title: string, items: WorldConflict[], testId: string) => {
    if (items.length === 0) return null;
    return (
      <section data-testid={testId} className="flex flex-col gap-2">
        <h2 className="text-small font-semibold uppercase tracking-wide text-muted">
          {title} ({items.length})
        </h2>
        <ul className="flex flex-col gap-2">{items.map(renderItem)}</ul>
      </section>
    );
  };

  if (loading && data === null) {
    return (
      <p data-testid="conflicts-loading" className="text-small text-muted">
        {t("relaciones.conflictos.loading")}
      </p>
    );
  }

  if (loadError) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p role="alert" className="text-small text-danger">
          {loadError}
        </p>
        <button
          type="button"
          data-testid="conflicts-retry"
          className="rounded-lg border border-edge px-3 py-1.5 text-small font-medium text-primary transition-colors hover:border-action hover:text-action"
          onClick={() => void load()}
        >
          {t("relaciones.conflictos.retry")}
        </button>
      </div>
    );
  }

  if (data === null || data.summary.total === 0) {
    return (
      <div data-testid="conflicts-empty">
        <EmptyState icon="check" message={t("relaciones.conflictos.empty")} />
        <p className="text-center text-small text-muted">
          {t("relaciones.conflictos.emptyHint")}
        </p>
      </div>
    );
  }

  return (
    <section data-testid="conflicts-panel" className="flex flex-col gap-4">
      <p data-testid="conflict-summary" className="text-small text-muted">
        {t("relaciones.conflictos.summary", {
          errors: data.summary.errors,
          warnings: data.summary.warnings,
          known: data.summary.known,
          muted: data.summary.muted,
        })}
      </p>
      {actionError ? (
        <p role="alert" className="text-small text-danger">
          {actionError}
        </p>
      ) : null}
      {renderGroup(t("relaciones.conflictos.errors"), groups.errors, "conflicts-errors")}
      {renderGroup(
        t("relaciones.conflictos.warnings"),
        groups.warnings,
        "conflicts-warnings",
      )}
      {renderGroup(
        t("relaciones.conflictos.known"),
        groups.known,
        "conflicts-known",
      )}
      {groups.muted.length > 0 ? (
        <details data-testid="conflicts-muted">
          <summary className="cursor-pointer select-none text-small font-semibold uppercase tracking-wide text-muted">
            {t("relaciones.conflictos.muted")} ({groups.muted.length})
          </summary>
          <ul className="mt-2 flex flex-col gap-2">
            {groups.muted.map(renderItem)}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
