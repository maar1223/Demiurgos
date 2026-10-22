import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GuidedCharacterPanel } from "@/components/organisms/GuidedCharacterPanel";
import { useGuidedCharacter } from "@/hooks/useGuidedCharacter";
import { useAppLanguage } from "@/hooks/useAppLanguage";
import { translate } from "@/i18n/messages";

vi.mock("@/hooks/useGuidedCharacter", () => ({ useGuidedCharacter: vi.fn() }));
vi.mock("@/hooks/useAppLanguage", () => ({ useAppLanguage: vi.fn() }));
vi.mock("@/api/methodologies", () => ({
  getGuidedMethods: vi.fn(() =>
    Promise.resolve({
      methods: [
        {
          skill_id: "narrative-character-creation",
          version: "1.2",
          name: "Creación de Personajes",
        },
      ],
      default: null,
    }),
  ),
}));

const useGuidedCharacterMock = vi.mocked(useGuidedCharacter);
const useAppLanguageMock = vi.mocked(useAppLanguage);

/** The hook returns `{ language, t }` (AD-3); `t` resolves the real catalogue. */
const lang = (language: "es" | "en") => ({
  language,
  t: (key: Parameters<typeof translate>[1], params?: Parameters<typeof translate>[2]) =>
    translate(language, key, params),
});

const baseState = () => ({
  session: {
    protocol_version: "guided-character-v1",
    session_id: "session-1",
    world: "Vibrantes",
    phase: "review" as const,
    mode: "full" as const,
    depth: "standard" as const,
    revision: 2,
    pending_question: null,
    messages: [{ role: "assistant" as const, content: "What drives them?" }],
    candidate: {
      accepted_canon: {},
      proposals: { desire: { value: "Protect the village", provenance: ["secret"] } },
      unresolved_references: [],
      conflicts: [],
    },
    proposal: {
      key: "desire",
      label: "Desire",
      value: "Protect the village",
      rationale: "A focused starting point",
    },
  },
  isLoading: false,
  error: null,
  send: vi.fn(),
  accept: vi.fn(),
  reject: vi.fn(),
  retryIndex: vi.fn(),
});

describe("GuidedCharacterPanel", () => {
  beforeEach(() => {
    useGuidedCharacterMock.mockReturnValue(baseState());
    useAppLanguageMock.mockReturnValue(lang("es"));
  });

  it("renders one focused prompt and hides provider provenance", () => {
    render(<GuidedCharacterPanel world="Vibrantes" />);

    expect(screen.getByText("What drives them?")).toBeInTheDocument();
    expect(screen.getByText(/Protect the village/)).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
    expect(screen.queryByText(/workflow|provenance/i)).not.toBeInTheDocument();
  });

  it("chooses the method before the first message and sends it with the session start (S6)", async () => {
    const user = userEvent.setup();
    const send = vi.fn();
    useGuidedCharacterMock.mockReturnValue({
      ...baseState(),
      session: null,
      send,
    });
    render(<GuidedCharacterPanel world="Vibrantes" />);

    const select = await screen.findByRole("combobox", {
      name: "Método de esta sesión",
    });
    await user.selectOptions(select, "narrative-character-creation");
    await user.type(
      screen.getByRole("textbox", { name: "Respuesta de creación de personaje" }),
      "Crea a Pert",
    );
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(send).toHaveBeenCalledWith("Crea a Pert", {
      skill_id: "narrative-character-creation",
      version: "1.2",
    });
  });

  it("defaults to the factory method and shows it before the session starts (S6)", async () => {
    useGuidedCharacterMock.mockReturnValue({
      ...baseState(),
      session: null,
    });
    render(<GuidedCharacterPanel world="Vibrantes" />);

    const select = await screen.findByRole("combobox", {
      name: "Método de esta sesión",
    });
    expect(select).toHaveValue("factory");
    expect(
      screen.getByRole("option", { name: "De fábrica (Creación de Personajes)" }),
    ).toBeInTheDocument();
  });

  it("shows the method that drives an existing session (S1)", async () => {
    useGuidedCharacterMock.mockReturnValue({
      ...baseState(),
      session: {
        ...baseState().session,
        methodology: {
          skill_id: "narrative-character-creation",
          skill_version: "1.2",
          flow_type: "guided-character",
          factory: false,
        },
      },
    });
    render(<GuidedCharacterPanel world="Vibrantes" />);
    expect(
      await screen.findByText("Método: Creación de Personajes"),
    ).toBeInTheDocument();
  });

  it("delegates rejection and acceptance without a client-side write", async () => {
    const user = userEvent.setup();
    const state = baseState();
    useGuidedCharacterMock.mockReturnValue(state);
    render(<GuidedCharacterPanel world="Vibrantes" />);

    await user.click(screen.getByRole("button", { name: "Rechazar" }));
    await user.click(screen.getByRole("button", { name: "Aceptar" }));

    expect(state.reject).toHaveBeenCalledTimes(1);
    expect(state.accept).toHaveBeenCalledTimes(1);
  });

  it("offers retry for non-indexed durable creation status", async () => {
    const user = userEvent.setup();
    const state = {
      ...baseState(),
      session: { ...baseState().session, proposal: null, phase: "complete" as const, index_status: "pending" as const },
    };
    useGuidedCharacterMock.mockReturnValue(state);
    render(<GuidedCharacterPanel world="Vibrantes" />);

    await user.click(screen.getByRole("button", { name: "Reintentar" }));

    expect(screen.getByRole("status")).toHaveTextContent("la indexación del grafo está pending");
    expect(state.retryIndex).toHaveBeenCalledTimes(1);
  });

  it("uses English copy when the configured language is en", () => {
    useAppLanguageMock.mockReturnValue(lang("en"));
    const state = baseState();
    useGuidedCharacterMock.mockReturnValue(state);
    render(<GuidedCharacterPanel world="Vibrantes" />);

    expect(screen.getByText("Create a character")).toBeInTheDocument();
    expect(screen.getByText("Suggested detail")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
  });

  it("renders a blocked-safe outcome for an unsupported phase and never infers permission", () => {
    useGuidedCharacterMock.mockReturnValue({
      ...baseState(),
      session: {
        ...baseState().session,
        phase: "blocked" as unknown as "review",
        proposal: {
          key: "desire",
          label: "Desire",
          value: "Protect the village",
        },
      },
    });
    render(<GuidedCharacterPanel world="Vibrantes" />);

    expect(screen.getByRole("alert")).toHaveTextContent(/no se puede actuar/i);
    expect(screen.queryByRole("button", { name: "Aceptar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rechazar" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("renders an English blocked-safe outcome for an unsupported phase", () => {
    useAppLanguageMock.mockReturnValue(lang("en"));
    useGuidedCharacterMock.mockReturnValue({
      ...baseState(),
      session: {
        ...baseState().session,
        phase: "unknown" as unknown as "review",
        proposal: {
          key: "desire",
          label: "Desire",
          value: "Protect the village",
        },
      },
    });
    render(<GuidedCharacterPanel world="Vibrantes" />);

    expect(screen.getByRole("alert")).toHaveTextContent(/cannot safely act/i);
    expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });
});
