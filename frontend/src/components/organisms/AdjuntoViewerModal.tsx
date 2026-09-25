import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { getAdjuntoContent } from "@/api/methodologies";
import { ApiError } from "@/api/types";
import type { MethodologyAdjunto } from "@/api/types";
import { Icon } from "@/components/atoms/Icon";
import { Badge } from "@/components/atoms/Badge";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { MarkdownBody } from "@/components/organisms/MarkdownViewer";
import { useAppLanguage } from "@/hooks/useAppLanguage";

type AdjuntoViewerStatus =
  | "idle"
  | "loading"
  | "ready"
  | "error"
  | "unauthorized"
  | "unavailable";

interface AdjuntoViewerModalProps {
  open: boolean;
  skillId: string;
  version: string;
  /** The pinned attachment to view; `null` keeps the modal inert. */
  adjunto: MethodologyAdjunto | null;
  onClose: () => void;
}

/** Human-readable byte size, consistent with MethodologyDetailView's formatter. */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Display name: the path basename with a trailing `.md` stripped. */
function basenameWithoutExt(path: string): string {
  const base = path.split("/").pop() ?? path;
  return base.replace(/\.md$/i, "");
}

/**
 * Read-only viewer for a published Taller skill's pinned exemplars (carriers).
 *
 * Fetches the carrier through `getAdjuntoContent` and renders it with the
 * shared `MarkdownBody` — deliberately WITHOUT `mundo`, because carriers have
 * no world media root (design D6). The modal follows the repo overlay
 * convention (CreateWorldModal/MoveModal): portal to `document.body`,
 * `role="dialog"` + `aria-modal` + `aria-labelledby`, Escape/overlay/X
 * dismissal, a local Tab focus trap, and initial focus on the close control.
 *
 * States: `idle` (nothing to show), `loading`, `ready`, `error` (retryable),
 * `unauthorized` (401 — muted note, never an error banner), and `unavailable`
 * (404/422 `attachment_unavailable` — distinguishable from the auth note).
 */
export function AdjuntoViewerModal({
  open,
  skillId,
  version,
  adjunto,
  onClose,
}: AdjuntoViewerModalProps) {
  const { t } = useAppLanguage();
  const [status, setStatus] = useState<AdjuntoViewerStatus>("idle");
  const [content, setContent] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  // Fetch the pinned carrier whenever the target or a retry changes.
  useEffect(() => {
    if (!open || !adjunto) {
      setStatus("idle");
      setContent(null);
      return;
    }

    let cancelled = false;
    setStatus("loading");
    setContent(null);

    getAdjuntoContent(skillId, version, adjunto.path)
      .then((text) => {
        if (cancelled) return;
        setContent(text);
        setStatus("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setContent(null);
        if (error instanceof ApiError && error.status === 401) {
          setStatus("unauthorized");
        } else if (
          error instanceof ApiError &&
          (error.status === 404 || error.status === 422)
        ) {
          setStatus("unavailable");
        } else {
          setStatus("error");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [open, skillId, version, adjunto?.path, reloadKey]);

  // Initial focus lands on the close control when the dialog opens.
  useEffect(() => {
    if (!open) return;
    closeButtonRef.current?.focus();
  }, [open]);

  // Escape closes; Tab/Shift+Tab cycle through the dialog's focusables only.
  useEffect(() => {
    if (!open) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusables = dialog.querySelectorAll<HTMLElement>(
        "input, button, [href], select, textarea, [tabindex]:not([tabindex='-1'])",
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === dialog)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  if (!open) return null;

  const title = adjunto ? basenameWithoutExt(adjunto.path) : "";

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-surface/80 backdrop-blur-sm"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="adjunto-viewer-title"
        className="mx-4 flex max-h-[80vh] w-full max-w-lg flex-col rounded-xl border border-edge bg-surface-raised shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        {/* Header — exemplar identity, derived from the pinned metadata. */}
        <div className="flex items-start justify-between gap-3 border-b border-edge px-6 py-4">
          <div className="min-w-0">
            <h2
              id="adjunto-viewer-title"
              className="truncate font-heading text-h4 text-primary"
            >
              {title}
            </h2>
            {adjunto && (
              <div className="mt-1 flex items-center gap-2">
                <Badge variant="info">{adjunto.nivel}</Badge>
                <span className="text-small text-muted">
                  {formatBytes(adjunto.bytes)}
                </span>
              </div>
            )}
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary"
            aria-label={t("common.close")}
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Scrollable body — `min-h-0 flex-1` lets it shrink and scroll inside
            the `max-h-[80vh]` dialog instead of overflowing or shifting layout. */}
        <div
          data-testid="adjunto-viewer-body"
          className="min-h-0 flex-1 overflow-y-auto px-6 py-4"
        >
          {status === "loading" && (
            <div className="flex items-center justify-center py-12">
              <Spinner size="md" />
            </div>
          )}

          {status === "unauthorized" && (
            <p
              data-testid="adjunto-unauthorized"
              className="text-small text-muted"
            >
              {t("adjunto.unauthorized")}
            </p>
          )}

          {status === "unavailable" && (
            <p
              data-testid="adjunto-unavailable"
              className="text-small text-muted"
            >
              {t("adjunto.unavailable")}
            </p>
          )}

          {status === "error" && (
            <ErrorBanner
              message={t("adjunto.loadError")}
              onRetry={() => setReloadKey((key) => key + 1)}
            />
          )}

          {status === "ready" && <MarkdownBody content={content ?? ""} />}
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default AdjuntoViewerModal;
