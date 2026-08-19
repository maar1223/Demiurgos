import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "@/components/atoms/Icon";
import { WorldSelector } from "@/components/molecules/WorldSelector";
import { CreateWorldModal } from "@/components/organisms/CreateWorldModal";
import { ConfirmDialog } from "@/components/organisms/ConfirmDialog";
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
  const [sessionActionLoading, setSessionActionLoading] = useState(false);
  const [sessionActionError, setSessionActionError] = useState<string | null>(null);
  const { status, isLoading: sessionLoading, error: sessionError, start, logout } =
    useLocalDevAuth(profileOpen);

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
  };

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
          role="dialog"
          aria-label="Perfil"
          className="absolute right-4 top-16 z-50 w-72 rounded-lg border border-filio bg-madero p-4 shadow-xl"
        >
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-heading text-body text-pergamino">Sesión de edición</h2>
            <span className="text-small text-tinta-desvaida">Local</span>
          </div>

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
    </header>
  );
}
