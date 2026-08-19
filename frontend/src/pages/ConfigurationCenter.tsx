import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getReadiness } from "@/api/onboarding";
import type { CardState, ReadinessSnapshot } from "@/api/types";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { MigrationPanel } from "@/components/organisms/MigrationPanel";
import { TelegramCard } from "@/components/organisms/TelegramCard";

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

/**
 * Capabilities without a dedicated contract (ONB-3.1/ONB-3.5): their cards
 * can NEVER render as "Configurado", because only their dedicated contracts
 * may mark them configured. Defense in depth: even if a stale/buggy backend
 * reports "configured" for one of these keys, the UI forces the honest
 * pending state instead of overstating readiness.
 *
 * - identity / backup: remote capabilities whose dedicated contracts do not
 *   exist in this change.
 * - import (ONB-3.5): the importer is a separate SDD; its card exposes
 *   entry/pending only and must never claim an import happened.
 *
 * NOTE (WU-3b1): telegram is intentionally NOT in this set anymore — ONB-3.3
 * gave it a dedicated backend contract whose `configured` state is proven by
 * a real server-side getMe check, so its card may truthfully render
 * configured.
 */
const DEFERRED_CARD_KEYS: ReadonlySet<string> = new Set(["identity", "backup", "import"]);

/** Essential local readiness badges (OC11/OC21): World + local editor. */
const ESSENTIAL_BADGES: { key: string; title: string }[] = [
  { key: "world", title: "Mundos" },
  { key: "editor", title: "Editor local" },
];

/** Remote capability labels shown in the offline card breakdown (OC5). */
const REMOTE_LABELS: Record<string, string> = {
  identity: "Identidad",
  telegram: "Telegram",
  backup: "Respaldo",
  assistant: "Asistente (IA)",
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
  { key: "identity", title: "Identidad", description: "Cuenta local / Google: revalidación online y recuperación autorizada.", action: { label: "Ir a Perfil", to: "/perfil" } },
  { key: "assistant", title: "IA texto y visión", description: "Modelo principal del Asistente (multimodal, validado).", action: { label: "Configurar", to: "/perfil" } },
  { key: "telegram", title: "Telegram", description: "Canal de mensajería para captura de ideas.", action: null },
  { key: "backup", title: "Respaldo y restauración", description: "Google Drive / rclone: respaldo y restauración, con consentimiento separado de la identidad.", action: null },
  { key: "locale", title: "Idioma, región y zona horaria", description: "Localización del paso 0, reconfigurable por separado.", action: { label: "Configurar", to: "/onboarding?step=step0" } },
  { key: "world", title: "Mundos", description: "Crear, importar o restaurar. Entrada al Taller de Mundo.", action: { label: "Abrir Taller de Mundo", to: "/taller-mundo" } },
  { key: "offline", title: "Offline / dispositivo", description: "Núcleo local (editor, ideas, grafo) sin conexión.", action: null },
  { key: "import", title: "Importar mundo", description: "Importar contenido a un mundo. El importador está operativo: iniciá una nueva importación o retomá una anterior desde el Taller de Mundo.", action: { label: "Ir al Taller de Mundo", to: "/taller-mundo" } },
];

