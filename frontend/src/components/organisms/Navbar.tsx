import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { WorldSelector } from "@/components/molecules/WorldSelector";
import type { WorldInfo } from "@/api/types";
import { NAV_LINKS, PLACEHOLDER_TOAST, AI_PLACEHOLDER_TOAST } from "@/lib/constants";

interface NavbarProps {
  worlds: WorldInfo[];
  currentWorld?: string;
  onWorldChange?: (world: string) => void;
}

/**
 * Global navigation header: logo, world selector, nav links, Asistente IA, avatar.
 * Renders on all pages. Collapses nav links on mobile.
 */
export function Navbar({ worlds, currentWorld, onWorldChange }: NavbarProps) {
  const navigate = useNavigate();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const handleNavClick = (to: string, active: boolean) => {
    if (!active) {
      alert(PLACEHOLDER_TOAST);
      return;
    }
    setMobileMenuOpen(false);
    navigate(to);
  };

  const handleAIClick = () => {
    alert(AI_PLACEHOLDER_TOAST);
  };

  const handleAvatarClick = () => {
    alert("Perfil — próximamente");
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

        {/* Right: World selector, AI button, avatar */}
        <div className="flex items-center gap-2">
          {/* World selector (extracted to WorldSelector molecule) */}
          <WorldSelector
            worlds={worlds}
            currentWorld={currentWorld}
            onWorldChange={onWorldChange}
          />

          {/* Asistente IA button (desktop) */}
          <Button
            variant="secondary"
            size="sm"
            onClick={handleAIClick}
            className="hidden md:inline-flex"
          >
            <Icon name="lightbulb" size={14} />
            Asistente IA
          </Button>

          {/* Avatar */}
          <button
            type="button"
            onClick={handleAvatarClick}
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
            <hr className="my-2 border-filio" />
            <button
              type="button"
              onClick={handleAIClick}
              className="flex items-center gap-2 rounded-lg px-3 py-2 text-body text-pergamino hover:bg-piedra"
            >
              <Icon name="lightbulb" size={16} />
              Asistente IA
            </button>
          </nav>
        </div>
      )}
    </header>
  );
}
