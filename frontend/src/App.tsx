import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import WikiHome from "@/pages/WikiHome";
import WikiEditor from "@/pages/WikiEditor";
import NotFound from "@/pages/NotFound";

/**
 * Root application component with routing.
 *
 * Routes:
 * - `/` → redirect to `/wiki`
 * - `/wiki` → Wiki Home page
 * - `/wiki/:mundo/:section/*` → WikiEditor (file tree + markdown viewer)
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
          element={<WikiEditor />}
        />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}
