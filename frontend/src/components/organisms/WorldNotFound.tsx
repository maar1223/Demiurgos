import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { useWorlds } from "@/hooks/useWorlds";
import { getWorldAliases } from "@/api/worlds";
import { WorldPickerDialog } from "@/components/organisms/WorldPickerDialog";
import { CreateWorldModal } from "@/components/organisms/CreateWorldModal";
import type { WorldInfo } from "@/api/types";

interface WorldNotFoundProps {
  /** The world name that was in the route but no longer exists. */
  mundo: string;
}

/**
 * Friendly dead-end replacement for "Mundo no encontrado".
 *
 * When a world-scoped route points at a world that no longer exists (e.g. it
 * was deleted), a centered `WorldPickerDialog` auto-opens offering the worlds
 * that DO exist (jump straight in) plus "Nuevo mundo". Dismissing it reveals a
 * plain inline "not found" state with a home action as fallback.
 */
export function WorldNotFound({ mundo }: WorldNotFoundProps) {
  const navigate = useNavigate();
  const { worlds } = useWorlds();
  const [open, setOpen] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const available = worlds.filter((w) => w.name !== mundo);

  // If the missing world is a rename alias, follow it so old URLs keep
  // working (no "not found" for a world that was renamed).
  useEffect(() => {
    let active = true;
    void getWorldAliases()
      .then((aliases) => {
        const canonical = aliases[mundo];
        if (active && canonical && canonical !== mundo) {
          navigate(`/wiki/${encodeURIComponent(canonical)}`, { replace: true });
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [mundo, navigate]);

  const goHome = () => navigate("/wiki");
  const pick = (name: string) => navigate(`/wiki/${encodeURIComponent(name)}`);

  const handleCreated = (world: WorldInfo) => {
    setCreateOpen(false);
    setOpen(false);
    navigate(`/wiki/${encodeURIComponent(world.name)}`);
  };

  return (
    <>
      {/* Inline fallback behind the dialog (visible if the user dismisses it). */}
      <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-raised text-status-error">
          <Icon name="error" size={32} />
        </div>
        <h2 className="font-heading text-h3 text-primary">Mundo no encontrado</h2>
        <p className="max-w-md text-body text-muted">
          No existe un mundo llamado «{mundo}» (fue borrado o el nombre cambió).
        </p>
        <Button variant="secondary" onClick={goHome}>
          <Icon name="chevron-left" size={16} />
          Volver al inicio
        </Button>
      </div>

      {open && (
        <WorldPickerDialog
          missingWorld={mundo}
          available={available}
          onPick={pick}
          onCreate={() => {
            // Close the picker so the create dialog is the only modal —
            // otherwise both are z-50 and the (body-portaled) picker can sit
            // above the inline create dialog in a page stacking context.
            setOpen(false);
            setCreateOpen(true);
          }}
          onClose={() => setOpen(false)}
          footerAction={{ label: "Volver al inicio", onAction: goHome }}
        />
      )}

      <CreateWorldModal
        isOpen={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={handleCreated}
      />
    </>
  );
}
