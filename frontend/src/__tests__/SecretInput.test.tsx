import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ComponentProps } from "react";
import { SecretInput } from "@/components/molecules/SecretInput";

/** Controlled wrapper mirroring real usage (value + onChange from state). */
function ControlledSecretInput(props: ComponentProps<typeof SecretInput>) {
  const [value, setValue] = useState("");
  return (
    <SecretInput
      {...props}
      value={value}
      onChange={(event) => {
        setValue(event.target.value);
        props.onChange?.(event);
      }}
    />
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SecretInput", () => {
  it("masks the value by default and toggles between text and password", async () => {
    const user = userEvent.setup();
    render(<ControlledSecretInput aria-label="Secret" />);

    const input = screen.getByLabelText("Secret");
    expect(input).toHaveAttribute("type", "password");

    await user.type(input, "hunter2");
    await user.click(screen.getByRole("button", { name: "Mostrar" }));
    expect(input).toHaveAttribute("type", "text");

    await user.click(screen.getByRole("button", { name: "Ocultar" }));
    expect(input).toHaveAttribute("type", "password");
  });

  it("copies the value, shows Copiado briefly, then reverts to Copiar", async () => {
    const user = userEvent.setup();
    // user-event's setup() installs its own clipboard stub, so ours must be
    // defined AFTER setup; we assert on the local reference, not the global.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    render(<ControlledSecretInput copyable aria-label="Secret" />);

    const input = screen.getByLabelText("Secret");
    await user.type(input, "clave-super-secreta");
    await user.click(screen.getByRole("button", { name: "Copiar" }));

    expect(writeText).toHaveBeenCalledWith("clave-super-secreta");
    // The aria-label stays "Copiar"; the visible text flips to "Copiado".
    expect(screen.getByRole("button", { name: "Copiar" })).toHaveTextContent(
      "Copiado",
    );

    await waitFor(
      () =>
        expect(
          screen.getByRole("button", { name: "Copiar" }),
        ).toHaveTextContent("Copiar"),
      { timeout: 2500 },
    );
  });

  it("disables the toggle and copy buttons while the field is empty", () => {
    render(<SecretInput copyable aria-label="Secret" />);

    expect(screen.getByRole("button", { name: "Mostrar" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Copiar" })).toBeDisabled();
  });

  it("is accessible: labeled input and labeled action buttons", () => {
    render(<SecretInput copyable aria-label="Token del bot" />);

    expect(screen.getByLabelText("Token del bot")).toHaveAttribute(
      "type",
      "password",
    );
    expect(screen.getByRole("button", { name: "Mostrar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copiar" })).toBeInTheDocument();
  });

  it("works uncontrolled and re-syncs button state after an external clear", async () => {
    const user = userEvent.setup();
    const ref = { current: null as HTMLInputElement | null };
    const { rerender } = render(
      <SecretInput ref={ref} copyable aria-label="Secret" />,
    );

    const input = screen.getByLabelText("Secret");
    await user.type(input, "abc");
    expect(screen.getByRole("button", { name: "Copiar" })).toBeEnabled();
    expect(ref.current).toBeInstanceOf(HTMLInputElement);

    // Simulate a parent clearing the field through the ref (like the
    // assistant panel's clear()/save()), followed by a parent re-render.
    if (ref.current) ref.current.value = "";
    rerender(<SecretInput ref={ref} copyable aria-label="Secret" />);

    expect(screen.getByRole("button", { name: "Copiar" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Mostrar" })).toBeDisabled();
  });
});