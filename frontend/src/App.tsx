import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import WikiHome from "@/pages/WikiHome";
import WikiWorld from "@/pages/WikiWorld";
import WikiEditor from "@/pages/WikiEditor";
import ProfilePage from "@/pages/ProfilePage";
import ToolWorkshop from "@/pages/ToolWorkshop";
import WorldWorkshop from "@/pages/WorldWorkshop";
import NotFound from "@/pages/NotFound";

/** Lazy-loaded entity page — code-split because it's only used on entity routes */
const EntityPage = lazy(() => import("@/pages/EntityPage"));

/**
 * Root application component with routing.
 *
 * Routes:
 * - `/` → redirect to `/wiki`
 * - `/wiki` → Wiki Home page
 * - `/taller-herramientas` → ToolWorkshop (Taller de Herramientas shell)
 * - `/taller-mundo` → WorldWorkshop (Taller de Mundo shell)
 * - `/perfil` → Profile page (local session + Integraciones → Captura de ideas)
 * - `/wiki/:mundo/entity/*path` → EntityPage (entity detail with connections)
 * - `/wiki/:mundo` → WikiWorld (section cards for one world)
 * - `/wiki/:mundo/:section/*` → WikiEditor (file tree + markdown viewer + split diff preview)
 * - `*` → 404 NotFound
 *
 * Route ordering is CRITICAL: `entity` MUST come before `:section` wildcard.
 * React Router matches top-down — `:section` would capture `entity` if defined first.
 * `/wiki/:mundo` (exact match) is ranked more specific than the wildcard routes
 * by React Router, but is listed before `:section/*` for clarity.
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/wiki" replace />} />
        <Route path="/wiki" element={<WikiHome />} />
        <Route path="/taller-herramientas" element={<ToolWorkshop />} />
        <Route path="/taller-mundo" element={<WorldWorkshop />} />
        <Route path="/perfil" element={<ProfilePage />} />
        <Route
          path="/wiki/:mundo/entity/*"
          element={
            <Suspense
              fallback={
                <div className="flex min-h-screen items-center justify-center bg-cripta">
                  <span className="text-tinta-desvaida">Cargando entidad…</span>
                </div>
              }
            >
              <EntityPage />
            </Suspense>
          }
        />
        <Route path="/wiki/:mundo" element={<WikiWorld />} />
        <Route
          path="/wiki/:mundo/:section/*"
          element={<WikiEditor />}
        />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}
