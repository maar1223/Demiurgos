import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { searchEntities } from "@/api/graph";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Module-level cache — survives across re-renders within the same page load.
// Each unique entity name is resolved once via the search API and cached.
// ---------------------------------------------------------------------------
const aliveCache = new Map<string, boolean>();
const pendingCache = new Map<string, Promise<void>>();

interface WikiLinkProps {
  /** The raw entity name from the wikilink (e.g. "Kaelen" from [[Kaelen]]) */
  name: string;
  /** Current world name for constructing entity URLs */
  mundo: string;
}

/**
 * Renders a wikilink with dead/alive detection.
 *
 * **Alive** (entity exists): blue, clickable Link to `/wiki/:mundo/entity/:name`.
 * **Dead** (entity not found): grey strikethrough name + "Crear" button
 * navigating to the entity page (which shows a creation prompt in PR 3).
 * **Resolving**: plain text while the search API call is in flight.
 *
 * Resolution uses a per-page-load `Map<string, boolean>` cache. On cache
 * miss, a single `searchEntities()` call resolves the name asynchronously.
 * Concurrent requests for the same name are deduplicated via a pending map.
 */
export function WikiLink({ name, mundo }: WikiLinkProps) {
  const cached = aliveCache.get(name);
  const [alive, setAlive] = useState<boolean | null>(cached ?? null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    // Already resolved or in-flight — nothing to do
    if (aliveCache.has(name)) return;
    if (pendingCache.has(name)) return;

    const promise = searchEntities(mundo, name)
      .then((results) => {
        const exists = results.length > 0;
        aliveCache.set(name, exists);
        if (mountedRef.current) setAlive(exists);
      })
      .catch(() => {
        // On error, treat as dead (graceful degradation)
        aliveCache.set(name, false);
        if (mountedRef.current) setAlive(false);
      })
      .finally(() => {
        pendingCache.delete(name);
      });

    pendingCache.set(name, promise);

    return () => {
      mountedRef.current = false;
    };
  }, [name, mundo]);

  // Encode entity name for URLs (handles names with slashes)
  const encodedName = name
    .split("/")
    .map((s) => encodeURIComponent(s))
    .join("/");
  const entityUrl = `/wiki/${encodeURIComponent(mundo)}/entity/${encodedName}`;

  // --- Resolving state ---
  if (alive === null) {
    return (
      <span className="text-tinta-desvaida" title={`Resolviendo "${name}"…`}>
        {name}
      </span>
    );
  }

  // --- Alive state ---
  if (alive) {
    return (
      <Link
        to={entityUrl}
        className={cn(
          "text-llamita hover:text-llama-alta",
          "underline underline-offset-2 decoration-llamita/40 hover:decoration-llama-alta",
          "transition-colors",
        )}
      >
        {name}
      </Link>
    );
  }

  // --- Dead state ---
  return (
    <span className="inline-flex items-center gap-1">
      <span className="text-sombra line-through">{name}</span>
      <Link
        to={entityUrl}
        className={cn(
          "ml-1 inline-flex items-center gap-0.5",
          "rounded bg-piedra px-1.5 py-0.5",
          "text-xs text-llamita no-underline",
          "hover:bg-filio transition-colors",
        )}
        title={`Crear entidad "${name}"`}
      >
        <Icon name="plus" size={10} />
        Crear
      </Link>
    </span>
  );
}
