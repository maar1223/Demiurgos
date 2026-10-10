import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { SecretInput } from "@/components/molecules/SecretInput";
import { WizardProgress } from "@/components/molecules/WizardProgress";
import type { ConnectionStatusSummary } from "@/components/molecules/ConnectionsPanel";
import {
  authorizeChat,
  clearIdeaCaptureToken,
  discoverChatCandidates,
  getIdeaCaptureStatus,
  saveIdeaCaptureConfig,
  setIdeaCaptureToken,
  testTelegramConnection,
} from "@/api/ideaCapture";
import type {
  AuthSessionStatus,
  CardState,
  ChatCandidate,
  ChatDiscoveryResult,
  IdeaCaptureConfig,
  IdeaCaptureStatus,
} from "@/api/types";
import { ApiError } from "@/api/types";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import type { MessageKey } from "@/i18n/messages";

/** Unified session controller surfaced by useAuthSession — passed in so the
 *  panel stays decoupled from the hook and easy to test. `start`/`logout`
 *  are optional because only the local-dev flow exposes them. */
export interface AuthSessionController {
  status: AuthSessionStatus | null;
  isLoading: boolean;
  error: Error | null;
  start?: () => Promise<AuthSessionStatus>;
  logout?: () => Promise<AuthSessionStatus>;
}

interface GroupRow {
  chat: string;
  senders: string;
}

/** The guided wizard steps. One step is visible at a time; the label doubles
 *  as the progress indicator entry (technical identifiers stay out of copy).
 *  Capture NEVER asks for a world: ideas always land in the global Taller de
 *  Ideas bank; the world is chosen later, when materializing an idea. */
const STEPS: readonly { id: string; labelKey: MessageKey }[] = [
  { id: "connect", labelKey: "ideaCapture.step.connect" },
  { id: "chat", labelKey: "ideaCapture.step.chat" },
  { id: "review", labelKey: "ideaCapture.step.review" },
  { id: "finish", labelKey: "ideaCapture.step.finish" },
];

const LAST_STEP = STEPS.length - 1;

const inputClass =
  "w-full rounded-md border border-edge bg-surface-raised py-1.5 px-3 " +
  "text-small text-primary placeholder:text-muted " +
  "focus:border-action focus:outline-none focus:ring-1 focus:ring-action/50 transition-colors";

const labelClass = "mb-1 block text-small text-muted";

/** Parse "1, 2, 3" / "1 2 3" into an int list; null when any token is not an
 *  integer (the backend mirrors this validation fail-closed). */
function parseIdList(text: string): number[] | null {
  const trimmed = text.trim();
  if (!trimmed) return [];
  const parts = trimmed.split(/[\s,]+/).filter(Boolean);
  const out: number[] = [];
  for (const part of parts) {
    if (!/^-?\d+$/.test(part)) return null;
    out.push(Number(part));
  }
  return out;
}

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

/** Number of currently authorized chats (private + groups), reading the local
 *  form state — i.e. exactly what the Finish step would persist. */
function countAuthorized(privateText: string, groupRows: GroupRow[]): number {
  const privateIds = parseIdList(privateText);
  const privateCount = privateIds === null ? 0 : privateIds.length;
  const groupCount = groupRows.filter((row) => /^-?\d+$/.test(row.chat.trim())).length;
  return privateCount + groupCount;
}

/**
 * Profile → Integraciones → Captura de ideas.
 *
 * Temporary, single-user MVP panel for the native Hermes/Telegram idea
 * capture, guided as a compact step-by-step wizard:
 *   1. Conectar bot — token entry (masked by default), save/replace/clear.
 *   2. Detectar chat — /start instruction, read-only discovery, one-click
 *      private authorization, explicit group authorization (fail-closed).
 *   3. Revisar — bot/chat summary + collapsed advanced settings (manual IDs,
 *      groups, media limits, raw retention). The destination is ALWAYS the
 *      global Taller de Ideas: no world is chosen at capture.
 *   4. Finalizar — save confirmation, exact Hermes gateway command, next
 *      action to start capture. The panel NEVER auto-starts Telegram.
 *
 * Everything lives behind the unified session boundary (credentials vault OR
 * local-dev): without an authenticated session the panel only shows the auth
 * gate. The bot token is stored server-side in .env and is never returned —
 * the input is masked by default and reveal/copy only apply to a value being
 * typed. Configure/discover is a migration-only flow. Production ingress is
 * owned by Hermes; the legacy serve command is never started from the panel.
 */
