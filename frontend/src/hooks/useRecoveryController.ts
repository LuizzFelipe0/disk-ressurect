import { useCallback, useEffect, useRef, useState } from "react";
import { recoveryService } from "../services/recoveryService";
import type { CarvingOptions, RecoveryResult } from "../types/recovery";
import { useCatalogSelection } from "./useCatalogSelection";
import { useCatalogBrowser } from "./useCatalogBrowser";
import { useRecoveryOperationState } from "./useRecoveryOperationState";
import { useRecoverySource } from "./useRecoverySource";

export function useRecoveryController() {
  const operation = useRecoveryOperationState();
  const {
    backendStatus, isAdministrator, busy, error, status, progress, partitionScanCanResume,
    backendSessionGeneration, beginOperation, finishOperation,
    setBusy, setError, setStatus, setProgress, ensureAdministrator,
  } = operation;
  const browser = useCatalogBrowser(setError);
  const {
    catalog, setCatalog, preview, previewLoading, searchQuery, setSearchQuery,
    searchResult, searchingCatalog, childrenById, parentById, loadingFolderIds,
    expandedFolderIds, setRootParents, clear: clearBrowser, getGeneration: getCatalogGeneration,
    toggleFolder, previewFile,
  } = browser;
  const selection = useCatalogSelection(catalog, childrenById, parentById);
  const [availableExtensions, setAvailableExtensions] = useState<string[]>([]);
  const [extensions, setExtensions] = useState<string[]>([]);
  const [minimumSizeKb, setMinimumSizeKb] = useState(0);
  const [outputDirectory, setOutputDirectory] = useState("");
  const [recoveryResult, setRecoveryResult] = useState<RecoveryResult | null>(null);
  const catalogBuildRequest = useRef(0);
  const recoveryCommandInFlight = useRef(false);

  const clearCatalog = useCallback(() => {
    clearBrowser();
    selection.clearSelection();
    setRecoveryResult(null);
  }, [clearBrowser, selection.clearSelection]);

  const source = useRecoverySource(clearCatalog, operation);

  useEffect(() => {
    void recoveryService.listSupportedFileTypes().then((fileTypes) => {
      setAvailableExtensions(fileTypes);
      setExtensions((current) => current.length ? current : fileTypes);
    }).catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : String(cause));
    });
  }, [setError]);

  const buildCatalog = useCallback(async (
    includeOrphaned = false,
    carvingOptions?: CarvingOptions,
    forceFreshValidation = false,
  ): Promise<boolean> => {
    if (!source.selectedVolumeId || recoveryCommandInFlight.current) return false;
    recoveryCommandInFlight.current = true;
    setBusy(true);
    const generation = getCatalogGeneration();
    if (!await ensureAdministrator()) {
      recoveryCommandInFlight.current = false;
      setBusy(false);
      return false;
    }
    if (generation !== getCatalogGeneration()) {
      recoveryCommandInFlight.current = false;
      setBusy(false);
      return false;
    }
    clearCatalog();
    const catalogGeneration = getCatalogGeneration();
    const requestId = ++catalogBuildRequest.current;
    const operationId = beginOperation();
    setError("");
    setProgress(null);
    setStatus(includeOrphaned
      ? "Reading MFT metadata and searching for orphaned entries…"
      : "Reading metadata and building the catalog…");
    try {
      const result = includeOrphaned
        ? await recoveryService.scanCatalog(
          source.selectedVolumeId, true, carvingOptions, forceFreshValidation, operationId,
        )
        : await recoveryService.scanCatalog(source.selectedVolumeId, false, undefined, false, operationId);
      if (catalogGeneration !== getCatalogGeneration() || requestId !== catalogBuildRequest.current) return false;
      setCatalog(result);
      setRootParents(result.roots);
      setStatus(`Catalog ready: ${result.recordCount.toLocaleString()} MFT records.`);
      return true;
    } catch (cause) {
      if (catalogGeneration === getCatalogGeneration() && requestId === catalogBuildRequest.current) {
        setError(cause instanceof Error ? cause.message : String(cause));
        setStatus("Unable to build the catalog.");
      }
      return false;
    } finally {
      if (requestId === catalogBuildRequest.current) setBusy(false);
      finishOperation(operationId);
      recoveryCommandInFlight.current = false;
    }
  }, [source.selectedVolumeId, ensureAdministrator, clearCatalog, beginOperation,
    finishOperation, getCatalogGeneration, setCatalog, setRootParents, setBusy, setError, setProgress, setStatus]);

  const chooseOutputDirectory = useCallback(async () => {
    try {
      const directory = await recoveryService.chooseOutputDirectory();
      if (directory) setOutputDirectory(directory);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [setError]);

  const recover = useCallback(async () => {
    if (!selection.selectedIds.size
        || (selection.selectedIds.size > 0 && !extensions.length) || !outputDirectory.trim()) {
    setError(!outputDirectory.trim() ? "Choose a destination folder to continue." : "Select files and at least one file type.");
      return;
    }
    if (recoveryCommandInFlight.current) return;
    recoveryCommandInFlight.current = true;
    setBusy(true);
    const sourceGeneration = source.getGeneration();
    const catalogGeneration = getCatalogGeneration();
    if (!await ensureAdministrator()) {
      recoveryCommandInFlight.current = false;
      setBusy(false);
      return;
    }
    if (sourceGeneration !== source.getGeneration() || catalogGeneration !== getCatalogGeneration()) {
      recoveryCommandInFlight.current = false;
      setBusy(false);
      return;
    }
    setError("");
    setProgress(null);
    setStatus("Recovering the selected items…");
    setRecoveryResult(null);
    const operationId = beginOperation();
    try {
      const result = await recoveryService.recover({
        selectedNodeIds: [...selection.selectedIds], excludedNodeIds: [...selection.excludedIds],
        outputDirectory, extensions, minimumSizeKb, operationId,
      });
      if (sourceGeneration !== source.getGeneration() || catalogGeneration !== getCatalogGeneration()) return;
      setRecoveryResult(result);
      setStatus(`Completed: ${result.recoveredCount} files recovered.`);
      setProgress({ stage: "extract", completed: 1, total: 1, message: "Recovery completed." });
    } catch (cause) {
      if (sourceGeneration === source.getGeneration() && catalogGeneration === getCatalogGeneration()) {
        setError(cause instanceof Error ? cause.message : String(cause));
        setStatus("Recovery failed.");
      }
    } finally {
      if (sourceGeneration === source.getGeneration() && catalogGeneration === getCatalogGeneration()) setBusy(false);
      finishOperation(operationId);
      recoveryCommandInFlight.current = false;
    }
  }, [selection.selectedIds, selection.excludedIds, extensions, outputDirectory, minimumSizeKb,
    source.getGeneration, ensureAdministrator, setError, setBusy, setProgress, setStatus,
    beginOperation, finishOperation, getCatalogGeneration]);

  const setExtensionSelected = useCallback((extension: string, checked: boolean) => {
    setExtensions((current) => checked
      ? [...new Set([...current, extension])]
      : current.filter((item) => item !== extension));
  }, []);

  return {
    backendStatus, isAdministrator, busy, error, status, progress,
    disks: source.disks, selectedDiskNumber: source.selectedDiskNumber,
    volumes: source.volumes, selectedVolumeId: source.selectedVolumeId, partitionScanCanResume,
    catalog, preview, previewLoading, searchQuery, setSearchQuery, searchResult, searchingCatalog,
    childrenById, parentById, loadingFolderIds, expandedFolderIds, toggleFolder, previewFile,
    ...selection, availableExtensions, extensions, minimumSizeKb, outputDirectory, recoveryResult,
    refreshDisks: source.refreshDisks, selectDisk: source.selectDisk,
    findPartitions: source.findPartitions, selectVolume: source.selectVolume, buildCatalog,
    chooseOutputDirectory, recover, setExtensionSelected, setMinimumSizeKb, setOutputDirectory,
    ensureAdministrator, backendSessionGeneration,
  };
}
