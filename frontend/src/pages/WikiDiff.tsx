import { useEffect, useCallback, useState } from "react";
import { useParams, useNavigate, useSearchParams, useLocation } from "react-router-dom";
import { useWorlds } from "@/hooks/useWorlds";
import { useFileContent } from "@/hooks/useFileContent";
import { useDiff } from "@/hooks/useDiff";
import { Navbar } from "@/components/organisms/Navbar";
import { DiffLayout } from "@/components/templates/DiffLayout";
import { DiffViewer } from "@/components/organisms/DiffViewer";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { Breadcrumb } from "@/components/molecules/Breadcrumb";
import { VALID_SECTIONS } from "@/lib/constants";
import { decodePathSegment, getErrorMessage } from "@/lib/utils";
import { saveFile } from "@/api/wiki";
import type { ApiError } from "@/api/types";

/**
 * Wiki Diff page (`/wiki/:mundo/:section/*path?diff=1`).
 *
 * Shows a side-by-side diff of current vs edited content.
 *
 * States per spec R3 (S20-S27):
 * - S20: User edits content and clicks "Ver diff" → diff renders
 * - S26: Diff API returns error → error banner
 * - S27: No edits pending → "Editá un archivo primero para ver el diff"
 * - S24: Accept → saveFile + navigate back
 * - S25: Reject → discard + navigate back
 * - S22: New file → all lines shown as added
 * - S23: No changes → "No hay cambios"
 */
