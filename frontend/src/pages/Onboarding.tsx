import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createWorld, getOnboardingStatus } from "@/api/onboarding";
import { createAccount } from "@/api/wiki";
import type { OnboardingStatus } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { ContentFolderStep } from "@/components/organisms/ContentFolderStep";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { LocaleForm, authHint } from "@/components/organisms/LocaleForm";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { markFirstValueHandoffPending } from "@/lib/firstValueHandoff";
import { setCurrentWorld } from "@/lib/currentWorld";
import type { MessageKey } from "@/i18n/messages";

/**
 * First-run onboarding (OC1/OC2, Slice 1).
 *
 * Flow: step 0 (locale) → account (always active on a fresh install) → content
 * folder (step 4: where the worlds live) → world creation → ready. Remote steps
 * (AI, Telegram, Backup) are NEVER blocking and are reported as pending — they
 * are resumed from the Profile (`/perfil`).
 * Completed steps are never replayed after a restart (server is
 * authoritative).
 *
 * The account step (R-AC-01) is BLOCKING and ALWAYS active on a fresh install
 * (vault-settings-configure removed the credentials-mode guard): username +
 * optional password, and the recovery words are generated server-side and
 * shown to the user EXACTLY ONCE. The backend derives "account" as the next
 * step; the account creation endpoint answers 200 with the vault OFF
 * (S-AC-01b), so no `.env` edit is required.
 *
 * Writes are gated on the authenticated local principal; a 401 surfaces a
 * clear hint (fail closed, never a silent bypass).
 */

const REMOTE_PENDING: Record<string, { titleKey: MessageKey; descriptionKey: MessageKey; enableLater?: { to: string; labelKey: MessageKey; ariaKey: MessageKey } }> = {
  ai: {
    titleKey: "onboarding.remote.ai.title",
    descriptionKey: "onboarding.remote.ai.desc",
    // S2b (degradable-ai-provider): non-blocking "enable the assistant
    // later" entry pointing at the existing Assistant Settings panel
    // (Profile -> Configuration Center -> Conexiones). The AI step is
    // never a blocker; the affordance only removes the "where do I do
    // this later?" ambiguity.
    enableLater: {
      to: "/perfil?tab=conexiones",
      labelKey: "onboarding.remote.ai.later",
      ariaKey: "onboarding.remote.ai.laterAria",
    },
  },
  telegram: {
    titleKey: "onboarding.remote.telegram.title",
    descriptionKey: "onboarding.remote.telegram.desc",
  },
  backup_handoff: {
    titleKey: "onboarding.remote.backup.title",
    descriptionKey: "onboarding.remote.backup.desc",
  },
};

