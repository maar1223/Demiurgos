import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createWorld, getOnboardingStatus } from "@/api/onboarding";
import { createAccount } from "@/api/wiki";
import type { OnboardingStatus } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { LocaleForm, authHint } from "@/components/organisms/LocaleForm";

/**
 * First-run onboarding (OC1/OC2, Slice 1).
 *
 * Flow: step 0 (locale) → account (always active on a fresh install) → world
 * creation → ready. Remote steps (AI, Telegram, Backup) are NEVER blocking and
 * are reported as pending — they are resumed from the Profile (`/perfil`).
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

const REMOTE_PENDING: Record<string, { title: string; description: string }> = {
  ai: {
    title: "Asistente de IA (texto y visión)",
    description:
      "Requiere un modelo local o remoto validado. Se retoma desde el Perfil.",
  },
  telegram: {
    title: "Telegram",
    description: "Requiere conexión y una cuenta configurada. Se retoma desde el Perfil.",
  },
  backup_handoff: {
    title: "Respaldo y restauración",
    description: "Requiere conexión y consentimiento. Se retoma desde el Perfil.",
  },
};

export default function Onboarding() {
  const navigate = useNavigate();
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
        navigate("/wiki", { replace: true });
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

  const hint = authHint(error ?? writeError);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-surface px-4 py-12">
      <div className="w-full max-w-xl">
        <h1 className="font-heading text-h3 text-primary">Bienvenida a Demiurgos</h1>
        <p className="mt-2 text-body text-muted">
          Configuración inicial para dejar la instalación operativa. Podés
          retomar cada capacidad después desde el Perfil.
        </p>

        {!!error && !status && (
          <div className="mt-6">
            <ErrorBanner message="No se pudo consultar el estado de la instalación." onRetry={loadStatus} />
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
          ) : (
            <WorldStep
              worldName={worldName}
              onWorldName={setWorldName}
              loreSkeleton={loreSkeleton}
              onLoreSkeleton={setLoreSkeleton}
              busy={busy}
              onSubmit={handleCreateWorld}
            />
          )
        ) : (
          status && (
            <div className="mt-8 rounded-lg border border-edge bg-surface-raised p-6">
              <h2 className="font-heading text-h4 text-primary">
                Paso 1: idioma, región y zona horaria
              </h2>
              <LocaleForm onSaved={handleStep0Saved} submitLabel="Continuar" />
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
  onSubmit: (e: FormEvent) => void;
}) {
  return (
    <form onSubmit={props.onSubmit} className="mt-8 rounded-lg border border-edge bg-surface-raised p-6">
      <h2 className="font-heading text-h4 text-primary">Creá tu mundo</h2>
      <p className="mt-1 text-small text-muted">
        Se crea un árbol canónico en minúsculas (lore, personajes). El
        mundo es el último paso operativo para entrar al Taller de Mundo.
      </p>

      <div className="mt-5 grid gap-4">
        <label htmlFor="onboarding-world-name" className="flex flex-col gap-1 text-small text-primary">
          Nombre del mundo
          <input
            id="onboarding-world-name"
            value={props.worldName}
            onChange={(e) => props.onWorldName(e.target.value)}
            required
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary"
            placeholder="mi-mundo"
          />
        </label>

        <label className="flex items-center gap-2 text-small text-primary">
          <input
            type="checkbox"
            checked={props.loreSkeleton}
            onChange={(e) => props.onLoreSkeleton(e.target.checked)}
            className="h-4 w-4"
          />
          Incluir la estructura Lore recomendada (carpetas vacías)
        </label>
      </div>

      <div className="mt-6 flex items-center justify-end">
        <Button type="submit" disabled={props.busy || !props.worldName.trim()}>
          {props.busy ? "Creando…" : "Crear mundo"}
        </Button>
      </div>
    </form>
  );
}

function PendingCards(props: { remotePending: string[]; worldDone: boolean }) {
  const items = props.remotePending.map((step) => REMOTE_PENDING[step]).filter(Boolean);
  return (
    <section aria-label="Capacidades pendientes" className="mt-8">
      <h2 className="font-heading text-h4 text-primary">Lo que queda pendiente</h2>
      <div aria-live="polite" className="mt-3 grid gap-3">
        {items.map((item) => (
          <div
            key={item.title}
            className="flex items-start justify-between gap-3 rounded-lg border border-edge bg-surface-raised p-4"
          >
            <div>
              <p className="text-body text-primary">{item.title}</p>
              <p className="mt-1 text-small text-muted">{item.description}</p>
            </div>
            <span className="inline-flex shrink-0 items-center rounded-full border border-edge bg-surface-raised px-2.5 py-0.5 text-xs font-medium text-primary">
              Pendiente
            </span>
          </div>
        ))}
        {props.worldDone && items.length === 0 && (
          <p className="text-small text-muted">No hay capacidades pendientes.</p>
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
  const hint = authHint(props.error);
  return (
    <form onSubmit={props.onSubmit} className="mt-8 rounded-lg border border-edge bg-surface-raised p-6">
      <h2 className="font-heading text-h4 text-primary">Creá tu cuenta</h2>
      <p className="mt-1 text-small text-muted">
        La cuenta protege tu instalación. La contraseña es opcional: sin ella
        alcanza con el botón Entrar para ingresar.
      </p>

      <div className="mt-5 grid gap-4">
        <label htmlFor="onboarding-account-username" className="flex flex-col gap-1 text-small text-primary">
          Usuario
          <input
            id="onboarding-account-username"
            value={props.username}
            onChange={(e) => props.onUsername(e.target.value)}
            required
            autoComplete="username"
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary focus:border-icon-muted focus:outline-none"
            placeholder="tu-usuario"
          />
        </label>

        <label htmlFor="onboarding-account-password" className="flex flex-col gap-1 text-small text-primary">
          Contraseña (opcional)
          <input
            id="onboarding-account-password"
            type="password"
            value={props.password}
            onChange={(e) => props.onPassword(e.target.value)}
            autoComplete="new-password"
            className="rounded-lg border border-edge bg-surface px-3 py-2 text-body text-primary focus:border-icon-muted focus:outline-none"
            placeholder="Dejalo vacío para entrar sin contraseña"
          />
        </label>
      </div>

      <div className="mt-5 rounded-lg border border-action/40 bg-action/10 p-3">
        <p className="text-small text-primary">
          Al crear la cuenta se generan tus{" "}
          <span className="font-medium">palabras claves</span>: son tu única
          forma de recuperarla si olvidás la contraseña. Se muestran una sola
          vez y no se pueden volver a ver.
        </p>
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
            : "No se pudo crear la cuenta"}
        </p>
      )}

      <div className="mt-6 flex items-center justify-end">
        <Button type="submit" disabled={props.busy || !props.username.trim()}>
          {props.busy ? "Creando…" : "Crear cuenta"}
        </Button>
      </div>
    </form>
  );
}

/** The recovery words, shown EXACTLY once after account creation (S-AC-01a/b)
 *  or rotation. The server persists only their hash — losing them plus the
 *  password means the vault is permanently locked (R-NF-03). */
function WordsCard({ words, onConfirm }: { words: string; onConfirm: () => void }) {
  return (
    <div className="mt-8 rounded-lg border border-status-success/40 bg-surface-raised p-6">
      <h2 className="font-heading text-h4 text-primary">Tus palabras claves</h2>
      <p className="mt-1 text-small text-muted">
        Guardalas en un lugar seguro, fuera del navegador. Solo se muestran una
        vez: si las perdés y olvidás la contraseña, la cuenta queda bloqueada
        para siempre.
      </p>
      <p
        className="mt-4 break-words rounded-lg border border-edge bg-surface p-4 font-mono text-body text-primary"
        data-testid="onboarding-words"
      >
        {words}
      </p>
      <div className="mt-6 flex items-center justify-end">
        <Button onClick={onConfirm}>Guardé mis palabras</Button>
      </div>
    </div>
  );
}