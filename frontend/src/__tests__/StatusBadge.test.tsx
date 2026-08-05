import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StatusBadge } from "@/components/molecules/StatusBadge";
import { ApiError } from "@/api/types";

describe("StatusBadge", () => {
  it("renders the Borrador chip for draft status", () => {
    render(<StatusBadge status="draft" onStatusChange={vi.fn()} />);

    expect(
      screen.getByRole("button", { name: "Estado: Borrador" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Borrador")).toBeInTheDocument();
  });

  it("renders the Canon chip for stable status", () => {
    render(<StatusBadge status="stable" onStatusChange={vi.fn()} />);

    expect(
      screen.getByRole("button", { name: "Estado: Canon" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Canon")).toBeInTheDocument();
  });

  it("opens the dropdown on click with both radio options", async () => {
    const user = userEvent.setup();
    render(<StatusBadge status="draft" onStatusChange={vi.fn()} />);

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Estado: Borrador" }));

    const menu = screen.getByRole("menu");
    expect(
      within(menu).getByRole("menuitemradio", { name: /borrador/i }),
    ).toBeInTheDocument();
    expect(
      within(menu).getByRole("menuitemradio", { name: /canon/i }),
    ).toBeInTheDocument();
  });

  it("calls onStatusChange with the selected status and closes", async () => {
    const onStatusChange = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<StatusBadge status="draft" onStatusChange={onStatusChange} />);

    await user.click(screen.getByRole("button", { name: "Estado: Borrador" }));
    await user.click(
      within(screen.getByRole("menu")).getByRole("menuitemradio", {
        name: /canon/i,
      }),
    );

    expect(onStatusChange).toHaveBeenCalledWith("stable");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("does not call onStatusChange when re-selecting the current status", async () => {
    const onStatusChange = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<StatusBadge status="stable" onStatusChange={onStatusChange} />);

    await user.click(screen.getByRole("button", { name: "Estado: Canon" }));
    await user.click(
      within(screen.getByRole("menu")).getByRole("menuitemradio", {
        name: /canon/i,
      }),
    );

    expect(onStatusChange).not.toHaveBeenCalled();
  });

  it("shows the error inline and keeps the dropdown open when the mutation fails", async () => {
    const onStatusChange = vi
      .fn()
      .mockRejectedValue(
        new ApiError(
          500,
          "Error interno del servidor. Revisá los logs del backend.",
          "Error interno del servidor. Revisá los logs del backend.",
        ),
      );
    const user = userEvent.setup();
    render(<StatusBadge status="draft" onStatusChange={onStatusChange} />);

    await user.click(screen.getByRole("button", { name: "Estado: Borrador" }));
    await user.click(
      within(screen.getByRole("menu")).getByRole("menuitemradio", {
        name: /canon/i,
      }),
    );

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent(/error interno del servidor/i);
    // Chip unchanged, dropdown still open for a retry
    expect(
      screen.getByRole("button", { name: "Estado: Borrador" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<StatusBadge status="draft" onStatusChange={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Estado: Borrador" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
