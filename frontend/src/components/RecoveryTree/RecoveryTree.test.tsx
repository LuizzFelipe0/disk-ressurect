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
});
