import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { WorldSelector } from "@/components/molecules/WorldSelector";
import { CreateWorldModal } from "@/components/organisms/CreateWorldModal";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
import { getAuthStatus, logoutSession, systemControlAction } from "@/api/wiki";
import { ApiError, type AuthSessionStatus } from "@/api/types";
import { reloadPage } from "@/lib/reloadPage";
import type { WorldInfo } from "@/api/types";
import {
  GENERIC_TEASER_LABEL,
  NAV_LINKS,
  PLACEHOLDER_TOAST,
  ROUTES,
  type NavLink,
} from "@/lib/constants";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";
import { useCurrentWorld } from "@/hooks/useCurrentWorld";
import { setCurrentWorld } from "@/lib/currentWorld";

interface NavbarProps {
  worlds: WorldInfo[];
  currentWorld?: string;
  onWorldChange?: (world: string) => void;
}

/**
 * Global navigation header: logo, world selector, nav links, avatar.
 * Renders on all pages. Collapses nav links on mobile.
 *
 * Workshop-nav contract: `available` links navigate to the Core workshops;
 * `teaser` links are non-actionable future/paid surfaces. The single generic
 * teaser (label "Próximamente") is never routable; the redundant badge is
 * suppressed when the label already says "Próximamente". Rightmost-marked
 * links (Taller de Publicación, when enabled) always render last.
 *
 * World creation: Navbar hosts the `+ Nuevo mundo` flow. Worlds are kept in
 * local state so a successful creation appears in the selector immediately;
 * the existing switch-confirm flow takes over for the optional
 * "¿Cambiar a {nombre}?" handoff.
 */
