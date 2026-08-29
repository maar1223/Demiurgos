/**
 * Full-page reload after a successful login/logout.
 *
 * Routed through a function so tests can stub it: jsdom's `Location.reload`
 * is an own non-configurable property — it cannot be spied on, and replacing
 * `window.location` (or proxying it) breaks the router. The repo already
 * works around unimplemented jsdom navigation the same way (`window.print`
 * stub in the test setup).
 */
export function reloadPage(): void {
  window.location.reload();
}