import { useEffect, useState } from "react";
import { Spinner } from "@/components/atoms/Spinner";
import { assembleBugReport } from "@/api/bugReports";
import { ApiError, type BugReportBundle } from "@/api/types";
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

/**
 * Perfil → Reporte de errores — bug-report panel (S2a skeleton).
 *
 * On mount it calls `GET /api/bugreport/assemble` — once, readonly — and
 * renders the allow-listed, content-scanned default bundle: app version,
 * allow-listed platform facts, the logs status (included/excluded + redaction
 * count + non-secret reason) and the allow-list itself. Assembly is
 * server-provided because the browser sandbox cannot read local logs/`uname`.
 *
 * This slice ships the skeleton only: the preview/edit + mandatory submit
 * gate, the submit UI and the strict fallback land in later slices. A failed
 * assembly never crashes the host page — it renders the localized error.
 */
export function ReportSection() {
  const { t } = useAppLanguage();

  const [bundle, setBundle] = useState<BugReportBundle | null>(null);
  const [assembling, setAssembling] = useState(true);
  const [assembleError, setAssembleError] = useState<string | null>(null);

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
        <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <dt className="text-small text-muted">
              {t("profile.bugreport.appVersion")}
            </dt>
            <dd className="font-medium text-primary" data-testid="bugreport-app-version">
              {bundle.app_version}
            </dd>
          </div>
          <div>
            <dt className="text-small text-muted">
              {t("profile.bugreport.platform")}
            </dt>
            <dd className="font-medium text-primary" data-testid="bugreport-platform">
              {bundle.platform.os} {bundle.platform.os_version} ·{" "}
              {bundle.platform.arch} · Python {bundle.platform.python_version}
            </dd>
          </div>
          <div>
            <dt className="text-small text-muted">{t("profile.bugreport.logs")}</dt>
            <dd className="font-medium text-primary" data-testid="bugreport-logs-status">
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
            <dd className="font-medium text-primary" data-testid="bugreport-allow-list">
              {bundle.allow_list.join(", ")}
            </dd>
          </div>
        </dl>
      ) : null}
    </section>
  );
}