export default function ConfigurationCenter() {
  const navigate = useNavigate();
  const [readiness, setReadiness] = useState<ReadinessSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [telegramOpen, setTelegramOpen] = useState(false);
  const [migrationOpen, setMigrationOpen] = useState(false);

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

  /**
   * Honest per-card state (ONB-3.1/ONB-3.5): capabilities without a dedicated
   * contract can never be "configured" in this slice — their dedicated
   * contracts are the only path to configured, and none exists yet. Even if
   * the backend reports "configured" for such a key (stale/buggy state), the
   * UI renders the truthful pending state.
   */
  const stateFor = (key: string): CardState => {
    const raw = cards[key] ?? "pending";
    if (DEFERRED_CARD_KEYS.has(key) && raw === "configured") return "pending";
    return raw as CardState;
  };

  /**
   * Per-card visible label. The assistant badge (OC19) reports
   * "Pendiente / no apto" when no multimodal model has passed the three
   * proofs — it never claims configured in that case.
   */
  const labelFor = (key: string, state: CardState): string => {
    if (key === "assistant" && state === "pending") return "Pendiente / no apto";
    return STATE_META[state].label;
  };

  const essentialBadge = (key: string): { label: string; badge: "default" | "success" | "error" } => {
    if (key === "editor") {
      return readiness?.local_editor.ok
        ? { label: "Listo", badge: "success" }
        : { label: "No disponible", badge: "error" };
    }
    return stateFor("world") === "configured"
      ? { label: "Listo", badge: "success" }
      : { label: "Pendiente", badge: "default" };
  };

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
          <div className="mt-8 space-y-8" aria-live="polite">
            {/* Essential local readiness badges (OC11/OC21) */}
            <section
              aria-labelledby="essential-readiness-title"
              className="rounded-lg border border-filio bg-madero p-5"
            >
              <h2 id="essential-readiness-title" className="font-heading text-body text-pergamino">
                Listo para trabajar
              </h2>
              <p className="mt-1 text-small text-tinta-desvaida">
                Capacidades esenciales locales: Mundo y editor local.
              </p>
              <div className="mt-3 flex flex-wrap gap-3">
                {ESSENTIAL_BADGES.map((badge) => {
                  const meta = essentialBadge(badge.key);
                  return (
                    <span key={badge.key} className="flex items-center gap-2">
                      <span className="text-small text-tinta-desvaida">{badge.title}:</span>
                      <Badge variant={meta.badge}>{meta.label}</Badge>
                      <span className="sr-only">Estado: {meta.label}</span>
                    </span>
                  );
                })}
              </div>
            </section>

            <div className="grid grid-cols-1 gap-4 tablet:grid-cols-2">
              {CARD_DEFS.map((card) => {
                const state = stateFor(card.key);
                const label = labelFor(card.key, state);
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
                        <Badge variant={meta.badge}>{label}</Badge>
                        <span className="sr-only">Estado: {label}</span>
                      </span>
                      {card.key === "telegram" ? (
                        <Button
                          variant="secondary"
                          size="sm"
                          aria-expanded={telegramOpen}
                          aria-controls="telegram-card-panel"
                          onClick={() => setTelegramOpen((open) => !open)}
                        >
                          {telegramOpen ? "Ocultar panel" : "Configurar Telegram"}
                        </Button>
                      ) : card.action ? (
                        <Button variant="secondary" size="sm" onClick={() => navigate(card.action!.to)}>
                          {card.action.label}
                        </Button>
                      ) : card.key === "backup" ? (
                        <span className="text-small text-sombra">
                          Pendiente — contrato dedicado en definición
                        </span>
                      ) : (
                        <span className="text-small text-sombra">Se retoma desde esta tarjeta</span>
                      )}
                    </div>
                    {/* ONB-4.4 (WU-4d) — Google identity card: entry only.
                        OAuth/OIDC is an MVP objective, NOT implemented in
                        this change: the card stays pending and only exposes
                        the revalidation / authorized-recovery entry in
                        Perfil. Identity uses a stable Google identifier
                        (sub), never the email, and never reuses another
                        installation's credential without authorization
                        (OC4/OC23). */}
                    {card.key === "identity" && (
                      <div className="mt-4 border-t border-filio pt-4">
                        <p className="text-small text-tinta-desvaida">
                          El vínculo con Google (OAuth/OIDC) es objetivo del MVP y aún no está
                          implementado: esta tarjeta queda pendiente y solo ofrece la entrada de
                          revalidación online o recuperación autorizada desde Perfil. La identidad
                          usa un identificador estable de Google (<code>sub</code>), nunca el
                          email, y no reutiliza credenciales de otra instalación sin autorización.
                        </p>
                      </div>
                    )}
                    {/* ONB-4.5 (WU-4d) — Backup/restore card: entry only.
                        Google Drive / rclone backup is not implemented in
                        this change; the card stays pending and is only an
                        entry for its dedicated contract. Drive consent is
                        separate from the Google identity consent, and backup
                        and restore are distinct flows (OC10/OC24). */}
                    {card.key === "backup" && (
                      <div className="mt-4 border-t border-filio pt-4">
                        <p className="text-small text-tinta-desvaida">
                          El respaldo y la restauración (Google Drive / rclone) no están
                          implementados en esta versión: la tarjeta queda pendiente y es solo la
                          entrada para su contrato dedicado. El consentimiento de Drive es
                          independiente del consentimiento de identidad de Google, y respaldo y
                          restauración son flujos distintos. Nunca se afirma configurado sin ese
                          contrato.
                        </p>
                      </div>
                    )}
                    {card.key === "telegram" && telegramOpen && (
                      <div id="telegram-card-panel" className="mt-4">
                        <TelegramCard />
                      </div>
                    )}
                    {/* ONB-4.2 — read-only legacy detection notice on the
                        Mundos card: uppercase Lore/Personajes found by the
                        backend are listed with the case-sensitive risk.
                        Detection never mutates; migration (ONB-4.3, WU-4c2)
                        is a separate, explicitly approved step that only runs
                        from the panel's ConfirmDialog. After a completed
                        migration the Center refreshes readiness so the notice
                        disappears once the tree is canonical. */}
                    {card.key === "world" && (readiness.legacy ?? []).length > 0 && (
                      <div className="mt-4 border-t border-filio pt-4">
                        <div role="note">
                          <p className="text-small font-medium text-pergamino">
                            Carpetas legacy detectadas
                          </p>
                          <p className="mt-1 text-small text-tinta-desvaida">
                            {readiness.legacy
                              .map((f) => `${f.world} (${f.folders.join(", ")})`)
                              .join("; ")}
                            . Las rutas distinguen mayúsculas y minúsculas: estas
                            carpetas no se reconocen como lore/personajes canónicos
                            y nunca se renombran de forma automática.
                          </p>
                        </div>
                        <div className="mt-3">
                          <Button
                            variant="secondary"
                            size="sm"
                            aria-expanded={migrationOpen}
                            aria-controls="migration-panel"
                            onClick={() => setMigrationOpen((open) => !open)}
                          >
                            {migrationOpen ? "Ocultar migración" : "Migrar carpetas legacy"}
                          </Button>
                        </div>
                        {migrationOpen && (
                          <div id="migration-panel" className="mt-4">
                            <MigrationPanel
                              findings={readiness.legacy}
                              onMigrated={load}
                            />
                          </div>
                        )}
                      </div>
                    )}
                    {card.key === "offline" && (
                      <dl className="mt-4 space-y-3 border-t border-filio pt-4">
                        <div className="flex items-center justify-between gap-3">
                          <dt className="text-small text-tinta-desvaida">Núcleo local</dt>
                          <dd className="flex items-center gap-2">
                            <Badge variant={readiness.offline.local_ready ? "success" : "error"}>
                              {readiness.offline.local_ready ? "Listo" : "No disponible"}
                            </Badge>
                            <span className="sr-only">
                              Estado: {readiness.offline.local_ready ? "Listo" : "No disponible"}
                            </span>
                          </dd>
                        </div>
                        <div>
                          <dt className="text-small text-tinta-desvaida">Remoto</dt>
                          <dd className="mt-1 text-small text-tinta-desvaida">
                            {readiness.offline.remote_pending.length > 0 ? (
                              <span>
                                Capacidades remotas pendientes (requieren conexión):{" "}
                                {readiness.offline.remote_pending
                                  .map((key) => REMOTE_LABELS[key] ?? key)
                                  .join(", ")}.
                              </span>
                            ) : (
                              <span>Sin capacidades remotas pendientes.</span>
                            )}
                          </dd>
                        </div>
                      </dl>
                    )}
                  </section>
                );
              })}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}