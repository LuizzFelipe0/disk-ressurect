// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ScanPage } from "./ScanPage";

const { buildCatalog, state } = vi.hoisted(() => ({
  buildCatalog: vi.fn(),
  state: { selectedVolumeId: "image:volume-1", rawImage: null as unknown, volumes: [], catalog: null as unknown },
}));

vi.mock("../../app/recoverySession", () => ({
  useStorageSession: () => state,
  useRecoveryOperation: () => ({ busy: false }),
  useCatalogSession: () => ({ buildCatalog, catalog: state.catalog }),
}));

afterEach(() => { cleanup(); buildCatalog.mockClear(); });

describe("ScanPage", () => {
  it("starts with the maximum recovery limits and a fresh audit enabled", () => {
    render(<MemoryRouter><ScanPage /></MemoryRouter>);
    expect((screen.getByRole("combobox", { name: "Orçamento de busca em espaço livre" }) as HTMLSelectElement).value).toBe("64");
    expect((screen.getByRole("combobox", { name: "Máximo de candidatos encontrados" }) as HTMLSelectElement).value).toBe("16384");
    expect((screen.getByRole("combobox", { name: "Leitura de candidatos por formato" }) as HTMLSelectElement).value).toBe("1024");
    expect((screen.getByRole("combobox", { name: "Memória máxima para candidatos" }) as HTMLSelectElement).value).toBe("512");
    expect((screen.getByRole("checkbox", { name: /Forçar nova auditoria completa/ }) as HTMLInputElement).checked).toBe(true);
  });

  it("passes the selected maximum budgets and audit policy into catalog construction", () => {
    render(<MemoryRouter><ScanPage /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Montar catálogo" }));
    expect(buildCatalog).toHaveBeenCalledWith(true, {
      scanBudgetGiB: 64, maxFiles: 16384, maxRetainedMiB: 512, maxCandidateReadMiBPerFormat: 1024,
    }, true);
  });
});
