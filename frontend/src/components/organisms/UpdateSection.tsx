import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { getAppConfig } from "@/api/config";
import { getUpdateStatus, setUpdateChannel, applyUpdate } from "@/api/updates";
import { getBugReportReleases } from "@/api/bugReports";
import { getAuthStatus, logoutSession } from "@/api/wiki";
import { reloadPage } from "@/lib/reloadPage";
import { ApiError, type UpdateChannel, type UpdateStatus } from "@/api/types";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { cn, getErrorMessage } from "@/lib/utils";
import {
  matchReleasedReports,
  readSubmittedReports,
  type FixedReport,
} from "@/lib/bugReportHistory";

/** Selectable channels in display order. The wire value doubles as the label
 *  key suffix; "Estable" is the server-owned fresh-install default. */
const CHANNELS: UpdateChannel[] = ["Estable", "Beta"];

const CHANNEL_LABEL_KEY = {
  Estable: "profile.updates.channel.estable",
  Beta: "profile.updates.channel.beta",
} as const;

/** Resolve a localized message for a caught error, falling back when the
 *  thrown value is not an `ApiError`. */
function describeError(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError) {
    return getErrorMessage(cause.status, cause.detail, cause.code, cause.params);
  }
  return fallback;
}

/**
 * Perfil → Actualizaciones — update panel (v1).
 *
 * Manual-only by design (spec: "Read-only frontend update panel"): the panel
 * runs NO timer/polling for checks. It reads the app's own metadata once on
 * mount to display the running version. Every check/channel/apply call is
 * driven by an explicit action — the "Buscar actualizaciones"
 * button (GET status), the channel selector (PUT channel), and the
 * "Instalar y reiniciar" apply flow. The status payload is advisory and
 * display-only. The apply flow mirrors the Navbar restart flow: confirmation
 * dialog → logout FIRST → apply dispatch (90s timeout) → full-screen
 * transition overlay polling until the stack is back.
 */
