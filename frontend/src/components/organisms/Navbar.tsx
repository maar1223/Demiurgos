import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { Icon, type IconName } from "@/components/atoms/Icon";
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
import { useTheme } from "@/hooks/useTheme";
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
  // Brand theme: resolvedTheme drives the wordmark/favicon and the toggle
  // (Light ↔ Dark). The system color-scheme is used only as the internal
  // initial/default; it is no longer a user-selectable mode. Once the user
  // picks either light or dark, the choice is persisted and "system" is gone.
  const { resolvedTheme, setTheme } = useTheme();
  const cycleTheme = () => {
    setTheme(resolvedTheme === "dark" ? "light" : "dark");
  };
  const themeIcon: IconName = resolvedTheme === "dark" ? "moon" : "sun";
  const themeLabel = `Tema: ${resolvedTheme === "dark" ? "oscuro" : "claro"}`;
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
  const navLinks = useMemo(
    () => [
      ...NAV_LINKS.filter((link) => !link.rightmost),
      ...NAV_LINKS.filter((link) => link.rightmost),
    ],
    [],
  );

  const isTeaser = (link: NavLink) => link.availability !== "available";

  // @skip-delegate — local, small, already-understood nav display logic.
  // Active workshop = the current route, or the wiki workspace when viewing a
  // world (Taller de Mundo owns it). Teasers are never active.
  const { pathname } = useLocation();
  const activePath = (() => {
    const direct = navLinks.find(
      (link) => !isTeaser(link) && link.to !== ROUTES.TALLER_MUNDO && pathname === link.to,
    );
    if (direct) return direct.to;
    if (pathname.startsWith("/wiki/") || pathname === ROUTES.TALLER_MUNDO) {
      return ROUTES.TALLER_MUNDO;
    }
    if (pathname === ROUTES.TALLER_HERRAMIENTAS) return ROUTES.TALLER_HERRAMIENTAS;
    if (pathname === ROUTES.IDEAS) return ROUTES.IDEAS;
    return null;
  })();

  // Sliding CTA indicator ("deck of cards" sweep). The pill is absolutely
  // positioned behind the active link and travels SMOOTHLY (continuous
  // interpolation, like liquid filling a bottle) from its current card across
  // the intermediate cards to land under the destination. Navigation itself is
  // instant — only the highlight glides. Only runs on desktop nav (md:flex).
  const navRef = useRef<HTMLElement>(null);
  const linkRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const sweepRafRef = useRef<number | null>(null);
  const [pill, setPill] = useState<{ left: number; width: number; visible: boolean }>({
    left: 0,
    width: 0,
    visible: false,
  });
  // Path of the intermediate card currently being "crossed" by the pill, so
  // it can glow while the highlight passes over it.
  const [sweepPath, setSweepPath] = useState<string | null>(null);

  // activePath must be read from a ref by the STABLE snapPill (see below) so
  // the mount/resize effect never re-runs on route change.
  const activePathRef = useRef<string | null>(activePath);
  useEffect(() => {
    activePathRef.current = activePath;
  }, [activePath]);
  // Latest pill position kept in a ref so the stable sweep callback can read it
  // without re-creating itself on every animation frame.
  const pillRef = useRef(pill);
  useEffect(() => {
    pillRef.current = pill;
  }, [pill]);

  /** Snap the pill under the current card without animating. Identity-stable:
   *  only ever triggered by mount/resize/fonts, NEVER by a route change. */
  const snapPill = useCallback(() => {
    const navEl = navRef.current;
    const path = activePathRef.current;
    if (!navEl || !path) return;
    const btn = linkRefs.current[path];
    if (!btn) return;
    const navBox = navEl.getBoundingClientRect();
    const box = btn.getBoundingClientRect();
    setPill({ left: box.left - navBox.left, width: box.width, visible: true });
  }, []);

  /** Glide the highlight card → card in ONE continuous motion, in the
   *  direction of the clicked card. It lights each intermediate card as it
   *  passes and lands on the target. A single global easing (no per-segment
   *  deceleration) keeps the motion fluid — it never stops at an intermediate
   *  card. Identity-stable: reads active path + pill position from refs. */
  const sweepToActive = useCallback(() => {
    const navEl = navRef.current;
    const target = activePathRef.current;
    if (!navEl || !target) return;
    const destBtn = linkRefs.current[target];
    if (!destBtn) return;
    const navBox = navEl.getBoundingClientRect();
    const toLeft = destBtn.getBoundingClientRect().left - navBox.left;
    const toWidth = destBtn.getBoundingClientRect().width;

    // Non-teaser cards in DOM order.
    const cards: { left: number; width: number; path: string }[] = [];
    for (const link of navLinks) {
      if (isTeaser(link)) continue;
      const btn = linkRefs.current[link.to];
      if (!btn) continue;
      const box = btn.getBoundingClientRect();
      cards.push({ left: box.left - navBox.left, width: box.width, path: link.to });
    }

    // Origin = card whose center is closest to the current pill position.
    const from = pillRef.current;
    const originIndex = cards.reduce(
      (best, c, i) =>
        Math.abs(c.left - from.left) < Math.abs(cards[best].left - from.left) ? i : best,
      0,
    );
    const destIndex = cards.findIndex((c) => c.path === target);
    if (originIndex < 0 || destIndex < 0) {
      setPill({ left: toLeft, width: toWidth, visible: true });
      setSweepPath(null);
      return;
    }
    // Ordered route origin → destination (inclusive), no duplicates.
    const step = destIndex >= originIndex ? 1 : -1;
    const route: number[] = [];
    for (let i = originIndex; step === 1 ? i <= destIndex : i >= destIndex; i += step) {
      route.push(i);
    }
    const path = route.map((i) => ({ left: cards[i].left, width: cards[i].width }));

    // jsdom/hidden nav has no real layout → ≤1 point or zero-size cards; snap.
    if (path.length < 2 || path.some((p) => Math.abs(p.left) < 0.001 && Math.abs(p.width) < 0.001)) {
      setPill({ left: toLeft, width: toWidth, visible: true });
      setSweepPath(null);
      return;
    }

    // ONE fluid motion across the whole route. Progress `t` is eased globally
    // (easeOutCubic) and mapped across the ordered waypoints, so the highlight
    // sweeps card → card but NEVER decelerates mid-route — it only slows at
    // the very end. Each intermediate card is lit while the highlight is over
    // its center; the target becomes the filled CTA pill on arrival.
    const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);
    const DURATION = 380; // total glide — smooth, no perceptible pause at cards
    const segCount = path.length - 1;
    if (sweepRafRef.current) cancelAnimationFrame(sweepRafRef.current);
    if (segCount <= 0) {
      setPill({ left: toLeft, width: toWidth, visible: true });
      setSweepPath(null);
      return;
    }

    const start = performance.now();
    const tick = (now: number) => {
      const raw = Math.min((now - start) / DURATION, 1);
      const t = easeOutCubic(raw);
      // Map global progress onto the ordered path. Clamp `seg` to [0, segCount-1]
      // and clamp `local` to [0,1] so the final point is always read safely.
      const scale = t * segCount;
      const seg = Math.max(0, Math.min(Math.floor(scale), segCount - 1));
      const local = Math.max(0, Math.min(scale - seg, 1));
      const a = path[seg];
      const b = path[seg + 1] ?? a;
      const left = a.left + (b.left - a.left) * local;
      const width = a.width + (b.width - a.width) * local;
      setPill({ left, width, visible: true });
      // Light the card we are currently over, unless it is the target.
      const overCard = cards.find(
        (c) => Math.abs(left - c.left) < 1 && c.path !== target,
      );
      setSweepPath(overCard ? overCard.path : null);
      if (raw < 1) {
        sweepRafRef.current = requestAnimationFrame(tick);
      } else {
        setSweepPath(null);
      }
    };
    sweepRafRef.current = requestAnimationFrame(tick);
  }, [navLinks, isTeaser]);

  // On mount + resize (STABLE, runs once): snap into place. A hard reload
  // (Ctrl+Shift+R) forces webfonts to re-download, so the text reflows AFTER
  // first paint and the pill (measured with fallback-font metrics) lands
  // misaligned. Re-measuring once document.fonts.ready resolves fixes it.
  useEffect(() => {
    snapPill();
    window.addEventListener("resize", snapPill);
    const fonts = (document as Document).fonts;
    fonts?.ready?.then(() => snapPill()).catch(() => undefined);
    return () => {
      window.removeEventListener("resize", snapPill);
    };
  }, [snapPill]);

  // On a real activePath change (after mount), glide the highlight. This is
  // the ONLY thing that reacts to route changes — snapPill never does.
  // We defer the glide by two frames (double requestAnimationFrame) so the
  // destination page's layout is painted and settle before we measure the card
  // positions — otherwise navigating to a world route measures the nav while
  // its DOM is still mid-transition, yielding stale / zero-size bounding boxes.
  const prevActive = useRef<string | null>(null);
  const mountedRef = useRef(false);
  useEffect(() => {
    // Skip the very FIRST run: snapPill already placed the highlight on mount
    // (or kept it hidden when there is no active taller). Using a dedicated
    // `mountedRef` (never `prevActive === null`) is essential: `activePath` is
    // ALSO `null` on routes with no active taller (e.g. /perfil), so a null-guard
    // would swallow the FIRST navigation out of such a route and leave the
    // highlight stuck on the wrong taller card.
    if (!mountedRef.current) {
      mountedRef.current = true;
      prevActive.current = activePath;
      return;
    }
    // Leaving to a route with no active taller: hide the highlight so it never
    // lingers on a stale workshop card (e.g. /perfil).
    if (activePath === null) {
      setPill((p) => (p.visible ? { ...p, visible: false } : p));
      prevActive.current = null;
      return;
    }
    if (prevActive.current !== activePath) {
      prevActive.current = activePath;
      // Defer measurement until the destination layout is painted.
      requestAnimationFrame(() => {
        sweepRafRef.current = requestAnimationFrame(() => sweepToActive());
      });
    }
  }, [activePath, sweepToActive]);

  // Clean up any pending sweep animation on unmount.
  useEffect(() => {
    return () => {
      if (sweepRafRef.current) cancelAnimationFrame(sweepRafRef.current);
    };
  }, []);

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
    <header className="sticky top-0 z-50 border-b border-edge bg-surface/95 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        {/* Left: Logo — theme-aware wordmark ("DEMIURGOS"). Gray in light,
            golden in dark; swapped in the same render cycle as the theme.
            24px tall so it stays within the 56px header without inflating
            width. */}
        <button
          type="button"
          onClick={() => navigate("/wiki")}
          aria-label="Demiurgos — ir al inicio"
          className="flex items-center transition-opacity hover:opacity-90"
        >
          <img
            src={resolvedTheme === "dark" ? "/wordmark-dark.svg" : "/wordmark-light.svg"}
            alt="Demiurgos"
            className="h-6 w-auto"
          />
        </button>

        {/* Center: Nav links (desktop). The native nav treats the Core
            workshops as a horizontal "deck of cards": the active one is a
            filled CTA globe (rounded-full pill) that visibly SWEEPS across
            the intermediate cards (stepwise, lighting each one) to land under
            the selected workshop. Body-size bold; teasers stay muted. */}
        <nav
          ref={navRef}
          aria-label="Navegación principal"
          className="relative hidden items-center gap-1 md:flex"
        >
          {pill.visible && (
            <span
              aria-hidden="true"
              className="absolute top-1/2 -translate-y-1/2 rounded-full bg-action shadow-sm"
              style={{ left: pill.left, width: pill.width, height: "calc(100% - 6px)" }}
            />
          )}
          {navLinks.map((link) => {
            const isActive = activePath === link.to;
            const isAvailable = !isTeaser(link);
            const isSweeping = sweepPath === link.to && !isActive;
            return (
              <button
                key={link.label}
                type="button"
                ref={(el) => {
                  linkRefs.current[link.to] = el;
                }}
                onClick={() => handleNavClick(link)}
                aria-current={isActive ? "page" : undefined}
                className={`relative rounded-full px-3.5 py-1.5 text-body font-bold transition-colors ${
                  isActive
                    ? "text-action-text"
                    : isSweeping
                      ? "bg-action/25 text-action"
                      : isAvailable
                        ? "text-primary hover:bg-surface-hover"
                        : "text-muted hover:text-primary hover:bg-surface-hover"
                }`}
              >
                {link.label}
                {isTeaser(link) && link.label !== GENERIC_TEASER_LABEL && (
                  <span
                    aria-hidden="true"
                    className="ml-1.5 rounded-full bg-surface-raised px-1.5 py-0.5 align-middle text-[10px] uppercase tracking-wide text-muted"
                  >
                    Próximamente
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Right: World selector, avatar */}
        <div className="flex items-center gap-2">
          <WorldSelector
            worlds={worlds}
            currentWorld={resolvedWorld}
            onWorldChange={onWorldChange}
            onRequestCreate={() => setCreatingWorld(true)}
          />

          {/* Theme toggle — 2-state: Light ↔ Dark. The icon reflects the
              effective theme; clicking persists the opposite one. The system
              color-scheme stays internal (initial default, THEME-01) and is
              no longer offered as a user choice. */}
          <button
            type="button"
            onClick={cycleTheme}
            aria-label={themeLabel}
            title="Cambiar tema"
            className="flex items-center justify-center rounded-lg p-1.5 text-icon-muted hover:bg-surface-hover hover:text-primary"
          >
            <Icon name={themeIcon} size={18} />
          </button>

          {/* Avatar */}
          <button
            type="button"
            ref={avatarRef}
            onClick={handleAvatarClick}
            aria-label="Perfil"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-raised text-icon-muted transition-colors hover:bg-surface-hover hover:text-primary"
          >
            <Icon name="avatar" size={18} />
          </button>

          {/* Mobile menu toggle */}
          <button
            type="button"
            onClick={() => setMobileMenuOpen((prev) => !prev)}
            className="flex items-center justify-center rounded-lg p-1.5 text-icon-muted hover:bg-surface-hover md:hidden"
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
          className="absolute right-4 top-16 z-50 w-72 rounded-lg border border-edge bg-surface-raised p-4 shadow-xl"
        >
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-heading text-body text-primary">Sesión de edición</h2>
            <span className="text-small text-muted">
              {vaultStatus?.mode === "credentials" ? "Credenciales" : "Local"}
            </span>
          </div>

          {vaultStatus?.mode === "credentials" ? (
            /* Credentials vault session is the single authoritative login
               (R-VC-01): the panel follows it, not the secondary local-dev one. */
            vaultLoading ? (
              <p className="mt-3 text-small text-muted">Comprobando sesión...</p>
            ) : vaultError ? (
              <p className="mt-3 text-small text-status-error">{vaultError.message}</p>
            ) : vaultStatus.authenticated ? (
              <>
                <p className="mt-3 text-small text-status-success">Sesión activa</p>
                <p className="mt-1 text-small text-muted">{vaultStatus.label}</p>
                 <button
                   type="button"
                   onClick={() => void handleSystemRequest("logout")}
                   disabled={systemBusy}
                   className="mt-3 w-full rounded-lg bg-surface-hover px-3 py-2 text-small text-primary disabled:opacity-60"
                 >
                   {systemBusy ? "Cerrando..." : "Cerrar sesión"}
                 </button>
               </>
             ) : (
               <p className="mt-3 text-small text-muted">
                 No hay una sesión de cuenta activa.
              </p>
            )
          ) : (
            <>
              {sessionLoading && (
                <p className="mt-3 text-small text-muted">Comprobando sesión local...</p>
              )}
              {sessionError && (
                <p className="mt-3 text-small text-status-error">{sessionError.message}</p>
              )}
              {!sessionLoading && !sessionError && status?.authenticated && (
                <>
                  <p className="mt-3 text-small text-status-success">Sesión local activa</p>
                  <p className="mt-1 text-small text-muted">{status.label}</p>
                  <button
                    type="button"
                    onClick={() => void handleSessionAction()}
                    disabled={sessionActionLoading}
                    className="mt-3 w-full rounded-lg bg-surface-hover px-3 py-2 text-small text-primary disabled:opacity-60"
                  >
                    {sessionActionLoading ? "Cerrando..." : "Cerrar sesión local"}
                  </button>
                </>
              )}
              {!sessionLoading && !sessionError && status && !status.authenticated && status.enabled && (
                <>
                  <p className="mt-3 text-small text-muted">Sesión local no iniciada.</p>
                  <button
                    type="button"
                    onClick={() => void handleSessionAction()}
                    disabled={sessionActionLoading}
                    className="mt-3 w-full rounded-lg bg-action px-3 py-2 text-small text-action-text hover:bg-action-hover disabled:opacity-60"
                  >
                    {sessionActionLoading ? "Iniciando..." : "Iniciar sesión local"}
                  </button>
                </>
              )}
              {!sessionLoading && !sessionError && status && !status.enabled && (
                <p className="mt-3 text-small text-muted">
                  Autenticación local desactivada. Activa DEMIURGOS_AUTH_MODE=local-dev para probar la edición.
                </p>
              )}
            </>
          )}

          {sessionActionError && (
            <p className="mt-3 text-small text-status-error">{sessionActionError}</p>
          )}

          <button
            type="button"
            onClick={() => {
              setProfileOpen(false);
              navigate("/perfil");
            }}
            className="mt-3 w-full rounded-lg bg-surface-hover px-3 py-2 text-small text-primary"
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
              <hr className="my-3 border-edge" />
              <div className="mt-1 space-y-2">
                <button
                  type="button"
                  onClick={() => handleSystemRequest("restart")}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-surface-hover px-3 py-2 text-small text-primary"
                >
                  <Icon name="refresh" size={16} />
                  Reiniciar Demiurgos
                </button>
                <button
                  type="button"
                  onClick={() => handleSystemRequest("shutdown")}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-surface-hover px-3 py-2 text-small text-status-error"
                >
                  <Icon name="power" size={16} />
                  Apagar Demiurgos
                </button>
                {systemNotice && (
                  <p className="text-small text-status-success">{systemNotice}</p>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* Mobile nav menu */}
      {mobileMenuOpen && (
        <div className="border-t border-edge bg-surface-raised md:hidden">
          <nav aria-label="Navegación móvil" className="flex flex-col gap-1 px-4 py-3">
            {navLinks.map((link) => {
              const isActive = activePath === link.to;
              return (
                <button
                  key={link.label}
                  type="button"
                  onClick={() => handleNavClick(link)}
                  aria-current={isActive ? "page" : undefined}
                  className={`rounded-lg px-3 py-2 text-left text-body font-bold transition-colors ${
                    isActive
                      ? "bg-action/15 text-action"
                      : isTeaser(link)
                        ? "text-muted hover:text-primary hover:bg-surface-hover"
                        : "text-primary hover:bg-surface-hover"
                  }`}
                >
                  {link.label}
                  {isTeaser(link) && link.label !== GENERIC_TEASER_LABEL && (
                    <span
                      aria-hidden="true"
                      className="ml-1.5 rounded-full bg-surface-raised px-1.5 py-0.5 align-middle text-[10px] uppercase tracking-wide text-muted"
                    >
                      Próximamente
                    </span>
                  )}
                </button>
              );
            })}
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
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-surface/90 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-3 px-6 text-center">
              {transition !== "off" && <Spinner size="lg" />}
              <p className="text-body text-primary">
                {transition === "restarting"
                  ? "Reiniciando Demiurgos…"
                  : transition === "shuttingDown"
                    ? "Apagando Demiurgos…"
                    : "Demiurgos se apagó"}
              </p>
              <p className="max-w-sm text-small text-muted">
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
