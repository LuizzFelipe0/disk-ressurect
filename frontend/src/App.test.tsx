// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const { recovery } = vi.hoisted(() => ({
  recovery: {
    backendStatus: "ready", isAdministrator: false, busy: false, error: "", status: "Choose a source disk",
    progress: null, partitionScanCanResume: false, disks: [], rawImage: null, selectedDiskNumber: "",
    volumes: [], selectedVolumeId: "", catalog: null, preview: null, previewLoading: false,
    searchQuery: "", searchResult: null, searchingCatalog: false, childrenById: {}, parentById: new Map(),
    loadingFolderIds: new Set(), expandedFolderIds: new Set(), selectedIds: new Set(), excludedIds: new Set(),
    availableExtensions: [], extensions: [], minimumSizeKb: 0, outputDirectory: "",
    refreshDisks: vi.fn(), selectDisk: vi.fn(), selectRawImage: vi.fn(), findPartitions: vi.fn(), selectVolume: vi.fn(),
    buildCatalog: vi.fn(), toggleFolder: vi.fn(), toggleSelection: vi.fn(), isSelected: vi.fn(() => false),
    selectAll: vi.fn(), clearSelection: vi.fn(), previewFile: vi.fn(), chooseOutputDirectory: vi.fn(),
    recover: vi.fn(), setExtensionSelected: vi.fn(), setMinimumSizeKb: vi.fn(), setOutputDirectory: vi.fn(),
    setSearchQuery: vi.fn(), ensureAdministrator: vi.fn(),
  },
}));

vi.mock("./hooks/useRecoveryController", () => ({ useRecoveryController: () => recovery }));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.location.hash = "#/";
});

describe("application navigation", () => {
  it("uses HashRouter routes and protects scan/catalog steps without an active volume", async () => {
    window.location.hash = "#/catalog";
    render(<App />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Armazenamento" })).toBeTruthy());
    expect(screen.getByRole("navigation", { name: "Etapas da recuperação" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Armazenamento" }).getAttribute("aria-current")).toBe("page");
  });

  it("keeps the shared operation status visible while changing routes", async () => {
    recovery.status = "A imagem raw foi selecionada";
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Armazenamento" }));
    await screen.findByRole("heading", { name: "Armazenamento" });
    expect(screen.getAllByRole("status")[0].textContent).toContain("imagem raw");
  });
});