export function UpdateSection() {
  const { t } = useAppLanguage();

  const [status, setStatus] = useState<UpdateStatus | null>(null);
  // Running version for the render-time display, read once from the app's own
  // metadata (`GET /api/config.app_version`). This is NOT the update check:
  // the check stays manual-only (spec: no background/polling request).
  const [appVersion, setAppVersion] = useState<string | null>(null);
  // Reports this install sent that a released version fixed (S12). The list is
  // matched locally, so the relay never learns who reported what.
  const [fixedReports, setFixedReports] = useState<FixedReport[]>([]);
  // The server owns the default channel ("Estable" on a fresh install). The
  // selector starts from that documented default and mirrors whatever the last
  // status read reported.
  const [channel, setChannel] = useState<UpdateChannel>("Estable");
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [savingChannel, setSavingChannel] = useState(false);
  const [channelError, setChannelError] = useState<string | null>(null);

  // Apply flow (mirrors Navbar restart): dialog -> logout -> POST -> overlay.
  const [applyOpen, setApplyOpen] = useState(false);
  const [applyBusy, setApplyBusy] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyNotice, setApplyNotice] = useState<string | null>(null);
  const applyTimerRef = useRef<number | null>(null);

  // Released fixes: one read on mount, matching the ids this install kept.
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const { releases } = await getBugReportReleases();
        if (active) {
          setFixedReports(matchReleasedReports(readSubmittedReports(), releases));
        }
      } catch {
        // The notice is an extra, never a blocker: a relay hiccup leaves the
        // panel working and simply shows nothing.
        if (active) setFixedReports([]);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  // Render-time version: one read of the app's own metadata on mount (spec
  // "Read-only frontend update panel" renders the current version). It never
  // polls and never triggers the advisory update check.
  useEffect(() => {
    let active = true;
    // Async IIFE so a synchronous throw from the client is caught too — the
    // panel must never crash a host page just because app metadata is missing.
    void (async () => {
      try {
        const config = await getAppConfig();
        if (active) setAppVersion(config.app_version);
      } catch {
        if (active) setAppVersion(null);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const check = useCallback(() => {
    setChecking(true);
    setCheckError(null);
    void getUpdateStatus()
      .then((next) => {
        setStatus(next);
        setChannel(next.channel);
      })
      .catch((cause: unknown) => {
        setCheckError(describeError(cause, t("profile.updates.checkError")));
      })
      .finally(() => setChecking(false));
  }, [t]);

  const selectChannel = useCallback(
    (next: UpdateChannel) => {
      if (next === channel || savingChannel) return;
      const previous = channel;
      // Optimistic: reflect the choice immediately, revert on rejection.
      setChannel(next);
      setSavingChannel(true);
      setChannelError(null);
      void setUpdateChannel(next)
        .then((result) => setChannel(result.channel))
        .catch((cause: unknown) => {
          setChannel(previous);
          setChannelError(describeError(cause, t("profile.updates.channelError")));
        })
        .finally(() => setSavingChannel(false));
    },
    [channel, savingChannel, t],
  );

  /** Open the apply confirmation dialog with a fresh error state. */
  const requestApply = useCallback(() => {
    setApplyError(null);
    setApplyNotice(null);
    setApplyOpen(true);
  }, []);

  /** Cancel/close must stop the busy state — never leave the dialog stuck. */
  const closeApply = useCallback(() => {
    setApplyOpen(false);
    setApplyBusy(false);
    setApplyError(null);
  }, []);

  /** Confirmed apply: logout FIRST, then dispatch, then show the overlay. */
  const confirmApply = useCallback(async () => {
    setApplyBusy(true);
    setApplyError(null);
    try {
      // Session safety (spec 'Local session is logged out before apply'): the
      // installer restarts the whole stack, so the local session must be
      // closed BEFORE the dispatch — the server never clears it itself.
      await logoutSession();
      try {
        await applyUpdate();
      } catch (cause: unknown) {
        // A dropped connection (status 0) means the installer killed the
        // backend mid-dispatch — the EXPECTED outcome once the apply starts.
        if (!(cause instanceof ApiError && cause.status === 0)) {
          setApplyError(describeError(cause, t("profile.updates.applyError")));
          return;
        }
      }
      // Accepted (or connection dropped mid-install): close the dialog and
      // show a blocking screen until the stack comes back.
      setApplyOpen(false);
      setApplying(true);
    } catch (cause: unknown) {
      // logoutSession itself failed — nothing was dispatched; keep the dialog
      // open so the user can retry or close.
      setApplyError(describeError(cause, t("profile.updates.applyError")));
    } finally {
      setApplyBusy(false);
    }
  }, [t]);

  // After an accepted apply the backend goes down (install) and comes back
  // (restart) with the new version. Poll a lightweight endpoint until it
  // responds, then reload the page automatically (mirrors Navbar restart).
  useEffect(() => {
    if (!applying) return;
    let attempts = 0;
    applyTimerRef.current = window.setInterval(async () => {
      attempts += 1;
      try {
        await getAuthStatus();
        if (applyTimerRef.current) window.clearInterval(applyTimerRef.current);
        reloadPage();
      } catch {
        if (attempts > 30) {
          if (applyTimerRef.current) window.clearInterval(applyTimerRef.current);
          setApplying(false);
          setApplyNotice(t("profile.updates.applyServerDown"));
        }
      }
    }, 2000);
    return () => {
      if (applyTimerRef.current) window.clearInterval(applyTimerRef.current);
    };
  }, [applying, t]);

  return (
    <section
      aria-labelledby="profile-updates-panel-title"
      className="rounded-lg border border-edge bg-surface-raised p-4"
    >
      <h3
        id="profile-updates-panel-title"
        className="font-heading text-body text-primary"
      >
        {t("profile.updates.panelTitle")}
      </h3>
      <p className="mt-1 text-small text-muted">{t("profile.updates.manualHint")}</p>

      <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <dt className="text-small text-muted">
            {t("profile.updates.currentVersion")}
          </dt>
          <dd className="font-medium text-primary" data-testid="update-current-version">
            {status?.current_version ??
              appVersion ??
              t("profile.updates.versionUnknown")}
          </dd>
        </div>
        <div>
          <dt className="text-small text-muted">
            {t("profile.updates.channelLabel")}
          </dt>
          <dd className="font-medium text-primary" data-testid="update-channel-value">
            {t(CHANNEL_LABEL_KEY[channel])}
          </dd>
        </div>
      </dl>

      {fixedReports.length > 0 && (
        <div
          className="mt-4 rounded-lg border border-edge bg-surface p-3"
          data-testid="updates-fixed-reports"
        >
          <p className="text-small font-medium text-primary">
            {t("profile.updates.fixedTitle")}
          </p>
          <ul className="mt-1 flex flex-col gap-1 text-small text-muted">
            {fixedReports.map((report) => (
              <li key={report.id} data-testid="updates-fixed-report">
                {t("profile.updates.fixedIn", {
                  id: report.id.slice(0, 8),
                  version: report.version,
                })}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4">
        <span className="text-small text-muted" id="profile-updates-channel-label">
          {t("profile.updates.channelLabel")}
        </span>
        <div
          role="radiogroup"
          aria-labelledby="profile-updates-channel-label"
          className="mt-2 flex flex-wrap gap-2"
        >
          {CHANNELS.map((option) => {
            const active = option === channel;
            return (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={active}
                disabled={savingChannel}
                onClick={() => selectChannel(option)}
                className={cn(
                  "rounded-lg border px-3 py-1.5 text-small transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50",
                  "disabled:cursor-not-allowed disabled:opacity-50",
                  active
                    ? "border-action bg-action text-action-text"
                    : "border-edge bg-surface text-primary hover:bg-surface-hover",
                )}
              >
                {t(CHANNEL_LABEL_KEY[option])}
              </button>
            );
          })}
        </div>
        {channelError && (
          <p role="alert" className="mt-2 text-small text-status-error">
            {channelError}
          </p>
        )}
      </div>

      <div className="mt-4">
        <Button onClick={check} disabled={checking}>
          {checking ? <Spinner size="sm" /> : <Icon name="download" size={16} />}
          {checking ? t("profile.updates.checking") : t("profile.updates.check")}
        </Button>
      </div>

      {checkError && (
        <p role="alert" className="mt-3 text-small text-status-error">
          {checkError}
        </p>
      )}

      {status && !checkError && (
        <div className="mt-4 rounded-lg border border-edge bg-surface p-3">
          {status.advisory_unavailable ? (
            <p className="text-small text-muted">
              {t("profile.updates.advisoryUnavailable")}
            </p>
          ) : status.update_available ? (
            <>
              <p className="flex items-center gap-2 text-small text-primary">
                <Icon name="download" size={16} className="text-action" />
                {t("profile.updates.available", { version: status.latest ?? "" })}
              </p>
              <Button onClick={requestApply} className="mt-3">
                <Icon name="download" size={16} />
                {t("profile.updates.apply")}
              </Button>
            </>
          ) : (
            <p className="flex items-center gap-2 text-small text-muted">
              <Icon name="check" size={16} className="text-status-success" />
              {t("profile.updates.upToDate")}
            </p>
          )}
        </div>
      )}

      {applyNotice && (
        <p role="alert" className="mt-3 text-small text-status-error">
          {applyNotice}
        </p>
      )}

      {/* Apply confirmation (mirrors Navbar restart): the install closes the
          local session and restarts the stack, so it requires an explicit
          confirm before logout + dispatch. */}
      {applyOpen && (
        <ConfirmDialog
          title={t("profile.updates.confirmTitle")}
          message={t("profile.updates.confirmMessage", {
            version: status?.latest ?? "",
          })}
          confirmLabel={t("profile.updates.apply")}
          isBusy={applyBusy}
          error={applyError}
          onConfirm={() => void confirmApply()}
          onClose={closeApply}
        />
      )}

      {/* Full-screen transition overlay while the installer runs and the
          backend restarts (mirrors Navbar's restarting overlay). */}
      {applying &&
        createPortal(
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-surface/90 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-3 px-6 text-center">
              <Spinner size="lg" />
              <p className="text-body text-primary">
                {t("profile.updates.applying")}
              </p>
              <p className="max-w-sm text-small text-muted">
                {t("profile.updates.transitionApplying")}
              </p>
            </div>
          </div>,
          document.body,
        )}
    </section>
  );
}
