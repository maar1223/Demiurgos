import { useCallback, useEffect, useState } from "react";
import { getContentRoot, setContentRoot } from "@/api/contentRoot";
import type { ContentRootInfo } from "@/api/contentRoot";
import { systemControlAction } from "@/api/wiki";
import { Button } from "@/components/atoms/Button";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import { formatBytes } from "@/components/organisms/ContentFolderStep";
import { CleanupOldContent, MoveContentDialog } from "@/components/organisms/MoveContentDialog";
import { useAppLanguage } from "@/hooks/useAppLanguage";

/**
 * "Carpeta de tu contenido" — the settings home of what onboarding introduced.
 *
 * Exactly one action per state, so the author never has to guess:
 *
 * | target              | current content | action |
 * |---------------------|-----------------|--------|
 * | empty               | no worlds       | use    |
 * | already holds data  | has content     | use    |
 * | empty               | has content     | move   |
 * | holds content       | no content      | use    |
 *
 * `commit` is false here: this surface does not advance onboarding, it only
 * records a new folder (or moves the content into an empty one).
 */
function messageOf(error: unknown): string {
  const detail = (error as { detail?: unknown })?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (error instanceof Error && error.message) return error.message;
  return String(error);
}

export function ContentFolderCard({ onChanged }: { onChanged?: () => void }) {
  const { t } = useAppLanguage();
  const [info, setInfo] = useState<ContentRootInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [moving, setMoving] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [restart, setRestart] = useState(false);

  const load = useCallback(() => {
    return getContentRoot()
      .then((payload) => {
        setInfo(payload);
        setRestart(payload.pending_restart);
      })
      .catch((failure) => setError(messageOf(failure)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    const chosen = draft.trim();
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      const payload = await setContentRoot(chosen);
      setInfo(payload);
      setEditing(false);
      setRestart(Boolean(payload.restart_required) || payload.pending_restart);
      onChanged?.();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="mt-4 flex justify-center" data-testid="content-folder-card-loading">
        <Spinner />
      </div>
    );
  }

  const pinned = info?.pinned === true;
  const hasContent = (info?.worlds ?? 0) > 0;

  return (
    <div className="mt-3 border-t border-edge pt-3" data-testid="content-folder-card">
      <h3 className="text-small font-medium text-primary">
        {t("content.card.title")}
      </h3>
      <dl className="mt-2 space-y-1">
        <div>
          <dt className="text-small text-muted">{t("onboarding.folder.path")}</dt>
          <dd
            className="break-all font-mono text-small text-primary"
            data-testid="content-card-path"
          >
            {info?.path ?? t("onboarding.folder.unconfigured")}
          </dd>
        </div>
        <div className="flex gap-6">
          <div>
            <dt className="text-small text-muted">{t("onboarding.folder.worlds")}</dt>
            <dd className="text-small text-primary" data-testid="content-card-worlds">
              {info?.worlds ?? 0}
            </dd>
          </div>
          <div>
            <dt className="text-small text-muted">{t("onboarding.folder.free")}</dt>
            <dd className="text-small text-primary" data-testid="content-card-free">
              {formatBytes(info?.disk.free_bytes)}
            </dd>
          </div>
        </div>
      </dl>

      {pinned && (
        <p className="mt-3 text-small text-secondary" data-testid="content-card-pinned">
          {t("onboarding.folder.pinnedByEnv")}
        </p>
      )}
      {error && (
        <div className="mt-3">
          <ErrorBanner message={error} onRetry={() => setError(null)} />
        </div>
      )}

      <div className="mt-3 space-y-3">
        {editing ? (
          <form className="space-y-2" onSubmit={save}>
            <label className="block text-small text-secondary" htmlFor="content-card-input">
              {t("onboarding.folder.newPath")}
            </label>
            <input
              id="content-card-input"
              className="w-full rounded border border-edge bg-surface px-3 py-2 font-mono text-small text-primary"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={t("onboarding.folder.newPathPlaceholder")}
              spellCheck={false}
              autoComplete="off"
            />
            <div className="flex gap-3">
              <Button type="submit" variant="primary" disabled={busy || !draft.trim()}>
                {t("onboarding.folder.save")}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
                {t("common.cancel")}
              </Button>
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap gap-3">
            {!pinned && !hasContent && (
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setDraft(info?.path ?? "");
                  setEditing(true);
                }}
              >
                {t("onboarding.folder.change")}
              </Button>
            )}
            {!pinned && hasContent && (
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setDraft("");
                  setMoving(true);
                }}
              >
                {t("content.card.move")}
              </Button>
            )}
          </div>
        )}

        {restart && (
          <div className="space-y-2" data-testid="content-card-restart">
            <p className="text-small text-primary">{t("onboarding.folder.restartRequired")}</p>
            <Button
              type="button"
              variant="primary"
              onClick={() => void systemControlAction("restart")}
            >
              {t("onboarding.folder.restartAction")}
            </Button>
          </div>
        )}

        {moving && (
          <MoveContentDialog
            contentRoot={info?.path ?? null}
            onClose={() => setMoving(false)}
            onMoved={() => {
              setMoving(false);
              void load();
            }}
          />
        )}

        <CleanupOldContent currentRoot={info?.path ?? null} onCleaned={() => void load()} />
      </div>
    </div>
  );
}
