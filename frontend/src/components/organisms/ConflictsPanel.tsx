import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import {
  fetchConflicts,
  rejectConflictProposal,
  setConflictDecision,
  sweepConflicts,
} from "@/api/conflicts";
import type {
  ConflictCode,
  ConflictDecisionKind,
  ConflictSweepResponse,
  ConflictsResponse,
  WorldConflict,
} from "@/api/conflicts";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ApiError } from "@/api/types";
import { encodePathSegment } from "@/lib/utils";
import type { MessageKey } from "@/i18n/messages";

interface ConflictsPanelProps {
  mundo: string;
}

/** Fichas reviewed per sweep call: the button names this number as its cost. */
const SWEEP_BATCH_SIZE = 3;

/** One user-facing sentence per conflict code (S8). */
const CODE_MESSAGES: Record<ConflictCode, MessageKey> = {
  version: "relaciones.conflictos.code.version",
  "missing-minimum": "relaciones.conflictos.code.missing-minimum",
  "unresolved-reference": "relaciones.conflictos.code.unresolved-reference",
  "ambiguous-reference": "relaciones.conflictos.code.ambiguous-reference",
  "duplicate-id": "relaciones.conflictos.code.duplicate-id",
  "dangling-relation": "relaciones.conflictos.code.dangling-relation",
  "self-relation": "relaciones.conflictos.code.self-relation",
  "canon-state-mismatch": "relaciones.conflictos.code.canon-state-mismatch",
  "semantic-contradiction":
    "relaciones.conflictos.code.semantic-contradiction",
};

const DECISION_ACTIONS: {
  kind: ConflictDecisionKind;
  label: MessageKey;
  hint: MessageKey;
}[] = [
  {
    kind: "intentional",
    label: "relaciones.conflictos.decision.intentional",
    hint: "relaciones.conflictos.decision.intentionalHint",
  },
  {
    kind: "muted",
    label: "relaciones.conflictos.decision.muted",
    hint: "relaciones.conflictos.decision.mutedHint",
  },
  {
    kind: "structural",
    label: "relaciones.conflictos.decision.structural",
    hint: "relaciones.conflictos.decision.structuralHint",
  },
];

const itemClass = "w-full text-left";
const actionClass =
  "rounded-lg border border-edge px-2 py-1 text-small font-medium text-primary transition-colors hover:border-action hover:text-action disabled:cursor-not-allowed disabled:opacity-50";

interface FichaHalfProps {
  label: string;
  name: string;
  path: string;
  quote: string | null;
  quoteTestId: string;
  openLabel: string;
  onOpen: () => void;
}

/** One half of a semantic contradiction: the ficha, its quote and its way in. */
function FichaHalf({
  label,
  name,
  path,
  quote,
  quoteTestId,
  openLabel,
  onOpen,
}: FichaHalfProps) {
  return (
    <button
      type="button"
      data-testid={`conflict-ficha-${label.toLowerCase()}`}
      onClick={onOpen}
      className="flex h-full flex-col gap-1 rounded-lg border border-edge p-3 text-left transition-colors hover:border-action"
    >
      <span className="block text-small font-medium text-primary">
        {label} · {name}
      </span>
      <span className="block truncate text-small text-muted">{path}</span>
      {quote ? (
        <span
          data-testid={quoteTestId}
          className="mt-1 block border-l-2 border-edge pl-2 text-small italic text-muted"
        >
          “{quote}”
        </span>
      ) : null}
      <span className="mt-auto pt-1 text-small font-medium text-action">
        {openLabel} →
      </span>
    </button>
  );
}

/**
 * Conflictos — the deterministic conflict panel (S1), the semantic proposals
 * (S3) and the Author's decisions (S2).
 *
 * The deterministic layer shows what the world's own structure contradicts. The
 * semantic sweep proposes ficha-vs-ficha contradictions, each backed by a
 * quote from both sides. Nothing here edits a ficha or decides canon: the panel
 * records the decision and links to the ficha.
 */
