// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRecoveryController } from "./useRecoveryController";

const { listDisks, listPartitions, scanCatalog, searchCatalog, listSupportedFileTypes, previewFile, recover, onProgress, getBackendStatus, onBackendStatus, getPrivilegeStatus, requestAdministrator } = vi.hoisted(() => ({
  listDisks: vi.fn(),
  listPartitions: vi.fn(),
  scanCatalog: vi.fn(),
  searchCatalog: vi.fn(),
  listSupportedFileTypes: vi.fn(),
  previewFile: vi.fn(),
  recover: vi.fn(),
  onProgress: vi.fn(() => vi.fn()),
  getBackendStatus: vi.fn(),
  onBackendStatus: vi.fn(() => vi.fn()),
  getPrivilegeStatus: vi.fn(),
  requestAdministrator: vi.fn(),
}));

vi.mock("../services/recoveryService", () => ({
  recoveryService: {
    listDisks,
    listPartitions,
    scanCatalog,
    searchCatalog,
    listSupportedFileTypes,
    previewFile,
    recover,
    onProgress,
    getBackendStatus,
    onBackendStatus,
    getPrivilegeStatus,
    requestAdministrator,
  },
}));

describe("useRecoveryController backend lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    listDisks.mockResolvedValue([{ number: 1, model: "Test disk", sizeBytes: 1024, serialNumber: "", displayName: "Disk 1" }]);
    listSupportedFileTypes.mockResolvedValue([".jpg", ".pdf"]);
    getBackendStatus.mockResolvedValue({ state: "ready", message: "Python service is ready" });
    getPrivilegeStatus.mockResolvedValue({ isAdministrator: true });
    requestAdministrator.mockResolvedValue({ relaunched: false, cancelled: true });
  });

  it("loads disks and marks the Python service ready", async () => {
    const { result } = renderHook(() => useRecoveryController());

    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    expect(result.current.disks).toHaveLength(1);
    expect(result.current.status).toContain("Choose a source disk");
    expect(listDisks).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.availableExtensions).toEqual([".jpg", ".pdf"]));
    expect(result.current.extensions).toEqual([".jpg", ".pdf"]);
  });

  it("searches a built catalog and stores parent ids for matching nodes", async () => {
    const root = { id: "n0", name: "Photos", path: "Photos", isDirectory: true, sizeBytes: 0, hasChildren: true, parentId: null };
    const match = { id: "n1", name: "Trip.jpg", path: "Photos/Trip.jpg", isDirectory: false, sizeBytes: 20, hasChildren: false, parentId: "n0", ancestorIds: ["n0"] };
    scanCatalog.mockResolvedValue({ recordCount: 2, availableExtensions: [".jpg"], roots: [root] });
    searchCatalog.mockResolvedValue({ totalMatches: 1, results: [match] });
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    act(() => result.current.selectVolume("1:4096"));
    let built = false;
    await act(async () => { built = await result.current.buildCatalog(); });
    expect(built).toBe(true);
    expect(scanCatalog).toHaveBeenCalledWith("1:4096", false, undefined, false, expect.any(String));

    act(() => result.current.setSearchQuery("trip"));
    await waitFor(() => expect(result.current.searchResult?.results).toEqual([match]));
    expect(searchCatalog).toHaveBeenCalledWith("trip");
    act(() => result.current.toggleSelection("n0", true));
    expect(result.current.isSelected("n1")).toBe(true);
  });

  it("passes the opt-in orphan scan flag to the catalog service", async () => {
    const diskValidation = {
      coverageStatus: "complete" as const,
      assessment: "inconclusive" as const,
      bytesRead: 100,
      sizeBytes: 100,
      readErrorCount: 0,
      partitionCount: 1,
      ntfsVolumeCount: 1,
      deletedMftRecordCount: 2,
      orphanedFileRecordCount: 1,
      unsupportedFilesystems: [],
    };
    scanCatalog.mockResolvedValue({ recordCount: 1, availableExtensions: [".jpg"], roots: [], diskValidation });
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    act(() => result.current.selectVolume("1:4096"));

    await act(async () => { await result.current.buildCatalog(true); });

    expect(scanCatalog).toHaveBeenCalledWith("1:4096", true, undefined, false, expect.any(String));
    expect(result.current.catalog?.diskValidation).toEqual(diskValidation);
  });

  it("clears the previous catalog selection as soon as a rebuild starts", async () => {
    const previousCatalog = {
      recordCount: 1,
      availableExtensions: [".jpg"],
      roots: [{ id: "old-root", name: "Old", path: "Old", isDirectory: true, sizeBytes: 0, hasChildren: false }],
    };
    scanCatalog.mockResolvedValueOnce(previousCatalog);
    let finishBuild!: (value: typeof previousCatalog) => void;
    scanCatalog.mockReturnValueOnce(new Promise((resolve) => { finishBuild = resolve; }));
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    act(() => result.current.selectVolume("1:4096"));
    await act(async () => { await result.current.buildCatalog(); });
    act(() => result.current.selectAll());
    expect(result.current.selectedIds).toEqual(new Set(["old-root"]));

    let pendingBuild!: Promise<boolean>;
    act(() => { pendingBuild = result.current.buildCatalog(); });
    await waitFor(() => expect(result.current.catalog).toBeNull());
    expect(result.current.selectedIds).toEqual(new Set());

    await act(async () => {
      finishBuild({ ...previousCatalog, roots: [{ ...previousCatalog.roots[0], id: "new-root" }] });
      await pendingBuild;
    });
    expect(result.current.catalog?.roots[0].id).toBe("new-root");
  });

  it("does not send duplicate catalog commands while one build is in flight", async () => {
    let finishBuild!: (value: { recordCount: number; availableExtensions: string[]; roots: never[] }) => void;
    scanCatalog.mockReturnValueOnce(new Promise((resolve) => { finishBuild = resolve; }));
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    act(() => result.current.selectVolume("1:4096"));

    let first!: Promise<boolean>;
    let duplicate!: Promise<boolean>;
    act(() => {
      first = result.current.buildCatalog();
      duplicate = result.current.buildCatalog();
    });
    await waitFor(() => expect(scanCatalog).toHaveBeenCalledTimes(1));
    await act(async () => {
      finishBuild({ recordCount: 0, availableExtensions: [], roots: [] });
      expect(await duplicate).toBe(false);
      expect(await first).toBe(true);
    });
    expect(scanCatalog).toHaveBeenCalledTimes(1);
  });

  it("does not send duplicate recovery commands while extraction is in flight", async () => {
    scanCatalog.mockResolvedValue({
      recordCount: 1, availableExtensions: [".jpg"],
      roots: [{ id: "photo", name: "photo.jpg", path: "photo.jpg", isDirectory: false, sizeBytes: 8, hasChildren: false }],
    });
    let finishRecovery!: (value: { candidateCount: number; recoveredCount: number }) => void;
    recover.mockReturnValueOnce(new Promise((resolve) => { finishRecovery = resolve; }));
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.extensions).toEqual([".jpg", ".pdf"]));
    act(() => result.current.selectVolume("1:4096"));
    await act(async () => { await result.current.buildCatalog(); });
    act(() => {
      result.current.selectAll();
      result.current.setOutputDirectory("D:\\Recovered");
    });

    let first!: Promise<void>;
    let duplicate!: Promise<void>;
    act(() => {
      first = result.current.recover();
      duplicate = result.current.recover();
    });
    await waitFor(() => expect(recover).toHaveBeenCalledTimes(1));
    await act(async () => {
      finishRecovery({ candidateCount: 1, recoveredCount: 1 });
      await Promise.all([first, duplicate]);
    });
    expect(recover).toHaveBeenCalledTimes(1);
  });

  it("ignores a catalog response after its source volume changes", async () => {
    let finishBuild!: (value: { recordCount: number; availableExtensions: string[]; roots: never[] }) => void;
    scanCatalog.mockReturnValueOnce(new Promise((resolve) => { finishBuild = resolve; }));
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    act(() => result.current.selectVolume("1:4096"));

    let pendingBuild!: Promise<boolean>;
    act(() => { pendingBuild = result.current.buildCatalog(); });
    await waitFor(() => expect(scanCatalog).toHaveBeenCalledTimes(1));
    act(() => result.current.selectVolume("2:8192"));
    await act(async () => {
      finishBuild({ recordCount: 1, availableExtensions: [".jpg"], roots: [] });
      await pendingBuild;
    });

    expect(result.current.selectedVolumeId).toBe("2:8192");
    expect(result.current.catalog).toBeNull();
  });

  it("passes the selected bounded carving budgets to the catalog service", async () => {
    scanCatalog.mockResolvedValue({ recordCount: 1, availableExtensions: [".jpg"], roots: [] });
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    act(() => result.current.selectVolume("1:4096"));

    const carvingOptions = {
        scanBudgetGiB: 16 as const, maxFiles: 16384 as const, maxRetainedMiB: 256 as const,
        maxCandidateReadMiBPerFormat: 1024 as const,
    };
    await act(async () => { await result.current.buildCatalog(true, carvingOptions); });

    expect(scanCatalog).toHaveBeenCalledWith("1:4096", true, carvingOptions, false, expect.any(String));
  });

  it("forwards an explicit request for a fresh full-disk validation", async () => {
    scanCatalog.mockResolvedValue({ recordCount: 1, availableExtensions: [], roots: [] });
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    act(() => result.current.selectVolume("1:4096"));

    await act(async () => {
      await result.current.buildCatalog(true, undefined, true);
    });

    expect(scanCatalog).toHaveBeenCalledWith("1:4096", true, undefined, true, expect.any(String));
  });

  it("loads a preview for the chosen file and clears it when the source changes", async () => {
    const file = { id: "n0", name: "photo.jpg", path: "photo.jpg", isDirectory: false, sizeBytes: 8, hasChildren: false };
    previewFile.mockResolvedValue({ available: true, name: "photo.jpg", mimeType: "image/jpeg", kind: "image", sizeBytes: 8, dataBase64: "AA==" });
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));

    await act(async () => { await result.current.previewFile(file); });

    expect(previewFile).toHaveBeenCalledWith("n0");
    expect(result.current.preview?.available).toBe(true);
    act(() => result.current.selectVolume("1:4096"));
    expect(result.current.preview).toBeNull();
  });

  it("restores saved deep-scan candidates when switching back to a disk", async () => {
    const savedCandidate = {
      id: "1:4096", diskNumber: 1, partitionNumber: 0, offset: 4096,
      sizeBytes: 8192, estimatedSize: true, name: "Lost NTFS candidate",
      scanSavedAt: "2026-10-27T12:00:00+00:00",
    };
    listDisks.mockResolvedValueOnce([{
      number: 1, model: "Test disk", sizeBytes: 1024, serialNumber: "test",
      displayName: "Disk 1", cachedPartitions: [savedCandidate],
    }]);
    const { result } = renderHook(() => useRecoveryController());

    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    act(() => result.current.selectDisk("1"));
    act(() => result.current.selectDisk(""));
    act(() => result.current.selectDisk("1"));

    expect(result.current.volumes).toEqual([savedCandidate]);
    expect(result.current.status).toContain("saved deep-scan candidate");
    expect(listPartitions).not.toHaveBeenCalled();
  });

  it("restores the single cached source disk and its candidates after application startup", async () => {
    const savedCandidate = {
      id: "1:4096", diskNumber: 1, partitionNumber: 0, offset: 4096,
      sizeBytes: 8192, estimatedSize: true, name: "Lost NTFS candidate",
      scanSavedAt: "2026-10-27T12:00:00+00:00",
    };
    listDisks.mockResolvedValueOnce([{
      number: 1, model: "Test disk", sizeBytes: 1024, serialNumber: "test",
      displayName: "Disk 1", cachedPartitions: [savedCandidate],
    }]);

    const { result } = renderHook(() => useRecoveryController());

    await waitFor(() => expect(result.current.volumes).toEqual([savedCandidate]));
    expect(result.current.selectedDiskNumber).toBe("1");
    expect(result.current.status).toContain("restored");
    expect(listPartitions).not.toHaveBeenCalled();
  });

  it("shows a useful error when disk discovery fails while the bridge is active", async () => {
    listDisks.mockRejectedValueOnce(new Error("Python executable was not found"));
    const { result } = renderHook(() => useRecoveryController());

    await waitFor(() => expect(result.current.status).toContain("Disk discovery failed"));
    expect(result.current.backendStatus).toBe("ready");
    expect(result.current.error).toBe("Python executable was not found");
  });

  it("distinguishes a stopped Python process from a disk query error", async () => {
    getBackendStatus.mockResolvedValue({ state: "error", message: "Python process exited" });
    listDisks.mockRejectedValueOnce(new Error("Python process stopped"));
    const { result } = renderHook(() => useRecoveryController());

    await waitFor(() => expect(result.current.backendStatus).toBe("error"));
    expect(result.current.error).toBe("Python process exited");
    expect(result.current.status).toContain("Python recovery process");
  });

  it("does not issue duplicate startup requests when React replays effects", async () => {
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));

    await act(async () => Promise.resolve());
    expect(listDisks).toHaveBeenCalledTimes(1);
  });

  it("does not scan a physical disk when administrator permission is declined", async () => {
    getPrivilegeStatus.mockResolvedValue({ isAdministrator: false });
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));

    act(() => result.current.selectDisk("0"));
    await act(async () => { await result.current.findPartitions(false); });

    expect(requestAdministrator).toHaveBeenCalledTimes(1);
    expect(listPartitions).not.toHaveBeenCalled();
    expect(result.current.status).toContain("canceled");
  });

  it("does not issue a duplicate partition scan while one request is pending", async () => {
    let finishScan!: (value: never[]) => void;
    listPartitions.mockReturnValueOnce(new Promise((resolve) => { finishScan = resolve; }));
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    act(() => result.current.selectDisk("1"));

    let first!: Promise<void>;
    let duplicate!: Promise<void>;
    act(() => {
      first = result.current.findPartitions(false);
      duplicate = result.current.findPartitions(false);
    });
    await waitFor(() => expect(listPartitions).toHaveBeenCalledTimes(1));
    await act(async () => {
      finishScan([]);
      await Promise.all([first, duplicate]);
    });
    expect(listPartitions).toHaveBeenCalledTimes(1);
  });

  it("retries a failed deep scan by resuming its saved position", async () => {
    listDisks.mockResolvedValueOnce([{
      number: 1, model: "Test disk", sizeBytes: 1024, serialNumber: "USB-1", displayName: "Disk 1",
    }]);
    const { result } = renderHook(() => useRecoveryController());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    act(() => result.current.selectDisk("1"));
    listDisks.mockResolvedValueOnce([{
      number: 4, model: "Test disk", sizeBytes: 1024, serialNumber: "USB-1",
      displayName: "Disk 4", deepScanResumeAvailable: true,
    }]);
    listPartitions.mockRejectedValueOnce(new Error("USB read failed"));

    await act(async () => { await result.current.findPartitions(true); });
    expect(result.current.partitionScanCanResume).toBe(true);
    expect(result.current.error).toBe("USB read failed");

    listPartitions.mockResolvedValueOnce([]);
    await act(async () => { await result.current.findPartitions(true, true); });

    expect(listPartitions).toHaveBeenNthCalledWith(1, 1, true, false, expect.any(String));
    expect(listPartitions).toHaveBeenNthCalledWith(2, 4, true, true, expect.any(String));
    expect(result.current.partitionScanCanResume).toBe(false);
  });
});
