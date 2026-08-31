import { useNavigate } from "react-router-dom";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { useWorlds } from "@/hooks/useWorlds";

interface WorldNotFoundProps {
  /** The world name that was in the route but no longer exists. */
  mundo: string;
}

/**
 * Friendly dead-end replacement for "Mundo no encontrado".
 *
 * When a world-scoped route points at a world that no longer exists (e.g. it
 * was deleted), instead of leaving the user on a "Volver al inicio" dead-end,
 * this lists the worlds that DO exist and lets them jump straight into one.
 * If there are no worlds left it falls back to the home action.
 */
export function WorldNotFound({ mundo }: WorldNotFoundProps) {
  const navigate = useNavigate();
  const { worlds } = useWorlds();
  const available = worlds.filter((w) => w.name !== mundo);

  return (
    <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-raised text-status-error">
        <Icon name="error" size={32} />
      </div>
      <h2 className="font-heading text-h3 text-primary">Mundo no encontrado</h2>
      <p className="max-w-md text-body text-muted">
        No existe un mundo llamado «{mundo}» (fue borrado o el nombre cambió).
      </p>

      {available.length > 0 ? (
        <>
          <p className="text-small text-muted">Elegí un mundo para continuar:</p>
          <div className="flex flex-wrap items-center justify-center gap-2">
            {available.map((w) => (
              <Button
                key={w.name}
                variant="secondary"
                onClick={() =>
                  navigate(`/wiki/${encodeURIComponent(w.name)}`)
                }
              >
                <Icon name="world" size={14} />
                {w.name}
              </Button>
            ))}
          </div>
        </>
      ) : (
        <Button variant="secondary" onClick={() => navigate("/wiki")}>
          <Icon name="chevron-left" size={16} />
          Volver al inicio
        </Button>
      )}
    </div>
  );
}
