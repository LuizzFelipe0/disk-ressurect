// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRecoveryController } from "./useRecoveryController";

const { listDisks, listPartitions, onProgress, getBackendStatus, onBackendStatus, getPrivilegeStatus, requestAdministrator } = vi.hoisted(() => ({
  listDisks: vi.fn(),
  listPartitions: vi.fn(),
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
    listDisks.mockResolvedValue([{ number: 1, model: "Test disk", sizeBytes: 1024, serialNumber: "", displayName: "Disk 1" }]);
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

    expect(listPartitions).toHaveBeenNthCalledWith(1, 1, true, false);
    expect(listPartitions).toHaveBeenNthCalledWith(2, 4, true, true);
    expect(result.current.partitionScanCanResume).toBe(false);
  });
});
