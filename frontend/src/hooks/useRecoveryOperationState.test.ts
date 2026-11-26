// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { recoveryService } from "../services/recoveryService";
import { useRecoveryOperationState } from "./useRecoveryOperationState";

const listeners = vi.hoisted(() => ({
  progress: undefined as ((event: { operationId?: string; stage: "scan"; completed: number; total: number; message: string }) => void) | undefined,
  backend: undefined as ((event: { state: "starting" | "ready" | "error"; message: string }) => void) | undefined,
  unsubscribeProgress: vi.fn(),
  unsubscribeBackend: vi.fn(),
}));

vi.mock("../services/recoveryService", () => ({
  recoveryService: {
    onProgress: (listener: typeof listeners.progress) => {
      listeners.progress = listener;
      return listeners.unsubscribeProgress;
    },
    onBackendStatus: (listener: typeof listeners.backend) => {
      listeners.backend = listener;
      return listeners.unsubscribeBackend;
    },
    getBackendStatus: vi.fn().mockResolvedValue({ state: "ready", message: "ready" }),
    getPrivilegeStatus: vi.fn().mockResolvedValue({ isAdministrator: true }),
    requestAdministrator: vi.fn(),
  },
}));

afterEach(() => {
  listeners.progress = undefined;
  listeners.backend = undefined;
  listeners.unsubscribeProgress.mockClear();
  listeners.unsubscribeBackend.mockClear();
  vi.mocked(recoveryService.getBackendStatus).mockResolvedValue({ state: "ready", message: "ready" });
});

describe("useRecoveryOperationState subscriptions", () => {
  it("removes progress and backend listeners when the page unmounts", async () => {
    const { result, unmount } = renderHook(() => useRecoveryOperationState());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));

    unmount();

    expect(listeners.unsubscribeProgress).toHaveBeenCalledOnce();
    expect(listeners.unsubscribeBackend).toHaveBeenCalledOnce();
  });

  it("ignores late progress from a finished operation and a stopped backend", async () => {
    const { result } = renderHook(() => useRecoveryOperationState());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    let operationId = "";
    act(() => { operationId = result.current.beginOperation(); });
    act(() => listeners.progress?.({ operationId, stage: "scan", completed: 1, total: 2, message: "active" }));
    expect(result.current.status).toBe("active");

    act(() => result.current.finishOperation(operationId));
    act(() => listeners.progress?.({ operationId, stage: "scan", completed: 2, total: 2, message: "late" }));
    expect(result.current.status).toBe("active");

    act(() => listeners.backend?.({ state: "error", message: "Python process exited" }));
    await waitFor(() => expect(result.current.backendStatus).toBe("error"));
    expect(result.current.error).toBe("Python process exited");
    expect(result.current.status).toBe("The Python recovery process has exited.");
  });

  it("invalidates active progress when the backend session restarts", async () => {
    const { result } = renderHook(() => useRecoveryOperationState());
    await waitFor(() => expect(result.current.backendStatus).toBe("ready"));
    let operationId = "";
    act(() => { operationId = result.current.beginOperation(); });
    act(() => listeners.progress?.({ operationId, stage: "scan", completed: 1, total: 2, message: "old session" }));
    act(() => listeners.backend?.({ state: "starting", message: "restarting" }));
    await waitFor(() => expect(result.current.backendSessionGeneration).toBe(1));
    act(() => listeners.progress?.({ operationId, stage: "scan", completed: 2, total: 2, message: "late old session" }));

    expect(result.current.progress).toBeNull();
    expect(result.current.status).toBe("old session");
  });
});
