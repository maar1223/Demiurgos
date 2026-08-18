import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getReadiness } from "@/api/onboarding";
import type { CardState, ReadinessSnapshot } from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";

/**
 * Configuration Center (OC12) — permanent surface for reviewing and resuming
 * capabilities by section, never replaying onboarding.
 *
 * Cards expose the four contractual states (pending / configured /
 * requires_connection / error) as BOTH color and text (non-color-only), with
 * semantic labels and an aria-live region. Each card resumes its own section
 * without touching the others.
 */

const STATE_META: Record<CardState, { label: string; badge: "default" | "success" | "warning" | "error" }> = {
  pending: { label: "Pendiente", badge: "default" },
  configured: { label: "Configurado", badge: "success" },
  requires_connection: { label: "Requiere conexión", badge: "warning" },
  error: { label: "Error", badge: "error" },
};

interface CardAction {
  label: string;
  to: string;
}

interface CardDef {
  key: string;
  title: string;
  description: string;
  action: CardAction | null;
}

const CARD_DEFS: CardDef[] = [
  { key: "identity", title: "Identidad", description: "Cuenta local / Google, revalidación y recuperación.", action: { label: "Ir a Perfil", to: "/perfil" } },
  { key: "assistant", title: "IA texto y visión", description: "Modelo principal del Asistente (multimodal, validado).", action: { label: "Configurar", to: "/perfil" } },
  { key: "telegram", title: "Telegram", description: "Canal de mensajería para captura de ideas.", action: { label: "Configurar", to: "/perfil" } },
  { key: "backup", title: "Respaldo y restauración", description: "Google Drive / rclone. Requiere conexión y consentimiento.", action: null },
  { key: "locale", title: "Idioma, región y zona horaria", description: "Localización del paso 0, reconfigurable por separado.", action: { label: "Configurar", to: "/onboarding?step=step0" } },
  { key: "world", title: "Mundos", description: "Crear, importar o restaurar. Entrada al Taller de Mundo.", action: { label: "Abrir Taller de Mundo", to: "/taller-mundo" } },
  { key: "offline", title: "Offline / dispositivo", description: "Núcleo local (editor, ideas, grafo) sin conexión.", action: null },
];

export default function ConfigurationCenter() {
  const navigate = useNavigate();
  const [readiness, setReadiness] = useState<ReadinessSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    void getReadiness()
      .then(setReadiness)
      .catch((cause: unknown) => setError(cause))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const cards = readiness?.cards ?? {};

  return (
    <div className="min-h-screen bg-cripta">
      <header className="border-b border-filio bg-cripta/95">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
          <h1 className="font-heading text-h4 text-pergamino">Centro de Configuración</h1>
          <Button variant="ghost" size="sm" onClick={() => navigate("/wiki")}>
            Volver
          </Button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 py-8">
        <p className="max-w-2xl text-body text-tinta-desvaida">
          Revisá y retomá cada capacidad de forma independiente. Las
          capacidades pendientes no se resuelven repitiendo el onboarding.
        </p>

        {loading && (
          <div className="mt-10 flex justify-center">
            <Spinner size="lg" />
          </div>
        )}

        {!!error && !readiness && (
          <div className="mt-6">
            <ErrorBanner
              message="No se pudieron cargar los estados de configuración."
              onRetry={load}
            />
          </div>
        )}

        {readiness && (
          <div className="mt-8 grid grid-cols-1 gap-4 tablet:grid-cols-2" aria-live="polite">
            {CARD_DEFS.map((card) => {
              const state: CardState = cards[card.key] ?? "pending";
              const meta = STATE_META[state];
              return (
                <section
                  key={card.key}
                  aria-labelledby={`card-title-${card.key}`}
                  className="flex flex-col justify-between gap-4 rounded-lg border border-filio bg-madero p-5"
                >
                  <div>
                    <h2 id={`card-title-${card.key}`} className="font-heading text-body text-pergamino">
                      {card.title}
                    </h2>
                    <p className="mt-1 text-small text-tinta-desvaida">{card.description}</p>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2">
                      <Badge variant={meta.badge}>{meta.label}</Badge>
                      <span className="sr-only">Estado: {meta.label}</span>
                    </span>
                    {card.action ? (
                      <Button variant="secondary" size="sm" onClick={() => navigate(card.action!.to)}>
                        {card.action.label}
                      </Button>
                    ) : (
                      <span className="text-small text-sombra">Se retoma desde esta tarjeta</span>
                    )}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}