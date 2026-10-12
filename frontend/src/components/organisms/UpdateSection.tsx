import { useCallback, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { getUpdateStatus, setUpdateChannel } from "@/api/updates";
import { ApiError, type UpdateChannel, type UpdateStatus } from "@/api/types";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { cn, getErrorMessage } from "@/lib/utils";

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
 * Perfil → Actualizaciones — read-only update panel (v1).
 *
 * Manual-only by design (spec: "Read-only frontend update panel"): the panel
 * issues NO request on mount and runs NO timer/polling. Every network call is
 * driven by an explicit action — the "Buscar actualizaciones" button (GET
 * status) or the channel selector (PUT channel). The status payload is
 * advisory and display-only; the apply/install flow ships in a later slice.
 */
export function UpdateSection() {
  const { t } = useAppLanguage();

  const [status, setStatus] = useState<UpdateStatus | null>(null);
  // The server owns the default channel ("Estable" on a fresh install). The
  // selector starts from that documented default and mirrors whatever the last
  // status read reported.
  const [channel, setChannel] = useState<UpdateChannel>("Estable");
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [savingChannel, setSavingChannel] = useState(false);
  const [channelError, setChannelError] = useState<string | null>(null);

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
            {status?.current_version ?? t("profile.updates.versionUnknown")}
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
            <p className="flex items-center gap-2 text-small text-primary">
              <Icon name="download" size={16} className="text-action" />
              {t("profile.updates.available", { version: status.latest ?? "" })}
            </p>
          ) : (
            <p className="flex items-center gap-2 text-small text-muted">
              <Icon name="check" size={16} className="text-status-success" />
              {t("profile.updates.upToDate")}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
