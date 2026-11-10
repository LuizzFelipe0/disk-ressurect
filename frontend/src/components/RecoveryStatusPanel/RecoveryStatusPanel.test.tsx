// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RecoveryStatusPanel, getProgressPercent } from "./index";

afterEach(cleanup);

const defaults = {
  status: "Scanning disk…",
  progress: { stage: "scan", completed: 25, total: 100, message: "Scanning disk…" },
  error: "",
  busy: false,
  isAdministrator: true,
  partitionScanCanResume: false,
  selectedDiskNumber: "1",
  backendStatus: "ready" as const,
  onRetryScan: vi.fn(),
  onRequestDiskAccess: vi.fn(),
};

describe("RecoveryStatusPanel", () => {
  it("caps progress and handles an empty total", () => {
    expect(getProgressPercent(defaults.progress)).toBe(25);
    expect(getProgressPercent({ ...defaults.progress, completed: 140 })).toBe(100);
    expect(getProgressPercent({ ...defaults.progress, completed: -4 })).toBe(0);
    expect(getProgressPercent({ ...defaults.progress, total: 0 })).toBe(0);
    expect(getProgressPercent(null)).toBe(0);
  });

  it("shows progress and retries a resumable scan", () => {
    const onRetryScan = vi.fn();
    render(<RecoveryStatusPanel {...defaults} partitionScanCanResume onRetryScan={onRetryScan} />);

    expect(screen.getByRole("status").textContent).toContain("Scanning disk…");
    expect((screen.getByRole("progressbar", { name: "Recovery progress" }) as HTMLProgressElement).value).toBe(25);
    fireEvent.click(screen.getByRole("button", { name: "Retry scan" }));
    expect(onRetryScan).toHaveBeenCalledTimes(1);
  });

  it("shows access, error, and backend notices with their actions", () => {
    const onRequestDiskAccess = vi.fn();
    render(<RecoveryStatusPanel
      {...defaults}
      isAdministrator={false}
      error="Disk read failed"
      backendStatus="error"
      onRequestDiskAccess={onRequestDiskAccess}
    />);

    expect(screen.getByRole("alert").textContent).toContain("Disk read failed");
    expect(screen.getByText("Administrator permission required")).toBeTruthy();
    expect(screen.getByText(/start another Python process/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Request disk access permission" }));
    expect(onRequestDiskAccess).toHaveBeenCalledTimes(1);
  });
});
