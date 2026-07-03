import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import WikiHome from "@/pages/WikiHome";
import WikiEditor from "@/pages/WikiEditor";
import WikiDiff from "@/pages/WikiDiff";
import NotFound from "@/pages/NotFound";

/**
 * Root application component with routing.
 *
 * Routes:
 * - `/` → redirect to `/wiki`
 * - `/wiki` → Wiki Home page
 * - `/wiki/:mundo/:section/*` → WikiEditor (file tree + markdown viewer)
 *   - With `?diff=1` → WikiDiff (side-by-side diff)
 * - `*` → 404 NotFound
 *
 * The diff route is handled inside WikiEditor/WikiDiff via query param.
 * When the URL contains `?diff=1`, the WikiDiff component renders instead.
 * Both share the same URL pattern but differ by query param.
 *
 * Per spec R3 (S20-S27): Diff at `/wiki/:mundo/:section/*path?diff=1`
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/wiki" replace />} />
        <Route path="/wiki" element={<WikiHome />} />
        <Route
          path="/wiki/:mundo/:section/*"
          element={<WikiEditorOrDiff />}
        />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}

/**
 * Decides whether to render WikiEditor or WikiDiff based on `?diff=1`.
 *
 * Both components share the same route pattern. The query parameter
 * `?diff=1` switches from the editor view to the diff view.
 */
function WikiEditorOrDiff() {
  const params = new URLSearchParams(window.location.search);
  const isDiff = params.get("diff") === "1";

  if (isDiff) {
    return <WikiDiff />;
  }

  return <WikiEditor />;
}
