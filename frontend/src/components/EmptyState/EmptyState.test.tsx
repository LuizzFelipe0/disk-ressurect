// @vitest-environment jsdom
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { EmptyState } from "./index";

afterEach(cleanup);

describe("EmptyState", () => {
  it("announces its message as a polite status", () => {
    render(<EmptyState>No files found.</EmptyState>);

    expect(screen.getByRole("status").textContent).toContain("No files found.");
    expect(screen.getByRole("status").getAttribute("aria-live")).toBe("polite");
  });

  it("supports a description and a next-step action", () => {
    render(
      <EmptyState title="Catalog is empty" description="Scan a partition to continue." action={<button>Scan disk</button>} />,
    );

    expect(screen.getByText("Scan a partition to continue.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Scan disk" })).toBeTruthy();
  });
});
