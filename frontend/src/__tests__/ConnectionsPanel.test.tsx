import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import {
  ConnectionsPanel,
  type ConnectionDef,
} from "@/components/molecules/ConnectionsPanel";

const connections: ConnectionDef[] = [
  {
    id: "assistant",
    icon: "demiurgos",
    title: "Asistente de Demiurgos",
    subtitle: "Configuración provider-neutral.",
    status: { label: "Activo", variant: "success" },
    body: <p>cuerpo asistente</p>,
  },
  {
    id: "telegram",
    icon: "lightbulb",
    title: "Captura de ideas",
    subtitle: "Hermes / Telegram.",
    status: { label: "Sin token", variant: "warning" },
    body: <p>cuerpo telegram</p>,
  },
];

describe("ConnectionsPanel", () => {
  it("exposes each row as a toggle button wired to its body region", () => {
    render(
      <ConnectionsPanel
        connections={connections}
        activeId="assistant"
        onSelect={vi.fn()}
      />,
    );

    const assistant = screen.getByRole("button", { name: "Asistente de Demiurgos" });
    const telegram = screen.getByRole("button", { name: "Captura de ideas" });
    expect(assistant).toHaveAttribute("aria-expanded", "true");
    expect(assistant).toHaveAttribute("aria-controls", "connection-assistant-body");
    expect(telegram).toHaveAttribute("aria-expanded", "false");
    expect(telegram).toHaveAttribute("aria-controls", "connection-telegram-body");

    // The heading owning each region carries EXACTLY the title: the subtitle,
    // the badge and the aria-hidden chevron never leak into the accessible name.
    expect(
      screen.getByRole("heading", { name: "Asistente de Demiurgos", level: 3 }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Captura de ideas", level: 3 }),
    ).toBeInTheDocument();
    // The group is a toggle group, never a tablist.
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("keeps both bodies mounted and hides only the inactive one", () => {
    render(
      <ConnectionsPanel
        connections={connections}
        activeId="assistant"
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("cuerpo asistente")).toBeInTheDocument();
    const assistantBody = document.getElementById("connection-assistant-body");
    const telegramBody = document.getElementById("connection-telegram-body");
    expect(assistantBody).not.toHaveAttribute("hidden");
    // The inactive body is still in the DOM (state preserved) but hidden.
    expect(telegramBody).toHaveAttribute("hidden");
    expect(telegramBody).toHaveTextContent("cuerpo telegram");
  });

  it("renders each status badge and reports the selection", () => {
    const onSelect = vi.fn();
    render(
      <ConnectionsPanel
        connections={connections}
        activeId="assistant"
        onSelect={onSelect}
      />,
    );

    expect(screen.getByText("Activo")).toBeInTheDocument();
    expect(screen.getByText("Sin token")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Captura de ideas" }));
    expect(onSelect).toHaveBeenCalledWith("telegram");
  });
});