export default function Onboarding() {
  const navigate = useNavigate();
  const { t } = useAppLanguage();
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [writeError, setWriteError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  // World form
  const [worldName, setWorldName] = useState("");
  const [loreSkeleton, setLoreSkeleton] = useState(true);

  // Account form (always active on a fresh install — R-AC-01)
  const [accountUsername, setAccountUsername] = useState("");
  const [accountPassword, setAccountPassword] = useState("");
  // Plaintext recovery words shown EXACTLY once after account creation
  // (S-AC-01a/b) — the server persists only their hash.
  const [accountWords, setAccountWords] = useState<string | null>(null);
  const [accountBusy, setAccountBusy] = useState(false);
  const [accountError, setAccountError] = useState<unknown>(null);

  const loadStatus = () => {
    setLoading(true);
    setError(null);
    void getOnboardingStatus()
      .then((next) => {
        setStatus(next);
        if (next.completed) {
          navigate("/wiki", { replace: true });
        }
      })
      .catch((cause: unknown) => setError(cause))
      .finally(() => setLoading(false));
  };

  useEffect(loadStatus, [navigate]);

  const handleStep0Saved = (next: OnboardingStatus) => {
    // The server is authoritative: step 0 is committed, so the next blocking
    // step renders from the refreshed status. A fully completed install is
    // redirected instead of replaying the flow.
    setStatus(next);
    if (next.completed) {
      navigate("/perfil", { replace: true });
    }
  };

  const handleCreateWorld = (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setWriteError(null);
    void createWorld(worldName.trim(), loreSkeleton)
      .then((result) => {
        if (result.kind === "collision" || result.kind === "invalid_name") {
          setWriteError(new Error(result.message));
          setBusy(false);
          return;
        }
        setBusy(false);
        if (result.kind === "created") {
          // First-value handoff (first-value-handoff spec): the created
          // world is marked pending so its WikiWorld shows the one-time hero;
          // it is also the active world for the session.
          setCurrentWorld(result.name);
          markFirstValueHandoffPending(result.name);
          navigate(`/wiki/${encodeURIComponent(result.name)}`, {
            replace: true,
          });
        } else {
          // already_exists / io_error keep the prior landing.
          navigate("/wiki", { replace: true });
        }
      })
      .catch((cause: unknown) => {
        setWriteError(cause);
        setBusy(false);
      });
  };

  const handleCreateAccount = (event: FormEvent) => {
    event.preventDefault();
    setAccountBusy(true);
    setAccountError(null);
    void createAccount(
      accountUsername.trim(),
      accountPassword || undefined,
    )
      .then(({ words }) => {
        // The words are shown exactly once; the account step is already
        // recorded server-side (blocking step committed by the endpoint).
        setAccountWords(words);
        setAccountBusy(false);
      })
      .catch((cause: unknown) => {
        setAccountError(cause);
        setAccountBusy(false);
      });
  };

  const handleContentFolderDone = () => {
    // The step is committed server-side and nothing moved: refresh so the
    // world step is offered next, on the folder the app actually has open.
    loadStatus();
  };

  const handleWordsConfirmed = () => {
    // Hide the one-time words card, then refresh the status: the account
    // step is done server-side, so the world step is offered next.
    setAccountWords(null);
    loadStatus();
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface">
        <Spinner size="lg" />
      </div>
    );
  }

  const hint = authHint(error ?? writeError, t);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-surface px-4 py-12">
      <div className="w-full max-w-xl">
        <h1 className="font-heading text-h3 text-primary">{t("onboarding.title")}</h1>
        <p className="mt-2 text-body text-muted">{t("onboarding.intro")}</p>

        {!!error && !status && (
          <div className="mt-6">
            <ErrorBanner message={t("onboarding.loadError")} onRetry={loadStatus} />
          </div>
        )}

        {hint && (
          <div className="mt-6" role="alert">
            <ErrorBanner message={hint} onRetry={() => setWriteError(null)} />
          </div>
        )}

        {status && !status.completed && status.completed_steps.includes("step0") ? (
          accountWords ? (
            <WordsCard words={accountWords} onConfirm={handleWordsConfirmed} />
          ) : !status.completed_steps.includes("account") ? (
            <AccountStep
              username={accountUsername}
              onUsername={setAccountUsername}
              password={accountPassword}
              onPassword={setAccountPassword}
              busy={accountBusy}
              error={accountError}
              onSubmit={handleCreateAccount}
            />
          ) : status.current_step === "content_folder" ? (
            <ContentFolderStep onDone={handleContentFolderDone} />
          ) : (
            <WorldStep
              worldName={worldName}
              onWorldName={setWorldName}
              loreSkeleton={loreSkeleton}
              onLoreSkeleton={setLoreSkeleton}
              busy={busy}
              error={writeError}
              onSubmit={handleCreateWorld}
            />
          )
        ) : (
          status && (
            <div className="mt-8 rounded-lg border border-edge bg-surface-raised p-6">
              <h2 className="font-heading text-h4 text-primary">
                {t("onboarding.step1.title")}
              </h2>
              <LocaleForm onSaved={handleStep0Saved} submitLabel={t("common.continue")} />
            </div>
          )
        )}

        {status && (
          <PendingCards
            remotePending={status.remote_pending}
            worldDone={status.completed_steps.includes("world")}
          />
        )}
      </div>
    </div>
  );
}

function WorldStep(props: {
  worldName: string;
  onWorldName: (v: string) => void;
  loreSkeleton: boolean;
  onLoreSkeleton: (v: boolean) => void;
  busy: boolean;
  error: unknown;
  onSubmit: (e: FormEvent) => void;
}) {
  const { t } = useAppLanguage();
  return (
    <form onSubmit={props.onSubmit} className="mt-8 rounded-lg border border-edge bg-surface-raised p-6">
      <h2 className="font-heading text-h4 text-primary">{t("onboarding.world.title")}</h2>
      <p className="mt-1 text-small text-muted">{t("onboarding.world.intro")}</p>

      <div className="mt-5 grid gap-4">
        <label htmlFor="onboarding-world-name" className="flex flex-col gap-1 text-small text-primary">
          {t("onboarding.world.name")}
          <input
            id="onboarding-world-name"
            value={props.worldName}
            onChange={(e) => props.onWorldName(e.target.value)}
            required
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
            placeholder={t("onboarding.world.namePlaceholder")}
          />
        </label>

        <label className="flex items-center gap-2 text-small text-primary">
          <input
            type="checkbox"
            checked={props.loreSkeleton}
            onChange={(e) => props.onLoreSkeleton(e.target.checked)}
            className="h-4 w-4"
          />
          {t("onboarding.world.loreSkeleton")}
        </label>
      </div>

      {!!props.error && (
        <p className="mt-4 text-small text-status-error" role="alert">
          {props.error instanceof Error
            ? props.error.message
            : t("onboarding.world.createError")}
        </p>
      )}

      <div className="mt-6 flex items-center justify-end">
        <Button type="submit" disabled={props.busy || !props.worldName.trim()}>
          {props.busy ? t("common.creating") : t("onboarding.world.create")}
        </Button>
      </div>
    </form>
  );
}

