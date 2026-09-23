import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ErrorBoundary } from "@/components/ErrorBoundary";

/** React logs every caught boundary error; keep the suite output clean. */
const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

afterEach(() => {
  consoleError.mockClear();
});

let flakyShouldThrow = false;

function Flaky() {
  if (flakyShouldThrow) throw new Error("render boom");
  return <p>Recovered content</p>;
}

function Bomb(): never {
  throw new Error("render boom");
}

describe("ErrorBoundary", () => {
  it("renders its children while no error is thrown", () => {
    render(
      <ErrorBoundary>
        <p>Safe content</p>
      </ErrorBoundary>,
    );

    expect(screen.getByText("Safe content")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reintentar" })).not.toBeInTheDocument();
  });

  it("renders the recoverable fallback instead of unmounting the tree", () => {
    render(
      <ErrorBoundary onReload={vi.fn()}>
        <Bomb />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("heading", { name: "Algo salió mal" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recargar página" })).toBeInTheDocument();
  });

  it("remounts the subtree after the retry action", async () => {
    flakyShouldThrow = true;
    const user = userEvent.setup();

    render(
      <ErrorBoundary>
        <Flaky />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();

    flakyShouldThrow = false;
    await user.click(screen.getByRole("button", { name: "Reintentar" }));

    expect(screen.getByText("Recovered content")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reintentar" })).not.toBeInTheDocument();
  });

  it("invokes the reload action through the reload button", async () => {
    const onReload = vi.fn();
    const user = userEvent.setup();

    render(
      <ErrorBoundary onReload={onReload}>
        <Bomb />
      </ErrorBoundary>,
    );

    await user.click(screen.getByRole("button", { name: "Recargar página" }));

    expect(onReload).toHaveBeenCalledTimes(1);
  });

  it("supports a custom fallback renderer", () => {
    render(
      <ErrorBoundary fallback={(error) => <p>Custom: {error.message}</p>}>
        <Bomb />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Custom: render boom")).toBeInTheDocument();
  });
});
