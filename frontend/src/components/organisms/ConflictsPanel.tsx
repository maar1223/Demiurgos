import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { fetchConflicts } from "@/api/conflicts";
import type {
  ConflictCode,
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

const itemClass =
  "w-full rounded-lg border border-edge bg-surface-raised p-3 text-left transition-colors hover:border-action";

/**
 * Conflictos S1 — the deterministic, read-only conflict panel.
 *
 * It shows what the world's own structure contradicts: broken or ambiguous
 * references, duplicated canonical ids, dangling or self relations, missing
 * minimums and draft/canon incoherence. Nothing here calls a model or writes:
 * the Author decides, and the panel only points at the ficha.
 */
export default function ConflictsPanel({ mundo }: ConflictsPanelProps) {
  const { t } = useAppLanguage();
  const navigate = useNavigate();
  const [data, setData] = useState<ConflictsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await fetchConflicts(mundo));
    } catch {
      setError(t("relaciones.conflictos.loadError"));
    } finally {
      setLoading(false);
    }
  }, [mundo, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const errors = useMemo(
    () => data?.conflicts.filter((conflict) => conflict.severity === "error") ?? [],
    [data],
  );
  const warnings = useMemo(
    () =>
      data?.conflicts.filter((conflict) => conflict.severity === "warning") ?? [],
    [data],
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

  const renderGroup = (title: string, items: WorldConflict[], testId: string) => {
    if (items.length === 0) return null;
    return (
      <section data-testid={testId} className="flex flex-col gap-2">
        <h2 className="text-small font-semibold uppercase tracking-wide text-muted">
          {title} ({items.length})
        </h2>
        <ul className="flex flex-col gap-2">
          {items.map((conflict) => (
            <li key={conflict.id} data-testid="conflict-item">
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
              </button>
            </li>
          ))}
        </ul>
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

  if (error) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p role="alert" className="text-small text-danger">
          {error}
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
        <EmptyState
          icon="check"
          message={t("relaciones.conflictos.empty")}
        />
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
        })}
      </p>
      {renderGroup(t("relaciones.conflictos.errors"), errors, "conflicts-errors")}
      {renderGroup(
        t("relaciones.conflictos.warnings"),
        warnings,
        "conflicts-warnings",
      )}
    </section>
  );
}
