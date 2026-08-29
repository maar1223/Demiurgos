import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { createWorld, getOnboardingStatus, submitStep0 } from "@/api/onboarding";
import { createAccount } from "@/api/wiki";
import { getAuthStatus } from "@/api/wiki";
import { ApiError, type AuthMode, type LocaleInput, type OnboardingStatus } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";

/**
 * First-run onboarding (OC1/OC2, Slice 1).
 *
 * Flow: step 0 (locale) → account (credentials mode only) → world creation →
 * ready. Remote steps (AI, Telegram, Backup) are NEVER blocking and are
 * reported as pending — they are resumed from the Centro de Configuración
 * tab inside the Profile (`/perfil`). Completed steps are never replayed
 * after a restart (server is authoritative).
 *
 * The account step (R-AC-01) is BLOCKING and only exists in credentials mode
 * (DEMIURGOS_AUTH_MODE=credentials): username + optional password, and the
 * recovery words are generated server-side and shown to the user EXACTLY
 * ONCE. In local-dev/disabled mode the step is skipped (the backend still
 * derives "account" as the next step, but the account endpoint answers 403
 * outside credentials mode).
 *
 * Writes are gated on the authenticated local principal; a 401 surfaces a
 * clear hint (fail closed, never a silent bypass).
 */

const LANGUAGE_OPTIONS = [
  { value: "es", label: "Español" },
  { value: "en", label: "English" },
];

const COMMON_TIMEZONES = [
  "UTC",
  "America/Argentina/Buenos_Aires",
  "America/Mexico_City",
  "America/New_York",
  "Europe/Madrid",
  "Asia/Kolkata",
  "Asia/Shanghai",
];

const REMOTE_PENDING: Record<string, { title: string; description: string }> = {
  ai: {
    title: "Asistente de IA (texto y visión)",
    description:
      "Requiere un modelo local o remoto validado. Se retoma desde el Centro de Configuración.",
  },
  telegram: {
    title: "Telegram",
    description: "Requiere conexión y una cuenta configurada. Se retoma desde el Centro de Configuración.",
  },
  backup_handoff: {
    title: "Respaldo y restauración",
    description: "Requiere conexión y consentimiento. Se retoma desde el Centro de Configuración.",
  },
};

function authHint(error: unknown): string | null {
  if (error instanceof ApiError && error.status === 401) {
    return "La configuración requiere una sesión local. Activá DEMIURGOS_AUTH_MODE=local-dev e iniciá sesión local desde el perfil.";
  }
  return null;
}

