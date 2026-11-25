// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HashRouter } from "react-router-dom";
import type { RecoveryResult } from "../../types/recovery";
import { RecoveryPage } from "./index";

const { recovery } = vi.hoisted(() => ({
  recovery: {
    backendStatus: "ready",
    isAdministrator: true,
    busy: false,
    error: "",
    status: "Catalog ready",
    progress: null,
    partitionScanCanResume: false,
    disks: [],
    rawImage: null,
    selectedDiskNumber: "1",
    volumes: [],
    selectedVolumeId: "1:4096",
    catalog: {
      recordCount: 42,
      orphanedRecordCount: 0,
      contentCarvedCount: 0,
      orphanScanPerformed: true,
      availableExtensions: [],
      roots: [],
      diskValidation: {
        coverageStatus: "complete",
        assessment: "inconclusive",
        bytesRead: 100,
        sizeBytes: 100,
        readErrorCount: 0,
        partitionCount: 1,
        ntfsVolumeCount: 1,
        deletedMftRecordCount: 0,
        orphanedFileRecordCount: 10833,
        inconsistentMftRecordCount: 0,
        orphanRecordsByAllocationStatus: { free: 9910, allocated: 0, mixed: 2, unknown: 921 },
      },
      contentCarving: {
        filesFound: 0,
        bytesScanned: 168820736,
        scanLimitReached: false,
        candidateBytesRead: 536870912,
        candidateLimitReached: true,
        fileCountLimitReached: false,
        retainedBytesLimitReached: false,
        rangeCount: 1,
        rangeCollectionTruncated: false,
        filesFoundByExtension: { ".jpg": 0, ".png": 0, ".pdf": 0 },
        candidatesExaminedByExtension: { ".jpg": 12, ".png": 8, ".pdf": 1 },
        candidateBytesReadByExtension: { ".jpg": 536870912, ".png": 0, ".pdf": 0 },
        candidateLimitReachedByExtension: { ".jpg": true, ".png": false, ".pdf": false },
        fileSizeLimitReachedByExtension: { ".jpg": false, ".png": false, ".pdf": false },
        decodedDataLimitReachedByExtension: { ".jpg": false, ".png": false, ".pdf": false },
        candidateReadCapBytes: 805306368,
        candidateReadCapBytesPerFormat: 268435456,
        scanByteCap: 1073741824,
        maxFileBytes: 33554432,
        maxDecodedPngBytes: 134217728,
        retainedBytesCap: 134217728,
        fileCountCap: 256,
        formatsAttempted: [".jpg", ".png", ".pdf"],
        validationScope: "contiguous_structure_and_signature",
      },
      lowConfidenceCarving: {
        bitmapUnobserved: {
          filesFound: 0, bytesScanned: 134217728, scanLimitReached: true,
          candidateBytesRead: 0, candidateLimitReached: false, fileCountLimitReached: false,
          retainedBytesLimitReached: false, rangeCount: 1, rangeCollectionTruncated: false,
          filesFoundByExtension: { ".jpg": 0 }, candidatesExaminedByExtension: { ".jpg": 2 },
          candidateBytesReadByExtension: { ".jpg": 0 }, formatsAttempted: [".jpg"],
          validationScope: "contiguous_structure_and_signature", confidence: "low",
          allocationStatus: "bitmap_unobserved", catalogItemsAdded: 0,
          candidateReadCapBytes: 50331648, candidateReadCapBytesPerFormat: 16777216,
          maxFileBytes: 16777216, maxDecodedPngBytes: 16777216,
          scanByteCap: 134217728, retainedBytesCap: 33554432, fileCountCap: 64,
          rangeBytesRetained: 4096, rangeCollectionCapBytes: 134217728,
        },
        possiblyReused: {
          filesFound: 0, bytesScanned: 0, scanLimitReached: false,
          candidateBytesRead: 0, candidateLimitReached: false, fileCountLimitReached: false,
          retainedBytesLimitReached: false, rangeCount: 0, rangeCollectionTruncated: false,
          filesFoundByExtension: { ".jpg": 0 }, candidatesExaminedByExtension: { ".jpg": 0 },
          candidateBytesReadByExtension: { ".jpg": 0 }, formatsAttempted: [".jpg"],
          validationScope: "contiguous_structure_and_signature", confidence: "low",
          allocationStatus: "possibly_reused", catalogItemsAdded: 0,
          candidateReadCapBytes: 50331648, candidateReadCapBytesPerFormat: 16777216,
          maxFileBytes: 16777216, maxDecodedPngBytes: 16777216,
          scanByteCap: 134217728, retainedBytesCap: 33554432, fileCountCap: 64,
          rangeBytesRetained: 0, rangeCollectionCapBytes: 134217728,
        },
      },
      recycleBinRecovery: {
        status: "inconclusive", inconclusive: true, indexCount: 3, aliasesAdded: 1,
        pairedCount: 2, missingContentCount: 1, ambiguousContentCount: 0,
        metadataMismatchCount: 0, invalidIndexCount: 0, readErrorCount: 0,
        limitedIndexCount: 0, incompleteContentCount: 0, unsupportedExtensionCount: 1,
        directoryContentCount: 0,
      },
      usnJournalEvidence: {
        status: "inconclusive", inconclusive: true, journalCount: 1, streamCount: 1,
        bytesRead: 1024, recordsExamined: 4, parsedRecords: 3, deletedEvents: 1,
        malformedRecords: 1, limitReached: true, errorCount: 0,
      },
      ntfsLogFileEvidence: {
        status: "inconclusive", inconclusive: true, logFileCount: 1,
        bytesRead: 8192, pagesExamined: 2, restartPages: 1, recordPages: 1,
        malformedPages: 0, currentLsns: ["0x0000000000010008"],
        limitReached: false, errorCount: 0, reason: null,
        recoveryClaim: "structural_evidence_only",
      },
    },
    preview: null,
    previewLoading: false,
    searchQuery: "",
    searchResult: null,
    searchingCatalog: false,
    childrenById: {},
    expandedFolderIds: new Set(),
    loadingFolderIds: new Set(),
    selectedIds: new Set(),
    extensions: [],
    availableExtensions: [],
    minimumSizeKb: 0,
    outputDirectory: "D:\\Recovered",
    recoveryResult: null as RecoveryResult | null,
    refreshDisks: vi.fn(),
    selectDisk: vi.fn(),
    findPartitions: vi.fn(),
    selectVolume: vi.fn(),
    buildCatalog: vi.fn(),
    setOutputDirectory: vi.fn(),
    chooseOutputDirectory: vi.fn(),
    setExtensionSelected: vi.fn(),
    setMinimumSizeKb: vi.fn(),
    selectAll: vi.fn(),
    clearSelection: vi.fn(),
    recover: vi.fn(),
    setSearchQuery: vi.fn(),
    toggleFolder: vi.fn(),
    isSelected: vi.fn(() => false),
    toggleSelection: vi.fn(),
    previewFile: vi.fn(),
    ensureAdministrator: vi.fn(),
    selectRawImage: vi.fn(),
  },
}));

