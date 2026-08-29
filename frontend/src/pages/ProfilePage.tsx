import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Navbar } from "@/components/organisms/Navbar";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { IdeaCapturePanel } from "@/components/organisms/IdeaCapturePanel";
import { AssistantSettingsPanel } from "@/components/organisms/AssistantSettingsPanel";
import { DeleteWorldModal } from "@/components/organisms/DeleteWorldModal";
import { WorldTrashPanel } from "@/components/organisms/WorldTrashPanel";
import { getIdeaCaptureStatus } from "@/api/ideaCapture";
import { getReadiness } from "@/api/onboarding";
import { getAuthStatus, logoutSession, rotateEmergencyKey } from "@/api/wiki";
import { useWorlds } from "@/hooks/useWorlds";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";
import { reloadPage } from "@/lib/reloadPage";
import type { AuthSessionStatus, ReadinessSnapshot, WorldInfo } from "@/api/types";
import {
  CARD_DEFS,
  ESSENTIAL_BADGES,
  MigrationPanel,
  REMOTE_LABELS,
  STATE_META,
  cardLabel,
  cardState,
  essentialBadgeFor,
} from "@/pages/ConfigurationCenter";
import { cn } from "@/lib/utils";

type ProfileSection = "sesion" | "configuracion" | "integraciones" | "asistente" | "mundos";

/** Sesión de edición — the same local-dev session controls as the Navbar
 *  dropdown, kept accessible from the full Profile page. Mode-aware: in the
 *  google vault mode (DEMIURGOS_AUTH_MODE=google) the panel shows the vault
 *  session (logout + emergency-key rotation); local-dev and disabled keep
 *  their legacy behavior unchanged. */
function SessionSection() {
  const localDev = useLocalDevAuth(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Unified status decides the vault branch; on failure the panel degrades
  // to the local-dev view — a low-stakes read, never a wall.
  const [vaultStatus, setVaultStatus] = useState<AuthSessionStatus | null>(null);
  const [rotating, setRotating] = useState(false);
  const [newKey, setNewKey] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void getAuthStatus()
      .then((next) => {
        if (active) setVaultStatus(next);
      })
      .catch(() => {
        if (active) setVaultStatus(null);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleVaultLogout = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      await logoutSession();
      reloadPage();
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : "No se pudo cerrar la sesión",
      );
    } finally {
      setActionLoading(false);
    }
  };

  const handleRotate = async () => {
    setRotating(true);
    setActionError(null);
    setNewKey(null);
    try {
      const { new_key } = await rotateEmergencyKey();
      // The server persists only the hash; the plaintext is shown once.
      setNewKey(new_key);
    } catch (cause) {
      setActionError(
        cause instanceof Error
          ? cause.message
          : "No se pudo rotar la clave de emergencia",
      );
    } finally {
      setRotating(false);
    }
  };

  const handleAction = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      if (localDev.status?.authenticated) {
        await localDev.logout();
      } else {
        await localDev.start();
      }
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : "No se pudo actualizar la sesión local",
      );
    } finally {
      setActionLoading(false);
    }
  };

  // Google vault mode: session controls + emergency-key rotation.
  if (vaultStatus?.mode === "google") {
    return (
      <div className="rounded-lg border border-filio bg-madero p-4">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-heading text-body text-pergamino">Sesión de edición</h3>
          <span className="text-small text-tinta-desvaida">Bóveda</span>
        </div>

        {vaultStatus.authenticated ? (
          <>
            <p className="mt-3 text-small text-musgo">Sesión activa</p>
            <p className="mt-1 text-small text-tinta-desvaida">{vaultStatus.label}</p>
            <p className="mt-1 text-small text-tinta-desvaida">
              Proveedor: {providerLabel(vaultStatus.provider)}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                variant="secondary"
                onClick={() => void handleVaultLogout()}
                disabled={actionLoading}
              >
                {actionLoading ? "Cerrando…" : "Cerrar sesión"}
              </Button>
              <Button
                variant="secondary"
                onClick={() => void handleRotate()}
                disabled={rotating}
              >
                {rotating ? "Rotando…" : "Rotar clave de emergencia"}
              </Button>
            </div>
            {newKey && (
              <div
                role="status"
                className="mt-4 rounded-lg border border-musgo/40 bg-cripta/50 p-3"
              >
                <p className="text-small text-musgo">
                  Nueva clave de recuperación — guardala fuera del navegador:
                </p>
                <p className="mt-2 break-words font-mono text-small text-pergamino">
                  {newKey}
                </p>
              </div>
            )}
          </>
        ) : (
          <p className="mt-3 text-small text-tinta-desvaida">
            No hay una sesión de bóveda activa. Iniciá sesión para editar y
            configurar el perfil.
          </p>
        )}

        {actionError && <p className="mt-3 text-small text-sangre">{actionError}</p>}
      </div>
    );
  }

  // Local-dev / disabled: legacy panel (unchanged).
  if (localDev.isLoading) {
    return (
      <div className="flex items-center gap-2 py-6 text-small text-tinta-desvaida">
        <Spinner size="sm" /> Comprobando sesión local…
      </div>
    );
  }

  if (localDev.error) {
    return <p className="text-small text-sangre">{localDev.error.message}</p>;
  }

  if (!localDev.status) return null;

  return (
    <div className="rounded-lg border border-filio bg-madero p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-heading text-body text-pergamino">Sesión de edición</h3>
        <span className="text-small text-tinta-desvaida">Local</span>
      </div>

      {localDev.status.authenticated && (
        <>
          <p className="mt-3 text-small text-musgo">Sesión local activa</p>
          <p className="mt-1 text-small text-tinta-desvaida">{localDev.status.label}</p>
          <Button
            variant="secondary"
            onClick={() => void handleAction()}
            disabled={actionLoading}
            className="mt-3"
          >
            {actionLoading ? "Cerrando…" : "Cerrar sesión local"}
          </Button>
        </>
      )}

      {!localDev.status.authenticated && localDev.status.enabled && (
        <>
          <p className="mt-3 text-small text-tinta-desvaida">
            Sesión local no iniciada. Iniciala para editar y configurar el perfil.
          </p>
          <Button
            variant="primary"
            onClick={() => void handleAction()}
            disabled={actionLoading}
            className="mt-3"
          >
            {actionLoading ? "Iniciando…" : "Iniciar sesión local"}
          </Button>
        </>
      )}

      {!localDev.status.enabled && (
        <p className="mt-3 text-small text-tinta-desvaida">
          Autenticación local desactivada. Activá{" "}
          <code className="text-plata">DEMIURGOS_AUTH_MODE=local-dev</code> en{" "}
          <code className="text-plata">.env</code> para probar la edición.
        </p>
      )}

      {actionError && <p className="mt-3 text-small text-sangre">{actionError}</p>}
    </div>
  );
}

