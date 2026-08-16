import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ToolWorkshop from "@/pages/ToolWorkshop";

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: vi.fn(),
}));

vi.mock("@/api/methodologies", () => ({
  getMethodologyStatus: vi.fn(),
  createMethodologyDraft: vi.fn(),
  publishMethodologyDraft: vi.fn(),
  activateMethodology: vi.fn(),
}));

import { useWorlds } from "@/hooks/useWorlds";
import {
  activateMethodology,
  getMethodologyStatus,
} from "@/api/methodologies";
import type { Mock } from "vitest";
import type { WorldInfo } from "@/api/types";

const worlds: WorldInfo[] = [
  {
    name: "Vibrantes",
    path: "/vibrantes",
    lore_count: 77,
    character_count: 10,
    saga_count: 4,
  },
];

const status = {
  published: [
    {
      skill_id: "guided-character-v1",
      version: "1.2.0",
      name: "Guided character methodology",
      description: "",
      digest: "abc",
      published_at: "2026-01-01",
    },
  ],
  activations: {},
  drafts: [],
};

function renderToolWorkshop() {
  return render(
    <MemoryRouter initialEntries={["/taller-herramientas"]}>
      <Routes>
        <Route path="/taller-herramientas" element={<ToolWorkshop />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ToolWorkshop", () => {
  beforeEach(() => {
    (useWorlds as Mock).mockReturnValue({
      worlds,
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });
    (getMethodologyStatus as Mock).mockResolvedValue(status);
    (activateMethodology as Mock).mockResolvedValue({
      world: "Vibrantes",
      skill_id: "guided-character-v1",
      version: "1.2.0",
      digest: "abc",
      activated_at: "2026-01-01",
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the workshop heading and the methodology library", async () => {
    renderToolWorkshop();

    expect(
      screen.getByRole("heading", { name: "Taller de Herramientas" }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
  });

  it("gates activation on the world chosen in the selector", async () => {
    const user = userEvent.setup();
    renderToolWorkshop();

    // No world selected → the library shows publications but cannot activate.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sin mundo" })).toBeDisabled();
    });

    const main = screen.getByRole("main");
    await user.click(within(main).getByRole("button", { name: "Mundos" }));
    await user.click(within(main).getByRole("option", { name: "Vibrantes" }));
    // Selecting a different world asks for confirmation before applying
    await user.click(screen.getByRole("button", { name: "Cambiar" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Activar" })).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: "Activar" }));

    await waitFor(() => {
      expect(activateMethodology).toHaveBeenCalledWith(
        "Vibrantes",
        "guided-character-v1",
        "1.2.0",
      );
    });
  });

  it("shows an honest loading state while worlds load", () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: true,
      error: null,
      mutate: vi.fn(),
    });

    renderToolWorkshop();
    expect(screen.getByRole("status", { name: "Cargando" })).toBeInTheDocument();
  });

  it("shows an honest error state when worlds fail to load", () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: false,
      error: new Error("boom"),
      mutate: vi.fn(),
    });

    renderToolWorkshop();
    expect(
      screen.getByText(/No se pudo cargar la lista de mundos/),
    ).toBeInTheDocument();
  });

  it("still shows publications but forbids activation when no worlds exist", async () => {
    (useWorlds as Mock).mockReturnValue({
      worlds: [],
      isLoading: false,
      error: null,
      mutate: vi.fn(),
    });

    renderToolWorkshop();

    await waitFor(() => {
      expect(
        screen.getByText("Guided character methodology"),
      ).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Sin mundo" })).toBeDisabled();
    expect(
      screen.getByText(/No hay mundos disponibles/),
    ).toBeInTheDocument();
  });
});