export default function Onboarding() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // `?step=step0` re-opens ONLY the locale step from the Profile's
  // "Centro de Configuración" tab (OC12 per-section resume) without replaying
  // the completed flow; after saving, the user lands back on `/perfil`.
  const reconfigure = searchParams.get("step") === "step0";
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [writeError, setWriteError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  // Step 0 form
  const [uiLang, setUiLang] = useState("es");
  const [conversationLang, setConversationLang] = useState("es");
  const [contentLang, setContentLang] = useState("es");
  const [region, setRegion] = useState("");
  const [regionExplicit, setRegionExplicit] = useState(false);
  const [timezone, setTimezone] = useState("UTC");

  // World form
  const [worldName, setWorldName] = useState("");
  const [loreSkeleton, setLoreSkeleton] = useState(true);

  // Account form (credentials mode)
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
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
        if (next.completed && !reconfigure) {
          navigate("/wiki", { replace: true });
        }
      })
      .catch((cause: unknown) => setError(cause))
      .finally(() => setLoading(false));
  };

  useEffect(loadStatus, [navigate, reconfigure]);

  // The account step only renders in credentials mode: the creation endpoint
  // answers 403 outside it, so local-dev/disabled onboarding skips the step.
  useEffect(() => {
    let active = true;
    void getAuthStatus()
      .then((next) => {
        if (active) setAuthMode(next.mode);
      })
      .catch(() => {
        // Fail open to non-credentials (skip the account step).
        if (active) setAuthMode(null);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleStep0 = (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setWriteError(null);
    const locale: LocaleInput = {
      ui: uiLang,
      conversation: conversationLang,
      content: contentLang,
      region: region.trim() ? region.trim() : null,
      region_explicit: regionExplicit,
      iana_timezone: timezone.trim(),
    };
    void submitStep0(locale)
      .then((next) => {
        setStatus(next);
        setBusy(false);
        if (next.completed || reconfigure) {
          // The Configuration Center now lives inside the Profile (Perfil →
          // "Centro de Configuración" tab), so the reconfigure handoff lands
          // there instead of a standalone page.
          navigate("/perfil", { replace: true });
        }
      })
      .catch((cause: unknown) => {
        setWriteError(cause);
        setBusy(false);
      });
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
      <div className="flex min-h-screen items-center justify-center bg-cripta">
        <Spinner size="lg" />
      </div>
    );
  }

  const hint = authHint(error ?? writeError);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-cripta px-4 py-12">
      <div className="w-full max-w-xl">
        <h1 className="font-heading text-h3 text-pergamino">Bienvenida a Demiurgos</h1>
        <p className="mt-2 text-body text-tinta-desvaida">
          Configuración inicial para dejar la instalación operativa. Podés
          retomar cada capacidad después desde el Centro de Configuración.
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
          ) : authMode === "credentials" &&
            !status.completed_steps.includes("account") ? (
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
            <Step0Form
              uiLang={uiLang}
              onUiLang={setUiLang}
              conversationLang={conversationLang}
              onConversationLang={setConversationLang}
              contentLang={contentLang}
              onContentLang={setContentLang}
              region={region}
              onRegion={setRegion}
              regionExplicit={regionExplicit}
              onRegionExplicit={setRegionExplicit}
              timezone={timezone}
              onTimezone={setTimezone}
              busy={busy}
              onSubmit={handleStep0}
              reconfiguring={reconfigure}
            />
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

function Step0Form(props: {
  uiLang: string;
  onUiLang: (v: string) => void;
  conversationLang: string;
  onConversationLang: (v: string) => void;
  contentLang: string;
  onContentLang: (v: string) => void;
  region: string;
  onRegion: (v: string) => void;
  regionExplicit: boolean;
  onRegionExplicit: (v: boolean) => void;
  timezone: string;
  onTimezone: (v: string) => void;
  busy: boolean;
  onSubmit: (e: FormEvent) => void;
  reconfiguring?: boolean;
}) {
  return (
    <form onSubmit={props.onSubmit} className="mt-8 rounded-lg border border-filio bg-madero p-6">
      <h2 className="font-heading text-h4 text-pergamino">
        {props.reconfiguring ? "Idioma, región y zona horaria" : "Paso 1: idioma, región y zona horaria"}
      </h2>
      <p className="mt-1 text-small text-tinta-desvaida">
        Cada lenguaje se configura de forma independiente; la región solo
        sugiere valores y nunca se aplica en silencio.
      </p>

      <div className="mt-5 grid gap-4">
        <label htmlFor="onboarding-ui-lang" className="flex flex-col gap-1 text-small text-pergamino">
          Idioma de la interfaz
          <select
            id="onboarding-ui-lang"
            value={props.uiLang}
            onChange={(e) => props.onUiLang(e.target.value)}
            className="rounded-lg border border-filio bg-cripta px-3 py-2 text-body text-pergamino"
          >
            {LANGUAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

        <label htmlFor="onboarding-conversation-lang" className="flex flex-col gap-1 text-small text-pergamino">
          Idioma de conversación (asistente)
          <select
            id="onboarding-conversation-lang"
            value={props.conversationLang}
            onChange={(e) => props.onConversationLang(e.target.value)}
            className="rounded-lg border border-filio bg-cripta px-3 py-2 text-body text-pergamino"
          >
            {LANGUAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

        <label htmlFor="onboarding-content-lang" className="flex flex-col gap-1 text-small text-pergamino">
          Idioma de contenido (prosa del mundo)
          <select
            id="onboarding-content-lang"
            value={props.contentLang}
            onChange={(e) => props.onContentLang(e.target.value)}
            className="rounded-lg border border-filio bg-cripta px-3 py-2 text-body text-pergamino"
          >
            {LANGUAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>

        <label htmlFor="onboarding-region" className="flex flex-col gap-1 text-small text-pergamino">
          Región (opcional; sugiere valores, nunca impone dialecto)
          <input
            id="onboarding-region"
            value={props.region}
            onChange={(e) => props.onRegion(e.target.value)}
            className="rounded-lg border border-filio bg-cripta px-3 py-2 text-body text-pergamino"
            placeholder="AR, MX, US…"
          />
        </label>

        <label className="flex items-center gap-2 text-small text-pergamino">
          <input
            type="checkbox"
            checked={props.regionExplicit}
            onChange={(e) => props.onRegionExplicit(e.target.checked)}
            className="h-4 w-4"
          />
          Confirmo la región de forma explícita (override)
        </label>

        <label htmlFor="onboarding-timezone" className="flex flex-col gap-1 text-small text-pergamino">
          Zona horaria (identificador IANA; los timestamps se guardan en UTC)
          <input
            id="onboarding-timezone"
            list="onboarding-timezones"
            value={props.timezone}
            onChange={(e) => props.onTimezone(e.target.value)}
            className="rounded-lg border border-filio bg-cripta px-3 py-2 text-body text-pergamino"
          />
          <datalist id="onboarding-timezones">
            {COMMON_TIMEZONES.map((tz) => (
              <option key={tz} value={tz} />
            ))}
          </datalist>
        </label>
      </div>

      <div className="mt-6 flex items-center justify-end">
        <Button type="submit" disabled={props.busy}>
          {props.busy ? "Guardando…" : "Continuar"}
        </Button>
      </div>
    </form>
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
    <form onSubmit={props.onSubmit} className="mt-8 rounded-lg border border-filio bg-madero p-6">
      <h2 className="font-heading text-h4 text-pergamino">Creá tu mundo</h2>
      <p className="mt-1 text-small text-tinta-desvaida">
        Se crea un árbol canónico en minúsculas (lore, personajes). El
        mundo es el último paso operativo para entrar al Taller de Mundo.
      </p>

      <div className="mt-5 grid gap-4">
        <label htmlFor="onboarding-world-name" className="flex flex-col gap-1 text-small text-pergamino">
          Nombre del mundo
          <input
            id="onboarding-world-name"
            value={props.worldName}
            onChange={(e) => props.onWorldName(e.target.value)}
            required
            className="rounded-lg border border-filio bg-cripta px-3 py-2 text-body text-pergamino"
            placeholder="mi-mundo"
          />
        </label>

        <label className="flex items-center gap-2 text-small text-pergamino">
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
      <h2 className="font-heading text-h4 text-pergamino">Lo que queda pendiente</h2>
      <div aria-live="polite" className="mt-3 grid gap-3">
        {items.map((item) => (
          <div
            key={item.title}
            className="flex items-start justify-between gap-3 rounded-lg border border-filio bg-madero p-4"
          >
            <div>
              <p className="text-body text-pergamino">{item.title}</p>
              <p className="mt-1 text-small text-tinta-desvaida">{item.description}</p>
            </div>
            <span className="inline-flex shrink-0 items-center rounded-full border border-filio bg-piedra px-2.5 py-0.5 text-xs font-medium text-pergamino">
              Pendiente
            </span>
          </div>
        ))}
        {props.worldDone && items.length === 0 && (
          <p className="text-small text-tinta-desvaida">No hay capacidades pendientes.</p>
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
    <form onSubmit={props.onSubmit} className="mt-8 rounded-lg border border-filio bg-madero p-6">
      <h2 className="font-heading text-h4 text-pergamino">Creá tu cuenta</h2>
      <p className="mt-1 text-small text-tinta-desvaida">
        La cuenta protege tu instalación. La contraseña es opcional: sin ella
        alcanza con el botón Entrar para ingresar.
      </p>

      <div className="mt-5 grid gap-4">
        <label htmlFor="onboarding-account-username" className="flex flex-col gap-1 text-small text-pergamino">
          Usuario
          <input
            id="onboarding-account-username"
            value={props.username}
            onChange={(e) => props.onUsername(e.target.value)}
            required
            autoComplete="username"
            className="rounded-lg border border-filio bg-cripta px-3 py-2 text-body text-pergamino focus:border-plata focus:outline-none"
            placeholder="tu-usuario"
          />
        </label>

        <label htmlFor="onboarding-account-password" className="flex flex-col gap-1 text-small text-pergamino">
          Contraseña (opcional)
          <input
            id="onboarding-account-password"
            type="password"
            value={props.password}
            onChange={(e) => props.onPassword(e.target.value)}
            autoComplete="new-password"
            className="rounded-lg border border-filio bg-cripta px-3 py-2 text-body text-pergamino focus:border-plata focus:outline-none"
            placeholder="Dejalo vacío para entrar sin contraseña"
          />
        </label>
      </div>

      <div className="mt-5 rounded-lg border border-llamita/40 bg-llamita/10 p-3">
        <p className="text-small text-pergamino">
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
        <p className="mt-4 text-small text-sangre" role="alert">
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
    <div className="mt-8 rounded-lg border border-musgo/40 bg-madero p-6">
      <h2 className="font-heading text-h4 text-pergamino">Tus palabras claves</h2>
      <p className="mt-1 text-small text-tinta-desvaida">
        Guardalas en un lugar seguro, fuera del navegador. Solo se muestran una
        vez: si las perdés y olvidás la contraseña, la cuenta queda bloqueada
        para siempre.
      </p>
      <p
        className="mt-4 break-words rounded-lg border border-filio bg-cripta p-4 font-mono text-body text-pergamino"
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