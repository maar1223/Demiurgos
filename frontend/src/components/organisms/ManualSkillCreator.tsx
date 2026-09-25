import { useState } from "react";
import {
  createMethodologyDraft,
  publishMethodologyDraft,
} from "@/api/methodologies";
import { Button } from "@/components/atoms/Button";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { useAppLanguage } from "@/hooks/useAppLanguage";

/**
 * Manual authoring mode — markdown draft form (REQ-CC-2).
 *
 * Lets the Author publish a methodology by typing the skill id, version, name
 * and Markdown source directly. World-agnostic: it has no world or taller
 * selector — publishing a draft never activates anything for a world.
 */
export function ManualSkillCreator() {
  const { t } = useAppLanguage();
  const [skillId, setSkillId] = useState("");
  const [version, setVersion] = useState("");
  const [name, setName] = useState("");
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handlePublish = async () => {
    if (!skillId.trim() || !version.trim() || !name.trim() || !source.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const draft = await createMethodologyDraft({
        skill_id: skillId.trim(),
        version: version.trim(),
        name: name.trim(),
        source,
      });
      await publishMethodologyDraft(draft.draft_id);
      setSkillId("");
      setVersion("");
      setName("");
      setSource("");
    } catch {
      setError(t("skillCreate.error"));
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
        <Button type="submit" size="sm" disabled={busy}>
          {t("skillCreate.submit")}
        </Button>
      </form>
    </div>
  );
}