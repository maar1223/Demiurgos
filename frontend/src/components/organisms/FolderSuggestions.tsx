import { useEffect, useState } from "react";

import { getContentDestinations, pickFolder } from "@/api/contentRoot";
import type { ContentDestinationCandidate } from "@/api/contentRoot";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { formatBytes } from "@/components/organisms/ContentFolderStep";

function messageOf(error: unknown): string {
  const detail = (error as { detail?: unknown })?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (error instanceof Error && error.message) return error.message;
  return String(error);
}

/**
 * Clickable folders, because a browser cannot browse the server's disk.
 *
 * The honest web-native answer to "let me choose a folder" is a list of the
 * places a destination usually is: mounted disks, home, Documents, siblings of
 * the current folder. Manual entry stays available; this only removes the need
 * to type a path from memory.
 */
export function FolderSuggestions({
  onPick,
  disabled = false,
}: {
  onPick: (path: string) => void;
  disabled?: boolean;
}) {
  const { t } = useAppLanguage();
  const [items, setItems] = useState<ContentDestinationCandidate[]>([]);
  const [nativeDialog, setNativeDialog] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getContentDestinations()
      .then(({ candidates, native_dialog: native }) => {
        if (!alive) return;
        setItems(candidates);
        setNativeDialog(Boolean(native));
      })
      .catch(() => alive && setItems([]))
      .finally(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
  }, []);

  if (!loaded || (items.length === 0 && !nativeDialog)) return null;

  const openDialog = async () => {
    setBusy(true);
    setError(null);
    try {
      const answer = await pickFolder();
      if (!answer.cancelled && answer.path) onPick(answer.path);
    } catch (failure) {
      // A dialog that cannot open is not a dead end, but it must not look like
      // nothing happened either: say it and leave the manual path available.
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-1" data-testid="content-folder-suggestions">
      {nativeDialog && (
        <button
          type="button"
          className="rounded border border-edge bg-surface-raised px-2 py-1 text-small text-primary hover:border-action disabled:opacity-50"
          disabled={disabled || busy}
          onClick={() => void openDialog()}
          data-testid="content-folder-choose"
        >
          {t("content.suggestions.choose")}
        </button>
      )}
      {error && (
        <p className="text-small text-danger" role="alert" data-testid="content-folder-dialog-error">
          {error}
        </p>
      )}
      {items.length > 0 && (
        <p className="text-small text-muted">{t("content.suggestions.label")}</p>
      )}
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item.path}>
            <button
              type="button"
              className="w-full rounded border border-edge bg-surface-raised px-2 py-1 text-left text-small text-primary hover:border-action disabled:opacity-50"
              disabled={disabled}
              onClick={() => onPick(item.path)}
              data-testid={`content-suggestion-${item.is_empty ? "empty" : "full"}`}
            >
              <span className="break-all font-mono">{item.path}</span>
              <span className="ml-2 text-muted">
                {formatBytes(item.free_bytes)}
                {item.is_empty ? ` · ${t("content.suggestions.empty")}` : ""}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