export function Navbar({ worlds: worldsProp, currentWorld, onWorldChange }: NavbarProps) {
  const navigate = useNavigate();
  const { world: activeWorld } = useCurrentWorld();
  const resolvedWorld = currentWorld ?? activeWorld ?? undefined;
  const [worlds, setWorlds] = useState<WorldInfo[]>(worldsProp);
  const [creatingWorld, setCreatingWorld] = useState(false);
  const [pendingSwitch, setPendingSwitch] = useState<string | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);
  const avatarRef = useRef<HTMLButtonElement>(null);
  const [sessionActionLoading, setSessionActionLoading] = useState(false);
  const [sessionActionError, setSessionActionError] = useState<string | null>(null);
  const [systemAction, setSystemAction] = useState<"restart" | "shutdown" | "logout" | null>(null);
  const [systemBusy, setSystemBusy] = useState(false);
  const [systemError, setSystemError] = useState<string | null>(null);
  const [systemNotice, setSystemNotice] = useState<string | null>(null);
  // Full-screen transition state: after a confirmed restart/shutdown we leave
  // the profile dialog and show a blocking overlay until the server is back
  // (restart) or confirmed off (shutdown → "off" final state).
  const [transition, setTransition] = useState<"restarting" | "shuttingDown" | "off" | null>(null);
  const restartTimerRef = useRef<number | null>(null);

  // After a restart the backend goes down and comes back. Poll a lightweight
  // endpoint until it responds, then reload the page automatically so the user
  // never has to think about manually refreshing (S-3.x UX).
  useEffect(() => {
    if (transition !== "restarting") return;
    let attempts = 0;
    restartTimerRef.current = window.setInterval(async () => {
      attempts += 1;
      try {
        await getAuthStatus();
        if (restartTimerRef.current) window.clearInterval(restartTimerRef.current);
        reloadPage();
      } catch {
        if (attempts > 30) {
          if (restartTimerRef.current) window.clearInterval(restartTimerRef.current);
          setTransition(null);
          setSystemNotice(
            "El servidor no respondió. Arráncalo de nuevo o recarga la página.",
          );
        }
      }
    }, 2000);
    return () => {
      if (restartTimerRef.current) window.clearInterval(restartTimerRef.current);
    };
  }, [transition]);

  // After a shutdown the backend goes down. Poll until it stops responding,
  // then switch the overlay to a clear "it's off now" state so the user gets
  // feedback even if the frontend process itself keeps running.
  useEffect(() => {
    if (transition !== "shuttingDown") return;
    let attempts = 0;
    const timer = window.setInterval(async () => {
      attempts += 1;
      try {
        await getAuthStatus();
        // Still up: keep waiting (shutdown may still be in progress).
      } catch {
        // Backend is down → it shut down. Show the final off state.
        window.clearInterval(timer);
        setTransition("off");
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [transition]);
  const { status, isLoading: sessionLoading, error: sessionError, start, logout } =
    useLocalDevAuth(profileOpen);

  // Unified session status (credentials vault mode, R-VC-01): when the vault is
  // active the credentials session is the ONE authoritative login, so the
  // profile panel (status, logout, system controls) must follow it — not the
  // secondary local-dev session. Falls back to local-dev when not credentials.
  const [vaultStatus, setVaultStatus] = useState<AuthSessionStatus | null>(null);
  const [vaultLoading, setVaultLoading] = useState(false);
  const [vaultError, setVaultError] = useState<Error | null>(null);

  useEffect(() => {
    if (!profileOpen) return;
    let active = true;
    setVaultLoading(true);
    setVaultError(null);
    void getAuthStatus()
      .then((next) => {
        if (active) setVaultStatus(next);
      })
      .catch((cause: unknown) => {
        if (active) {
          setVaultError(
            cause instanceof Error ? cause : new Error("No se pudo consultar la sesión"),
          );
        }
      })
      .finally(() => {
        if (active) setVaultLoading(false);
      });
    return () => {
      active = false;
    };
  }, [profileOpen]);

  // Keep the local worlds list in sync with the parent prop. `useState`
  // initialization alone would freeze the list at first render — on a hard
  // reload SWR still has `worldsProp === []` while fetching, so without this
  // sync the selector would stay empty forever (both the world list and the
  // `+ Nuevo mundo` entry). Appends from `handleWorldCreated` are preserved
  // because the refreshed prop includes the newly-created world.
  useEffect(() => {
    setWorlds(worldsProp);
  }, [worldsProp]);

  const handleWorldCreated = (world: WorldInfo) => {
    setWorlds((prev) => (prev.some((w) => w.name === world.name) ? prev : [...prev, world]));
    setCreatingWorld(false);
    setPendingSwitch(world.name);
  };

  const confirmSwitch = () => {
    if (!pendingSwitch) return;
    setCurrentWorld(pendingSwitch);
    onWorldChange?.(pendingSwitch);
    setPendingSwitch(null);
  };

  // Taller de Publicación (rightmost) always renders last — never hidden
  // behind future teasers regardless of the constant ordering.
  const navLinks = [
    ...NAV_LINKS.filter((link) => !link.rightmost),
    ...NAV_LINKS.filter((link) => link.rightmost),
  ];

  const isTeaser = (link: NavLink) => link.availability !== "available";

  const handleNavClick = (link: NavLink) => {
    if (isTeaser(link)) {
      alert(PLACEHOLDER_TOAST);
      return;
    }
    setMobileMenuOpen(false);
    // With an active world, "Taller de Mundo" jumps straight into that world's
    // wiki workspace; otherwise it lands on the world-selection surface.
    if (link.to === ROUTES.TALLER_MUNDO && activeWorld) {
      navigate(`/wiki/${encodeURIComponent(activeWorld)}`);
      return;
    }
    navigate(link.to);
  };

  const handleAvatarClick = () => {
    setProfileOpen((open) => !open);
    setSessionActionError(null);
    setSystemNotice(null);
  };

  // Close the profile dropdown when clicking anywhere outside it (or the
  // avatar button), so the panel doesn't linger on screen. Ignoring the avatar
  // keeps toggling via the button working.
  useEffect(() => {
    if (!profileOpen) return;
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (profileRef.current?.contains(target)) return;
      if (avatarRef.current?.contains(target)) return;
      setProfileOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [profileOpen]);

  const handleSessionAction = async () => {
    setSessionActionLoading(true);
    setSessionActionError(null);
    try {
      if (status?.authenticated) {
        await logout();
      } else {
        await start();
      }
    } catch (cause: unknown) {
      setSessionActionError(
        cause instanceof Error ? cause.message : "No se pudo actualizar la sesión local",
      );
    } finally {
      setSessionActionLoading(false);
    }
  };

  /** Log out of the credentials vault session (authoritative when the vault
   *  is active). Clears the session cookie and reloads so the AuthGate shows
   *  the login again. */
  /** Opens the confirm dialog for a session/system operation (fresh error). */
  const handleSystemRequest = (action: "restart" | "shutdown" | "logout") => {
    setSystemError(null);
    setSystemNotice(null);
    setSystemAction(action);
  };

  /** Cancel/close must stop the busy state — never leave the dialog stuck. */
  const handleSystemClose = () => {
    setSystemAction(null);
    setSystemBusy(false);
    setSystemError(null);
  };

  const handleSystemConfirm = async (action: "restart" | "shutdown" | "logout") => {
    setSystemBusy(true);
    setSystemError(null);
    try {
      // Log out of the vault session: clears the session and reloads to the
      // login screen. The server keeps running; the bot keeps receiving ideas.
      if (action === "logout") {
        await logoutSession();
        reloadPage();
        return;
      }

      // Restart/shutdown. A dropped connection (status 0) means the launcher
      // killed uvicorn mid-POST, which is the EXPECTED outcome — treat it as
      // success. Any other error (401/500/spawn) keeps the dialog open with
      // the message so the user can retry or close.
      try {
        await systemControlAction(action);
      } catch (cause: unknown) {
        if (!(cause instanceof ApiError && cause.status === 0)) {
          setSystemError(
            cause instanceof Error ? cause.message : "No se pudo completar la operación",
          );
          return;
        }
      }
      // Success: close the dialog and show a blocking screen. On restart the
      // polling effect reloads the page automatically once the server is back.
      setSystemAction(null);
      setSystemBusy(false);
      setTransition(action === "restart" ? "restarting" : "shuttingDown");
    } catch (cause: unknown) {
      setSystemError(
        cause instanceof Error ? cause.message : "No se pudo completar la operación",
      );
    } finally {
      setSystemBusy(false);
    }
  };

  return (
    <header className="sticky top-0 z-50 border-b border-filio bg-cripta/95 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        {/* Left: Logo */}
        <button
          type="button"
          onClick={() => navigate("/wiki")}
          className="flex items-center gap-2 text-llamita hover:text-llama-alta transition-colors"
        >
          <Icon name="demiurgos" size={28} />
          <span className="hidden font-heading text-h4 text-pergamino sm:inline">
            Demiurgos
          </span>
        </button>

        {/* Center: Nav links (desktop) */}
        <nav aria-label="Navegación principal" className="hidden items-center gap-1 md:flex">
          {navLinks.map((link) => (
            <button
              key={link.label}
              type="button"
              onClick={() => handleNavClick(link)}
              className={`rounded-lg px-3 py-1.5 text-small transition-colors ${
                isTeaser(link)
                  ? "text-sombra cursor-pointer hover:text-pergamino hover:bg-piedra"
                  : "text-pergamino hover:bg-piedra"
              }`}
            >
              {link.label}
              {isTeaser(link) && link.label !== GENERIC_TEASER_LABEL && (
                <span
                  aria-hidden="true"
                  className="ml-1.5 rounded-full bg-filio px-1.5 py-0.5 align-middle text-[10px] uppercase tracking-wide text-tinta-desvaida"
                >
                  Próximamente
                </span>
              )}
            </button>
          ))}
        </nav>

        {/* Right: World selector, avatar */}
        <div className="flex items-center gap-2">
          <WorldSelector
            worlds={worlds}
            currentWorld={resolvedWorld}
            onWorldChange={onWorldChange}
            onRequestCreate={() => setCreatingWorld(true)}
          />

          {/* Avatar */}
          <button
            type="button"
            ref={avatarRef}
            onClick={handleAvatarClick}
            aria-label="Perfil"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-filio text-plata transition-colors hover:bg-piedra hover:text-pergamino"
          >
            <Icon name="avatar" size={18} />
          </button>

          {/* Mobile menu toggle */}
          <button
            type="button"
            onClick={() => setMobileMenuOpen((prev) => !prev)}
            className="flex items-center justify-center rounded-lg p-1.5 text-plata hover:bg-piedra md:hidden"
          >
            <Icon name={mobileMenuOpen ? "close" : "menu"} size={20} />
          </button>
        </div>
      </div>

      {profileOpen && (
        <div
          ref={profileRef}
          role="dialog"
          aria-label="Perfil"
          className="absolute right-4 top-16 z-50 w-72 rounded-lg border border-filio bg-madero p-4 shadow-xl"
        >
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-heading text-body text-pergamino">Sesión de edición</h2>
            <span className="text-small text-tinta-desvaida">
              {vaultStatus?.mode === "credentials" ? "Credenciales" : "Local"}
            </span>
          </div>

          {vaultStatus?.mode === "credentials" ? (
            /* Credentials vault session is the single authoritative login
               (R-VC-01): the panel follows it, not the secondary local-dev one. */
            vaultLoading ? (
              <p className="mt-3 text-small text-tinta-desvaida">Comprobando sesión...</p>
            ) : vaultError ? (
              <p className="mt-3 text-small text-sangre">{vaultError.message}</p>
            ) : vaultStatus.authenticated ? (
              <>
                <p className="mt-3 text-small text-musgo">Sesión activa</p>
                <p className="mt-1 text-small text-tinta-desvaida">{vaultStatus.label}</p>
                 <button
                   type="button"
                   onClick={() => void handleSystemRequest("logout")}
                   disabled={systemBusy}
                   className="mt-3 w-full rounded-lg bg-piedra px-3 py-2 text-small text-pergamino hover:bg-filio disabled:opacity-60"
                 >
                   {systemBusy ? "Cerrando..." : "Cerrar sesión"}
                 </button>
               </>
             ) : (
               <p className="mt-3 text-small text-tinta-desvaida">
                 No hay una sesión de cuenta activa.
              </p>
            )
          ) : (
            <>
              {sessionLoading && (
                <p className="mt-3 text-small text-tinta-desvaida">Comprobando sesión local...</p>
              )}
              {sessionError && (
                <p className="mt-3 text-small text-sangre">{sessionError.message}</p>
              )}
              {!sessionLoading && !sessionError && status?.authenticated && (
                <>
                  <p className="mt-3 text-small text-musgo">Sesión local activa</p>
                  <p className="mt-1 text-small text-tinta-desvaida">{status.label}</p>
                  <button
                    type="button"
                    onClick={() => void handleSessionAction()}
                    disabled={sessionActionLoading}
                    className="mt-3 w-full rounded-lg bg-piedra px-3 py-2 text-small text-pergamino hover:bg-filio disabled:opacity-60"
                  >
                    {sessionActionLoading ? "Cerrando..." : "Cerrar sesión local"}
                  </button>
                </>
              )}
              {!sessionLoading && !sessionError && status && !status.authenticated && status.enabled && (
                <>
                  <p className="mt-3 text-small text-tinta-desvaida">Sesión local no iniciada.</p>
                  <button
                    type="button"
                    onClick={() => void handleSessionAction()}
                    disabled={sessionActionLoading}
                    className="mt-3 w-full rounded-lg bg-llamita px-3 py-2 text-small text-cripta hover:bg-llama-alta disabled:opacity-60"
                  >
                    {sessionActionLoading ? "Iniciando..." : "Iniciar sesión local"}
                  </button>
                </>
              )}
              {!sessionLoading && !sessionError && status && !status.enabled && (
                <p className="mt-3 text-small text-tinta-desvaida">
                  Autenticación local desactivada. Activa DEMIURGOS_AUTH_MODE=local-dev para probar la edición.
                </p>
              )}
            </>
          )}

          {sessionActionError && (
            <p className="mt-3 text-small text-sangre">{sessionActionError}</p>
          )}

          <button
            type="button"
            onClick={() => {
              setProfileOpen(false);
              navigate("/perfil");
            }}
            className="mt-3 w-full rounded-lg bg-piedra px-3 py-2 text-small text-pergamino hover:bg-filio"
          >
            Perfil completo
          </button>

          {/* System-control zone — restart/shutdown of the whole stack. Available
              with ANY active session (credentials vault OR local-dev), so the
              vault login alone is enough to restart/shut down. */}
          {(vaultStatus?.mode === "credentials"
            ? vaultStatus.authenticated
            : status?.authenticated) && (
            <>
              <hr className="my-3 border-filio" />
              <div className="mt-1 space-y-2">
                <button
                  type="button"
                  onClick={() => handleSystemRequest("restart")}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-piedra px-3 py-2 text-small text-pergamino hover:bg-filio"
                >
                  <Icon name="refresh" size={16} />
                  Reiniciar Demiurgos
                </button>
                <button
                  type="button"
                  onClick={() => handleSystemRequest("shutdown")}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-piedra px-3 py-2 text-small text-sangre hover:bg-filio"
                >
                  <Icon name="power" size={16} />
                  Apagar Demiurgos
                </button>
                {systemNotice && (
                  <p className="text-small text-musgo">{systemNotice}</p>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* Mobile nav menu */}
      {mobileMenuOpen && (
        <div className="border-t border-filio bg-madero md:hidden">
          <nav aria-label="Navegación móvil" className="flex flex-col gap-1 px-4 py-3">
            {navLinks.map((link) => (
              <button
                key={link.label}
                type="button"
                onClick={() => handleNavClick(link)}
                className={`rounded-lg px-3 py-2 text-left text-body transition-colors ${
                  isTeaser(link)
                    ? "text-sombra hover:text-pergamino hover:bg-piedra"
                    : "text-pergamino hover:bg-piedra"
                }`}
              >
                {link.label}
                {isTeaser(link) && link.label !== GENERIC_TEASER_LABEL && (
                  <span
                    aria-hidden="true"
                    className="ml-1.5 rounded-full bg-filio px-1.5 py-0.5 align-middle text-[10px] uppercase tracking-wide text-tinta-desvaida"
                  >
                    Próximamente
                  </span>
                )}
              </button>
            ))}
          </nav>
        </div>
      )}

      {/* World creation modal — opened from the WorldSelector's
          `+ Nuevo mundo` entry. Parent-rendered so the modal lifecycle stays
          explicit and the dropdown remains closed underneath. */}
      <CreateWorldModal
        isOpen={creatingWorld}
        onClose={() => setCreatingWorld(false)}
        onCreated={handleWorldCreated}
      />

      {/* Post-creation switch confirmation. Reuses the existing
          ConfirmDialog pattern so the user can decline switching to the
          newly-created world without losing it. */}
      {pendingSwitch && (
        <ConfirmDialog
          title="Cambiar mundo activo"
          message={`¿Querés cambiar el mundo activo a «${pendingSwitch}»?`}
          confirmLabel="Cambiar"
          onConfirm={confirmSwitch}
          onClose={() => setPendingSwitch(null)}
        />
      )}

      {/* System restart/shutdown confirmation. `isBusy` disables the actions
          while logout + POST are in flight; `error` surfaces connection-lost
          and launcher failures. Close (X/Escape/overlay) always resets the
          busy state. */}
       {systemAction && (
         <ConfirmDialog
           title={
             systemAction === "restart"
               ? "Reiniciar Demiurgos"
               : systemAction === "shutdown"
                 ? "Apagar Demiurgos"
                 : "Cerrar sesión"
           }
           message={
             systemAction === "restart"
               ? "La conexión se cortará y la página quedará en blanco por unos segundos. Cuando el servidor vuelva, la página se recargará automáticamente; tu sesión se conserva."
               : systemAction === "shutdown"
                 ? "El servidor se detendrá y el bot dejará de recibir ideas. Para volver a usarlo, arráncalo de nuevo; tu sesión se conserva."
                 : "Cerrar la sesión deja el servidor y el bot corriendo; puedes volver a entrar cuando quieras."
           }
           confirmLabel={
             systemAction === "restart"
               ? "Reiniciar"
               : systemAction === "shutdown"
                 ? "Apagar"
                 : "Cerrar sesión"
           }
           isBusy={systemBusy}
           error={systemError}
           onConfirm={() => void handleSystemConfirm(systemAction)}
           onClose={handleSystemClose}
         />
       )}

      {transition &&
        createPortal(
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-cripta/90 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-3 px-6 text-center">
              {transition !== "off" && <Spinner size="lg" />}
              <p className="text-body text-pergamino">
                {transition === "restarting"
                  ? "Reiniciando Demiurgos…"
                  : transition === "shuttingDown"
                    ? "Apagando Demiurgos…"
                    : "Demiurgos se apagó"}
              </p>
              <p className="max-w-sm text-small text-tinta-desvaida">
                {transition === "restarting"
                  ? "El servidor se está reiniciando. La página se recargará automáticamente cuando vuelva; tu sesión se conserva."
                  : transition === "shuttingDown"
                    ? "El servidor se está apagando. Cuando termine, la pantalla lo confirmará; tu sesión se conserva."
                    : "La aplicación se detuvo por completo. Arráncalo de nuevo para volver a usarla; tu sesión se conserva."}
              </p>
            </div>
          </div>,
          document.body,
        )}
    </header>
  );
}