export default function ConflictsPanel({ mundo }: ConflictsPanelProps) {
  const { t } = useAppLanguage();
  const navigate = useNavigate();
  const [data, setData] = useState<ConflictsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [sweepNotice, setSweepNotice] = useState("");

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
      conflict.state !== "proposed" &&
      conflict.decision !== "intentional" &&
      conflict.decision !== "muted" &&
      conflict.severity === severity;
    return {
      proposed: items.filter((conflict) => conflict.state === "proposed"),
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

  const reject = useCallback(
    async (conflict: WorldConflict) => {
      setBusy(true);
      setActionError("");
      try {
        setData(await rejectConflictProposal(mundo, conflict.id));
      } catch {
        setActionError(t("relaciones.conflictos.actionError"));
      } finally {
        setBusy(false);
      }
    },
    [mundo, t],
  );

  const sweepMessage = (result: ConflictSweepResponse): string => {
    if (result.status === "unavailable") {
      return t("relaciones.conflictos.sweepUnavailable");
    }
    if (result.status === "done") {
      return t("relaciones.conflictos.sweepNone");
    }
    const done = t("relaciones.conflictos.sweepDone", {
      swept: result.swept,
      created: result.created,
    });
    // A claim whose quote is not in the ficha never reaches the list: say so,
    // or "1 propuesta nueva" looks like a lie next to an empty panel.
    return result.discarded
      ? `${done} ${t("relaciones.conflictos.sweepDiscarded", {
          count: result.discarded,
        })}`
      : done;
  };

  const sweep = useCallback(async () => {
    setBusy(true);
    setActionError("");
    setSweepNotice("");
    try {
      const result = await sweepConflicts(mundo, { size: SWEEP_BATCH_SIZE });
      setSweepNotice(sweepMessage(result));
      setData(await fetchConflicts(mundo));
    } catch (err) {
      // A timeout is not a failure: the provider may still be working and the
      // proposals can appear on the next load.
      setActionError(
        err instanceof ApiError && err.code === "network.timeout"
          ? t("relaciones.conflictos.sweepTimeout")
          : t("relaciones.conflictos.actionError"),
      );
    } finally {
      setBusy(false);
    }
    // sweepMessage only reads `t`, which is stable per language.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mundo, t]);

  // Open the EDITABLE ficha in the Taller de Mundo: the Author clicks a
  // conflict to fix it, not to read it. With a quote, the editor lands on the
  // exact fragment the conflict talks about.
  const openPath = useCallback(
    (path: string, quote?: string | null) => {
      const base = `/wiki/${encodeURIComponent(mundo)}/${encodePathSegment(path)}`;
      navigate(
        quote ? `${base}?highlight=${encodeURIComponent(quote)}` : base,
      );
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
    const proposal = conflict.state === "proposed";
    const decided = conflict.decision !== null;
    return (
      <li key={conflict.id} data-testid="conflict-item">
        <div className="rounded-lg border border-edge bg-surface-raised p-3">
          <div className={itemClass}>
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
          </div>
          {proposal ? (
            <div
              data-testid="conflict-pair"
              className="mt-2 grid gap-2 sm:grid-cols-2"
            >
              <FichaHalf
                label="A"
                name={conflict.name}
                path={conflict.path}
                quote={conflict.evidence_a}
                quoteTestId="conflict-quote-a"
                openLabel={t("relaciones.conflictos.openFicha")}
                onOpen={() => openPath(conflict.path, conflict.evidence_a)}
              />
              {conflict.path_b ? (
                <FichaHalf
                  label="B"
                  name={conflict.name_b ?? conflict.source_b ?? ""}
                  path={conflict.path_b}
                  quote={conflict.evidence_b}
                  quoteTestId="conflict-quote-b"
                  openLabel={t("relaciones.conflictos.openFicha")}
                  onOpen={() =>
                    openPath(conflict.path_b!, conflict.evidence_b)
                  }
                />
              ) : conflict.source_b ? (
                // Degraded: an older backend (or a ficha the graph no longer
                // resolves) still names the other side, it just cannot link it.
                <div
                  data-testid="conflict-ficha-b"
                  className="flex flex-col gap-1 rounded-lg border border-edge/60 p-3 opacity-70"
                >
                  <span className="block text-small font-medium text-primary">
                    B · {conflict.source_b}
                  </span>
                  <span className="text-small text-muted">
                    {t("relaciones.conflictos.unresolvedTarget")}
                  </span>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="mt-2">
              <button
                type="button"
                data-testid="open-ficha"
                className={actionClass}
                onClick={() => openPath(conflict.path)}
              >
                {t("relaciones.conflictos.openFicha")}
              </button>
            </div>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            {proposal ? (
              <>
                {DECISION_ACTIONS.filter(
                  (action) => action.kind !== "muted",
                ).map((action) => (
                  <button
                    key={action.kind}
                    type="button"
                    title={t(action.hint)}
                    className={actionClass}
                    disabled={busy}
                    onClick={() => void decide(conflict, action.kind)}
                  >
                    {t(action.label)}
                  </button>
                ))}
                <button
                  type="button"
                  data-testid="reject-proposal"
                  title={t("relaciones.conflictos.decision.rejectHint")}
                  className={actionClass}
                  disabled={busy}
                  onClick={() => void reject(conflict)}
                >
                  {t("relaciones.conflictos.decision.reject")}
                </button>
              </>
            ) : decided ? (
              <button
                type="button"
                title={t("relaciones.conflictos.decision.clearHint")}
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
                  title={t(action.hint)}
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

  // A missing `review` means an older backend, not "everything reviewed".
  const review = data?.summary.review ?? null;
  const allReviewed = review !== null && review.pending === 0;

  const sweepButton = (
    <button
      type="button"
      data-testid="conflict-sweep"
      className="rounded-lg border border-edge px-3 py-1.5 text-small font-medium text-primary transition-colors hover:border-action hover:text-action disabled:cursor-not-allowed disabled:opacity-50"
      disabled={busy || loading || allReviewed}
      onClick={() => void sweep()}
    >
      {busy
        ? t("relaciones.conflictos.sweeping")
        : allReviewed
          ? t("relaciones.conflictos.sweepAllDone")
          : review
            ? t("relaciones.conflictos.sweep", {
                count: SWEEP_BATCH_SIZE,
                pending: review.pending,
              })
            : t("relaciones.conflictos.sweepBase", {
                count: SWEEP_BATCH_SIZE,
              })}
    </button>
  );

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

  const empty = data === null || data.summary.total === 0;

  return (
    <section data-testid="conflicts-panel" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-edge bg-surface-raised p-4">
        <p data-testid="conflict-summary" className="text-small text-muted">
          {review
            ? t("relaciones.conflictos.summary", {
                pending: review.pending,
                total: review.total,
                errors: data?.summary.errors ?? 0,
                warnings: data?.summary.warnings ?? 0,
                proposed: data?.summary.proposed ?? 0,
                known: data?.summary.known ?? 0,
                muted: data?.summary.muted ?? 0,
              })
            : t("relaciones.conflictos.summaryNoReview", {
                errors: data?.summary.errors ?? 0,
                warnings: data?.summary.warnings ?? 0,
                proposed: data?.summary.proposed ?? 0,
                known: data?.summary.known ?? 0,
                muted: data?.summary.muted ?? 0,
              })}
        </p>
        {sweepButton}
      </div>

      {actionError ? (
        <p role="alert" className="text-small text-danger">
          {actionError}
        </p>
      ) : null}
      {sweepNotice ? (
        <p data-testid="sweep-notice" className="text-small text-muted">
          {sweepNotice}
        </p>
      ) : null}

      {empty ? (
        <div data-testid="conflicts-empty">
          <EmptyState icon="check" message={t("relaciones.conflictos.empty")} />
          <p className="text-center text-small text-muted">
            {t("relaciones.conflictos.emptyHint")}
          </p>
        </div>
      ) : null}

      {renderGroup(
        t("relaciones.conflictos.proposed"),
        groups.proposed,
        "conflicts-proposed",
      )}
      {renderGroup(t("relaciones.conflictos.errors"), groups.errors, "conflicts-errors")}
      {renderGroup(
        t("relaciones.conflictos.warnings"),
        groups.warnings,
        "conflicts-warnings",
      )}
      {renderGroup(t("relaciones.conflictos.known"), groups.known, "conflicts-known")}
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
