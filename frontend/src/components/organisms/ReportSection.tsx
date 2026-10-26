import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { TelegramLinkPanel } from "@/components/organisms/TelegramLinkPanel";
import { assembleBugReport, fallbackBody, submitBugReport } from "@/api/bugReports";
import {
  ApiError,
  type BugReportBundle,
  type BugReportFallback,
  type BugReportSubmitPayload,
} from "@/api/types";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { getErrorMessage } from "@/lib/utils";

/** Resolve a localized message for a caught error, falling back when the
 *  thrown value is not an `ApiError`. */
function describeError(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError) {
    return getErrorMessage(cause.status, cause.detail, cause.code, cause.params);
  }
  return fallback;
}

/** Screenshot bounds — the server re-enforces every one of them (S5). */
const ATTACHMENTS_MAX = 2;
const ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024;
const ATTACHMENT_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

function describeBytes(bytes: number): string {
  const megabytes = bytes / (1024 * 1024);
  return megabytes >= 1
    ? `${megabytes.toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** One chosen screenshot: a thumbnail, its name and a remove action.
 *
 *  The object URL is created and revoked with the file, so a removed or
 *  replaced image cannot keep its bytes alive. When the environment cannot mint
 *  one (jsdom), the name is shown instead of a broken image.
 */
function AttachmentThumb({
  file,
  onRemove,
  removeLabel,
}: {
  file: File;
  onRemove: () => void;
  removeLabel: string;
}) {
  const [url, setUrl] = useState("");

  useEffect(() => {
    if (typeof URL.createObjectURL !== "function") return;
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);

  return (
    <li
      className="flex items-center gap-3 rounded-lg border border-edge bg-surface p-2"
      data-testid="bugreport-attachment"
    >
      {url ? (
        <img
          src={url}
          alt={file.name}
          className="h-12 w-12 rounded object-cover"
        />
      ) : null}
      <span className="min-w-0 flex-1 truncate text-small text-primary">
        {file.name} · {describeBytes(file.size)}
      </span>
      <Button variant="secondary" onClick={onRemove} aria-label={`${removeLabel} ${file.name}`}>
        ×
      </Button>
    </li>
  );
}

const FIELD_INPUT_CLASS =
  "rounded-lg border border-edge bg-surface px-3 py-2 text-small text-primary " +
  "placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50";

/**
 * Perfil → Reporte de errores — bug-report panel.
 *
 * On mount it calls `GET /api/bugreport/assemble` — once, readonly — and
 * renders the allow-listed, content-scanned default bundle. Assembly is
 * server-provided because the browser sandbox cannot read local logs/`uname`.
 *
 * The flow enforces the spec's MANDATORY preview gate: submission stays
 * disabled until the exact payload has been rendered for review. The user can
 * edit the description and remove fields (logs, contact); any edit invalidates
 * the preview so the submitted payload is always exactly what was shown.
 * Submit goes through the stateless relay (`submitBugReport`); on success the
 * panel reports delivery and hides the fallback, on failure it prepares the
 * STRICT fallback (`fallbackBody`) — a privacy-scrubbed copy-paste issue body
 * plus the `maar1223/Demiurgos` issue-form link, offered only on failure.
 */
export function ReportSection() {
  const { t } = useAppLanguage();

  const [bundle, setBundle] = useState<BugReportBundle | null>(null);
  const [assembling, setAssembling] = useState(true);
  const [assembleError, setAssembleError] = useState<string | null>(null);

  // Editable review state (spec: preview and edit are mandatory before submit).
  const [description, setDescription] = useState("");
  const [contact, setContact] = useState("");
  const [includeLogs, setIncludeLogs] = useState(true);
  // The mandatory gate: submit stays disabled until the exact bundle has been
  // shown at least once, and re-locks on every edit so nothing ships unseen.
  const [previewed, setPreviewed] = useState(false);

  // Screenshots are chosen explicitly, never captured (§S5): adding or removing
  // one re-locks the gate, because the image leaves only after it was seen.
  const [attachments, setAttachments] = useState<File[]>([]);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const attachmentInput = useRef<HTMLInputElement>(null);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  // Strict fallback state — populated ONLY after a failed delivery.
  const [fallback, setFallback] = useState<BugReportFallback | null>(null);
  const [fallbackError, setFallbackError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // One read-only assemble on mount (spec: assembly is a server step). The
  // guard flag keeps a slow response from setting state on an unmounted panel.
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const next = await assembleBugReport();
        if (active) setBundle(next);
      } catch (cause: unknown) {
        if (active) {
          setAssembleError(describeError(cause, t("profile.bugreport.loadError")));
        }
      } finally {
        if (active) setAssembling(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [t]);

  const logsIncluded = Boolean(bundle?.logs.included) && includeLogs;

  // The submitted payload is built live from the current review state, so edits
  // and removals are always reflected (spec: edits/removals reflected).
  const buildPayload = useCallback((): BugReportSubmitPayload | null => {
    if (!bundle) return null;
    const trimmedContact = contact.trim();
    return {
      app_version: bundle.app_version,
      platform: bundle.platform,
      description,
      ...(trimmedContact ? { contact: trimmedContact } : {}),
      ...(logsIncluded ? { logs: bundle.logs.content } : {}),
    };
  }, [bundle, contact, description, logsIncluded]);

  const payloadPreview = useMemo(() => {
    const payload = buildPayload();
    return payload ? JSON.stringify(payload, null, 2) : "";
  }, [buildPayload]);

  /** Any review edit invalidates the preview — the exact-shown guarantee. */
  const markEdited = useCallback(() => setPreviewed(false), []);

  const addAttachments = useCallback(
    (chosen: FileList | null) => {
      if (chosen === null || chosen.length === 0) return;
      setAttachmentError(null);
      const next = [...attachments];
      let error: string | null = null;
      for (const file of Array.from(chosen)) {
        if (next.length >= ATTACHMENTS_MAX) {
          error = t("profile.bugreport.attachmentLimit");
          break;
        }
        if (!ATTACHMENT_TYPES.has(file.type)) {
          error = t("profile.bugreport.attachmentType");
          continue;
        }
        if (file.size > ATTACHMENT_MAX_BYTES) {
          error = t("profile.bugreport.attachmentTooLarge");
          continue;
        }
        next.push(file);
      }
      setAttachmentError(error);
      if (next.length !== attachments.length) {
        setAttachments(next);
        markEdited();
      }
    },
    [attachments, markEdited, t],
  );

  const removeAttachment = useCallback(
    (target: File) => {
      setAttachments((current) => current.filter((file) => file !== target));
      setAttachmentError(null);
      markEdited();
    },
    [markEdited],
  );

  const submit = useCallback(async () => {
    const payload = buildPayload();
    if (!payload || !previewed || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    setFallback(null);
    setFallbackError(null);
    setCopied(false);
    try {
      await submitBugReport(payload, attachments);
      setSubmitted(true);
    } catch (cause: unknown) {
      setSubmitError(describeError(cause, t("profile.bugreport.submitError")));
      // STRICT fallback: prepared ONLY after a failed delivery, never in
      // parallel with a success.
      try {
        const next = await fallbackBody(payload);
        setFallback(next);
      } catch (fallbackCause: unknown) {
        setFallbackError(
          describeError(fallbackCause, t("error.bugreport.fallbackFailed")),
        );
      }
    } finally {
      setSubmitting(false);
    }
  }, [attachments, buildPayload, previewed, submitting, t]);

  const copyFallback = useCallback(async () => {
    if (!fallback || !navigator.clipboard) {
      setCopied(false);
      return;
    }
    try {
      await navigator.clipboard.writeText(fallback.body);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }, [fallback]);

  return (
    <section
      aria-labelledby="profile-report-panel-title"
      className="rounded-lg border border-edge bg-surface-raised p-4"
    >
      <h3
        id="profile-report-panel-title"
        className="font-heading text-body text-primary"
      >
        {t("profile.bugreport.panelTitle")}
      </h3>
      <p className="mt-1 text-small text-muted">{t("profile.bugreport.intro")}</p>

      <TelegramLinkPanel />

      {assembling ? (
        <div className="mt-4 flex items-center gap-2 text-small text-muted">
          <Spinner size="sm" />
          {t("profile.bugreport.loading")}
        </div>
      ) : assembleError ? (
        <p role="alert" className="mt-4 text-small text-status-error">
          {assembleError}
        </p>
      ) : bundle ? (
        <>
          <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-small text-muted">
                {t("profile.bugreport.appVersion")}
              </dt>
              <dd
                className="font-medium text-primary"
                data-testid="bugreport-app-version"
              >
                {bundle.app_version}
              </dd>
            </div>
            <div>
              <dt className="text-small text-muted">
                {t("profile.bugreport.platform")}
              </dt>
              <dd
                className="font-medium text-primary"
                data-testid="bugreport-platform"
              >
                {bundle.platform.os} {bundle.platform.os_version} ·{" "}
                {bundle.platform.arch} · Python {bundle.platform.python_version}
              </dd>
            </div>
            <div>
              <dt className="text-small text-muted">
                {t("profile.bugreport.logs")}
              </dt>
              <dd
                className="font-medium text-primary"
                data-testid="bugreport-logs-status"
              >
                {bundle.logs.included
                  ? t("profile.bugreport.logsIncluded")
                  : t("profile.bugreport.logsExcluded")}
                {bundle.logs.redacted_lines > 0 &&
                  ` · ${t("profile.bugreport.redactedLines", {
                    count: bundle.logs.redacted_lines,
                  })}`}
              </dd>
              {!bundle.logs.included && bundle.logs.reason && (
                <dd className="text-small text-muted">
                  {t("profile.bugreport.logsReason")}: {bundle.logs.reason}
                </dd>
              )}
            </div>
            <div>
              <dt className="text-small text-muted">
                {t("profile.bugreport.allowList")}
              </dt>
              <dd
                className="font-medium text-primary"
                data-testid="bugreport-allow-list"
              >
                {bundle.allow_list.join(", ")}
              </dd>
            </div>
          </dl>

          {/* Editable review fields — every edit re-locks the mandatory gate. */}
          <div className="mt-4 flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <label
                htmlFor="bugreport-description"
                className="text-small text-muted"
              >
                {t("profile.bugreport.descriptionLabel")}
              </label>
              <textarea
                id="bugreport-description"
                rows={4}
                value={description}
                placeholder={t("profile.bugreport.descriptionPlaceholder")}
                onChange={(event) => {
                  setDescription(event.target.value);
                  markEdited();
                }}
                className={FIELD_INPUT_CLASS}
                data-testid="bugreport-description"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="bugreport-contact" className="text-small text-muted">
                {t("profile.bugreport.contactLabel")}
              </label>
              <input
                id="bugreport-contact"
                type="text"
                value={contact}
                placeholder={t("profile.bugreport.contactPlaceholder")}
                onChange={(event) => {
                  setContact(event.target.value);
                  markEdited();
                }}
                className={FIELD_INPUT_CLASS}
                data-testid="bugreport-contact"
              />
            </div>
            {bundle.logs.included && (
              <label className="flex items-center gap-2 text-small text-primary">
                <input
                  type="checkbox"
                  checked={includeLogs}
                  onChange={(event) => {
                    setIncludeLogs(event.target.checked);
                    markEdited();
                  }}
                />
                {t("profile.bugreport.includeLogs")}
              </label>
            )}
          </div>

          <div className="mt-4 flex flex-col gap-2">
            <p className="text-small font-medium text-primary">
              {t("profile.bugreport.attachmentsTitle")}
            </p>
            <p className="text-small text-muted">
              {t("profile.bugreport.attachmentsHint")}
            </p>
            <input
              ref={attachmentInput}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              className="sr-only"
              aria-label={t("profile.bugreport.addScreenshot")}
              onChange={(event) => {
                addAttachments(event.target.files);
                event.target.value = "";
              }}
              data-testid="bugreport-attachment-input"
            />
            <div>
              <Button
                variant="secondary"
                onClick={() => attachmentInput.current?.click()}
                disabled={attachments.length >= ATTACHMENTS_MAX}
              >
                {t("profile.bugreport.addScreenshot")}
              </Button>
            </div>
            {attachments.length > 0 && (
              <ul className="flex flex-col gap-2">
                {attachments.map((file) => (
                  <AttachmentThumb
                    key={`${file.name}-${file.size}-${file.lastModified}`}
                    file={file}
                    onRemove={() => removeAttachment(file)}
                    removeLabel={t("profile.bugreport.removeScreenshot")}
                  />
                ))}
              </ul>
            )}
            {attachmentError && (
              <p role="alert" className="text-small text-status-error">
                {attachmentError}
              </p>
            )}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button variant="secondary" onClick={() => setPreviewed(true)}>
              {t("profile.bugreport.preview")}
            </Button>
            <Button
              onClick={() => void submit()}
              disabled={!previewed || submitting || submitted}
            >
              {submitting && <Spinner size="sm" />}
              {submitting
                ? t("profile.bugreport.submitting")
                : t("profile.bugreport.submit")}
            </Button>
          </div>

          {previewed && (
            <div
              className="mt-4 rounded-lg border border-edge bg-surface p-3"
              data-testid="bugreport-preview"
            >
              <p className="text-small font-medium text-primary">
                {t("profile.bugreport.previewTitle")}
              </p>
              <p className="mt-1 text-small text-muted">
                {t("profile.bugreport.previewHint")}
              </p>
              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-small text-primary">
                {payloadPreview}
              </pre>
              {attachments.length > 0 && (
                <div className="mt-2" data-testid="bugreport-preview-attachments">
                  <p className="text-small font-medium text-primary">
                    {t("profile.bugreport.previewAttachments", {
                      count: attachments.length,
                    })}
                  </p>
                  <ul className="mt-1 flex flex-col gap-1 text-small text-muted">
                    {attachments.map((file) => (
                      <li key={`${file.name}-${file.size}-${file.lastModified}`}>
                        {file.name} · {describeBytes(file.size)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {submitted && (
            <p role="status" className="mt-3 text-small text-status-success">
              {t("profile.bugreport.submitSuccess")}
            </p>
          )}

          {submitError && (
            <p role="alert" className="mt-3 text-small text-status-error">
              {submitError}
            </p>
          )}

          {fallback && (
            <div
              className="mt-4 rounded-lg border border-edge bg-surface p-3"
              data-testid="bugreport-fallback"
            >
              <p className="text-small font-medium text-primary">
                {t("profile.bugreport.fallbackTitle")}
              </p>
              <p className="mt-1 text-small text-muted">
                {t("profile.bugreport.fallbackHint")}
              </p>
              <p className="mt-1 text-small text-muted">
                {t("profile.bugreport.fallbackScrubNote")}
              </p>
              <textarea
                readOnly
                rows={8}
                value={fallback.body}
                aria-label={t("profile.bugreport.fallbackBodyLabel")}
                className={`mt-2 w-full ${FIELD_INPUT_CLASS}`}
                data-testid="bugreport-fallback-body"
              />
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Button variant="secondary" onClick={() => void copyFallback()}>
                  {copied
                    ? t("profile.bugreport.fallbackCopied")
                    : t("profile.bugreport.fallbackCopy")}
                </Button>
                <a
                  href={fallback.issue_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid="bugreport-fallback-link"
                  className="text-small font-medium text-action underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
                >
                  {t("profile.bugreport.fallbackOpen")}
                </a>
              </div>
            </div>
          )}

          {fallbackError && (
            <p role="alert" className="mt-3 text-small text-status-error">
              {fallbackError}
            </p>
          )}
        </>
      ) : null}
    </section>
  );
}
