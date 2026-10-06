import { useState } from "react";
import {
  approveDraftTrigger,
  createMethodologyDraft,
  publishMethodologyDraft,
} from "@/api/methodologies";
import { ApiError, type TriggerApproval } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { TriggerApprovalBlock } from "@/components/organisms/TriggerApprovalBlock";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { localizeApiError } from "@/i18n/errors";
import { isTriggerApproved } from "@/lib/triggerBound";

/**
 * Manual authoring mode — markdown draft form (REQ-CC-2).
 *
 * Lets the Author publish a methodology by typing the skill id, version, name
 * and Markdown source directly. World-agnostic: it has no world or taller
 * selector — publishing a draft never activates anything for a world.
 *
 * Etapa 2 gate (D2/D4/D6/D7): the description is the skill's trigger. The
 * Author edits/approves it through one `TriggerApprovalBlock`; the approve
 * action creates the editable draft on first use (the approval binds to a
 * draft) and records the approval. Publish stays disabled until a matching
 * approval exists, and the server re-validates regardless of the client state.
 */
export function ManualSkillCreator() {
  const { t } = useAppLanguage();
  const [skillId, setSkillId] = useState("");
  const [version, setVersion] = useState("");
  const [name, setName] = useState("");
  const [source, setSource] = useState("");
  const [description, setDescription] = useState("");
  const [draftId, setDraftId] = useState<string | null>(null);
  const [approval, setApproval] = useState<TriggerApproval | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fieldsReady =
    skillId.trim() !== "" &&
    version.trim() !== "" &&
    name.trim() !== "" &&
    source.trim() !== "";
  const approved = isTriggerApproved(approval, description);

  const resetForm = () => {
    setSkillId("");
    setVersion("");
    setName("");
    setSource("");
    setDescription("");
    setDraftId(null);
    setApproval(null);
  };

  const fail = (cause: unknown) => {
    setError(
      cause instanceof ApiError
        ? localizeApiError(cause, t)
        : t("skillCreate.error"),
    );
  };

  /** The single explicit approve action (D6). On first use it creates the
   *  draft the approval binds to; afterwards it re-approves the same draft. */
  const handleApprove = async (text: string) => {
    if (busy || !fieldsReady) return;
    setBusy(true);
    setError(null);
    try {
      let id = draftId;
      if (!id) {
        const draft = await createMethodologyDraft({
          skill_id: skillId.trim(),
          version: version.trim(),
          name: name.trim(),
          source,
          description: text.trim() || undefined,
        });
        id = draft.draft_id;
        setDraftId(id);
      }
      const result = await approveDraftTrigger(id, text);
      setApproval(result.trigger_approval);
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy(false);
    }
  };

  /** Publish — gated on a matching approval (the client gate is UX only; the
   *  server refuses without a valid approval). */
  const handlePublish = async () => {
    if (!draftId || !approved || busy) return;
    setBusy(true);
    setError(null);
    try {
      await publishMethodologyDraft(draftId);
      resetForm();
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-edge/20 bg-surface-raised/40 p-4">
      <h3 className="font-heading text-h4 text-primary">
        {t("skillCreate.title")}
      </h3>
      {error && <ErrorBanner message={error} className="mt-3" />}
      <form
        className="mt-4 space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          void handlePublish();
        }}
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="flex flex-col gap-1 text-small text-muted">
            Skill ID
            <input
              className="rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50"
              value={skillId}
              onChange={(event) => setSkillId(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-small text-muted">
            {t("skillCreate.version")}
            <input
              className="rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50"
              value={version}
              onChange={(event) => setVersion(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-small text-muted">
            {t("skillCreate.name")}
            <input
              className="rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-small text-muted">
          {t("skillCreate.source")}
          <textarea
            className="min-h-24 rounded-lg bg-surface px-3 py-2 text-body text-primary outline-none focus:ring-2 focus:ring-action/50"
            value={source}
            onChange={(event) => setSource(event.target.value)}
          />
        </label>
        <TriggerApprovalBlock
          value={description}
          onChange={setDescription}
          approval={approval}
          onApprove={handleApprove}
          disabled={busy}
          approveDisabled={!fieldsReady}
        />
        <Button type="submit" size="sm" disabled={busy || !approved}>
          {t("skillCreate.submit")}
        </Button>
      </form>
    </div>
  );
}