/** Human label for the active session provider. */
function providerLabel(provider?: AuthSessionStatus["provider"]): string {
  switch (provider) {
    case "google":
      return "Google";
    case "emergency":
      return "Clave de emergencia";
    case "local-dev":
      return "Local";
    default:
      return "Desconocido";
  }
}

/** Perfil → Integraciones → Captura de ideas — the single Telegram surface.
 *  The guided wizard covers the write-only bot token (save/replace/clear) and
 *  getMe-backed connection validation via the "Detectar chat" step. */
function IntegrationsSection() {
  const auth = useLocalDevAuth(true);
  return (
    <div>
      <h3 className="font-heading text-body text-pergamino">Captura de ideas</h3>
      <p className="mt-1 text-small text-tinta-desvaida">
        Hermes / Telegram — ingreso de ideas nativo desde el bot.
      </p>
      <div className="mt-4">
        <IdeaCapturePanel auth={auth} />
      </div>
    </div>
  );
}

function AssistantSection() {
  const auth = useLocalDevAuth(true);
  return <AssistantSettingsPanel auth={auth} />;
}

/**
 * Perfil → Centro de Configuración — the configuration capabilities that have
 * NO home elsewhere in the Profile: Respaldo y restauración, Idioma/región/zona
 * horaria and Offline/dispositivo, plus the essential local readiness summary.
 *
 * The other Configuration Center cards (Identidad, IA texto y visión, Telegram,
 * Mundos, Importar mundo) are intentionally NOT duplicated here — each of those
 * already lives in a dedicated Profile tab (Asistente IA / Mundos /
 * Integraciones) or in the Profile/Taller de Mundo themselves (nav-restructure
 * decision): the idea-capture wizard (with the Telegram bot config folded in)
 * renders under Integraciones and the legacy-folder MigrationPanel under
 * Mundos. State semantics (ONB-3.1/ONB-3.5
 * anti-overstatement guard, OC19 assistant label, OC11/OC21 essential badges)
 * are reused from ConfigurationCenter.tsx so the Profile tabs and the shared
 * module never drift.
 */
