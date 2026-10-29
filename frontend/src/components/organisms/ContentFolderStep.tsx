import { FormEvent, useEffect, useState } from "react";
import {
  commitContentFolderStep,
  getContentRoot,
  setContentRoot,
} from "@/api/contentRoot";
import type { ContentRootInfo } from "@/api/contentRoot";
import { systemControlAction } from "@/api/wiki";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { useAppLanguage } from "@/hooks/useAppLanguage";

/**
 * Onboarding step 4 — where the author's worlds live.
 *
 * Shows the folder the app is USING (not a promise), how many worlds it holds
 * and how much room is left, and lets the author change it. Changing it writes
 * the data-root pointer, which moves no bytes and cannot rebind the running
 * process: the step then asks for a restart instead of continuing, because
 * creating the first world now would land it in the folder the app booted with.
 *
 * The folder is never silent: `env` origin means the environment pins it and the
 * change form is not offered.
 */

/** Bytes as a short human figure; `null` never invents a number. */
export function formatBytes(bytes: number | null | undefined): string {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) {
    return "—";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded =
    unit === 0 || value >= 100
      ? String(Math.round(value))
      : value.toFixed(1).replace(/\.0$/, "");
  return `${rounded} ${units[unit]}`;
}

function messageOf(error: unknown): string {
  const detail = (error as { detail?: unknown })?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (error instanceof Error && error.message) return error.message;
  return String(error);
}

export function ContentFolderStep({ onDone }: { onDone: () => void }) {
  const { t } = useAppLanguage();
  const [info, setInfo] = useState<ContentRootInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [restart, setRestart] = useState(false);

  useEffect(() => {
    let alive = true;
    getContentRoot()
      .then((payload) => {
        if (!alive) return;
        setInfo(payload);
        setRestart(payload.pending_restart);
      })
      .catch((failure) => alive && setError(messageOf(failure)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const submit = async (event: FormEvent) => {
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
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  const accept = async () => {
    setBusy(true);
    setError(null);
    try {
      await commitContentFolderStep();
      onDone();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="mt-8 flex justify-center" data-testid="content-folder-loading">
        <Spinner />
      </div>
    );
  }

  // `pinned` is the server's verdict: the shipped launchers export
  // DEMIURGOS_DATA_ROOT from the pointer, so origin "env" alone means nothing.
  const pinnedByEnv = info?.pinned === true;
  const unusable = info !== null && !info.usable;

  return (
    <div className="mt-8 rounded-lg border border-edge bg-surface-raised p-6">
      <h2 className="font-heading text-h4 text-primary">
        {t("onboarding.folder.title")}
      </h2>
      <p className="mt-2 text-small text-secondary">
        {t("onboarding.folder.intro")}
      </p>

      <dl className="mt-4 space-y-2">
        <div>
          <dt className="text-small text-secondary">
            {t("onboarding.folder.path")}
          </dt>
          <dd
            className="break-all font-mono text-small text-primary"
            data-testid="content-folder-path"
          >
            {info?.path ?? t("onboarding.folder.unconfigured")}
          </dd>
        </div>
        <div className="flex gap-6">
          <div>
            <dt className="text-small text-secondary">
              {t("onboarding.folder.worlds")}
            </dt>
            <dd className="text-small text-primary" data-testid="content-folder-worlds">
              {info?.worlds ?? 0}
            </dd>
          </div>
          <div>
            <dt className="text-small text-secondary">
              {t("onboarding.folder.free")}
            </dt>
            <dd className="text-small text-primary" data-testid="content-folder-free">
              {formatBytes(info?.disk.free_bytes)}
            </dd>
          </div>
        </div>
      </dl>

      {pinnedByEnv && (
        <p className="mt-4 text-small text-secondary" data-testid="content-folder-env">
          {t("onboarding.folder.pinnedByEnv", {
            env: info?.path ?? "—",
            recorded: info?.recorded_path ?? "—",
          })}
        </p>
      )}
      {unusable && (
        <p className="mt-4 text-small text-danger" data-testid="content-folder-unusable">
          {info?.warning ?? info?.reason ?? t("onboarding.folder.unusable")}
        </p>
      )}

      {error && (
        <div className="mt-4">
          <ErrorBanner message={error} onRetry={() => setError(null)} />
        </div>
      )}

      {restart ? (
        <div className="mt-6 space-y-3">
          <p className="text-small text-primary" role="alert" data-testid="content-folder-restart">
            {t("onboarding.folder.restartRequired")}
          </p>
          <Button
            type="button"
            variant="primary"
            onClick={() => void systemControlAction("restart")}
          >
            {t("onboarding.folder.restartAction")}
          </Button>
        </div>
      ) : (
        <div className="mt-6 space-y-3">
          {editing ? (
            <form className="space-y-2" onSubmit={submit}>
              <label className="block text-small text-secondary" htmlFor="content-folder-input">
                {t("onboarding.folder.newPath")}
              </label>
              <input
                id="content-folder-input"
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
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setEditing(false);
                    setError(null);
                  }}
                >
                  {t("common.cancel")}
                </Button>
              </div>
            </form>
          ) : (
            <div className="flex flex-wrap gap-3">
              <Button type="button" variant="primary" disabled={busy} onClick={() => void accept()}>
                {t("onboarding.folder.accept")}
              </Button>
              {!pinnedByEnv && (
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
            </div>
          )}
        </div>
      )}
    </div>
  );
}
