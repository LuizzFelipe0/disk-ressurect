// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CatalogNode } from "../../types/recovery";
import { RecoveryTree } from "./index";

afterEach(cleanup);

const folder: CatalogNode = {
  id: "folder-1", name: "Photos", path: "Photos", isDirectory: true, sizeBytes: 0, hasChildren: true,
};
const file: CatalogNode = {
  id: "file-1", name: "holiday.jpg", path: "Photos/holiday.jpg", isDirectory: false, sizeBytes: 2048, hasChildren: false,
};

const makeProps = (overrides: Partial<ComponentProps<typeof RecoveryTree>> = {}) => ({
  roots: [folder],
  childrenById: {},
  expandedFolderIds: new Set<string>(),
  loadingFolderIds: new Set<string>(),
  isSelected: () => false,
  onToggleFolder: vi.fn(),
  onToggleSelection: vi.fn(),
  onPreview: vi.fn(),
  ...overrides,
});

describe("RecoveryTree", () => {
  it("renders an accessible empty state when there are no catalog roots", () => {
    render(<RecoveryTree {...makeProps({ roots: [] })} />);

    expect(screen.getByRole("status").textContent).toContain("No folders or files to display.");
  });

  it("requests lazy folder loading and announces the in-flight state", () => {
    const onToggleFolder = vi.fn();
    const { rerender } = render(<RecoveryTree {...makeProps({ onToggleFolder })} />);
    fireEvent.click(screen.getByRole("button", { name: "Expand Photos" }));
    expect(onToggleFolder).toHaveBeenCalledWith(folder);

    rerender(<RecoveryTree {...makeProps({ onToggleFolder, loadingFolderIds: new Set([folder.id]) })} />);
    expect(screen.getByRole("status").textContent).toContain("Loading contents of Photos");
    expect((screen.getByRole("button", { name: "Expand Photos" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows loaded children and reports checkbox selection changes", () => {
    const onToggleSelection = vi.fn();
    render(<RecoveryTree {...makeProps({
      childrenById: { [folder.id]: [file] },
      expandedFolderIds: new Set([folder.id]),
      onToggleSelection,
    })} />);

    expect(screen.getByText("holiday.jpg")).toBeTruthy();
    expect(screen.getByText("2.0 KB")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select holiday.jpg" }));
    expect(onToggleSelection).toHaveBeenCalledWith(file.id, true);
  });

  it("renders only the viewport and reaches loaded children when scrolled", () => {
    const loadedFiles = Array.from({ length: 100 }, (_, index) => ({
      ...file,
      id: `file-${index}`,
      name: `file-${index}.jpg`,
      path: `Photos/file-${index}.jpg`,
    }));
    render(<RecoveryTree {...makeProps({
      childrenById: { [folder.id]: loadedFiles },
      expandedFolderIds: new Set([folder.id]),
    })} />);

    const viewport = screen.getByRole("tree");
    expect(screen.getByRole("checkbox", { name: "Select file-0.jpg" })).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: "Select file-99.jpg" })).toBeNull();
    expect(screen.getAllByRole("treeitem").length).toBeLessThan(50);

    Object.defineProperty(viewport, "scrollTop", { configurable: true, value: 3_000, writable: true });
    fireEvent.scroll(viewport);

    expect(screen.getByRole("checkbox", { name: "Select file-99.jpg" })).toBeTruthy();
    expect(screen.getAllByRole("treeitem").length).toBeLessThan(50);
  });

  it("keeps a large catalog virtualized while scrolling deep into the list", () => {
    const roots = Array.from({ length: 100_000 }, (_, index) => ({
      ...file,
      id: `large-file-${index}`,
      name: `large-file-${index}.jpg`,
      path: `large-file-${index}.jpg`,
    }));
    render(<RecoveryTree {...makeProps({ roots })} />);
    const viewport = screen.getByRole("tree");

    expect(screen.getAllByRole("treeitem").length).toBeLessThan(50);
    Object.defineProperty(viewport, "scrollTop", { configurable: true, value: 1_800_000, writable: true });
    fireEvent.scroll(viewport);

    expect(screen.getByRole("checkbox", { name: "Select large-file-50000.jpg" })).toBeTruthy();
    expect(screen.getAllByRole("treeitem").length).toBeLessThan(50);
  });

  it("opens an image preview without changing the recovery checkbox", () => {
    const onPreview = vi.fn();
    render(<RecoveryTree {...makeProps({ roots: [file], onPreview })} />);

    fireEvent.click(screen.getByRole("button", { name: "Preview holiday.jpg" }));

    expect(onPreview).toHaveBeenCalledWith(file);
    expect(screen.getByRole("checkbox", { name: "Select holiday.jpg" })).toBeTruthy();
  });

  it("labels deleted orphan records explicitly", () => {
    render(<RecoveryTree {...makeProps({
      roots: [{ ...file, isDeleted: true, isOrphaned: true }],
    })} />);

    expect(screen.getByText("Found outside the list")).toBeTruthy();
  });

  it("labels records recovered by exact USN and MFT evidence", () => {
    render(<RecoveryTree {...makeProps({
      roots: [{ ...file, recoverySource: "usn_journal_mft" }],
    })} />);

    expect(screen.getByText("Recovered using USN and MFT evidence")).toBeTruthy();
  });

  it("shows resolved and inconclusive fragmented data evidence", () => {
    render(<RecoveryTree {...makeProps({ roots: [
      { ...file, id: "resolved", dataExtentResolution: "resolved", dataExtentCount: 2 },
      { ...file, id: "uncertain", name: "uncertain.jpg", dataExtentResolution: "inconclusive",
        dataExtentResolutionReason: "data_extent_vcn_gap_or_overlap" },
    ] })} />);

    expect(screen.getByText(/Fragmented data map reconstructed \(2 extents\)/)).toBeTruthy();
    expect(screen.getByText(/Fragmented data map is inconclusive/)
      .getAttribute("title")).toBe("data_extent_vcn_gap_or_overlap");
  });

  it("shows translated fragmented data evidence in Portuguese", () => {
    render(<RecoveryTree {...makeProps({
      language: "pt-BR",
      roots: [{ ...file, dataExtentResolution: "resolved", dataExtentCount: 2 }],
    })} />);

    expect(screen.getByText(/Mapa de dados fragmentado reconstruído \(2 partes\)/)).toBeTruthy();
  });

  it("shows signature and cluster allocation evidence for orphan candidates", () => {
    render(<RecoveryTree {...makeProps({
      roots: [{ ...file, isDeleted: true, isOrphaned: true,
        contentValidation: "signature_match", clusterAllocationStatus: "free" }],
    })} />);

    expect(screen.getByText(/Header matches extension/)).toBeTruthy();
    expect(screen.getByText(/Clusters marked free/)).toBeTruthy();
  });

  it("labels raw carved content as a generated-name candidate", () => {
    render(<RecoveryTree {...makeProps({
      roots: [{ ...file, name: "Carved_0000000000001000.jpg", isOrphaned: true, isContentCarved: true }],
    })} />);

    expect(screen.getByText("Raw-carved file candidate")).toBeTruthy();
  });

  it("labels a Recycle Bin recovery alias and exposes its original path", () => {
    render(<RecoveryTree {...makeProps({ roots: [{
      ...file,
      name: "Recovered_0123456789ab_report.pdf",
      path: "Lost_Files_DeepScan/RecycleBin/Recovered_0123456789ab_report.pdf",
      recoverySource: "recycle_bin",
      originalPath: "C:\\Users\\sample\\Documents\\report.pdf",
      deletionTimestampUtc: "2026-11-20T10:30:00+00:00",
    }] })} />);

    screen.getByText("Recovered_0123456789ab_report.pdf");
    expect(screen.getByText("Recovered through Recycle Bin metadata")).toBeTruthy();
    expect(screen.getByTitle(/Original path/).getAttribute("title"))
      .toContain("C:\\Users\\sample\\Documents\\report.pdf");
  });

  it("labels low-confidence carving allocation statuses", () => {
    render(<RecoveryTree {...makeProps({ roots: [
      { ...file, name: "Possible_current.jpg", isContentCarved: true, clusterAllocationStatus: "bitmap_unobserved" },
      { ...file, id: "reused", name: "Possibly_reused.jpg", isContentCarved: true, clusterAllocationStatus: "possibly_reused" },
    ] })} />);

    expect(screen.getByText(/Bitmap was not observed; data may be current/)).toBeTruthy();
    expect(screen.getByText(/Clusters may contain reused data; deletion is unconfirmed/)).toBeTruthy();
  });
});
