// @vitest-environment jsdom
import React from "react";
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { StoragePage } from "./StoragePage";

const { selectRawImage } = vi.hoisted(() => ({ selectRawImage: vi.fn() }));
vi.mock("../../app/recoverySession", () => ({
  useStorageSession: () => ({
    rawImage: null, selectedDiskNumber: "", disks: [], volumes: [], selectedVolumeId: "",
    selectRawImage, refreshDisks: vi.fn(), findPartitions: vi.fn(), selectDisk: vi.fn(), selectVolume: vi.fn(),
  }),
  useRecoveryOperation: () => ({ busy: false, backendStatus: "ready" }),
}));

afterEach(() => { cleanup(); selectRawImage.mockClear(); });

describe("StoragePage raw image route", () => {
  it("opens the Electron picker for the image source route", async () => {
    render(<MemoryRouter initialEntries={["/storage?source=image"]}>
      <Routes><Route path="/storage" element={<StoragePage />} /></Routes>
    </MemoryRouter>);
    await waitFor(() => expect(selectRawImage).toHaveBeenCalledOnce());
  });
});
