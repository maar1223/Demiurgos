import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import WikiHome from "@/pages/WikiHome";
import NotFound from "@/pages/NotFound";

/**
 * Root application component with routing.
 *
 * Routes:
 * - `/` → redirect to `/wiki`
 * - `/wiki` → Wiki Home page
 * - `/wiki/:mundo/:section/*path` → WikiEditor (placeholder for PR 2)
 * - `*` → 404 NotFound
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/wiki" replace />} />
        <Route path="/wiki" element={<WikiHome />} />
        <Route
          path="/wiki/:mundo/:section/*"
          element={<WikiEditorPlaceholder />}
        />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}

/**
 * Placeholder for the WikiEditor page (implemented in PR 2).
 */
function WikiEditorPlaceholder() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-cripta">
      <p className="text-body text-tinta-desvaida">
        Editor — próximamente
      </p>
    </div>
  );
}
