import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "@/components/atoms/Icon";
import { WorldSelector } from "@/components/molecules/WorldSelector";
import type { WorldInfo } from "@/api/types";
import { NAV_LINKS, PLACEHOLDER_TOAST } from "@/lib/constants";
import { useLocalDevAuth } from "@/hooks/useLocalDevAuth";

interface NavbarProps {
  worlds: WorldInfo[];
  currentWorld?: string;
  onWorldChange?: (world: string) => void;
}

/**
 * Global navigation header: logo, world selector, nav links, avatar.
 * Renders on all pages. Collapses nav links on mobile.
 */
export function Navbar({ worlds, currentWorld, onWorldChange }: NavbarProps) {
  const navigate = useNavigate();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [sessionActionLoading, setSessionActionLoading] = useState(false);
  const [sessionActionError, setSessionActionError] = useState<string | null>(null);
  const { status, isLoading: sessionLoading, error: sessionError, start, logout } =
    useLocalDevAuth(profileOpen);

  const handleNavClick = (to: string, active: boolean) => {
    if (!active) {
      alert(PLACEHOLDER_TOAST);
      return;
    }
    setMobileMenuOpen(false);
    navigate(to);
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
        <nav className="hidden items-center gap-1 md:flex">
          {NAV_LINKS.map((link) => (
            <button
              key={link.label}
              type="button"
              onClick={() => handleNavClick(link.to, link.active)}
              className={`rounded-lg px-3 py-1.5 text-small transition-colors ${
                link.active
                  ? "text-pergamino hover:bg-piedra"
                  : "text-sombra cursor-pointer hover:text-pergamino hover:bg-piedra"
              }`}
            >
              {link.label}
            </button>
          ))}
        </nav>

        {/* Right: World selector, avatar */}
        <div className="flex items-center gap-2">
          <WorldSelector
            worlds={worlds}
            currentWorld={currentWorld}
            onWorldChange={onWorldChange}
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
          <nav className="flex flex-col gap-1 px-4 py-3">
            {NAV_LINKS.map((link) => (
              <button
                key={link.label}
                type="button"
                onClick={() => handleNavClick(link.to, link.active)}
                className={`rounded-lg px-3 py-2 text-left text-body transition-colors ${
                  link.active
                    ? "text-pergamino hover:bg-piedra"
                    : "text-sombra hover:text-pergamino hover:bg-piedra"
                }`}
              >
                {link.label}
              </button>
            ))}
          </nav>
        </div>
      )}
    </header>
  );
}
