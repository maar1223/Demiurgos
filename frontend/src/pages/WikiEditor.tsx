import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useWorlds } from "@/hooks/useWorlds";
import { useFileTree } from "@/hooks/useFileTree";
import { useFileContent } from "@/hooks/useFileContent";
import { useImageUpload } from "@/hooks/useImages";
import { Navbar } from "@/components/organisms/Navbar";
import { EditorLayout } from "@/components/templates/EditorLayout";
import { FileTree } from "@/components/organisms/FileTree";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";
import { EntitySearchPanel } from "@/components/organisms/EntitySearchPanel";
import { AIAssistantSidebar } from "@/components/organisms/AIAssistantSidebar";
import { TabBar } from "@/components/molecules/TabBar";
import type { SidebarTab } from "@/components/molecules/TabBar";
import { SectionTabs } from "@/components/molecules/SectionTabs";
import { Breadcrumb } from "@/components/molecules/Breadcrumb";
import { EmptyState } from "@/components/organisms/EmptyState";
import { ErrorBanner } from "@/components/organisms/ErrorBanner";
import { Spinner } from "@/components/atoms/Spinner";
import { Icon } from "@/components/atoms/Icon";
import { Button } from "@/components/atoms/Button";
import { DropZone } from "@/components/atoms/DropZone";
import { ImagePicker } from "@/components/organisms/ImagePicker";
import { VALID_SECTIONS } from "@/lib/constants";
import { decodePathSegment, getErrorMessage } from "@/lib/utils";
import { splitFrontmatter, mergeFrontmatter } from "@/lib/frontmatter";
import { saveFile } from "@/api/wiki";
import type { ApiError } from "@/api/types";

// CodeMirror is heavy (~300KB) — load the live diff editor only when the
// preview is actually opened, keeping the initial bundle lean.
const LiveDiffEditor = lazy(() => import("@/components/organisms/LiveDiffEditor"));

// Type-only import of the imperative handle — erased at runtime, so it does
// not pull the lazy chunk into the initial bundle.
import type { LiveDiffEditorHandle } from "@/components/organisms/LiveDiffEditor";

