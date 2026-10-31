import { useCallback, useEffect, useState } from "react";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import {
  acceptRelationProposal,
  applyRelationReconcile,
  fetchRelationReconcilePreview,
  fetchRelationCandidates,
  fetchRelationProposals,
  muteRelationCandidate,
  rejectRelationProposal,
  sweepRelations,
  unmuteRelationCandidate,
} from "@/api/graph";
import type {
  RelationCandidate,
  RelationProposal,
  RelationReconcilePreview,
} from "@/api/types";

interface ProposalsPanelProps {
  mundo: string;
}

const buttonClass =
  "rounded-lg border border-edge px-3 py-1.5 text-small font-medium text-primary transition-colors hover:border-action hover:text-action disabled:cursor-not-allowed disabled:opacity-50";

/**
 * P3 — on-demand semantic sweep.
 *
 * The panel is the only surface that triggers model work: one fiche per click.
 * It never writes by itself; accepting a proposal is the write.
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
  const [reconcilePreview, setReconcilePreview] =
    useState<RelationReconcilePreview | null>(null);
  const [confirmReconcile, setConfirmReconcile] = useState(false);

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

  const handleSweep = () =>
    run(async () => {
      const result = await sweepRelations(mundo);
      if (result.status === "swept") {
        setNotice(
          t("relaciones.propuestas.swept", {
            path: result.path,
            count: result.created,
          }),
        );
      } else if (result.status === "done") {
        setNotice(t("relaciones.propuestas.done"));
      } else {
        setNotice(t("relaciones.propuestas.unavailable"));
      }
    });

  const previewReconcile = () =>
    run(async () => {
      const preview = await fetchRelationReconcilePreview(mundo);
      setReconcilePreview(preview);
      if (preview.files === 0) {
        setNotice(t("relaciones.reconcile.empty"));
      }
    });

  const applyReconcile = () =>
    run(async () => {
      const result = await applyRelationReconcile(mundo);
      setConfirmReconcile(false);
      setReconcilePreview(null);
      if (result.failed.length > 0) {
        setError(
          t("relaciones.reconcile.failed", { count: result.failed.length }),
        );
      }
      setNotice(
        t("relaciones.reconcile.applied", {
          files: result.applied,
          backup: result.backup,
        }),
      );
    });

  const badge =
    candidates.length > 0
      ? t("relaciones.propuestas.badge", { count: candidates.length })
      : t("relaciones.propuestas.badgeNone");

  return (
    <section data-testid="proposals-panel" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-edge bg-surface-raised p-4">
        <div>
          <p data-testid="candidate-count" className="text-body font-medium text-primary">
            {badge}
          </p>
          <p className="mt-1 text-small text-muted">
            {t("relaciones.propuestas.hint")}
          </p>
        </div>
        <button
          type="button"
          data-testid="sweep-button"
          className={buttonClass}
          onClick={handleSweep}
          disabled={busy || loading || candidates.length === 0}
        >
          {busy
            ? t("relaciones.propuestas.sweeping")
            : t("relaciones.propuestas.sweep")}
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
                  <p className="text-small text-muted">
                    {t("relaciones.propuestas.confidence", {
                      value: Math.round(proposal.confidence * 100),
                    })}
                    {proposal.evidence ? ` · ${proposal.evidence}` : ""}
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

      <div className="rounded-xl border border-edge bg-surface-raised p-4">
        <h2 className="text-small font-semibold uppercase tracking-wide text-muted">
          {t("relaciones.reconcile.title")}
        </h2>
        <p className="mt-1 text-small text-muted">
          {t("relaciones.reconcile.hint")}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="reconcile-preview"
            className={buttonClass}
            disabled={busy}
            onClick={previewReconcile}
          >
            {t("relaciones.reconcile.preview")}
          </button>
          <button
            type="button"
            data-testid="reconcile-apply"
            className={buttonClass}
            disabled={
              busy || reconcilePreview === null || reconcilePreview.files === 0
            }
            onClick={() => setConfirmReconcile(true)}
          >
            {t("relaciones.reconcile.apply")}
          </button>
        </div>
        {reconcilePreview ? (
          <div className="mt-3">
            <p data-testid="reconcile-summary" className="text-small text-primary">
              {t("relaciones.reconcile.files", {
                count: reconcilePreview.files,
              })}
              {" · "}
              {t("relaciones.reconcile.additions", {
                count: reconcilePreview.additions,
              })}
              {" · "}
              {t("relaciones.reconcile.removals", {
                count: reconcilePreview.removals,
              })}
            </p>
            <ul className="mt-2 flex max-h-48 flex-col gap-1 overflow-auto text-small text-muted">
              {reconcilePreview.items.map((item) => (
                <li key={item.path}>
                  {item.path}
                  {" · "}
                  {t("relaciones.reconcile.additions", {
                    count: item.add.length,
                  })}
                  {" · "}
                  {t("relaciones.reconcile.removals", {
                    count: item.remove.length,
                  })}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      {confirmReconcile && reconcilePreview ? (
        <ConfirmDialog
          title={t("relaciones.reconcile.confirmTitle")}
          message={t("relaciones.reconcile.confirmMessage", {
            files: reconcilePreview.files,
            additions: reconcilePreview.additions,
            removals: reconcilePreview.removals,
          })}
          confirmLabel={t("relaciones.reconcile.apply")}
          confirmVariant="danger"
          isBusy={busy}
          onConfirm={applyReconcile}
          onClose={() => setConfirmReconcile(false)}
        />
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