function ConfigurationSection() {
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

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-small text-tinta-desvaida">
        <Spinner size="sm" /> Comprobando configuración…
      </div>
    );
  }

  if (!!error && !readiness) {
    return (
      <ErrorBanner
        message="No se pudieron cargar los estados de configuración."
        onRetry={load}
      />
    );
  }

  if (!readiness) return null;

  const cards = readiness.cards ?? {};
  const keepCards = CARD_DEFS.filter((card) =>
    ["backup", "locale", "offline"].includes(card.key),
  );

  return (
    <div className="space-y-4" aria-live="polite">
      {/* Essential local readiness (OC11/OC21) — the tab's intro block. */}
      <section
        aria-labelledby="config-readiness-title"
        className="rounded-lg border border-filio bg-madero p-4"
      >
        <div className="flex items-center justify-between gap-3">
          <h3
            id="config-readiness-title"
            className="font-heading text-body text-pergamino"
          >
            Listo para trabajar
          </h3>
        </div>
        <p className="mt-1 text-small text-tinta-desvaida">
          Capacidades esenciales locales: Mundo y editor local.
        </p>
        <div className="mt-3 flex flex-wrap gap-3">
          {ESSENTIAL_BADGES.map((badge) => {
            const meta = essentialBadgeFor(readiness, cards, badge.key);
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

      {/* Kept configuration cards — same rounded-box style as the other
          Profile sections (title row on top, content below). */}
      {keepCards.map((card) => {
        const state = cardState(cards, card.key);
        const label = cardLabel(card.key, state);
        const meta = STATE_META[state];
        return (
          <section
            key={card.key}
            aria-labelledby={`config-card-title-${card.key}`}
            className="rounded-lg border border-filio bg-madero p-4"
          >
            <div className="flex items-center justify-between gap-3">
              <h3
                id={`config-card-title-${card.key}`}
                className="font-heading text-body text-pergamino"
              >
                {card.title}
              </h3>
              <span className="flex items-center gap-2">
                <Badge variant={meta.badge}>{label}</Badge>
                <span className="sr-only">Estado: {label}</span>
              </span>
            </div>
            <p className="mt-1 text-small text-tinta-desvaida">{card.description}</p>

            {card.key === "backup" && (
              <>
                <p className="mt-3 text-small text-sombra">
                  Pendiente — contrato dedicado en definición
                </p>
                {/* ONB-4.5 (WU-4d) — Backup/restore card: entry only.
                    Google Drive / rclone backup is not implemented in
                    this change; the card stays pending and is only an
                    entry for its dedicated contract. Drive consent is
                    separate from the Google identity consent, and backup
                    and restore are distinct flows (OC10/OC24). */}
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
              </>
            )}

            {card.key === "locale" && card.action && (
              <div className="mt-3">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => navigate(card.action!.to)}
                >
                  {card.action.label}
                </Button>
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
  );
}

/**
 * Perfil → Mundos — world management: the "Zona peligrosa" delete flow and
 * the world-level recycle bin ("Papelera de mundos"). Also hosts the legacy
 * uppercase-folder migration panel (ONB-4.3, WU-4c2), relocated from the
 * standalone Centro de Configuración page (nav-restructure decision):
 * detection stays read-only and the migration only runs through the panel's
 * explicit confirm flow.
 *
 * The delete button mirrors the backend guards: it is disabled for the active
 * world (idea-capture config) and when the world is the only one left. A
 * successful delete refreshes the worlds list and bumps the trash panel's
 * refresh token so the new entry appears immediately.
 */
function WorldsSection() {
  const { worlds, isLoading, error, mutate } = useWorlds();
  const [deleteTarget, setDeleteTarget] = useState<WorldInfo | null>(null);
  const [trashRefresh, setTrashRefresh] = useState(0);
  const [activeWorld, setActiveWorld] = useState("");
  const [legacy, setLegacy] = useState<ReadinessSnapshot["legacy"]>([]);

  // The backend refuses to delete the active world; mirror that rule in the
  // UI with a disabled button + tooltip. Fail-open: if the idea-capture
  // status cannot be read, no world is treated as active.
  useEffect(() => {
    let active = true;
    void getIdeaCaptureStatus()
      .then((status) => {
        if (active) setActiveWorld(status.config.active_world ?? "");
      })
      .catch(() => {
        if (active) setActiveWorld("");
      });
    return () => {
      active = false;
    };
  }, []);

  // ONB-4.2/4.3 — read-only legacy detection: readiness is the source of
  // truth for uppercase folders; after a completed migration the panel
  // refreshes readiness so the notice disappears once the tree is canonical.
  const loadLegacy = useCallback(() => {
    void getReadiness()
      .then((readiness) => setLegacy(readiness.legacy ?? []))
      .catch(() => setLegacy([]));
  }, []);

  useEffect(loadLegacy, [loadLegacy]);

  const onlyWorld = worlds.length <= 1;

  const handleDeleted = useCallback(() => {
    void mutate();
    setTrashRefresh((n) => n + 1);
    setDeleteTarget(null);
  }, [mutate]);

  const handleTrashChanged = useCallback(() => {
    // A restore makes a world reappear; a purge only empties the trash.
    void mutate();
  }, [mutate]);

  return (
    <div>
      <h3 className="font-heading text-body text-pergamino">Mundos</h3>
      <p className="mt-1 text-small text-tinta-desvaida">
        Gestioná los mundos del taller: eliminá uno (queda recuperable 30 días en la papelera) o
        restaurá mundos eliminados.
      </p>

      {/* Zona peligrosa — 3-step confirmation before any delete. */}
      <div className="mt-4 rounded-lg border border-sangre/30 bg-sangre/10 p-4">
        <h4 className="flex items-center gap-2 font-heading text-body text-sangre">
          <Icon name="trash" size={18} />
          Zona peligrosa
        </h4>
        <p className="mt-1 text-small text-tinta-desvaida">
          Eliminar un mundo lo mueve a la papelera durante 30 días; no se destruye de inmediato.
        </p>

        {error && (
          <div
            role="alert"
            className="mt-3 rounded-lg border border-sangre/30 bg-sangre/10 px-3 py-2 text-small text-sangre"
          >
            {error.message}
          </div>
        )}

        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <Spinner size="md" />
          </div>
        ) : worlds.length === 0 ? (
          <p className="mt-3 text-small text-tinta-desvaida">No hay mundos creados todavía.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2">
            {worlds.map((world) => {
              const isActive = activeWorld.toLowerCase() === world.name.toLowerCase();
              const disabledReason = isActive
                ? "No se puede eliminar el mundo activo"
                : onlyWorld
                  ? "Debe existir al menos un mundo"
                  : null;
              return (
                <li
                  key={world.name}
                  className="flex items-center gap-3 rounded-lg border border-filio bg-cripta/50 px-3 py-2"
                >
                  <Icon name="world" size={18} className="shrink-0 text-plata" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-small text-pergamino">{world.name}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      <Badge>Lore {world.lore_count}</Badge>
                      <Badge>Personajes {world.character_count}</Badge>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={disabledReason !== null}
                    title={disabledReason ?? undefined}
                    onClick={() => setDeleteTarget(world)}
                  >
                    Borrar
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Papelera de mundos — restore / permanent delete. */}
      <div className="mt-6">
        <WorldTrashPanel refreshToken={trashRefresh} onChanged={handleTrashChanged} />
      </div>

      {/* ONB-4.2/4.3 (WU-4c2) — legacy uppercase-folder migration, relocated
          from the standalone Centro de Configuración page. Rendered only when
          readiness detected legacy folders; migration never runs automatically
          and always requires the panel's explicit confirm flow. */}
      {legacy.length > 0 && (
        <div className="mt-6">
          <MigrationPanel findings={legacy} onMigrated={loadLegacy} />
        </div>
      )}

      {deleteTarget && (
        <DeleteWorldModal
          world={deleteTarget}
          onDeleted={handleDeleted}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}

/**
 * Profile page (`/perfil`) — the unified configuration surface.
 *
 * Sections: Sesión de edición (local-dev auth, same controls as the Navbar
 * dropdown), Centro de Configuración (configuration capabilities without a
 * Profile home: backup, locale, offline + essential readiness), Integraciones
 * (idea-capture wizard — the single Telegram surface, ONB-3.3), Asistente IA
 * (assistant settings) and Mundos (world delete + recycle bin + legacy-folder
 * migration, ONB-4.3). The whole page sits behind the same local-dev auth
 * boundary as wiki editing.
 */
export default function ProfilePage() {
  const { worlds } = useWorlds();
  const [section, setSection] = useState<ProfileSection>("sesion");

  const tabs: { id: ProfileSection; label: string }[] = [
    { id: "sesion", label: "Sesión de edición" },
    { id: "configuracion", label: "Centro de Configuración" },
    { id: "integraciones", label: "Integraciones" },
    { id: "asistente", label: "Asistente IA" },
    { id: "mundos", label: "Mundos" },
  ];

  return (
    <div className="flex min-h-screen flex-col bg-cripta">
      <Navbar worlds={worlds} />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
        <h1 className="font-heading text-h3 text-pergamino">Perfil</h1>
        <div className="mt-6 flex flex-col gap-6 md:flex-row">
          <nav
            aria-label="Secciones del perfil"
            className="flex gap-1 md:w-56 md:flex-col md:gap-1"
          >
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setSection(tab.id)}
                aria-current={section === tab.id ? "page" : undefined}
                className={cn(
                  "rounded-lg px-3 py-2 text-left text-body transition-colors",
                  section === tab.id
                    ? "bg-piedra text-pergamino"
                    : "text-tinta-desvaida hover:bg-madero hover:text-pergamino",
                )}
              >
                {tab.label}
              </button>
            ))}
          </nav>
          <section className="min-w-0 flex-1">
            {section === "sesion" ? (
              <SessionSection />
            ) : section === "configuracion" ? (
              <ConfigurationSection />
            ) : section === "integraciones" ? (
              <IntegrationsSection />
            ) : section === "mundos" ? (
              <WorldsSection />
            ) : (
              <AssistantSection />
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
