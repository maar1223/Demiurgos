import { useCallback, useEffect, useState } from "react";
import useSWR from "swr";
import { Navbar } from "@/components/organisms/Navbar";
import { EditorLayout } from "@/components/templates/EditorLayout";
import { TabBar, type SidebarTab } from "@/components/molecules/TabBar";
import { AIAssistantSidebar } from "@/components/organisms/AIAssistantSidebar";
import { MarkdownViewer } from "@/components/organisms/MarkdownViewer";
import { Icon } from "@/components/atoms/Icon";
import { Spinner } from "@/components/atoms/Spinner";
import { useWorlds } from "@/hooks/useWorlds";
import {
  createIdea,
  deleteIdea,
  getIdea,
  listIdeas,
  materializeIdea,
  updateIdea,
  type IdeaDetail,
  type IdeaListFilters,
  type IdeaSource,
  type IdeaStatus,
  type IdeaSummary,
  type IdeaType,
  IDEA_TYPES,
} from "@/api/ideas";
import { getErrorMessage } from "@/lib/utils";
import type { ApiError } from "@/api/types";

const TYPE_LABELS: Record<IdeaType, string> = {
  personaje: "Personaje",
  relacion: "Relación",
  ambientacion: "Ambientación",
  trama: "Trama",
  concepto: "Concepto",
  sin_clasificar: "Sin clasificar",
};

const SOURCE_LABELS: Record<IdeaSource, string> = {
  telegram: "Telegram",
  manual: "Manual",
  assistant: "Asistente",
};

const STATUS_LABELS: Record<IdeaStatus, string> = {
  fresh: "Nueva",
  used: "Usada",
};

/**
 * IdeasWorkshop — the global Taller de Ideas (`/ideas`).
 *
 * World-agnostic two-panel page mirroring the wiki editor: the left panel
 * (EditorLayout sidebar) holds the filterable idea list plus the manual
 * create form; the main area shows the selected idea detail with the
 * materialize ("usar en el mundo") and reclassify actions; the right panel
 * hosts the AI assistant in null-mundo context (`ideas-global` session).
 * Functional-first: no visual polish beyond the shared design tokens.
 */