vi.mock("../../hooks/useRecoveryController", () => ({
  useRecoveryController: () => recovery,
}));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.location.hash = "#/";
});

const renderRecoveryPage = () => render(<HashRouter><RecoveryPage /></HashRouter>);
const goToCatalog = () => fireEvent.click(screen.getByRole("button", { name: "4 Catálogo" }));
const goToScan = () => fireEvent.click(screen.getByRole("button", { name: "3 Varredura" }));

describe("RecoveryPage audit details", () => {
  it("offers raw image selection through the Electron file picker", () => {
    renderRecoveryPage();
    fireEvent.click(screen.getByRole("button", { name: "Abrir imagem raw…" }));
    expect(recovery.selectRawImage).toHaveBeenCalledOnce();
  });

  it("opens the image picker when reached from the raw-image homepage action", async () => {
    window.location.hash = "#/recovery?source=image";
    renderRecoveryPage();
    await waitFor(() => expect(recovery.selectRawImage).toHaveBeenCalledOnce());
  });

  it("connects the visible scan, catalog and recovery steps to backend operations", async () => {
    recovery.selectedIds.add("candidate-1" as never);
    recovery.extensions.push(".jpg" as never);
    recovery.buildCatalog = vi.fn().mockResolvedValue(true);
    recovery.recover = vi.fn();
    renderRecoveryPage();

    fireEvent.click(screen.getByRole("button", { name: /Continuar/ }));
    expect(screen.getByRole("heading", { name: "Configure a varredura" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Iniciar varredura" }));
    await screen.findByRole("heading", { name: "Arquivos encontrados" });
    expect(recovery.buildCatalog).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: /Continuar/ }));
    expect(screen.getByRole("heading", { name: "Recuperar selecionados" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Recuperar selecionados" }));
    expect(recovery.recover).toHaveBeenCalledOnce();

    recovery.selectedIds.clear();
    recovery.extensions.length = 0;
    recovery.buildCatalog = vi.fn();
    recovery.recover = vi.fn();
  });

  it("shows bounded per-file recovery outcomes in a separate overlay", async () => {
    recovery.recoveryResult = {
      selectedCount: 1, candidateCount: 2, recoveredCount: 1, rejectedCount: 1,
      resultsTruncated: false, statusCounts: { recovered: 1, signature_mismatch: 1 },
      results: [
        { name: "photo.jpg", path: "Photos/photo.jpg", status: "recovered", reason: "", bytesWritten: 1024 },
        { name: "broken.jpg", path: "Photos/broken.jpg", status: "signature_mismatch", reason: "Header mismatch", bytesWritten: 0 },
      ],
    };
    renderRecoveryPage();
    fireEvent.click(screen.getByRole("button", { name: "Resultados da recuperação" }));
    const dialog = await screen.findByRole("dialog", { name: "Resultados da recuperação" });
    expect(within(dialog).getByText(/Selecionados: 1; tentativas: 2; recuperados: 1; rejeitados ou com falha: 1/)).toBeTruthy();
    expect(within(dialog).getByText("broken.jpg")).toBeTruthy();
    recovery.recoveryResult = null;
  });

  it("does not allow opening the catalog before it has been built", () => {
    const catalog = recovery.catalog;
    recovery.catalog = null as never;
    renderRecoveryPage();
    recovery.catalog = catalog;
    expect((screen.getByRole("button", { name: "4 Catálogo" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("opens the filter drawer with file type, size and selection controls", async () => {
    renderRecoveryPage();
    goToCatalog();

    const filterTrigger = screen.getByRole("button", { name: "Filtros" });
    expect(filterTrigger.closest("header")).not.toBeNull();
    fireEvent.click(filterTrigger);
    const dialog = await screen.findByRole("dialog", { name: "Filtros" });
    expect(within(dialog).queryByRole("navigation")).toBeNull();
    expect(within(dialog).getAllByText("Tipos de arquivo")).toHaveLength(1);
    expect(within(dialog).getAllByText("Tamanho mínimo")).toHaveLength(1);
    expect(within(dialog).queryByRole("button", { name: "Recuperar selecionados" })).toBeNull();
    expect(screen.getByRole("button", { name: /Varredura/ })).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Fechar" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Filtros" })).toBeNull());
  });

  it("defaults to the maximum recovery budgets and lets users adjust them", () => {
    renderRecoveryPage();
    goToScan();

    const scanBudget = screen.getByRole("combobox", { name: "Orçamento de busca em espaço livre" });
    const maxFiles = screen.getByRole("combobox", { name: "Máximo de candidatos encontrados" });
    const candidateReadBudget = screen.getByRole("combobox", { name: "Leitura de candidatos por formato" });
    const retainedBudget = screen.getByRole("combobox", { name: "Memória máxima para candidatos" });
    const forceFresh = screen.getByRole("checkbox", {
      name: "Forçar nova auditoria completa do disco (padrão; ignora cache; pode levar horas)",
    });
    expect((screen.getByLabelText("Procurar arquivos excluídos que não aparecem na lista (ativado por padrão)") as HTMLInputElement).checked).toBe(true);
    expect((forceFresh as HTMLInputElement).checked).toBe(true);
    expect((scanBudget as HTMLSelectElement).value).toBe("64");
    expect((maxFiles as HTMLSelectElement).value).toBe("16384");
    expect((candidateReadBudget as HTMLSelectElement).value).toBe("1024");
    expect((retainedBudget as HTMLSelectElement).value).toBe("512");
    fireEvent.click(screen.getByRole("button", { name: "Iniciar varredura" }));

    expect(recovery.buildCatalog).toHaveBeenCalledWith(true, {
      scanBudgetGiB: 64, maxFiles: 16384, maxRetainedMiB: 512,
      maxCandidateReadMiBPerFormat: 1024,
    }, true);
  });

  it("keeps audit results out of Found Files until the report overlay is opened and restores trigger focus", async () => {
    renderRecoveryPage();
    goToCatalog();

    const foundFiles = screen.getByRole("heading", { name: "Arquivos encontrados" }).parentElement;
    expect(foundFiles).toBeTruthy();
    expect(within(foundFiles!).queryByText(/A auditoria do disco inteiro é inconclusiva/)).toBeNull();
    expect(within(foundFiles!).queryByText(/Registros órfãos por status de alocação/)).toBeNull();
    expect(within(foundFiles!).queryByText(/O carving encontrou/)).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();

    const trigger = screen.getByRole("button", { name: "Detalhes da auditoria do disco" });
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Detalhes da auditoria do disco" });
    expect(within(dialog).getByText(/A auditoria do disco inteiro é inconclusiva/)).toBeTruthy();
    expect(within(dialog).getByText(/Registros órfãos por status de alocação/)).toBeTruthy();
    expect(within(dialog).getByText(/O carving encontrou/)).toBeTruthy();
    expect(within(dialog).getByText(/\.jpg: 0 candidato\(s\) encontrado\(s\), 12 candidato\(s\) examinado\(s\)/)).toBeTruthy();
    expect(within(dialog).getByText(/Limites atingidos neste formato: leitura de candidatos/)).toBeTruthy();
    expect(within(dialog).getByText(/Candidatos encontrados por carving de baixa confiança/)).toBeTruthy();
    expect(within(dialog).getByRole("heading", { name: "Recuperação pela Lixeira do Windows" })).toBeTruthy();
    expect(within(dialog).getByText(/1 atalho\(s\) de recuperação adicionado/)).toBeTruthy();
    expect(within(dialog).getByRole("heading", { name: "Evidências do diário USN do NTFS" })).toBeTruthy();
    expect(within(dialog).getByText(/1 eventos de exclusão/)).toBeTruthy();
    expect(within(dialog).getByRole("heading", { name: "Evidências estruturais do $LogFile NTFS" })).toBeTruthy();
    expect(within(dialog).getByText(/0x0000000000010008/)).toBeTruthy();
    expect(within(dialog).getByText(/não recupera conteúdo de arquivos/)).toBeTruthy();
    expect(within(dialog).getByRole("heading", { name: "Bitmap não observado; os dados podem ser atuais" })).toBeTruthy();
    expect(within(dialog).getAllByText(/lê até 16\.777\.216 bytes de candidatos por formato e 50\.331\.648 no total/)).toHaveLength(2);

    fireEvent.click(within(dialog).getByRole("button", { name: "Fechar" }));
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("labels reused read coverage as a historical snapshot", async () => {
    const diskValidation = recovery.catalog.diskValidation;
    Object.assign(diskValidation, {
      coverageStatus: "cached_snapshot",
      evidenceFreshness: "cached_snapshot",
      evidenceScannedAt: "2026-11-23T12:00:00+00:00",
    });
    renderRecoveryPage();
    goToCatalog();

    fireEvent.click(screen.getByRole("button", { name: "Detalhes da auditoria do disco" }));
    const dialog = await screen.findByRole("dialog", { name: "Detalhes da auditoria do disco" });
    expect(within(dialog).getByText(/A cobertura de leitura é um registro histórico de 2026-11-23/))
      .toBeTruthy();
    expect(within(dialog).queryByText(/A auditoria do disco inteiro é inconclusiva/)).toBeNull();
    Object.assign(diskValidation, {
      coverageStatus: "complete",
      evidenceFreshness: "fresh",
      evidenceScannedAt: undefined,
    });
  });
});