/**
 * Wiki Editor page (`/wiki/:mundo/:section/*path`).
 *
 * States:
 * - 🔴 Invalid section: ErrorBanner with link back
 * - 🟡 Loading world list: Spinner
 * - 🟢 Ready: EditorLayout with FileTree sidebar + MarkdownViewer + Breadcrumb
 *
 * Edit mode: "Editar" switches to a textarea. The toolbar offers
 * [Cancelar] [Vista previa] [Guardar]. "Vista previa" swaps the textarea
 * for a live diff view — original on the left (red, read-only), editable
 * draft on the right (green): you click a line and type directly in the
 * diff, and it recomputes on every keystroke. Wikilinks from the Contexto
 * panel insert at the caret of the focused diff line through the
 * imperative `insertText` handle (appended at the end when nothing is
 * focused). "Guardar" persists via POST /save and exits edit mode.
 *
 * The YAML frontmatter of wiki fichas is agent-only metadata: it never
 * appears in the editor, the diff, or the viewer. Only the body is
 * displayed/edited; the raw block is re-merged on save so the file on
 * disk stays byte-identical.
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

  // Split preview state — toggles the LiveDiffEditor merge view
  const [previewOpen, setPreviewOpen] = useState(false);

  // Save state
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Textarea ref for wikilink cursor insertion
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Live diff imperative handle — wikilink insertion while the preview is open
  const liveDiffRef = useRef<LiveDiffEditorHandle>(null);

  // Image picker modal state — reachable only from the editing toolbar
  const [showPicker, setShowPicker] = useState(false);

  // Image upload (DropZone in view mode) — uploads + revalidates the gallery
  const { upload, isUploading, uploadError } = useImageUpload(mundo ?? "");

  // Sidebar tab state — persisted in sessionStorage by TabBar
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>(() => {
    if (typeof window === "undefined") return "asistente";
    const stored = sessionStorage.getItem("sidebar-tab");
    if (stored === "asistente" || stored === "contexto") return stored;
    return "asistente";
  });

  // Decode the path from URL encoding
  const filePath = splatPath ? decodePathSegment(splatPath) : undefined;

  // Validate section
  const sectionValid = section && VALID_SECTIONS.includes(section as typeof VALID_SECTIONS[number]);

  // Worlds (for Navbar world selector and world validation)
  const { worlds, isLoading: worldsLoading } = useWorlds();

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

  // Content to display/edit — the YAML frontmatter is agent-only metadata
  // and is hidden from every user-facing surface (editor, diff, viewer).
  // `body` is the displayable baseline; the raw `frontmatter` block is kept
  // aside (re-derived only when the file content changes, so it survives
  // edits) and re-merged on save to keep the on-disk file byte-identical.
  const { frontmatter, body } = useMemo(
    () => splitFrontmatter(file?.content ?? ""),
    [file?.content],
  );

  // Baseline body — used for change detection and as the diff `original`
  const currentContent = body;

  // Initialise edited content when file path actually changes.
  // MUST use useEffect + useRef, NOT setState during render:
  // React 18 StrictMode double-invokes the component function, and a
  // setState during render would overwrite the user's edits with the
  // original file content. Effect runs AFTER commit, outside StrictMode's
  // double-invocation path.
  const prevFilePathRef = useRef<string | undefined>();
  useEffect(() => {
    if (filePath && filePath !== prevFilePathRef.current && currentContent) {
      setEditedContent(currentContent);
      prevFilePathRef.current = filePath;
    }
  }, [filePath, currentContent]);

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

  // Section tab click: navigate to the section root (resets file path).
  // The tree/content SWR keys include `section`, so both re-fetch on change.
  const handleSectionSelect = useCallback(
    (nextSection: string) => {
      if (!mundo) return;
      navigate(`/wiki/${encodeURIComponent(mundo)}/${nextSection}`);
    },
    [mundo, navigate],
  );

  // Auto-clear the "Guardado ✓" feedback after a short delay
  useEffect(() => {
    if (!saveSuccess) return;
    const t = setTimeout(() => setSaveSuccess(false), 2500);
    return () => clearTimeout(t);
  }, [saveSuccess]);

  // Save the edited content via POST /save, then exit edit mode.
  const handleSave = useCallback(async () => {
    if (!mundo || !section || !filePath || editedContent === null) return;
    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      await saveFile(mundo, section, filePath, mergeFrontmatter(frontmatter, editedContent));
      await retryContent();
      setPreviewOpen(false);
      setIsEditing(false);
      setSaveSuccess(true);
    } catch (err) {
      const apiErr = err as ApiError;
      setSaveError(getErrorMessage(apiErr.status, apiErr.detail));
    } finally {
      setIsSaving(false);
    }
  }, [mundo, section, filePath, frontmatter, editedContent, retryContent]);

  // Toggle edit mode — exiting resets preview and transient state
  const handleToggleEdit = useCallback(() => {
    if (isEditing) {
      // Exiting edit mode — reset edited content to original body
      if (file) {
        setEditedContent(currentContent);
      }
      setPreviewOpen(false);
      setSaveError(null);
      setSaveSuccess(false);
    } else {
      // Entering edit mode — initialise content if needed
      if (editedContent === null && file) {
        setEditedContent(currentContent);
      }
    }
    setIsEditing((prev) => !prev);
  }, [isEditing, file, editedContent, currentContent]);

  // Insert a wikilink at the cursor position. While the preview is open the
  // live diff's side B is the writing surface — the imperative handle
  // splices the wikilink into the focused diff line (or appends at the end).
  // Otherwise insert into the textarea at its preserved caret.
  const handleInsertWikilink = useCallback(
    (name: string) => {
      const wikilink = `[[${name}]]`;
      if (previewOpen) {
        liveDiffRef.current?.insertText(wikilink);
        return;
      }
      const ta = textareaRef.current;
      if (!ta) return;

      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const current = editedContent ?? "";

      const newContent =
        current.slice(0, start) + wikilink + current.slice(end);
      setEditedContent(newContent);

      // Restore cursor after the inserted wikilink
      requestAnimationFrame(() => {
        ta.focus();
        ta.selectionStart = ta.selectionEnd = start + wikilink.length;
      });
    },
    [editedContent, previewOpen],
  );

  // Insert an image markdown at the cursor position. Mirrors the wikilink
  // flow: while the preview is open the live diff is the writing surface
  // (imperative insertText), otherwise splice into the textarea caret.
  const insertMarkdown = useCallback(
    (path: string) => {
      const name = path.split("/").pop()?.split(".")[0] ?? "image";
      const md = `![${name}](${path})`;
      if (previewOpen) {
        liveDiffRef.current?.insertText(md);
        return;
      }
      const ta = textareaRef.current;
      if (!ta) return;

      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const current = editedContent ?? "";

      const newContent =
        current.slice(0, start) + md + current.slice(end);
      setEditedContent(newContent);

      // Restore cursor after the inserted markdown
      requestAnimationFrame(() => {
        ta.focus();
        ta.selectionStart = ta.selectionEnd = start + md.length;
      });
    },
    [editedContent, previewOpen],
  );

  // Handle file drop in view mode — upload and append markdown at the end
  const handleFileDrop = useCallback(
    async (file: File) => {
      if (!mundo) return;
      try {
        const result = await upload(file);
        const md = `![${result.path.split("/").pop()!.split(".")[0]}](${result.path})`;
        setEditedContent((prev) => (prev ?? "") + "\n" + md + "\n");
      } catch (err) {
        // Upload error — surfaced by the uploadError banner
        console.error("Upload failed:", err);
      }
    },
    [mundo, upload],
  );

  const hasChanges =
    editedContent !== null && editedContent !== currentContent;

  // Right panel content — always visible
  const rightPanelContent = (
    <div className="flex h-full flex-col">
      <TabBar onTabChange={setSidebarTab} />
      {sidebarTab === "asistente" ? (
        <AIAssistantSidebar mundo={mundo!} section={section} filePath={filePath} />
      ) : (
        <EntitySearchPanel mundo={mundo!} onInsert={handleInsertWikilink} />
      )}
    </div>
  );

  // Editor textarea — used standalone; the preview replaces it with the
  // live diff (side B of the diff is the writing surface while open)
  const editorTextarea = (
    <textarea
      ref={textareaRef}
      value={editedContent ?? ""}
      onChange={(e) => setEditedContent(e.target.value)}
      className="min-h-[400px] w-full resize-y rounded-lg border border-filio bg-madero px-4 py-3 font-mono text-body text-pergamino placeholder:text-sombra focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50"
      aria-label="Editor de contenido"
      spellCheck={false}
    />
  );

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
        <Navbar
          worlds={worlds}
          currentWorld={mundo}
        />
      }
      sidebar={
        <div className="flex h-full min-h-0 flex-col">
          <SectionTabs
            activeSection={section}
            onSelect={handleSectionSelect}
          />
          <div className="min-h-0 flex-1 overflow-y-auto pb-2">
            <FileTree
              key={section}
              nodes={treeNodes}
              selectedPath={filePath}
              onSelect={handleFileSelect}
              isLoading={treeLoading}
              error={treeError}
              onRetry={retryTree}
            />
          </div>
        </div>
      }
      rightPanel={rightPanelContent}
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
            {saveSuccess && (
              <span className="ml-2 rounded bg-musgo/10 px-2 py-0.5 text-xs text-musgo">
                Guardado ✓
              </span>
            )}
          </span>
          <div className="flex items-center gap-2">
            {isEditing ? (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowPicker(true)}
                >
                  <Icon name="image" size={14} />
                  Imagen
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleToggleEdit}
                  disabled={isSaving}
                >
                  <Icon name="close" size={14} />
                  Cancelar
                </Button>
                {hasChanges && (
                  <>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setPreviewOpen((prev) => !prev)}
                    >
                      <Icon name="diff" size={14} />
                      Vista previa
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={handleSave}
                      disabled={isSaving}
                    >
                      <Icon name="save" size={14} />
                      Guardar
                    </Button>
                  </>
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

      {/* Save error banner */}
      {saveError && (
        <ErrorBanner message={saveError} className="mb-4" />
      )}

      {/* Upload error banner */}
      {uploadError && (
        <div className="mb-4 rounded-lg border border-sangre/50 bg-sangre/10 px-4 py-2 text-small text-sangre">
          Error al subir imagen: {uploadError.message}
        </div>
      )}

      {/* Upload progress indicator */}
      {isUploading && (
        <div className="mb-4 rounded-lg border border-llamita/30 bg-llamita/5 px-4 py-2 text-small text-llamita">
          Subiendo imagen…
        </div>
      )}

      {/* DropZone in view mode — drag & drop an image to upload it */}
      {filePath && file && !isEditing && (
        <div className="mb-4">
          <DropZone onFile={handleFileDrop} />
        </div>
      )}

      {/* Content area: live diff preview, textarea editor, or viewer */}
      {isEditing && editedContent !== null ? (
        // The preview REPLACES the textarea — the diff's right side is the
        // writing surface. The textarea unmounts while the preview is open
        // and remounts (with the preserved draft) when it closes.
        previewOpen ? (
          <Suspense
            fallback={
              <div className="flex h-[70vh] items-center justify-center rounded-lg border border-filio bg-madero">
                <Spinner size="lg" />
              </div>
            }
          >
            <LiveDiffEditor
              ref={liveDiffRef}
              original={currentContent}
              value={editedContent}
              onChange={setEditedContent}
            />
          </Suspense>
        ) : (
          editorTextarea
        )
      ) : (
        <MarkdownViewer
          content={file ? body : null}
          fileName={file?.name}
          isLoading={contentLoading}
          error={contentError}
          onRetry={retryContent}
          mundo={mundo}
        />
      )}

      {/* Image picker modal — opened from the editing toolbar */}
      {showPicker && mundo && (
        <ImagePicker
          mundo={mundo}
          onSelect={(path) => {
            insertMarkdown(path);
            setShowPicker(false);
          }}
          onClose={() => setShowPicker(false)}
        />
      )}
    </EditorLayout>
  );
}
