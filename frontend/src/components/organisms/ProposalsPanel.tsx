import { useCallback, useEffect, useState } from "react";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import {
  acceptRelationProposal,
  fetchRelationCandidates,
  fetchRelationProposals,
  muteRelationCandidate,
  rejectRelationProposal,
  sweepRelations,
  unmuteRelationCandidate,
} from "@/api/graph";
import type { RelationCandidate, RelationProposal } from "@/api/types";

interface ProposalsPanelProps {
  mundo: string;
}

/** Bounded batch size: the number the button names as its cost (S8). */
const BATCH_SIZE = 5;

const buttonClass =
  "rounded-lg border border-edge px-3 py-1.5 text-small font-medium text-primary transition-colors hover:border-action hover:text-action disabled:cursor-not-allowed disabled:opacity-50";

/**
 * P3 — on-demand semantic sweep.
 *
 * The panel is the only surface that triggers model work. It reviews a
 * bounded batch of fichas per click and never writes by itself: accepting a
 * proposal is the write. The button states its cost as a number, so the model
 * spend is visible before the click.
 */
export default function ProposalsPanel({ mundo }: ProposalsPanelProps) {
  const { t } = useAppLanguage();
  const [candidates, setCandidates] = useState<RelationCandidate[]>([]);
  const [muted, setMuted] = useState<string[]>([]);
  const [proposals, setProposals] = useState<RelationProposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    const [candidateResponse, proposalResponse] = await Promise.all([
      fetchRelationCandidates(mundo),
      fetchRelationProposals(mundo),
    ]);
    setCandidates(candidateResponse.items);
    setMuted(candidateResponse.muted);
    setProposals(proposalResponse.items);
  }, [mundo]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    refresh()
      .catch(() => {
        if (alive) setError(t("relaciones.propuestas.loadError"));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [refresh, t]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await action();
      await refresh();
    } catch {
      setError(t("relaciones.propuestas.actionError"));
    } finally {
      setBusy(false);
    }
  };

  const batchSize =
    candidates.length > 0 ? Math.min(BATCH_SIZE, candidates.length) : BATCH_SIZE;

  const handleSweep = () =>
    run(async () => {
      const result = await sweepRelations(mundo);
      if (result.status === "swept") {
        if (typeof result.swept === "number") {
          setNotice(
            t(
              result.swept === 1
                ? "relaciones.propuestas.batchDoneOne"
                : "relaciones.propuestas.batchDone",
              { fichas: result.swept, count: result.created },
            ),
          );
        } else {
          // Pre-batch response: keep the old single-ficha message readable.
          setNotice(
            t("relaciones.propuestas.swept", {
              path: result.path ?? "",
              count: result.created,
            }),
          );
        }
      } else if (result.status === "done") {
        setNotice(t("relaciones.propuestas.done"));
      } else {
        setNotice(t("relaciones.propuestas.unavailable"));
      }
    });

  const sweepLabel = busy
    ? t(
        batchSize === 1
          ? "relaciones.propuestas.sweepRunningOne"
          : "relaciones.propuestas.sweepRunning",
        { count: batchSize },
      )
    : t(
        batchSize === 1
          ? "relaciones.propuestas.sweepBatchOne"
          : "relaciones.propuestas.sweepBatch",
        { count: batchSize },
      );

  const badge =
    candidates.length > 0
      ? t("relaciones.propuestas.badge", { count: candidates.length })
      : t("relaciones.propuestas.badgeNone");

  const remaining =
    candidates.length === 0
      ? t("relaciones.propuestas.noneLeft")
      : candidates.length === 1
        ? t("relaciones.propuestas.remainingOne")
        : t("relaciones.propuestas.remaining", { count: candidates.length });

  return (
    <section data-testid="proposals-panel" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-edge bg-surface-raised p-4">
        <div>
          <p data-testid="candidate-count" className="text-body font-medium text-primary">
            {badge}
          </p>
          <p data-testid="candidate-remaining" className="mt-1 text-small text-muted">
            {remaining}
          </p>
        </div>
        <button
          type="button"
          data-testid="sweep-button"
          className={buttonClass}
          onClick={handleSweep}
          disabled={busy || loading || candidates.length === 0}
        >
          {sweepLabel}
        </button>
      </div>

      {error ? (
        <p role="alert" className="text-small text-danger">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p data-testid="sweep-notice" className="text-small text-muted">
          {notice}
        </p>
      ) : null}

      <div>
        <h2 className="mb-2 text-small font-semibold uppercase tracking-wide text-muted">
          {t("relaciones.propuestas.queue")}
        </h2>
        {proposals.length === 0 ? (
          <p className="text-small text-muted">
            {t("relaciones.propuestas.empty")}
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {proposals.map((proposal) => (
              <li
                key={proposal.id}
                data-testid="proposal-item"
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-edge bg-surface-raised p-3"
              >
                <div className="min-w-0">
                  <p className="text-small text-primary">
                    <span className="font-medium">{proposal.source_path}</span>
                    {" → "}
                    <span className="font-medium">{proposal.target_id}</span>
                    {proposal.relationship_type ? (
                      <span className="ml-2 text-muted">
                        {proposal.relationship_type}
                      </span>
                    ) : null}
                  </p>
                  {proposal.evidence ? (
                    <blockquote
                      data-testid="proposal-evidence"
                      className="mt-1 border-l-2 border-edge pl-2 text-small italic text-muted"
                    >
                      {proposal.evidence}
                    </blockquote>
                  ) : null}
                  <p className="text-small text-muted">
                    {t("relaciones.propuestas.confidence", {
                      value: Math.round(proposal.confidence * 100),
                    })}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className={buttonClass}
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        await acceptRelationProposal(mundo, proposal.id);
                      })
                    }
                  >
                    {t("relaciones.propuestas.accept")}
                  </button>
                  <button
                    type="button"
                    className={buttonClass}
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        await rejectRelationProposal(mundo, proposal.id);
                      })
                    }
                  >
                    {t("relaciones.propuestas.reject")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {candidates.length > 0 ? (
        <div>
          <h2 className="mb-2 text-small font-semibold uppercase tracking-wide text-muted">
            {t("relaciones.propuestas.candidates")}
          </h2>
          <ul className="flex flex-col gap-1">
            {candidates.map((candidate) => (
              <li
                key={candidate.path}
                className="flex items-center justify-between gap-3 text-small"
              >
                <span className="min-w-0 truncate text-primary">
                  {candidate.title}
                  <span className="ml-2 text-muted">{candidate.path}</span>
                </span>
                <button
                  type="button"
                  className={buttonClass}
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await muteRelationCandidate(mundo, candidate.path);
                    })
                  }
                >
                  {t("relaciones.propuestas.mute")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {muted.length > 0 ? (
        <div>
          <h2 className="mb-2 text-small font-semibold uppercase tracking-wide text-muted">
            {t("relaciones.propuestas.muted")}
          </h2>
          <ul className="flex flex-col gap-1">
            {muted.map((path) => (
              <li
                key={path}
                className="flex items-center justify-between gap-3 text-small"
              >
                <span className="min-w-0 truncate text-muted">{path}</span>
                <button
                  type="button"
                  className={buttonClass}
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await unmuteRelationCandidate(mundo, path);
                    })
                  }
                >
                  {t("relaciones.propuestas.unmute")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
