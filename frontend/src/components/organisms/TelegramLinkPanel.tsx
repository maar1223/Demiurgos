import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { QrCode } from "@/components/atoms/QrCode";
import {
  revokeTelegramLink,
  startTelegramLink,
  telegramLinkState,
  telegramLinkStatus,
  type BugReportLinkFlags,
} from "@/api/bugReports";
import {
  ApiError,
  type BugReportLinkPermissions,
  type BugReportLinkStatus,
} from "@/api/types";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import {
  clearPendingLink,
  readPendingLink,
  writePendingLink,
} from "@/lib/bugReportHistory";
import { getErrorMessage } from "@/lib/utils";

/** Resolve a localized message for a caught error, falling back when the thrown
 *  value is not an `ApiError`. */
function describeError(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError) {
    return getErrorMessage(cause.status, cause.detail, cause.code, cause.params);
  }
  return fallback;
}

function mmss(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

type Phase = "idle" | "starting" | "pending" | "linked" | "expired";

interface LinkedIdentity {
  username: string | null;
  display_name: string | null;
  permissions: BugReportLinkPermissions;
}

/**
 * Telegram linking for the bug reporter (S7–S11).
 *
 * The browser never talks to the relay: the backend mints and polls the ticket
 * with the shared key, and it keeps the one-time signing token server-side.
 *
 * Flow: mint a ticket → show a QR of the `https://t.me/...` deep link plus the
 * code to type → poll every two seconds → close the loop the moment the phone
 * confirms, with the handle Telegram gave us. Polling stops at expiry, and the
 * countdown is honest about it rather than spinning forever.
 *
 * `pollIntervalMs` exists so tests do not have to wait two seconds; production
 * always uses the default.
 */
export function TelegramLinkPanel({
  pollIntervalMs = 2000,
  slowHintMs = 30_000,
}: {
  pollIntervalMs?: number;
  slowHintMs?: number;
}) {
  const { t } = useAppLanguage();

  const [phase, setPhase] = useState<Phase>("idle");
  const [ticket, setTicket] = useState<string | null>(null);
  const [telegramUrl, setTelegramUrl] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  // When the phone has not confirmed after a while, say what to do instead of
  // leaving a bare "waiting" on screen.
  const [waitedLong, setWaitedLong] = useState(false);
  const [linked, setLinked] = useState<LinkedIdentity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [reportIdentity, setReportIdentity] = useState(true);
  const [notifyReleases, setNotifyReleases] = useState(true);
  // Set the moment a ticket is requested. A synchronous ref, because the mount
  // read must not overwrite a ticket that was already minted while it was in
  // flight — React state would still be the pre-click value in that closure.
  const startedByUser = useRef(false);

  const start = useCallback(
    async (silent: boolean, flags: BugReportLinkFlags) => {
      startedByUser.current = true;
      if (!silent) setPhase("starting");
      setError(null);
      setCopied(false);
      try {
        const next = await startTelegramLink(flags);
        setTicket(next.ticket);
        setTelegramUrl(next.telegram_url);
        setExpiresAt(next.expires_at);
        setLinked(null);
        // The token is minted on the first poll after the phone confirms, so a
        // reload mid-flow must be able to resume this ticket.
        writePendingLink({
          ticket: next.ticket,
          expires_at: next.expires_at,
          telegram_url: next.telegram_url,
        });
        setWaitedLong(false);
        setPhase("pending");
      } catch (cause: unknown) {
        setError(describeError(cause, t("profile.bugreport.telegramError")));
        setPhase("idle");
      }
    },
    [t],
  );

  // The link lives in the relay (S10), so the panel asks it once on mount
  // instead of trusting a local flag. A failed read is not an error worth an
  // alert: the connect action still works, it just cannot say "already linked".
  useEffect(() => {
    let active = true;

    const read = async () => {
      let linkedNow = false;
      try {
        const next = await telegramLinkState();
        if (active && !startedByUser.current && next.state === "linked") {
          linkedNow = true;
          setLinked({
            username: next.username,
            display_name: next.display_name,
            permissions: next.permissions,
          });
          setTelegramUrl(next.telegram_url);
          // A click that already started a ticket must win over this read.
          setPhase((current) => (current === "idle" ? "linked" : current));
        }
      } catch {
        // Offline or relay down: leaving the connect action in place is honest.
      }

      // No link yet: a ticket minted before a reload is still live, so resume
      // polling it instead of making the user scan a second QR.
      if (!active || startedByUser.current || linkedNow) return;
      const pending = readPendingLink();
      if (pending === null) return;
      setTicket(pending.ticket);
      setTelegramUrl(pending.telegram_url);
      setExpiresAt(pending.expires_at);
      setWaitedLong(false);
      setPhase((current) => (current === "idle" ? "pending" : current));
    };

    void read();
    return () => {
      active = false;
    };
  }, []);

  // Countdown to the ticket's expiry; at zero the ticket is gone and polling
  // must stop instead of asking a dead ticket forever.
  useEffect(() => {
    if (phase !== "pending" || expiresAt === null) {
      setSecondsLeft(null);
      return;
    }
    const target = Date.parse(expiresAt);
    if (Number.isNaN(target)) {
      setSecondsLeft(null);
      return;
    }
    const tick = () => {
      const left = Math.max(0, Math.ceil((target - Date.now()) / 1000));
      setSecondsLeft(left);
      if (left === 0) {
        clearPendingLink();
        setWaitedLong(false);
        setPhase((current) => (current === "pending" ? "expired" : current));
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [expiresAt, phase]);

  // A phone that never confirms would leave "waiting" on screen with nothing to
  // do about it. After a short window, say what actually helps — and re-arm the
  // window whenever a new ticket is minted.
  useEffect(() => {
    if (phase !== "pending") return;
    const id = setTimeout(() => setWaitedLong(true), slowHintMs);
    return () => clearTimeout(id);
  }, [phase, slowHintMs, ticket]);

  // The phone does the work; the panel polls until it answers.
  useEffect(() => {
    if (phase !== "pending" || ticket === null) return;
    let active = true;
    let inFlight = false;

    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const next: BugReportLinkStatus = await telegramLinkStatus(ticket);
        if (!active) return;
        if (next.state === "linked") {
          clearPendingLink();
          setWaitedLong(false);
          setLinked({
            username: next.username,
            display_name: next.display_name,
            permissions: next.permissions,
          });
          setPhase("linked");
        } else if (next.state === "expired") {
          setPhase("expired");
        } else if (next.expires_at) {
          setExpiresAt(next.expires_at);
        }
      } catch (cause: unknown) {
        if (active) {
          setError(describeError(cause, t("profile.bugreport.telegramError")));
        }
      } finally {
        inFlight = false;
      }
    };

    void poll();
    const id = setInterval(() => void poll(), pollIntervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [phase, pollIntervalMs, t, ticket]);

  const copyTicket = useCallback(async () => {
    if (ticket === null || !navigator.clipboard) {
      setCopied(false);
      return;
    }
    try {
      await navigator.clipboard.writeText(ticket);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }, [ticket]);

  const applyFlag = useCallback(
    (flag: "report_identity" | "notify_releases", value: boolean) => {
      if (flag === "report_identity") setReportIdentity(value);
      else setNotifyReleases(value);
      if (phase === "pending") {
        // A permission is a separate grant (S11); stating it on a reused ticket
        // must reach the relay, which is what minting again does.
        void start(true, {
          report_identity: flag === "report_identity" ? value : reportIdentity,
          notify_releases: flag === "notify_releases" ? value : notifyReleases,
        });
      }
    },
    [notifyReleases, phase, reportIdentity, start],
  );

  const disconnect = useCallback(async () => {
    setError(null);
    try {
      await revokeTelegramLink();
    } catch (cause: unknown) {
      setError(describeError(cause, t("profile.bugreport.telegramError")));
      return;
    }
    clearPendingLink();
    setWaitedLong(false);
    setPhase("idle");
    setTicket(null);
    setTelegramUrl(null);
    setExpiresAt(null);
    setLinked(null);
    setCopied(false);
  }, [t]);

  const connectedAs =
    linked?.username !== null && linked?.username !== undefined
      ? `@${linked.username}`
      : (linked?.display_name ?? "");

  return (
    <section
      aria-labelledby="bugreport-telegram-title"
      className="mt-4 rounded-lg border border-edge bg-surface p-3"
      data-testid="bugreport-telegram"
    >
      <h4 id="bugreport-telegram-title" className="text-small font-medium text-primary">
        {t("profile.bugreport.telegramTitle")}
      </h4>
      <p className="mt-1 text-small text-muted">
        {t("profile.bugreport.telegramIntro")}
      </p>

      {error && (
        <p role="alert" className="mt-2 text-small text-status-error">
          {error}
        </p>
      )}

      {(phase === "idle" || phase === "starting") && (
        <div className="mt-2">
          <Button
            variant="secondary"
            onClick={() => void start(false, {
              report_identity: reportIdentity,
              notify_releases: notifyReleases,
            })}
            disabled={phase === "starting"}
          >
            {phase === "starting" && <Spinner size="sm" />}
            {phase === "starting"
              ? t("profile.bugreport.telegramStarting")
              : t("profile.bugreport.telegramConnect")}
          </Button>
        </div>
      )}

      {phase === "pending" && ticket !== null && (
        <div className="mt-3 flex flex-col gap-3 sm:flex-row">
          {telegramUrl !== null && (
            <QrCode value={telegramUrl} label={t("profile.bugreport.telegramScan")} />
          )}
          <div className="flex min-w-0 flex-col gap-2">
            <p className="text-small text-muted">
              {t("profile.bugreport.telegramScan")}
            </p>
            {telegramUrl !== null ? (
              <a
                href={telegramUrl}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="bugreport-telegram-link"
                className="text-small font-medium text-action underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
              >
                {t("profile.bugreport.telegramOpenLink")}
              </a>
            ) : (
              <p className="text-small text-muted">
                {t("profile.bugreport.telegramNoLink")}
              </p>
            )}
            <p className="text-small text-primary">
              <span className="text-muted">
                {t("profile.bugreport.telegramCodeLabel")}:{" "}
              </span>
              <span className="font-mono" data-testid="bugreport-telegram-ticket">
                {ticket}
              </span>
            </p>
            <div>
              <Button variant="secondary" onClick={() => void copyTicket()}>
                {copied
                  ? t("profile.bugreport.telegramCopied")
                  : t("profile.bugreport.telegramCopyCode")}
              </Button>
            </div>
            {secondsLeft !== null && (
              <p className="text-small text-muted" data-testid="bugreport-telegram-countdown">
                {t("profile.bugreport.telegramExpiresIn", { time: mmss(secondsLeft) })}
              </p>
            )}
            <p role="status" className="text-small text-muted">
              {t("profile.bugreport.telegramWaiting")}
            </p>
            {waitedLong && (
              <p className="text-small text-muted" data-testid="bugreport-telegram-slow">
                {t("profile.bugreport.telegramWaitingSlow")}
              </p>
            )}
            <div className="flex flex-col gap-1">
              <label className="flex items-start gap-2 text-small text-primary">
                <input
                  type="checkbox"
                  checked={reportIdentity}
                  onChange={(event) => applyFlag("report_identity", event.target.checked)}
                  className="mt-1"
                />
                {t("profile.bugreport.telegramPermReport")}
              </label>
              <label className="flex items-start gap-2 text-small text-primary">
                <input
                  type="checkbox"
                  checked={notifyReleases}
                  onChange={(event) => applyFlag("notify_releases", event.target.checked)}
                  className="mt-1"
                />
                {t("profile.bugreport.telegramPermReleases")}
              </label>
            </div>
            <div>
              <Button
                variant="secondary"
                onClick={() =>
                  void start(false, {
                    report_identity: reportIdentity,
                    notify_releases: notifyReleases,
                  })
                }
              >
                {t("profile.bugreport.telegramRegenerate")}
              </Button>
            </div>
          </div>
        </div>
      )}

      {phase === "expired" && (
        <div className="mt-2 flex flex-col gap-2">
          <p className="text-small text-muted" role="status">
            {t("profile.bugreport.telegramExpired")}
          </p>
          <div>
            <Button
              variant="secondary"
              onClick={() =>
                void start(false, {
                  report_identity: reportIdentity,
                  notify_releases: notifyReleases,
                })
              }
            >
              {t("profile.bugreport.telegramRegenerate")}
            </Button>
          </div>
        </div>
      )}

      {phase === "linked" && linked !== null && (
        <div className="mt-3 flex flex-col gap-2">
          <p role="status" className="text-small text-status-success">
            {connectedAs === ""
              ? t("profile.bugreport.telegramConnectedAnon")
              : t("profile.bugreport.telegramConnected", { user: connectedAs })}
          </p>
          <ul className="flex flex-col gap-1 text-small text-muted">
            <li data-testid="bugreport-telegram-permission-report">
              {linked.permissions.report_identity ? "✓" : "✕"}{" "}
              {t("profile.bugreport.telegramPermReport")}
            </li>
            <li data-testid="bugreport-telegram-permission-releases">
              {linked.permissions.notify_releases ? "✓" : "✕"}{" "}
              {t("profile.bugreport.telegramPermReleases")}
            </li>
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            {telegramUrl !== null && (
              <a
                href={telegramUrl}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="bugreport-telegram-open"
                className="text-small font-medium text-action underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action/50"
              >
                {t("profile.bugreport.telegramOpenTelegram")}
              </a>
            )}
            <Button variant="secondary" onClick={() => void disconnect()}>
              {t("profile.bugreport.telegramDisconnect")}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