export default function WikiDiff() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { mundo, section, "*": splatPath } = useParams<{
    mundo: string;
    section: string;
    "*"?: string;
  }>();

  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // Decode the path
  const filePath = splatPath ? decodePathSegment(splatPath) : undefined;

  // Validate section
  const sectionValid = section && VALID_SECTIONS.includes(section as typeof VALID_SECTIONS[number]);

  // Check for ?diff=1
  const diffParam = searchParams.get("diff");
  const isDiffMode = diffParam === "1";

  // Get the edited content from route state (passed from WikiEditor)
  const locationState = location.state as { editedContent?: string } | null;
  const editedContent = locationState?.editedContent;

  // Worlds (for Navbar)
  const { worlds, isLoading: worldsLoading } = useWorlds();

  // Current file content (for reference)
  const {
    isLoading: contentLoading,
  } = useFileContent(
    mundo,
    sectionValid ? section : undefined,
    filePath,
  );

  // Diff hook
  const { diff, isLoading: diffLoading, error: diffError, triggerDiff, reset } = useDiff();

  // Auto-trigger diff when the page loads with edited content
  useEffect(() => {
    if (!mundo || !section || !filePath || !isDiffMode) return;

    if (editedContent) {
      triggerDiff(mundo, section, filePath, editedContent).catch(() => {
        // Error is captured by useDiff's error state
      });
    }
  }, [mundo, section, filePath, isDiffMode, editedContent, triggerDiff]);

  // Handle accept: save the new content and navigate back
  const handleAccept = useCallback(async () => {
    if (!mundo || !section || !filePath || !editedContent) return;

    setIsSaving(true);
    setSaveError(null);

    try {
      await saveFile(mundo, section, filePath, editedContent);
      // Navigate back to the editor view (without ?diff=1)
      const encodedPath = filePath.split("/").map((s) => encodeURIComponent(s)).join("/");
      navigate(`/wiki/${encodeURIComponent(mundo)}/${section}/${encodedPath}`, { replace: true });
    } catch (err) {
      const apiErr = err as ApiError;
      setSaveError(getErrorMessage(apiErr.status, apiErr.detail));
    } finally {
      setIsSaving(false);
    }
  }, [mundo, section, filePath, editedContent, navigate]);

  // Handle reject: discard and navigate back
  const handleReject = useCallback(() => {
    if (!mundo || !section || !filePath) return;

    reset();
    const encodedPath = filePath.split("/").map((s) => encodeURIComponent(s)).join("/");
    navigate(`/wiki/${encodeURIComponent(mundo)}/${section}/${encodedPath}`, { replace: true });
  }, [mundo, section, filePath, navigate, reset]);

  // Breadcrumb segments
  const breadcrumbSegments = [mundo, section, filePath].filter(Boolean) as string[];

  // --- Render states ---

  // Invalid section
  if (section && !sectionValid) {
    return (
      <DiffLayout
        header={<Navbar worlds={worlds} />}
      >
        <div className="flex flex-col items-center justify-center gap-4 py-24">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-piedra text-sangre">
            <Icon name="error" size={32} />
          </div>
          <h2 className="font-heading text-h3 text-pergamino">
            Sección no válida
          </h2>
          <Button variant="secondary" onClick={() => navigate("/wiki")}>
            <Icon name="chevron-left" size={16} />
            Volver al inicio
          </Button>
        </div>
      </DiffLayout>
    );
  }

  // Loading
  if (worldsLoading || contentLoading) {
    return (
      <DiffLayout
        header={<Navbar worlds={[]} />}
      >
        <div className="flex items-center justify-center py-24">
          <Spinner size="lg" />
        </div>
      </DiffLayout>
    );
  }

  // World/route errors
  if (!mundo || !section || !filePath) {
    return (
      <DiffLayout
        header={<Navbar worlds={worlds} />}
      >
        <EmptyState
          icon="error"
          message="Faltan parámetros de ruta."
          actionLabel="Volver al inicio"
          onAction={() => navigate("/wiki")}
        />
      </DiffLayout>
    );
  }

  // S27: No edits pending — user navigated directly without editing
  if (!editedContent) {
    return (
      <DiffLayout
        header={<Navbar worlds={worlds} currentWorld={mundo} />}
      >
        <div className="flex flex-col items-center justify-center gap-4 py-24">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-piedra text-plata/50">
            <Icon name="diff" size={32} />
          </div>
          <h2 className="font-heading text-h3 text-pergamino">
            Sin cambios para revisar
          </h2>
          <p className="text-body text-tinta-desvaida">
            Editá un archivo primero para ver el diff.
          </p>
          <Button variant="secondary" onClick={handleReject}>
            <Icon name="chevron-left" size={16} />
            Volver al editor
          </Button>
        </div>
      </DiffLayout>
    );
  }

  // S26: Diff API error
  if (diffError) {
    return (
      <DiffLayout
        header={<Navbar worlds={worlds} currentWorld={mundo} />}
      >
        <div className="flex flex-col gap-4 py-8">
          <Breadcrumb
            segments={breadcrumbSegments}
            onSegmentClick={(i) => {
              if (i === 0 && mundo) {
                navigate(`/wiki/${encodeURIComponent(mundo)}/${section}`);
              }
            }}
          />
          <ErrorBanner
            message="No se pudo generar la vista previa del diff"
            onRetry={() => {
              if (mundo && section && filePath && editedContent) {
                triggerDiff(mundo, section, filePath, editedContent);
              }
            }}
          />
          <Button variant="secondary" size="sm" onClick={handleReject}>
            <Icon name="chevron-left" size={14} />
            Volver al editor
          </Button>
        </div>
      </DiffLayout>
    );
  }

  // Save error banner (shown above the diff if save fails)
  const saveErrorBanner = saveError ? (
    <ErrorBanner message={saveError} />
  ) : null;

  // Ready state: show the diff
  return (
    <DiffLayout
      header={<Navbar worlds={worlds} currentWorld={mundo} />}
    >
      <div className="flex flex-col gap-4">
        {/* Breadcrumb */}
        <Breadcrumb
          segments={breadcrumbSegments}
          onSegmentClick={(i) => {
            if (i === 0 && mundo) {
              navigate(`/wiki/${encodeURIComponent(mundo)}/${section}`);
            }
          }}
        />

        {/* Page heading */}
        <div className="flex items-center gap-2">
          <Icon name="diff" size={20} className="text-llamita" />
          <h1 className="font-heading text-h3 text-pergamino">
            Vista previa de cambios
          </h1>
        </div>

        {/* Save error */}
        {saveErrorBanner}

        {/* Diff content */}
        <DiffViewer
          diff={diff?.diff ?? []}
          isLoading={diffLoading || isSaving}
          error={null}
          onAccept={handleAccept}
          onReject={handleReject}
          actionsDisabled={isSaving}
        />
      </div>
    </DiffLayout>
  );
}
