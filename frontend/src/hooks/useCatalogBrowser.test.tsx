// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useCatalogBrowser } from "./useCatalogBrowser";

const { getChildren, previewFile, searchCatalog } = vi.hoisted(() => ({
  getChildren: vi.fn(), previewFile: vi.fn(), searchCatalog: vi.fn(),
}));
vi.mock("../services/recoveryService", () => ({
  recoveryService: { getChildren, previewFile, searchCatalog },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("useCatalogBrowser session invalidation", () => {
  it("adds loaded child links to the existing parent index", async () => {
    const root = { id: "root", name: "Photos", path: "Photos", isDirectory: true, sizeBytes: 0, hasChildren: true };
    const child = { id: "child", name: "summer.jpg", path: "Photos/summer.jpg", isDirectory: false, sizeBytes: 10, hasChildren: false };
    const setError = vi.fn();
    getChildren.mockResolvedValue([child]);
    const { result } = renderHook(() => useCatalogBrowser(setError));

    act(() => result.current.setRootParents([root]));
    const parentIndex = result.current.parentById;
    await act(async () => { await result.current.toggleFolder(root); });

    expect(result.current.parentById).toBe(parentIndex);
    expect(result.current.parentById.get(child.id)).toBe(root.id);
  });

  it("discards folder results from the catalog that was cleared", async () => {
    const response = deferred<Array<{ id: string; name: string; path: string; isDirectory: boolean; sizeBytes: number; hasChildren: boolean }>>();
    getChildren.mockReturnValue(response.promise);
    const { result } = renderHook(() => useCatalogBrowser(vi.fn()));
    const node = { id: "old-folder", name: "Old", path: "Old", isDirectory: true, sizeBytes: 0, hasChildren: true };
    let pending!: Promise<void>;
    act(() => { pending = result.current.toggleFolder(node); });
    act(() => result.current.clear());
    await act(async () => {
      response.resolve([{ id: "stale-file", name: "old.jpg", path: "Old/old.jpg", isDirectory: false, sizeBytes: 10, hasChildren: false }]);
      await pending;
    });
    expect(result.current.childrenById).toEqual({});
    expect(result.current.expandedFolderIds.size).toBe(0);
    expect(result.current.loadingFolderIds.size).toBe(0);
  });

  it("discards preview results from an invalidated catalog", async () => {
    const response = deferred<{ available: boolean; kind: "image"; dataBase64: string }>();
    previewFile.mockReturnValue(response.promise);
    const { result } = renderHook(() => useCatalogBrowser(vi.fn()));
    const node = { id: "old-file", name: "old.jpg", path: "old.jpg", isDirectory: false, sizeBytes: 10, hasChildren: false };
    let pending!: Promise<void>;
    act(() => { pending = result.current.previewFile(node); });
    act(() => result.current.clear());
    await act(async () => {
      response.resolve({ available: true, kind: "image", dataBase64: "c3RhbGU=" });
      await pending;
    });
    expect(result.current.preview).toBeNull();
    expect(result.current.previewLoading).toBe(false);
  });
});