export function IdeaCapturePanel({
  auth,
  onStatus,
}: {
  auth: AuthSessionController;
  /** Reports the connection status to the shell. Keyed on the primitive
   *  `has_token` + authorized-chat count so a fresh object per render cannot
   *  loop the parent. */
  onStatus?: (status: ConnectionStatusSummary) => void;
}) {
  const { t } = useAppLanguage();
  const authenticated = auth.status?.authenticated ?? false;
  const progressSteps = STEPS.map((entry) => ({
    id: entry.id,
    label: t(entry.labelKey),
  }));

  // ------------------------------------------------------------------ data
  const [status, setStatus] = useState<IdeaCaptureStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    getIdeaCaptureStatus()
      .then(setStatus)
      .catch((cause: unknown) =>
        setLoadError(errorText(cause, t("ideaCapture.loadError"))),
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!authenticated) return;
    refresh();
  }, [authenticated, refresh]);

  // -------------------------------------------------------------- wizard
  const [step, setStep] = useState(0);

  // ------------------------------------------------------------- form state
  const [privateText, setPrivateText] = useState("");
  const [groupRows, setGroupRows] = useState<GroupRow[]>([]);
  const [limits, setLimits] = useState({
    image_mb: 20,
    audio_mb: 50,
    audio_minutes: 5,
    raw_retention_days: 30,
  });
  const [formError, setFormError] = useState<string | null>(null);
  const [formNotice, setFormNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Hydrate the form whenever the server status changes.
  useEffect(() => {
    if (!status) return;
    setPrivateText(status.config.private_chat_ids.join(", "));
    setGroupRows(
      Object.entries(status.config.approved_groups).map(([chat, senders]) => ({
        chat,
        senders: senders.join(", "),
      })),
    );
    setLimits({ ...status.config.limits });
  }, [status]);

  // ---------------------------------------------------------------- token
  const hasToken = status?.has_token ?? false;
  const [tokenDraft, setTokenDraft] = useState("");
  const [tokenBusy, setTokenBusy] = useState(false);
  const [tokenMessage, setTokenMessage] = useState<string | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [confirmingClear, setConfirmingClear] = useState(false);

  // ------------------------------------------------------- connection probe
  // The row badge is probe-driven: it only turns green after a successful live
  // probe. `verifying` is a transient in-flight state; `verifyState` holds the
  // last probe result (or null before the first probe).
  const [verifying, setVerifying] = useState(false);
  const [verifyState, setVerifyState] = useState<CardState | null>(null);

  /** Fire-and-forget probe of the stored token (fail-open): a transport error
   *  never blocks the flow and leaves the honest non-green state. */
  const runProbe = useCallback(() => {
    setVerifying(true);
    testTelegramConnection()
      .then((result) => setVerifyState(result.state))
      .catch(() => setVerifyState("requires_connection"))
      .finally(() => setVerifying(false));
  }, []);

  // Report the connection status to the shell as a row badge. Probe-driven
  // precedence: no token → warning; verifying → info; probe `configured` →
  // success; probe `error` → error; otherwise (`requires_connection`/none) →
  // warning. A freshly saved token never renders green on its own.
  useEffect(() => {
    if (!onStatus) return;
    if (!hasToken) {
      onStatus({ label: t("ideaCapture.status.noToken"), variant: "warning" });
    } else if (verifying) {
      onStatus({ label: t("ideaCapture.verify.probing"), variant: "info" });
    } else if (verifyState === "configured") {
      onStatus({ label: t("ideaCapture.badge.configured"), variant: "success" });
    } else if (verifyState === "error") {
      onStatus({ label: t("ideaCapture.badge.error"), variant: "error" });
    } else {
      onStatus({ label: t("ideaCapture.badge.requires"), variant: "warning" });
    }
  }, [onStatus, hasToken, verifying, verifyState]);

  const handleTokenSave = async () => {
    const value = tokenDraft.trim();
    if (!value || tokenBusy) return;
    setTokenBusy(true);
    setTokenMessage(null);
    setTokenError(null);
    try {
      await setIdeaCaptureToken(value);
      setTokenDraft("");
      setStatus((prev) => (prev ? { ...prev, has_token: true } : prev));
      setTokenMessage(t("ideaCapture.tokenSaved"));
      // Probe the freshly stored token (fire-and-forget, fail-open).
      void runProbe();
    } catch (cause) {
      setTokenError(errorText(cause, t("ideaCapture.tokenSaveError")));
    } finally {
      setTokenBusy(false);
    }
  };

  const handleClearToken = async () => {
    if (!confirmingClear) {
      setConfirmingClear(true);
      return;
    }
    if (tokenBusy) return;
    setTokenBusy(true);
    setTokenMessage(null);
    setTokenError(null);
    try {
      await clearIdeaCaptureToken();
      setConfirmingClear(false);
      setTokenDraft("");
      setStatus((prev) => (prev ? { ...prev, has_token: false } : prev));
      setVerifyState(null);
      setTokenMessage(t("ideaCapture.tokenRemoved"));
    } catch (cause) {
      setTokenError(errorText(cause, t("ideaCapture.tokenRemoveError")));
    } finally {
      setTokenBusy(false);
    }
  };

  // ------------------------------------------------------ Detectar mi chat
  const [discoverResult, setDiscoverResult] = useState<ChatDiscoveryResult | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [discoverRemediation, setDiscoverRemediation] = useState<{
    code: string;
    message: string;
  } | null>(null);
  const [discoverNotice, setDiscoverNotice] = useState<string | null>(null);
  const [authorizingId, setAuthorizingId] = useState<number | null>(null);
  const [groupDrafts, setGroupDrafts] = useState<
    Record<number, { senders: string; confirmed: boolean }>
  >({});

  /** Any in-flight request — nav (Back/Continuar) is disabled meanwhile. */
  const busy = tokenBusy || discovering || authorizingId !== null || saving;

  const handleDiscover = async () => {
    if (discovering) return;
    setDiscovering(true);
    setDiscoverError(null);
    setDiscoverRemediation(null);
    setDiscoverNotice(null);
    setDiscoverResult(null);
    try {
      const result = await discoverChatCandidates();
      setDiscoverResult(result);
      // The bot just proved reachable: refresh the probe-driven badge.
      void runProbe();
    } catch (cause) {
      if (cause instanceof ApiError && cause.code) {
        // Backend mapped the Telegram failure to a machine-readable
        // remediation code (webhook_conflict, invalid_token, network…):
        // render dedicated guidance instead of a bare message.
        setDiscoverRemediation({
          code: cause.code,
          message:
            cause.message ||
            errorText(cause, t("ideaCapture.discoverError")),
        });
      } else {
        setDiscoverError(errorText(cause, t("ideaCapture.discoverError")));
      }
    } finally {
      setDiscovering(false);
    }
  };

  const handleAuthorizePrivate = async (candidate: ChatCandidate) => {
    if (authorizingId !== null) return;
    setAuthorizingId(candidate.id);
    setDiscoverError(null);
    setDiscoverNotice(null);
    try {
      const next = await authorizeChat({
        chat_id: candidate.id,
        chat_type: "private",
      });
      setStatus(next);
      setDiscoverNotice(
        next.message || t("ideaCapture.privateAuthorized"),
      );
      setDiscoverResult(null);
      // Authorization refreshes the badge: the bot is now genuinely usable.
      void runProbe();
    } catch (cause) {
      setDiscoverError(errorText(cause, t("ideaCapture.authorizeError")));
    } finally {
      setAuthorizingId(null);
    }
  };

  const handleAuthorizeGroup = async (candidate: ChatCandidate) => {
    if (authorizingId !== null) return;
    const draft = groupDrafts[candidate.id];
    const senders = parseIdList(draft?.senders ?? "");
    if (senders === null || senders.length === 0) {
      setDiscoverError(t("ideaCapture.groupSenderError"));
      return;
    }
    if (!draft?.confirmed) {
      setDiscoverError(t("ideaCapture.groupConfirmError"));
      return;
    }
    setAuthorizingId(candidate.id);
    setDiscoverError(null);
    setDiscoverNotice(null);
    try {
      const next = await authorizeChat({
        chat_id: candidate.id,
        chat_type: candidate.type,
        sender_ids: senders,
        confirm_group: true,
      });
      setStatus(next);
      setDiscoverNotice(
        next.message || t("ideaCapture.groupAuthorized"),
      );
      setDiscoverResult(null);
      // Group authorization refreshes the badge too.
      void runProbe();
    } catch (cause) {
      setDiscoverError(errorText(cause, t("ideaCapture.groupAuthorizeError")));
    } finally {
      setAuthorizingId(null);
    }
  };

  // ----------------------------------------------------------- config save
  const handleSaveConfig = async () => {
    setFormError(null);
    setFormNotice(null);

    const privateChatIds = parseIdList(privateText);
    if (privateChatIds === null) {
      setFormError(t("ideaCapture.privateIdsError"));
      return;
    }
    const groups: Record<string, number[]> = {};
    for (const row of groupRows) {
      const chat = row.chat.trim();
      if (!chat) continue;
      if (!/^-?\d+$/.test(chat)) {
        setFormError(t("ideaCapture.groupIntegerError", { chat }));
        return;
      }
      const senders = parseIdList(row.senders);
      if (senders === null) {
        setFormError(t("ideaCapture.groupSendersError", { chat }));
        return;
      }
      groups[chat] = senders;
    }
    for (const [key, value] of Object.entries(limits)) {
      if (!Number.isInteger(value) || value < 1) {
        setFormError(t("ideaCapture.limitError", { key }));
        return;
      }
    }

    const config: IdeaCaptureConfig = {
      private_chat_ids: privateChatIds,
      approved_groups: groups,
      limits: { ...limits },
    };
    setSaving(true);
    try {
      const next = await saveIdeaCaptureConfig(config);
      setStatus(next);
      setSaved(true);
      setFormNotice(t("ideaCapture.configSaved"));
    } catch (cause) {
      setFormError(errorText(cause, t("ideaCapture.configSaveError")));
    } finally {
      setSaving(false);
    }
  };

  // ------------------------------------------------------------------ gate
  // Unified session gate (credentials vault OR local-dev). Auth disabled
  // (enabled=false) fails open: the panel renders and any 401 surfaces
  // through the existing error handlers.
  if (auth.isLoading) {
    return (
      <div className="flex items-center gap-2 py-6 text-small text-muted">
        <Spinner size="sm" /> {t("ideaCapture.checkingSession")}
      </div>
    );
  }

  if (auth.error) {
    return (
      <div className="rounded-lg border border-edge bg-surface-raised p-4">
        <p className="text-small text-muted">
          {t("ideaCapture.sessionCheckError")}
        </p>
        {auth.error.message && (
          <p className="mt-2 text-small text-status-error">{auth.error.message}</p>
        )}
      </div>
    );
  }

  if (auth.status?.enabled && !authenticated) {
    if (auth.status.mode === "local-dev") {
      return (
        <div className="rounded-lg border border-edge bg-surface-raised p-4">
          <p className="text-small text-muted">
            {t("ideaCapture.localNotStarted")}
          </p>
          <Button
            variant="secondary"
            onClick={() => void auth.start?.()}
            className="mt-3"
          >
            {t("ideaCapture.startLocal")}
          </Button>
        </div>
      );
    }
    // Credentials vault mode: the login surface is the app-level AuthGate, so
    // the panel only explains the expired session (no in-page login here).
    return (
      <div className="rounded-lg border border-edge bg-surface-raised p-4">
        <p className="text-small text-muted">
          {t("ideaCapture.sessionExpired")}
        </p>
      </div>
    );
  }

  const failClosed = countAuthorized(privateText, groupRows) === 0;
  // Capture never asks for a world: only the bot token gates the first step.
  const canContinue = step === 0 ? hasToken : true;

  const goNext = () => {
    if (!canContinue || busy) return;
    setFormError(null);
    setFormNotice(null);
    setStep((prev) => Math.min(prev + 1, LAST_STEP));
  };
  const goBack = () => {
    if (busy) return;
    setFormError(null);
    setFormNotice(null);
    setStep((prev) => Math.max(prev - 1, 0));
  };

  return (
    <div className="space-y-5">
      {/* Operational distinction: discovery is migration-only; Hermes owns ingress. */}
      <div className="rounded-lg border border-edge bg-surface-raised p-3 text-small text-muted">
        <span className="font-medium text-primary">{t("ideaCapture.howTitle")}</span>{" "}
        {t("ideaCapture.howPart1")}{" "}
        <strong>{t("ideaCapture.howStrong")}</strong>{" "}
        {t("ideaCapture.howPart2")}
      </div>

      {loadError && (
        <div className="rounded-lg border border-status-error/40 bg-status-error/10 p-3 text-small text-status-error">
          {loadError}
        </div>
      )}

      {loading && !status && (
        <div className="flex items-center gap-2 py-4 text-small text-muted">
          <Spinner size="sm" /> {t("ideaCapture.loadingConfig")}
        </div>
      )}

      {status && (
        <>
          {/* --------------------------------------------------- progress */}
          <WizardProgress steps={progressSteps} current={step} />

          {/* -------------------------------------------------- step content */}
          <div className="rounded-lg border border-edge bg-surface-raised p-5">
            {step === 0 && (
              <section aria-label={t("ideaCapture.connectSectionAria")}>
                <h4 className="font-heading text-body text-primary">
                  {t("ideaCapture.connectTitle")}
                </h4>
                <p className="mt-1 text-small text-muted">
                  {hasToken
                    ? t("ideaCapture.tokenConfigured")
                    : t("ideaCapture.tokenMissing")}
                </p>
                <div className="mt-3">
                  <SecretInput
                    copyable
                    value={tokenDraft}
                    onChange={(event) => {
                      setTokenDraft(event.target.value);
                      setConfirmingClear(false);
                    }}
                    placeholder={
                      hasToken
                        ? t("ideaCapture.tokenPlaceholderConfigured")
                        : t("ideaCapture.tokenPlaceholder")
                    }
                    autoComplete="off"
                    spellCheck={false}
                    aria-label={t("ideaCapture.tokenAria")}
                    disabled={tokenBusy}
                    onCopyError={() => setTokenError(t("ideaCapture.copyError"))}
                    className={inputClass}
                  />
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => void handleTokenSave()}
                    disabled={!tokenDraft.trim() || tokenBusy}
                  >
                    {tokenBusy
                      ? t("ideaCapture.saving")
                      : hasToken
                        ? t("ideaCapture.replaceToken")
                        : t("ideaCapture.saveToken")}
                  </Button>
                  {hasToken && (
                    <Button
                      variant="secondary"
                      onClick={() => void handleClearToken()}
                      disabled={tokenBusy}
                    >
                      {confirmingClear
                        ? t("ideaCapture.confirmDelete")
                        : t("ideaCapture.deleteToken")}
                    </Button>
                  )}
                </div>
                {tokenMessage && (
                  <p className="mt-3 text-small text-status-success">{tokenMessage}</p>
                )}
                {tokenError && (
                  <p className="mt-3 text-small text-status-error">{tokenError}</p>
                )}
              </section>
            )}

            {step === 1 && (
              <section aria-label={t("ideaCapture.chatSectionAria")}>
                <h4 className="font-heading text-body text-primary">
                  {t("ideaCapture.chatTitle")}
                </h4>
                <p className="mt-1 text-small text-muted">
                  {t("ideaCapture.chatIntro1")}{" "}
                  <code className="text-icon-muted">/start</code>{" "}
                  {t("ideaCapture.chatIntro2")}{" "}
                  <em>{t("ideaCapture.discoverCta")}</em>
                  {t("ideaCapture.chatIntro3")}
                </p>
                <div className="mt-3 flex items-center gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => void handleDiscover()}
                    disabled={discovering}
                  >
                    {discovering ? t("ideaCapture.discovering") : t("ideaCapture.discoverCta")}
                  </Button>
                  {discovering && <Spinner size="sm" />}
                </div>
                {discoverError && (
                  <p className="mt-3 text-small text-status-error">{discoverError}</p>
                )}
                {discoverRemediation && (
                  <div
                    role="alert"
                    className="mt-3 rounded-lg border border-action/40 bg-action/10 p-3 text-small"
                  >
                    <p className="text-detail">
                      <strong>{t("ideaCapture.discoverFailedTitle")}</strong>
                    </p>
                    <p className="mt-1 text-muted">
                      {discoverRemediation.message}
                    </p>
                    {discoverRemediation.code === "webhook_conflict" && (
                      <div className="mt-2">
                        <p className="text-muted">
                          <strong>{t("ideaCapture.webhookTitle")}</strong>{" "}
                          {t("ideaCapture.webhookBody")}
                        </p>
                        <ul className="mt-1 list-disc pl-5 text-muted">
                          <li>
                            {t("ideaCapture.webhookBotfather")}{" "}
                            <strong>BotFather</strong>: <code>/deletewebhook</code>
                          </li>
                          <li>
                            {t("ideaCapture.webhookApiBefore")}{" "}
                            <code>deleteWebhook</code>{" "}
                            {t("ideaCapture.webhookApiAfter")}
                          </li>
                        </ul>
                        <p className="mt-2 text-muted">
                          {t("ideaCapture.webhookDecision")}{" "}
                          <em>{t("ideaCapture.discoverCta")}</em>{" "}
                          {t("ideaCapture.webhookDecisionTail")}
                        </p>
                      </div>
                    )}
                  </div>
                )}
                {discoverNotice && (
                  <p className="mt-3 text-small text-status-success">{discoverNotice}</p>
                )}
                {discoverResult && (
                  <div className="mt-3">
                    {discoverResult.candidates.length === 0 ? (
                      <div className="rounded-lg border border-edge bg-surface-raised p-3 text-small text-muted">
                        {discoverResult.message}
                      </div>
                    ) : (
                      <ul className="space-y-2">
                        {discoverResult.candidates.map((candidate) =>
                          candidate.kind === "private" ? (
                            <li
                              key={candidate.id}
                              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-edge bg-surface-raised p-3"
                            >
                              <div className="min-w-0">
                                <p className="truncate text-small text-primary">
                                  {candidate.title || t("ideaCapture.privateNoName")}
                                </p>
                                <p className="text-xs text-muted">
                                  {t("ideaCapture.privateOneClick")}
                                </p>
                              </div>
                              <Button
                                variant="secondary"
                                onClick={() => void handleAuthorizePrivate(candidate)}
                                disabled={authorizingId !== null}
                              >
                                {authorizingId === candidate.id
                                  ? t("ideaCapture.authorizing")
                                  : t("ideaCapture.authorize")}
                              </Button>
                            </li>
                          ) : (
                            <li
                              key={candidate.id}
                              className="rounded-md border border-edge bg-surface-raised p-3"
                            >
                              <p className="truncate text-small text-primary">
                                {candidate.title || t("ideaCapture.groupNoTitle")}
                              </p>
                              <p className="text-xs text-muted">
                                {t("ideaCapture.groupExplicit")}
                              </p>
                              <div className="mt-2 space-y-2">
                                <input
                                  type="text"
                                  value={groupDrafts[candidate.id]?.senders ?? ""}
                                  onChange={(event) =>
                                    setGroupDrafts((prev) => ({
                                      ...prev,
                                      [candidate.id]: {
                                        senders: event.target.value,
                                        confirmed:
                                          prev[candidate.id]?.confirmed ?? false,
                                      },
                                    }))
                                  }
                                  placeholder={t("ideaCapture.sendersPlaceholder")}
                                  aria-label={t("ideaCapture.sendersAria", { id: candidate.id })}
                                  className={inputClass}
                                />
                                <label className="flex items-center gap-2 text-small text-muted">
                                  <input
                                    type="checkbox"
                                    checked={groupDrafts[candidate.id]?.confirmed ?? false}
                                    onChange={(event) =>
                                      setGroupDrafts((prev) => ({
                                        ...prev,
                                        [candidate.id]: {
                                          senders: prev[candidate.id]?.senders ?? "",
                                          confirmed: event.target.checked,
                                        },
                                      }))
                                    }
                                    aria-label={t("ideaCapture.groupConfirmAria", { id: candidate.id })}
                                    className="accent-action"
                                  />
                                  {t("ideaCapture.groupConfirmLabel")}
                                </label>
                                <Button
                                  variant="secondary"
                                  onClick={() => void handleAuthorizeGroup(candidate)}
                                  disabled={authorizingId !== null}
                                >
                                  {authorizingId === candidate.id
                                    ? t("ideaCapture.authorizing")
                                    : t("ideaCapture.authorizeGroup")}
                                </Button>
                              </div>
                            </li>
                          ),
                        )}
                      </ul>
                    )}
                  </div>
                )}
                {failClosed ? (
                  <div className="mt-3 rounded-lg border border-action/40 bg-action/10 p-3 text-small text-detail">
                     <strong>{t("ideaCapture.failClosedStrong")}</strong>{" "}
                     {t("ideaCapture.failClosedBody")}{" "}
                     <em>{t("ideaCapture.reviewAdvanced")}</em>
                     {t("ideaCapture.failClosedTail")}
                  </div>
                ) : (
                  <p className="mt-3 text-small text-status-success">
                    {t("ideaCapture.authActive", {
                      count: countAuthorized(privateText, groupRows),
                    })}
                  </p>
                )}
                <p className="mt-3 text-small text-muted">
                  {t("ideaCapture.problemsHint1")}{" "}
                  <em>{t("ideaCapture.reviewAdvanced")}</em>
                  {t("ideaCapture.problemsHintTail")}
                </p>
              </section>
            )}

            {step === 2 && (
              <section aria-label={t("ideaCapture.reviewSectionAria")}>
                <h4 className="font-heading text-body text-primary">
                  {t("ideaCapture.reviewTitle")}
                </h4>
                <dl className="mt-3 space-y-2 text-small">
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-muted">{t("ideaCapture.botTelegram")}</dt>
                    <dd className="text-primary">
                      {hasToken ? t("ideaCapture.tokenConfiguredShort") : t("ideaCapture.status.noToken")}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-muted">{t("ideaCapture.authorizedChat")}</dt>
                    <dd className="text-primary">
                      {failClosed
                        ? t("ideaCapture.noneFailClosed")
                        : t("ideaCapture.chatCount", {
                            count: countAuthorized(privateText, groupRows),
                          })}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-muted">{t("ideaCapture.destination")}</dt>
                    <dd className="text-primary">{t("ideaCapture.ideasWorkshop")}</dd>
                  </div>
                </dl>
                <p className="mt-3 text-small text-muted">
                  {t("ideaCapture.reviewBodyPart1")}{" "}
                  <strong>{t("ideaCapture.reviewBodyStrong")}</strong>{" "}
                  {t("ideaCapture.reviewBodyPart2")}
                </p>

                {failClosed && (
                  <div className="mt-3 rounded-lg border border-action/40 bg-action/10 p-3 text-small text-detail">
                     <strong>{t("ideaCapture.failClosedStrong")}</strong>{" "}
                     {t("ideaCapture.failClosedShortBody")}
                  </div>
                )}
                {!status.validation.ok && (
                  <div className="mt-3 rounded-lg border border-status-error/40 bg-status-error/10 p-3 text-small text-status-error">
                    <strong>{t("ideaCapture.validationErrors")}</strong>
                    <ul className="mt-1 list-disc pl-5">
                      {status.validation.errors.map((error) => (
                        <li key={error}>{error}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* ------------------------- advanced (collapsed by default) */}
                <div className="mt-4 rounded-md border border-edge bg-surface-raised">
                  <button
                    type="button"
                    onClick={() => setAdvancedOpen((open) => !open)}
                    aria-expanded={advancedOpen}
                    aria-controls="ic-advanced-panel"
                    className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-small font-medium text-icon-muted hover:text-primary"
                  >
                    {t("ideaCapture.advancedToggle")}
                    <Icon
                      name={advancedOpen ? "chevron-down" : "chevron-right"}
                      size={16}
                    />
                  </button>
                  {advancedOpen && (
                    <div
                      id="ic-advanced-panel"
                      className="space-y-3 border-t border-edge p-3"
                    >
                      <div>
                        <label htmlFor="ic-private-chats" className={labelClass}>
                          {t("ideaCapture.privateChatsLabel")}
                        </label>
                        <input
                          id="ic-private-chats"
                          type="text"
                          value={privateText}
                          onChange={(event) => setPrivateText(event.target.value)}
                          placeholder="123456789, 555000111"
                          className={inputClass}
                        />
                      </div>

                      <div>
                        <span className={labelClass}>{t("ideaCapture.groupsLabel")}</span>
                        <div className="space-y-2">
                          {groupRows.map((row, index) => (
                            <div key={index} className="flex items-center gap-2">
                              <input
                                type="text"
                                value={row.chat}
                                onChange={(event) => {
                                  const next = [...groupRows];
                                  next[index] = { ...next[index], chat: event.target.value };
                                  setGroupRows(next);
                                }}
                                placeholder={t("ideaCapture.groupIdPlaceholder")}
                                aria-label={t("ideaCapture.groupIdAria", { id: index + 1 })}
                                className={inputClass}
                              />
                              <input
                                type="text"
                                value={row.senders}
                                onChange={(event) => {
                                  const next = [...groupRows];
                                  next[index] = { ...next[index], senders: event.target.value };
                                  setGroupRows(next);
                                }}
                                placeholder={t("ideaCapture.sendersPlaceholder")}
                                aria-label={t("ideaCapture.sendersAria", { id: index + 1 })}
                                className={inputClass}
                              />
                              <button
                                type="button"
                                onClick={() =>
                                  setGroupRows(groupRows.filter((_, i) => i !== index))
                                }
                                aria-label={t("ideaCapture.removeGroupAria", { id: index + 1 })}
                                className="shrink-0 rounded-md p-2 text-status-error hover:bg-surface-hover"
                              >
                                <Icon name="trash" size={16} />
                              </button>
                            </div>
                          ))}
                          <Button
                            variant="secondary"
                            onClick={() => setGroupRows([...groupRows, { chat: "", senders: "" }])}
                          >
                            <Icon name="plus" size={14} /> {t("ideaCapture.addGroup")}
                          </Button>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                        {(
                          [
                            ["limits.image_mb", t("ideaCapture.limitImage"), limits.image_mb],
                            ["limits.audio_mb", t("ideaCapture.limitAudio"), limits.audio_mb],
                            ["limits.audio_minutes", t("ideaCapture.limitAudioMinutes"), limits.audio_minutes],
                            ["limits.raw_retention_days", t("ideaCapture.limitRetention"), limits.raw_retention_days],
                          ] as const
                        ).map(([key, label, value]) => (
                          <div key={key}>
                            <label htmlFor={key} className={labelClass}>
                              {label}
                            </label>
                            <input
                              id={key}
                              type="number"
                              min={1}
                              step={1}
                              value={value}
                              onChange={(event) =>
                                setLimits((prev) => ({
                                  ...prev,
                                  [key.split(".")[1]]: Number(event.target.value),
                                }))
                              }
                              className={inputClass}
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {formError && (
                  <p className="mt-3 text-small text-status-error">{formError}</p>
                )}
                {formNotice && (
                  <p className="mt-3 text-small text-status-success">{formNotice}</p>
                )}
              </section>
            )}

            {step === 3 && (
              <section aria-label={t("ideaCapture.finishSectionAria")}>
                <h4 className="font-heading text-body text-primary">
                  {t("ideaCapture.finishTitle")}
                </h4>
                <p className="mt-1 text-small text-muted">
                  {t("ideaCapture.finishBody1")}{" "}
                  <strong>{t("ideaCapture.finishBodyStrong")}</strong>{" "}
                  {t("ideaCapture.finishBody2")}
                </p>
                <div className="mt-3">
                  <Button
                    variant="primary"
                    onClick={() => void handleSaveConfig()}
                    disabled={saving}
                  >
                    {saving ? t("ideaCapture.saving") : t("ideaCapture.saveConfig")}
                  </Button>
                </div>
                {formError && (
                  <p className="mt-3 text-small text-status-error">{formError}</p>
                )}
                {formNotice && (
                  <p className="mt-3 text-small text-status-success">{formNotice}</p>
                )}
                {saved && status && (
                  <div className="mt-3 space-y-3">
                    <div className="rounded-lg border border-status-success/40 bg-status-success/10 p-3 text-small text-status-success">
                      <strong>{t("ideaCapture.doneStrong")}</strong>{" "}
                      {t("ideaCapture.doneBody")}
                    </div>
                    <pre className="overflow-x-auto rounded-md border border-edge bg-surface p-3 text-small text-status-success">
                      {status.serve.command}
                    </pre>
                    {status.serve.runnable ? (
                      <p className="text-small text-status-success">
                        {t("ideaCapture.readyToRun")}
                      </p>
                    ) : (
                      <ul className="list-disc pl-5 text-small text-status-error">
                        {status.serve.blocked_reasons.map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                    )}
                    <p className="text-small text-muted">
                      <strong>{t("ideaCapture.nextStepStrong")}</strong>{" "}
                      {t("ideaCapture.nextStepBody")}
                    </p>
                  </div>
                )}
                {status && (
                  <div className="mt-4 rounded-md border border-edge bg-surface-raised p-3">
                    <h4 className="font-heading text-small text-primary">
                      {t("ideaCapture.limitationsTitle")}
                    </h4>
                    <ul className="mt-2 list-disc pl-5 text-small text-muted">
                      {status.limitations.map((limitation) => (
                        <li key={limitation} className="mt-1">
                          {limitation}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            )}
          </div>

          {/* ----------------------------------------------------- footer nav */}
          <div className="flex items-center justify-between">
            <Button
              variant="ghost"
              onClick={goBack}
              disabled={step === 0 || busy}
            >
              <Icon name="chevron-left" size={16} /> {t("ideaCapture.back")}
            </Button>
            {step < LAST_STEP && (
              <div className="flex flex-col items-end gap-1">
                <Button
                  variant="secondary"
                  onClick={goNext}
                  disabled={!canContinue || busy}
                >
                  {t("ideaCapture.continue")} <Icon name="chevron-right" size={16} />
                </Button>
                {step === 0 && !hasToken && (
                  <span className="text-xs text-muted">
                    {t("ideaCapture.saveTokenToContinue")}
                  </span>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