export default function IdeasWorkshop() {
  const { worlds } = useWorlds();

  // ── Filters ──────────────────────────────────────────────────────────────
  const [typeFilter, setTypeFilter] = useState<"" | IdeaType>("");
  const [statusFilter, setStatusFilter] = useState<"" | IdeaStatus>("");
  const [sourceFilter, setSourceFilter] = useState<"" | IdeaSource>("");

  // ── Selection & panels ───────────────────────────────────────────────────
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>("asistente");
  const [materializeFor, setMaterializeFor] = useState<string | null>(null);

  // ── Feedback ─────────────────────────────────────────────────────────────
  const [actionError, setActionError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const filters: IdeaListFilters = {
    type: typeFilter || undefined,
    status: statusFilter || undefined,
    source: sourceFilter || undefined,
  };

  // ── Data (SWR mirrors the wiki page pattern) ─────────────────────────────
  const listKey = [
    "ideas",
    typeFilter,
    statusFilter,
    sourceFilter,
  ];
  const {
    data: listData,
    error: listError,
    isLoading: listLoading,
    mutate: mutateList,
  } = useSWR(listKey, () => listIdeas(filters), {
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    errorRetryCount: 2,
  });

  const {
    data: detail,
    error: detailError,
    isLoading: detailLoading,
    mutate: mutateDetail,
  } = useSWR<IdeaDetail | null>(
    selectedSlug ? ["idea", selectedSlug] : null,
    () => getIdea(selectedSlug as string),
    { revalidateOnFocus: true },
  );

  const ideas = listData?.ideas ?? [];
  const selectedIdea = detail ?? null;

  const notifyError = useCallback((err: unknown) => {
    const apiError = err as ApiError;
    setActionError(getErrorMessage(apiError.status, apiError.detail));
  }, []);

  const showToast = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 2500);
  }, []);

  // ── Create ───────────────────────────────────────────────────────────────
  const [createSlug, setCreateSlug] = useState("");
  const [createType, setCreateType] = useState<IdeaType>("sin_clasificar");
  const [createTitle, setCreateTitle] = useState("");
  const [createTags, setCreateTags] = useState("");
  const [createBody, setCreateBody] = useState("");
  const [creating, setCreating] = useState(false);

  const resetCreateForm = useCallback(() => {
    setCreateSlug("");
    setCreateType("sin_clasificar");
    setCreateTitle("");
    setCreateTags("");
    setCreateBody("");
    setShowCreate(false);
  }, []);

  const handleCreate = useCallback(async () => {
    const slug = createSlug.trim();
    const body = createBody.trim();
    if (!slug || !body) {
      setActionError("Completá el slug y el cuerpo de la idea.");
      return;
    }
    setCreating(true);
    setActionError(null);
    try {
      const created = await createIdea({
        slug,
        type: createType,
        body,
        tags: createTags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
        ...(createTitle.trim() ? { title: createTitle.trim() } : {}),
      });
      await mutateList();
      resetCreateForm();
      setSelectedSlug(created.slug);
      showToast(`Idea "${created.title || created.slug}" creada.`);
    } catch (err) {
      notifyError(err);
    } finally {
      setCreating(false);
    }
  }, [createBody, createSlug, createTags, createTitle, createType, mutateList, notifyError, resetCreateForm, showToast]);

  // ── Reclassify (type correction) ────────────────────────────────────────
  const [reclassifyType, setReclassifyType] = useState<IdeaType>("sin_clasificar");
  const [reclassifying, setReclassifying] = useState(false);

  const openDetail = useCallback((slug: string) => {
    setSelectedSlug(slug);
    setMaterializeFor(null);
  }, []);

  // Keep the reclassify select in sync with the loaded idea type.
  useEffect(() => {
    if (selectedIdea) setReclassifyType(selectedIdea.type);
  }, [selectedIdea?.slug]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleReclassify = useCallback(async () => {
    if (!selectedSlug || reclassifyType === selectedIdea?.type) return;
    setReclassifying(true);
    setActionError(null);
    try {
      await updateIdea(selectedSlug, { type: reclassifyType });
      await mutateDetail();
      await mutateList();
      showToast(`Idea reclasificada como "${TYPE_LABELS[reclassifyType]}".`);
    } catch (err) {
      notifyError(err);
    } finally {
      setReclassifying(false);
    }
  }, [selectedSlug, reclassifyType, selectedIdea?.type, mutateDetail, mutateList, notifyError, showToast]);

  // ── Edit title ──────────────────────────────────────────────────────────
  const [editTitle, setEditTitle] = useState("");
  const [savingTitle, setSavingTitle] = useState(false);

  // Keep the title input in sync with the loaded idea (reclassify pattern).
  useEffect(() => {
    if (selectedIdea) setEditTitle(selectedIdea.title ?? "");
  }, [selectedIdea?.slug]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleEditTitle = useCallback(async () => {
    if (!selectedSlug || editTitle.trim() === (selectedIdea?.title ?? "")) return;
    setSavingTitle(true);
    setActionError(null);
    try {
      await updateIdea(selectedSlug, { title: editTitle.trim() });
      await mutateDetail();
      await mutateList();
      showToast(`Título guardado: "${editTitle.trim()}".`);
    } catch (err) {
      notifyError(err);
    } finally {
      setSavingTitle(false);
    }
  }, [selectedSlug, editTitle, selectedIdea?.title, mutateDetail, mutateList, notifyError, showToast]);

  // ── Materialize ("usar en el mundo") ─────────────────────────────────────
  const [materializeWorld, setMaterializeWorld] = useState("");
  const [materializeCanonRel, setMaterializeCanonRel] = useState("");
  const [materializing, setMaterializing] = useState(false);

  const handleMaterialize = useCallback(async () => {
    if (!materializeFor || !materializeWorld) {
      setActionError("Elegí un mundo para materializar la idea.");
      return;
    }
    setMaterializing(true);
    setActionError(null);
    try {
      const result = await materializeIdea(
        materializeFor,
        materializeWorld,
        materializeCanonRel.trim() || undefined,
      );
      await mutateDetail();
      await mutateList();
      setMaterializeFor(null);
      setMaterializeWorld("");
      setMaterializeCanonRel("");
      showToast(
        `Idea materializada en ${materializeWorld} (usada en: ${result.used_in.join(", ")}).`,
      );
    } catch (err) {
      notifyError(err);
    } finally {
      setMaterializing(false);
    }
  }, [materializeCanonRel, materializeFor, materializeWorld, mutateDetail, mutateList, notifyError, showToast]);

  // ── Delete ───────────────────────────────────────────────────────────────
  const [deleting, setDeleting] = useState(false);

  const handleDelete = useCallback(async () => {
    if (!selectedSlug) return;
    if (!window.confirm(`¿Eliminar la idea "${selectedSlug}" del banco global?`)) {
      return;
    }
    setDeleting(true);
    setActionError(null);
    try {
      await deleteIdea(selectedSlug);
      setSelectedSlug(null);
      await mutateList();
      showToast(`Idea "${selectedSlug}" eliminada.`);
    } catch (err) {
      notifyError(err);
    } finally {
      setDeleting(false);
    }
  }, [selectedSlug, mutateList, notifyError, showToast]);

  // ── Left panel: filters + list + create form ─────────────────────────────
  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="border-b border-filio px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-heading text-body font-medium text-pergamino">Ideas</h2>
          <span className="text-xs text-tinta-desvaida">{ideas.length}</span>
        </div>
        <button
          type="button"
          onClick={() => {
            setActionError(null);
            setShowCreate((prev) => !prev);
          }}
          className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-md bg-llamita px-2.5 py-1.5 text-xs font-medium text-cripta transition-colors hover:bg-llama-alta"
          aria-label="Nueva idea"
        >
          <Icon name="plus" size={13} />
          Nueva idea
        </button>
      </div>

      {showCreate && (
        <div
          role="group"
          aria-label="Crear idea"
          className="border-b border-filio bg-cripta/60 px-4 py-3"
        >
          <div className="space-y-2">
            <div>
              <label htmlFor="idea-slug" className="mb-1 block text-xs text-tinta-desvaida">
                Slug
              </label>
              <input
                id="idea-slug"
                value={createSlug}
                onChange={(e) => setCreateSlug(e.target.value)}
                placeholder="ej: arquero-ciego"
                className="w-full rounded-md border border-filio bg-madero px-2.5 py-1.5 text-xs text-pergamino placeholder:text-sombra focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50"
              />
            </div>
            <div>
              <label htmlFor="idea-type" className="mb-1 block text-xs text-tinta-desvaida">
                Tipo
              </label>
              <select
                id="idea-type"
                value={createType}
                onChange={(e) => setCreateType(e.target.value as IdeaType)}
                className="w-full rounded-md border border-filio bg-madero px-2.5 py-1.5 text-xs text-pergamino focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50"
              >
                {IDEA_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {TYPE_LABELS[type]}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="idea-title" className="mb-1 block text-xs text-tinta-desvaida">
                Título (opcional)
              </label>
              <input
                id="idea-title"
                value={createTitle}
                onChange={(e) => setCreateTitle(e.target.value)}
                placeholder="ej: prototipo de diosa"
                className="w-full rounded-md border border-filio bg-madero px-2.5 py-1.5 text-xs text-pergamino placeholder:text-sombra focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50"
              />
            </div>
            <div>
              <label htmlFor="idea-tags" className="mb-1 block text-xs text-tinta-desvaida">
                Etiquetas (separadas por coma)
              </label>
              <input
                id="idea-tags"
                value={createTags}
                onChange={(e) => setCreateTags(e.target.value)}
                placeholder="ej: arquero, ciego"
                className="w-full rounded-md border border-filio bg-madero px-2.5 py-1.5 text-xs text-pergamino placeholder:text-sombra focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50"
              />
            </div>
            <div>
              <label htmlFor="idea-body" className="mb-1 block text-xs text-tinta-desvaida">
                Cuerpo
              </label>
              <textarea
                id="idea-body"
                value={createBody}
                onChange={(e) => setCreateBody(e.target.value)}
                rows={4}
                placeholder="Describí la idea..."
                className="w-full resize-none rounded-md border border-filio bg-madero px-2.5 py-1.5 text-xs text-pergamino placeholder:text-sombra focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50"
              />
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => void handleCreate()}
                disabled={creating}
                className="flex-1 rounded-md bg-llamita px-2.5 py-1.5 text-xs font-medium text-cripta transition-colors hover:bg-llama-alta disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creating ? "Creando..." : "Crear idea"}
              </button>
              <button
                type="button"
                onClick={resetCreateForm}
                disabled={creating}
                className="rounded-md border border-filio px-2.5 py-1.5 text-xs text-tinta-desvaida transition-colors hover:border-llamita/40 hover:text-pergamino disabled:opacity-50"
              >
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-1.5 border-b border-filio px-4 py-2.5" aria-label="Filtros">
        <select
          aria-label="Filtrar por tipo"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as "" | IdeaType)}
          className="w-full rounded-md border border-filio bg-madero px-1.5 py-1 text-xs text-pergamino focus:border-llamita focus:outline-none"
        >
          <option value="">Tipo</option>
          {IDEA_TYPES.map((type) => (
            <option key={type} value={type}>
              {TYPE_LABELS[type]}
            </option>
          ))}
        </select>
        <select
          aria-label="Filtrar por estado"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as "" | IdeaStatus)}
          className="w-full rounded-md border border-filio bg-madero px-1.5 py-1 text-xs text-pergamino focus:border-llamita focus:outline-none"
        >
          <option value="">Estado</option>
          <option value="fresh">{STATUS_LABELS.fresh}</option>
          <option value="used">{STATUS_LABELS.used}</option>
        </select>
        <select
          aria-label="Filtrar por origen"
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value as "" | IdeaSource)}
          className="w-full rounded-md border border-filio bg-madero px-1.5 py-1 text-xs text-pergamino focus:border-llamita focus:outline-none"
        >
          <option value="">Origen</option>
          <option value="telegram">{SOURCE_LABELS.telegram}</option>
          <option value="manual">{SOURCE_LABELS.manual}</option>
          <option value="assistant">{SOURCE_LABELS.assistant}</option>
        </select>
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        {listLoading ? (
          <div className="flex items-center justify-center py-10" role="status">
            <Spinner size="md" />
          </div>
        ) : listError ? (
          <p className="px-4 py-6 text-center text-xs text-sangre">
            {getErrorMessage((listError as ApiError).status, (listError as ApiError).detail)}
          </p>
        ) : ideas.length === 0 ? (
          <p className="px-4 py-6 text-center text-xs text-tinta-desvaida">
            No hay ideas. Creá la primera con "Nueva idea".
          </p>
        ) : (
          <ul aria-label="Lista de ideas" className="space-y-0.5 px-2">
            {ideas.map((idea: IdeaSummary) => (
              <li key={idea.slug}>
                <button
                  type="button"
                  onClick={() => openDetail(idea.slug)}
                  aria-current={selectedSlug === idea.slug ? "true" : undefined}
                  className={[
                    "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left transition-colors",
                    selectedSlug === idea.slug
                      ? "bg-llamita/10 text-llamita"
                      : "text-tinta-desvaida hover:bg-piedra hover:text-pergamino",
                  ].join(" ")}
                >
                  <Icon name="lightbulb" size={14} className="shrink-0 opacity-60" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium">{idea.title || idea.slug}</span>
                    <span className="block truncate text-xs opacity-60">
                      {TYPE_LABELS[idea.type]} · {STATUS_LABELS[idea.status]}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );

  // ── Main panel: detail ───────────────────────────────────────────────────
  const main = (
    <div className="mx-auto max-w-3xl">
      {detailLoading ? (
        <div className="flex items-center justify-center py-24" role="status">
          <Spinner size="lg" />
        </div>
      ) : detailError ? (
        <div className="py-16 text-center">
          <p className="text-body text-sangre">
            {getErrorMessage((detailError as ApiError).status, (detailError as ApiError).detail)}
          </p>
        </div>
      ) : !selectedIdea ? (
        <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-llamita/10 text-llamita">
            <Icon name="lightbulb" size={28} />
          </div>
          <h2 className="font-heading text-h3 text-pergamino">Banco global de ideas</h2>
          <p className="max-w-sm text-body text-tinta-desvaida">
            Seleccioná una idea del listado para verla en detalle, reclasificarla o
            materializarla en un mundo.
          </p>
        </div>
      ) : (
        <article aria-label={`Idea ${selectedIdea.slug}`}>
          <header className="mb-4 border-b border-filio pb-4">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-heading text-h2 text-pergamino">{selectedIdea.title || selectedIdea.slug}</h2>
              <span className="rounded-full bg-llamita/10 px-2.5 py-0.5 text-xs text-llamita">
                {TYPE_LABELS[selectedIdea.type]}
              </span>
              <span className="rounded-full bg-piedra px-2.5 py-0.5 text-xs text-tinta-desvaida">
                {STATUS_LABELS[selectedIdea.status]}
              </span>
            </div>
            <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-tinta-desvaida">
              <div>
                <dt className="inline">Origen: </dt>
                <dd className="inline">{SOURCE_LABELS[selectedIdea.source]}</dd>
              </div>
              <div>
                <dt className="inline">Creada: </dt>
                <dd className="inline">{new Date(selectedIdea.timestamp).toLocaleString()}</dd>
              </div>
              {selectedIdea.tags.length > 0 && (
                <div>
                  <dt className="inline">Etiquetas: </dt>
                  <dd className="inline">{selectedIdea.tags.join(", ")}</dd>
                </div>
              )}
              {selectedIdea.used_in.length > 0 && (
                <div>
                  <dt className="inline">Usada en: </dt>
                  <dd className="inline">{selectedIdea.used_in.join(", ")}</dd>
                </div>
              )}
            </dl>
          </header>

          {/* Body rendered as GFM markdown (R-1). Frontmatter is stripped
              inside MarkdownViewer (splitFrontmatter); no `mundo` prop by
              design — /api/ideas/media/... embeds pass through MarkdownImage.
              imageFit="contain" keeps exact proportions (no crop) so images
              of any resolution render consistently in the idea bank. */}
          <div className="mb-6">
            <MarkdownViewer content={selectedIdea.body} imageFit="contain" />
          </div>

          {/* Edit title */}
          <section aria-label="Título de la idea" className="mb-4 rounded-lg border border-filio bg-madero p-4">
            <h3 className="mb-2 text-body font-medium text-pergamino">Título</h3>
            <div className="flex flex-wrap items-center gap-2">
              <input
                id="edit-idea-title"
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                placeholder="Sin título — se muestra el slug"
                className="min-w-0 flex-1 rounded-md border border-filio bg-cripta px-2.5 py-1.5 text-xs text-pergamino placeholder:text-sombra focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50"
              />
              <button
                type="button"
                onClick={() => void handleEditTitle()}
                disabled={savingTitle || editTitle.trim() === (selectedIdea.title ?? "")}
                className="rounded-md bg-llamita px-3 py-1.5 text-xs font-medium text-cripta transition-colors hover:bg-llama-alta disabled:cursor-not-allowed disabled:opacity-50"
              >
                {savingTitle ? "Guardando..." : "Guardar título"}
              </button>
            </div>
          </section>

          {/* Reclassify */}
          <section aria-label="Reclasificar idea" className="mb-4 rounded-lg border border-filio bg-madero p-4">
            <h3 className="mb-2 text-body font-medium text-pergamino">Clasificación</h3>
            <div className="flex flex-wrap items-center gap-2">
              <select
                aria-label="Tipo de la idea"
                value={reclassifyType}
                onChange={(e) => setReclassifyType(e.target.value as IdeaType)}
                className="rounded-md border border-filio bg-cripta px-2.5 py-1.5 text-xs text-pergamino focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50"
              >
                {IDEA_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {TYPE_LABELS[type]}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void handleReclassify()}
                disabled={reclassifying || reclassifyType === selectedIdea.type}
                className="rounded-md bg-llamita px-3 py-1.5 text-xs font-medium text-cripta transition-colors hover:bg-llama-alta disabled:cursor-not-allowed disabled:opacity-50"
              >
                {reclassifying ? "Guardando..." : "Guardar tipo"}
              </button>
            </div>
          </section>

          {/* Materialize */}
          <section aria-label="Usar idea en un mundo" className="mb-4 rounded-lg border border-filio bg-madero p-4">
            <h3 className="mb-2 text-body font-medium text-pergamino">Usar en un mundo</h3>
            {materializeFor !== selectedIdea.slug ? (
              <button
                type="button"
                onClick={() => {
                  setActionError(null);
                  setMaterializeFor(selectedIdea.slug);
                }}
                className="flex items-center gap-1.5 rounded-md border border-filio px-3 py-1.5 text-xs text-tinta-desvaida transition-colors hover:border-llamita/40 hover:text-pergamino"
              >
                <Icon name="world" size={13} />
                Materializar
              </button>
            ) : (
              <div className="space-y-2">
                <div>
                  <label htmlFor="materialize-world" className="mb-1 block text-xs text-tinta-desvaida">
                    Mundo
                  </label>
                  <select
                    id="materialize-world"
                    value={materializeWorld}
                    onChange={(e) => setMaterializeWorld(e.target.value)}
                    className="w-full rounded-md border border-filio bg-cripta px-2.5 py-1.5 text-xs text-pergamino focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50"
                  >
                    <option value="">Elegí un mundo...</option>
                    {worlds.map((world) => (
                      <option key={world.name} value={world.name}>
                        {world.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="materialize-canon-rel" className="mb-1 block text-xs text-tinta-desvaida">
                    Ruta canónica (opcional)
                  </label>
                  <input
                    id="materialize-canon-rel"
                    value={materializeCanonRel}
                    onChange={(e) => setMaterializeCanonRel(e.target.value)}
                    placeholder="ej: personajes/arquero.md"
                    className="w-full rounded-md border border-filio bg-cripta px-2.5 py-1.5 text-xs text-pergamino placeholder:text-sombra focus:border-llamita focus:outline-none focus:ring-1 focus:ring-llamita/50"
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void handleMaterialize()}
                    disabled={materializing || !materializeWorld}
                    className="rounded-md bg-llamita px-3 py-1.5 text-xs font-medium text-cripta transition-colors hover:bg-llama-alta disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {materializing ? "Materializando..." : "Materializar"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMaterializeFor(null);
                      setMaterializeWorld("");
                      setMaterializeCanonRel("");
                    }}
                    disabled={materializing}
                    className="rounded-md border border-filio px-3 py-1.5 text-xs text-tinta-desvaida transition-colors hover:border-llamita/40 hover:text-pergamino disabled:opacity-50"
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            )}
          </section>

          {/* Delete */}
          <div className="flex justify-end border-t border-filio pt-4">
            <button
              type="button"
              onClick={() => void handleDelete()}
              disabled={deleting}
              className="flex items-center gap-1.5 rounded-md border border-sangre/30 px-3 py-1.5 text-xs text-sangre transition-colors hover:bg-sangre/10 disabled:opacity-50"
              aria-label={`Eliminar idea ${selectedIdea.slug}`}
            >
              <Icon name="trash" size={13} />
              {deleting ? "Eliminando..." : "Eliminar"}
            </button>
          </div>
        </article>
      )}
    </div>
  );

  // ── Right panel: persistent assistant (null-mundo) ───────────────────────
  const contextPanel = (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-4">
      <h2 className="mb-2 text-body font-medium text-pergamino">Contexto</h2>
      <p className="text-xs leading-relaxed text-tinta-desvaida">
        El Taller de Ideas es un banco global, sin mundo activo. Las ideas son
        arquetipos reutilizables que podés materializar en cualquier mundo.
      </p>
      <dl className="mt-4 space-y-2 text-xs text-tinta-desvaida">
        <div className="flex justify-between">
          <dt>Ideas en el banco</dt>
          <dd className="text-pergamino">{ideas.length}</dd>
        </div>
        {selectedIdea && (
          <>
            <div className="flex justify-between">
              <dt>Idea seleccionada</dt>
              <dd className="text-pergamino">{selectedIdea.slug}</dd>
            </div>
            <div className="flex justify-between">
              <dt>Estado</dt>
              <dd className="text-pergamino">{STATUS_LABELS[selectedIdea.status]}</dd>
            </div>
          </>
        )}
      </dl>
    </div>
  );

  const rightPanel = (
    <div className="flex h-full flex-col">
      <TabBar onTabChange={setSidebarTab} />
      {sidebarTab === "asistente" ? (
        <AIAssistantSidebar />
      ) : (
        contextPanel
      )}
    </div>
  );

  return (
    <EditorLayout
      header={<Navbar worlds={worlds} />}
      sidebar={sidebar}
      rightPanel={rightPanel}
    >
      {(actionError || toast) && (
        <div className="mb-4">
          {actionError && (
            <div role="alert" className="rounded-lg border border-sangre/30 bg-sangre/10 px-3 py-2 text-xs text-sangre">
              {actionError}
            </div>
          )}
          {toast && (
            <div role="status" className="rounded-lg border border-llamita/30 bg-llamita/10 px-3 py-2 text-xs text-pergamino">
              {toast}
            </div>
          )}
        </div>
      )}
      {main}
    </EditorLayout>
  );
}