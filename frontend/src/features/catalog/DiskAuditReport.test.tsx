// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LanguageProvider } from "../../app/language";
import { DiskAuditReport } from "./DiskAuditReport";
import type { CatalogInfo } from "../../types/recovery";

const catalog: CatalogInfo = {
  recordCount: 299,
  orphanedRecordCount: 10833,
  contentCarvedCount: 256,
  orphanScanPerformed: true,
  roots: [],
  availableExtensions: [".jpg", ".png"],
  diskValidation: {
    coverageStatus: "complete", assessment: "inconclusive", evidenceFreshness: "fresh",
    bytesRead: 100, sizeBytes: 100, readErrorCount: 0, partitionCount: 1, ntfsVolumeCount: 1,
    deletedMftRecordCount: 1, orphanedFileRecordCount: 10833, inconsistentMftRecordCount: 0,
    unsupportedFilesystems: [],
    orphanRecordsByAllocationStatus: { free: 9910, allocated: 0, mixed: 2, unknown: 921 },
  },
  contentCarving: {
    filesFound: 256, bytesScanned: 1024, scanLimitReached: true, candidateBytesRead: 512,
    candidateLimitReached: true, fileCountLimitReached: false, retainedBytesLimitReached: false,
    rangeCount: 1, rangeCollectionTruncated: false, formatsAttempted: [".jpg", ".png"],
    filesFoundByExtension: { ".jpg": 190, ".png": 66 },
    candidatesExaminedByExtension: { ".jpg": 310, ".png": 215 },
    candidateBytesReadByExtension: { ".jpg": 256, ".png": 256 },
    candidateLimitReachedByExtension: { ".jpg": true }, candidateReadCapBytes: 805306368,
    candidateReadCapBytesPerFormat: 268435456, scanByteCap: 1073741824, maxFileBytes: 33554432,
    maxDecodedPngBytes: 67108864, retainedBytesCap: 134217728, fileCountCap: 256,
    validationScope: "contiguous_structure_and_signature",
  },
  lowConfidenceCarving: {
    bitmapUnobserved: {
      filesFound: 0, bytesScanned: 0, scanLimitReached: false, candidateBytesRead: 0,
      candidateLimitReached: false, fileCountLimitReached: false, retainedBytesLimitReached: false,
      rangeCount: 0, rangeCollectionTruncated: false, confidence: "low",
      allocationStatus: "bitmap_unobserved", catalogItemsAdded: 0, formatsAttempted: [".jpg"],
    },
    possiblyReused: {
      filesFound: 0, bytesScanned: 1024, scanLimitReached: false, candidateBytesRead: 0,
      candidateLimitReached: false, fileCountLimitReached: false, retainedBytesLimitReached: false,
      rangeCount: 1, rangeCollectionTruncated: false, confidence: "low",
      allocationStatus: "possibly_reused", catalogItemsAdded: 0, formatsAttempted: [".jpg"],
    },
  },
};

afterEach(() => { cleanup(); });

const renderReport = () => render(<LanguageProvider><DiskAuditReport catalog={catalog} /></LanguageProvider>);

describe("DiskAuditReport", () => {
  it("keeps the catalog summary clean and shows complete carving and allocation evidence in an overlay", async () => {
    renderReport();
    expect(screen.queryByText(/A auditoria do disco inteiro é inconclusiva/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Detalhes da auditoria do disco" }));
    const dialog = await screen.findByRole("dialog", { name: "Detalhes da auditoria do disco" });
    expect(within(dialog).getByText(/A auditoria do disco inteiro é inconclusiva/)).toBeTruthy();
    expect(within(dialog).getByText(/Registros órfãos por status de alocação/)).toBeTruthy();
    expect(within(dialog).getByText(/\.jpg: 190 candidato\(s\) encontrado\(s\), 310 candidato\(s\) examinado\(s\)/)).toBeTruthy();
    expect(within(dialog).getByRole("heading", { name: "Bitmap não observado; os dados podem ser atuais" })).toBeTruthy();
    expect(within(dialog).getByRole("heading", { name: "Os clusters podem conter dados reutilizados; exclusão não confirmada" })).toBeTruthy();
    const trigger = screen.getByRole("button", { name: "Detalhes da auditoria do disco" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Fechar" }));
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("identifies cached evidence as a historical snapshot", async () => {
    catalog.diskValidation!.coverageStatus = "cached_snapshot";
    catalog.diskValidation!.evidenceFreshness = "cached_snapshot";
    catalog.diskValidation!.evidenceScannedAt = "2026-11-23T12:00:00+00:00";
    renderReport();
    fireEvent.click(screen.getByRole("button", { name: "Detalhes da auditoria do disco" }));
    const dialog = await screen.findByRole("dialog", { name: "Detalhes da auditoria do disco" });
    expect(within(dialog).getByText(/A cobertura de leitura é um registro histórico de 2026-11-23/)).toBeTruthy();
    catalog.diskValidation!.coverageStatus = "complete";
    catalog.diskValidation!.evidenceFreshness = "fresh";
    catalog.diskValidation!.evidenceScannedAt = undefined;
  });
});
