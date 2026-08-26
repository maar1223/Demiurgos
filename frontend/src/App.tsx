import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import WikiHome from "@/pages/WikiHome";
import WikiWorld from "@/pages/WikiWorld";
import WikiEditor from "@/pages/WikiEditor";
import ProfilePage from "@/pages/ProfilePage";
import ToolWorkshop from "@/pages/ToolWorkshop";
import WorldWorkshop from "@/pages/WorldWorkshop";
import WorldImporter from "@/pages/WorldImporter";
import RelacionesCanon from "@/pages/RelacionesCanon";
import Onboarding from "@/pages/Onboarding";
import LoginScreen from "@/pages/LoginScreen";
import NotFound from "@/pages/NotFound";
import { useOnboardingGate } from "@/hooks/useOnboardingGate";
import { useAuthGate } from "@/hooks/useAuthGate";

/** Lazy-loaded entity page — code-split because it's only used on entity routes */
const EntityPage = lazy(() => import("@/pages/EntityPage"));

/** Lazy-loaded ideas workshop — world-agnostic two-panel page at /ideas */
const IdeasWorkshop = lazy(() => import("@/pages/IdeasWorkshop"));

/**
 * Authentication gate (MANDATORY when DEMIURGOS_AUTH_MODE=local-dev):
 * when local auth is enabled, the user MUST authenticate before accessing
 * any application surface. This prevents the common UX failure where users
 * navigate the app without realizing they need to authenticate, then
 * encounter silent failures on write operations.
 *
 * The login screen is a full-page blocking screen, similar to onboarding.
 * When auth is disabled (default), the gate always passes through.
 */
function AuthGate() {
  const { loading, needsLogin } = useAuthGate();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-cripta">
        <span className="text-tinta-desvaida">Verificando autenticación…</span>
      </div>
    );
  }

  if (needsLogin) {
    return <LoginScreen />;
  }

  return <Outlet />;
}

/**
 * First-run gate (ONB-1.1): while onboarding is pending AND no world exists,
 * every Core surface redirects to `/onboarding`. Existing installations with
 * a world are never forced back into onboarding.
 */
function FirstRunGate() {
  const { loading, needsOnboarding } = useOnboardingGate();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-cripta">
        <span className="text-tinta-desvaida">Comprobando configuración…</span>
      </div>
    );
  }

  if (needsOnboarding) {
    return <Navigate to="/onboarding" replace />;
  }

  return <Outlet />;
}

/**
 * Root application component with routing.
 *
 * Routes:
 * - `/` → redirect to `/wiki`
 * - `/onboarding` → first-run onboarding (outside the gate)
 * - `/wiki` → Wiki Home page
 * - `/taller-herramientas` → ToolWorkshop (Taller de Herramientas shell)
 * - `/ideas` → IdeasWorkshop (Taller de Ideas — global, world-agnostic bank)
 * - `/taller-mundo` → WorldWorkshop (Taller de Mundo shell)
 * - `/perfil` → Profile page (Sesión de edición + Centro de Configuración tab +
 *   Integraciones → Captura de ideas (single Telegram surface), Asistente IA,
 *   Mundos incl. migración de carpetas legacy)
 * - `/wiki/:mundo/entity/*path` → EntityPage (entity detail with connections)
 * - `/wiki/:mundo` → WikiWorld (section cards for one world)
 * - `/wiki/:mundo/importer` → WorldImporter (world-level import workflow)
 * - `/wiki/:mundo/:section/*` → WikiEditor (file tree + markdown viewer + split diff preview)
 * - `*` → 404 NotFound
 *
 * Route ordering is CRITICAL: `entity` MUST come before `:section` wildcard,
 * and `importer` must be listed before the `:section/*` wildcard so the
 * fixed segment wins over the dynamic section match.
 * React Router matches top-down — `:section` would capture `entity` if defined first.
 * `/wiki/:mundo` (exact match) is ranked more specific than the wildcard routes
 * by React Router, but is listed before `:section/*` for clarity.
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/wiki" replace />} />
        <Route path="/onboarding" element={<Onboarding />} />

        <Route element={<AuthGate />}>
          <Route element={<FirstRunGate />}>
            <Route path="/wiki" element={<WikiHome />} />
            <Route path="/taller-herramientas" element={<ToolWorkshop />} />
            <Route
              path="/ideas"
              element={
                <Suspense
                  fallback={
                    <div className="flex min-h-screen items-center justify-center bg-cripta">
                      <span className="text-tinta-desvaida">Cargando Taller de Ideas…</span>
                    </div>
                  }
                >
                  <IdeasWorkshop />
                </Suspense>
              }
            />
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
              path="/taller-mundo/:mundo/relaciones-canon"
              element={<RelacionesCanon />}
            />
            <Route path="/wiki/:mundo/importer" element={<WorldImporter />} />
            <Route path="/wiki/:mundo/:section/*" element={<WikiEditor />} />
          </Route>
        </Route>

        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}
