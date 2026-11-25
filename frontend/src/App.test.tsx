// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./pages/RecoveryPage", () => ({
  RecoveryPage: () => <h1>Recovery workflow</h1>,
}));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.location.hash = "#/";
});

describe("application entry", () => {
  it("shows a homepage before opening the existing recovery workflow", async () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Recupere arquivos com segurança" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Iniciar recuperação" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Recovery workflow" })).toBeTruthy());
  });

  it("redirects unknown routes to the homepage", async () => {
    window.location.hash = "#/unknown-route";
    render(<App />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Recupere arquivos com segurança" })).toBeTruthy());
  });
});