function PendingCards(props: { remotePending: string[]; worldDone: boolean }) {
  const { t } = useAppLanguage();
  const items = props.remotePending
    .map((step) => REMOTE_PENDING[step])
    .filter(Boolean);
  return (
    <section aria-label={t("onboarding.pending.aria")} className="mt-8">
      <h2 className="font-heading text-h4 text-primary">{t("onboarding.pending.title")}</h2>
      <div aria-live="polite" className="mt-3 grid gap-3">
        {items.map((item) => (
          <div
            key={item.titleKey}
            className="flex items-start justify-between gap-3 rounded-lg border border-edge bg-surface-raised p-4"
          >
            <div>
              <p className="text-body text-primary">{t(item.titleKey)}</p>
              <p className="mt-1 text-small text-muted">{t(item.descriptionKey)}</p>
              {item.enableLater && (
                <Link
                  to={item.enableLater.to}
                  aria-label={t(item.enableLater.ariaKey)}
                  className="mt-2 inline-flex items-center gap-1 text-small font-medium text-action hover:underline"
                >
                  {t(item.enableLater.labelKey)}
                  <span aria-hidden="true">&rarr;</span>
                </Link>
              )}
            </div>
            <span className="inline-flex shrink-0 items-center rounded-full border border-edge bg-surface-raised px-2.5 py-0.5 text-xs font-medium text-primary">
              {t("onboarding.pending.badge")}
            </span>
          </div>
        ))}
        {props.worldDone && items.length === 0 && (
          <p className="text-small text-muted">{t("onboarding.pending.none")}</p>
        )}
      </div>
    </section>
  );
}

function AccountStep(props: {
  username: string;
  onUsername: (v: string) => void;
  password: string;
  onPassword: (v: string) => void;
  busy: boolean;
  error: unknown;
  onSubmit: (e: FormEvent) => void;
}) {
  const { t } = useAppLanguage();
  const hint = authHint(props.error, t);
  return (
    <form onSubmit={props.onSubmit} className="mt-8 rounded-lg border border-edge bg-surface-raised p-6">
      <h2 className="font-heading text-h4 text-primary">{t("onboarding.account.title")}</h2>
      <p className="mt-1 text-small text-muted">{t("onboarding.account.intro")}</p>

      <div className="mt-5 grid gap-4">
        <label htmlFor="onboarding-account-username" className="flex flex-col gap-1 text-small text-primary">
          {t("onboarding.account.username")}
          <input
            id="onboarding-account-username"
            value={props.username}
            onChange={(e) => props.onUsername(e.target.value)}
            required
            autoComplete="username"
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary focus:border-icon-muted focus:outline-none"
            placeholder={t("onboarding.account.usernamePlaceholder")}
          />
        </label>

        <label htmlFor="onboarding-account-password" className="flex flex-col gap-1 text-small text-primary">
          {t("onboarding.account.password")}
          <input
            id="onboarding-account-password"
            type="password"
            value={props.password}
            onChange={(e) => props.onPassword(e.target.value)}
            autoComplete="new-password"
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary focus:border-icon-muted focus:outline-none"
            placeholder={t("onboarding.account.passwordPlaceholder")}
          />
        </label>
      </div>

      <div className="mt-5 rounded-lg border border-action/40 bg-action/10 p-3">
        <p className="text-small text-primary">{t("onboarding.account.wordsIntro")}</p>
      </div>

      {hint && (
        <div className="mt-4" role="alert">
          <ErrorBanner message={hint} onRetry={() => undefined} />
        </div>
      )}
      {!!props.error && !hint && (
        <p className="mt-4 text-small text-status-error" role="alert">
          {props.error instanceof Error
            ? props.error.message
            : t("onboarding.account.createError")}
        </p>
      )}

      <div className="mt-6 flex items-center justify-end">
        <Button type="submit" disabled={props.busy || !props.username.trim()}>
          {props.busy ? t("common.creating") : t("onboarding.account.create")}
        </Button>
      </div>
    </form>
  );
}

/** The recovery words, shown EXACTLY once after account creation (S-AC-01a/b)
 *  or rotation. The server persists only their hash — losing them plus the
 *  password means the vault is permanently locked (R-NF-03). */
function WordsCard({ words, onConfirm }: { words: string; onConfirm: () => void }) {
  const { t } = useAppLanguage();
  return (
    <div className="mt-8 rounded-lg border border-status-success/40 bg-surface-raised p-6">
      <h2 className="font-heading text-h4 text-primary">{t("onboarding.words.title")}</h2>
      <p className="mt-1 text-small text-muted">{t("onboarding.words.intro")}</p>
      <p
        className="mt-4 break-words rounded-lg border border-edge bg-surface p-4 font-mono text-body text-primary"
        data-testid="onboarding-words"
      >
        {words}
      </p>
      <div className="mt-6 flex items-center justify-end">
        <Button onClick={onConfirm}>{t("onboarding.words.confirm")}</Button>
      </div>
    </div>
  );
}