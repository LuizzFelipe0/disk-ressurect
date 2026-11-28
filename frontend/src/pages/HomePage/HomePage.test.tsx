// @vitest-environment jsdom
import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { HomePage } from "./index";

vi.mock("../../hooks/useLanguagePreference", () => ({
  useLanguagePreference: () => ({ language: "en-US", changeLanguage: vi.fn() }),
}));

describe("HomePage source options", () => {
  it("offers the physical-disk workflow without a raw-image entry point", () => {
    render(<MemoryRouter><HomePage /></MemoryRouter>);

    expect(screen.getByRole("link", { name: "Choose physical storage" })
      .getAttribute("href")).toBe("/recovery");
    expect(screen.queryByRole("link", { name: /raw image/i })).toBeNull();
    expect(screen.queryByText(/raw disk or partition image/i)).toBeNull();
  });
});
