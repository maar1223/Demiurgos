import { useNavigate } from "react-router-dom";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";

/**
 * 404 Not Found page with navigation back to Wiki Home.
 */
export default function NotFound() {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-surface px-4">
      <div className="flex h-20 w-20 items-center justify-center rounded-full bg-surface-raised text-muted">
        <Icon name="error" size={40} />
      </div>
      <h1 className="font-heading text-h2 text-primary">404</h1>
      <p className="text-body text-muted">
        Página no encontrada
      </p>
      <Button variant="primary" onClick={() => navigate("/wiki")}>
        <Icon name="chevron-left" size={16} />
        Volver al inicio
      </Button>
    </div>
  );
}
