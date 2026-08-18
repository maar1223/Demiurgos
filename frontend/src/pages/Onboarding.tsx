import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { createWorld, getOnboardingStatus, submitStep0 } from "@/api/onboarding";
import { ApiError, type LocaleInput, type OnboardingStatus } from "@/api/types";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";

/**
 * First-run onboarding (OC1/OC2, Slice 1).
 *
 * Flow: step 0 (locale) → world creation → ready. Remote steps (AI, Telegram,
 * Backup) are NEVER blocking and are reported as pending — they are resumed
 * from the Configuration Center. Completed steps are never replayed after a
 * restart (server is authoritative).
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
  // `?step=step0` re-opens ONLY the locale step from the Configuration Center
  // (OC12 per-section resume) without replaying the completed flow.
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
          navigate("/centro-configuracion", { replace: true });
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
          <WorldStep
            worldName={worldName}
            onWorldName={setWorldName}
            loreSkeleton={loreSkeleton}
            onLoreSkeleton={setLoreSkeleton}
            busy={busy}
            onSubmit={handleCreateWorld}
          />
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
        Se crea un árbol canónico en minúsculas (lore, personajes, sagas). El
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