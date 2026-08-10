import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ProfilePage from "@/pages/ProfilePage";

vi.mock("@/hooks/useWorlds", () => ({
  useWorlds: () => ({ worlds: [] }),
}));

vi.mock("@/hooks/useLocalDevAuth", () => ({
  useLocalDevAuth: () => ({
    status: {
      mode: "local-dev",
      enabled: true,
      authenticated: true,
      label: "Local development user",
    },
    isLoading: false,
    error: null,
    start: vi.fn(),
    logout: vi.fn(),
  }),
}));

vi.mock("@/components/organisms/Navbar", () => ({
  Navbar: () => <div aria-label="navbar" />,
}));

vi.mock("@/components/organisms/IdeaCapturePanel", () => ({
  IdeaCapturePanel: () => <div>idea capture</div>,
}));

vi.mock("@/components/organisms/AssistantSettingsPanel", () => ({
  AssistantSettingsPanel: () => <div>assistant settings panel</div>,
}));

describe("ProfilePage", () => {
  it("renders the assistant section entry point and panel", () => {
    render(<ProfilePage />);

    fireEvent.click(screen.getByRole("button", { name: "Asistente IA" }));

    expect(screen.getByText("assistant settings panel")).toBeInTheDocument();
  });
});
