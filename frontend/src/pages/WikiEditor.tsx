import { useCallback, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useWorlds } from "@/hooks/useWorlds";
import { useFileTree } from "@/hooks/useFileTree";
import { useFileContent } from "@/hooks/useFileContent";
import { Navbar } from "@/components/organisms/Navbar";
import { EditorLayout } from "@/components/templates/EditorLayout";
import { FileTree } from "@/components/organisms/FileTree";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";
import { Breadcrumb } from "@/components/molecules/Breadcrumb";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { VALID_SECTIONS } from "@/lib/constants";
import { decodePathSegment } from "@/lib/utils";

/**
 * Wiki Editor page (`/wiki/:mundo/:section/*path`).
 *
 * States:
 * - 🔴 Invalid section: ErrorBanner with link back
 * - 🟡 Loading world list: Spinner
 * - 🟢 Ready: EditorLayout with FileTree sidebar + MarkdownViewer + Breadcrumb
 *
 * Supports an edit mode: clicking "Editar" switches to a textarea for editing.
 * "Ver diff" navigates to the diff page with the edited content.
 */
export default function WikiEditor() {
  const navigate = useNavigate();
  const { mundo, section, "*": splatPath } = useParams<{
    mundo: string;
    section: string;
    "*"?: string;
  }>();

  // Edit mode state
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState<string | null>(null);

  // Decode the path from URL encoding
  const filePath = splatPath ? decodePathSegment(splatPath) : undefined;

  // Validate section
  const sectionValid = section && VALID_SECTIONS.includes(section as typeof VALID_SECTIONS[number]);

  // Worlds (for Navbar world selector and world validation)
  const { worlds, isLoading: worldsLoading, error: worldsError } = useWorlds();

  // File tree for the sidebar
  const {
    nodes: treeNodes,
    isLoading: treeLoading,
    error: treeError,
    mutate: retryTree,
  } = useFileTree(mundo, sectionValid ? section : undefined);

  // File content for the markdown viewer
  const {
    file,
    isLoading: contentLoading,
    error: contentError,
    mutate: retryContent,
  } = useFileContent(
    mundo,
    sectionValid ? section : undefined,
    filePath,
  );

  // Content to display/edit
  const currentContent = file?.content ?? "";

  // Initialise edited content when file loads or path changes
  // We use a ref to track whether we've initialised for this file path
  const [initialisedPath, setInitialisedPath] = useState<string | null>(null);
  if (filePath && filePath !== initialisedPath && currentContent) {
    setEditedContent(currentContent);
    setInitialisedPath(filePath);
  }

  // Breadcrumb segments
  const breadcrumbSegments = useMemo(() => {
    const segs: string[] = [];
    if (mundo) segs.push(mundo);
    if (section) segs.push(section);
    if (filePath) {
      const parts = filePath.split("/");
      segs.push(...parts);
    }
    return segs;
  }, [mundo, section, filePath]);

  // Breadcrumb click handler: navigate to that directory level
  const handleBreadcrumbClick = useCallback(
    (index: number) => {
      if (!mundo || !section) return;

      if (index === 0) {
        navigate(`/wiki/${encodeURIComponent(mundo)}/${section}`);
        return;
      }
      if (index === 1) {
        navigate(`/wiki/${encodeURIComponent(mundo)}/${section}`);
        return;
      }

      const pathParts = breadcrumbSegments.slice(2, index + 1);
      const newPath = pathParts.map((s) => encodeURIComponent(s)).join("/");
      navigate(`/wiki/${encodeURIComponent(mundo)}/${section}/${newPath}`);
    },
    [mundo, section, navigate, breadcrumbSegments],
  );

  // File tree node click: navigate to the selected file
  const handleFileSelect = useCallback(
    (path: string) => {
      if (!mundo || !section) return;
      const encodedPath = path.split("/").map((s) => encodeURIComponent(s)).join("/");
      navigate(`/wiki/${encodeURIComponent(mundo)}/${section}/${encodedPath}`);
    },
    [mundo, section, navigate],
  );

  // Navigate to diff page with edited content
  const handleViewDiff = useCallback(() => {
    if (!mundo || !section || !filePath || editedContent === null) return;
    navigate(
      `/wiki/${encodeURIComponent(mundo)}/${section}/${encodePathSegments(filePath)}?diff=1`,
      { state: { editedContent } },
    );
  }, [mundo, section, filePath, editedContent, navigate]);

  // Toggle edit mode
  const handleToggleEdit = useCallback(() => {
    if (isEditing) {
      // Exiting edit mode — reset edited content to original
      if (file) {
        setEditedContent(file.content);
      }
    } else {
      // Entering edit mode — initialise content if needed
      if (editedContent === null && file) {
        setEditedContent(file.content);
      }
    }
    setIsEditing((prev) => !prev);
  }, [isEditing, file, editedContent]);

  const hasChanges =
    editedContent !== null && editedContent !== currentContent;

  // --- Render states ---

  // Invalid section
  if (section && !sectionValid) {
    return (
      <EditorLayout
        header={
          <Navbar worlds={worlds} currentWorld={mundo} />
        }
        sidebar={null}
      >
        <div className="flex flex-col items-center justify-center gap-4 py-24">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-piedra text-sangre">
            <Icon name="error" size={32} />
          </div>
          <h2 className="font-heading text-h3 text-pergamino">
            Sección no válida
          </h2>
          <p className="text-body text-tinta-desvaida">
            Secciones válidas:{" "}
            {VALID_SECTIONS.map((s) => `"${s}"`).join(", ")}
          </p>
          <Button variant="secondary" onClick={() => navigate("/wiki")}>
            <Icon name="chevron-left" size={16} />
            Volver al inicio
          </Button>
        </div>
      </EditorLayout>
    );
  }

  // Loading world list
  if (worldsLoading) {
    return (
      <EditorLayout
        header={<Navbar worlds={[]} />}
        sidebar={null}
      >
        <div className="flex items-center justify-center py-24">
          <Spinner size="lg" />
        </div>
      </EditorLayout>
    );
  }

  // World not found (loaded worlds, but this one doesn't exist)
  const worldExists = worlds.some((w) => w.name === mundo);

  // Has issues that prevent rendering
  if (!mundo || !section) {
    return (
      <EditorLayout
        header={<Navbar worlds={worlds} />}
        sidebar={null}
      >
        <EmptyState
          icon="error"
          message="Faltan parámetros de ruta. Seleccioná un mundo desde la página principal."
          actionLabel="Ir al inicio"
          onAction={() => navigate("/wiki")}
        />
      </EditorLayout>
    );
  }

  if (!worldExists) {
    return (
      <EditorLayout
        header={<Navbar worlds={worlds} currentWorld={mundo} />}
        sidebar={null}
      >
        <div className="flex flex-col items-center justify-center gap-4 py-24">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-piedra text-sangre">
            <Icon name="error" size={32} />
          </div>
          <h2 className="font-heading text-h3 text-pergamino">
            Mundo no encontrado
          </h2>
          <p className="text-body text-tinta-desvaida">
            No existe un mundo llamado "{mundo}".
          </p>
          <Button variant="secondary" onClick={() => navigate("/wiki")}>
            <Icon name="chevron-left" size={16} />
            Volver al inicio
          </Button>
        </div>
      </EditorLayout>
    );
  }

  // Ready state
  return (
    <EditorLayout
      header={
        <Navbar worlds={worlds} currentWorld={mundo} />
      }
      sidebar={
        <FileTree
          nodes={treeNodes}
          selectedPath={filePath}
          onSelect={handleFileSelect}
          isLoading={treeLoading}
          error={treeError}
          onRetry={retryTree}
        />
      }
    >
      {/* Breadcrumb */}
      <div className="mb-6">
        <Breadcrumb
          segments={breadcrumbSegments}
          onSegmentClick={handleBreadcrumbClick}
        />
      </div>

      {/* Toolbar — shown when a file is selected */}
      {filePath && file && (
        <div className="mb-4 flex items-center justify-between rounded-lg border border-filio bg-madero px-4 py-2">
          <span className="text-small text-tinta-desvaida">
            {file.name}
            {isEditing && (
              <span className="ml-2 rounded bg-llamita/10 px-2 py-0.5 text-xs text-llamita">
                Editando
              </span>
            )}
          </span>
          <div className="flex items-center gap-2">
            {isEditing ? (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleToggleEdit}
                >
                  <Icon name="close" size={14} />
                  Cancelar
                </Button>
                {hasChanges && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleViewDiff}
                  >
                    <Icon name="diff" size={14} />
                    Ver diff
                  </Button>
                )}
              </>
            ) : (
              <Button
                variant="secondary"
                size="sm"
                onClick={handleToggleEdit}
              >
                <Icon name="edit" size={14} />
                Editar
              </Button>
            )}
          </div>
        </div>
      )}

      {/* Content area: editor or viewer */}
      {isEditing && editedContent !== null ? (
        <textarea
          value={editedContent}
          onChange={(e) => setEditedContent(e.target.value)}
          className="min-h-[400px] w-full resize-y rounded-lg border border-filio bg-madero px-4 py-3 font-mono text-body text-pergamino placeholder:text-sombra focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50"
          aria-label="Editor de contenido"
          spellCheck={false}
        />
      ) : (
        <MarkdownViewer
          content={file?.content ?? null}
          fileName={file?.name}
          isLoading={contentLoading}
          error={contentError}
          onRetry={retryContent}
        />
      )}
    </EditorLayout>
  );
}

/**
 * Encodes a path for use in URLs, preserving forward slashes.
 */
function encodePathSegments(path: string): string {
  return path.split("/").map((s) => encodeURIComponent(s)).join("/");
}
