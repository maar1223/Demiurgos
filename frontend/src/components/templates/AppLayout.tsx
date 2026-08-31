import { Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { Navbar } from "@/components/organisms/Navbar";
import { useWorlds } from "@/hooks/useWorlds";
import { useCurrentWorld } from "@/hooks/useCurrentWorld";

interface AppLayoutProps {
  /** Called after the world changes so the page can react (e.g. refetch). */
  onWorldOverrideChange?: (world: string) => void;
}

/**
 * Shared app shell: renders the global Navbar above the routed page.
 *
 * A SINGLE persistent layout covers every authenticated route. The Navbar lives
 * HERE (a pathless layout route) — not per-page — so it stays mounted across
 * all route changes, including crossing between world and non-world routes.
 * This is what enables the sliding active-pill animation: a persistent Navbar
 * keeps its pill position, so the highlight can glide card → card instead of
 * snapping on a fresh mount.
 *
 * World resolution: on a world-scoped route we read `:mundo` from the URL via
 * `useParams()` and feed it to the Navbar as `currentWorld`; elsewhere we fall
 * back to the localStorage active world. So the selector always reflects the
 * world being viewed without the page having to pass anything.
 *
 * World-change navigation is uniform (Opción A): switching worlds from the
 * WorldSelector navigates to `/wiki/<world>`, preserving the current section
 * (and any sub-path) when already inside a `/wiki/:mundo/:section/*` route.
 */
export function AppLayout({ onWorldOverrideChange }: AppLayoutProps) {
  const { mundo } = useParams();
  const { worlds } = useWorlds();
  const { world: currentWorld } = useCurrentWorld();
  const resolvedWorld = mundo ?? currentWorld ?? undefined;
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const handleWorldChange = (world: string) => {
    if (onWorldOverrideChange) onWorldOverrideChange(world);
    const match = pathname.match(/^\/wiki\/([^/]+)(\/.*)?$/);
    if (match) {
      const [, , section] = match;
      navigate(`/wiki/${encodeURIComponent(world)}${section ?? ""}`, {
        replace: true,
      });
    } else {
      navigate(`/wiki/${encodeURIComponent(world)}`, { replace: true });
    }
  };

  return (
    <>
      <Navbar
        worlds={worlds}
        currentWorld={resolvedWorld}
        onWorldChange={handleWorldChange}
      />
      <Outlet />
    </>
  );
}