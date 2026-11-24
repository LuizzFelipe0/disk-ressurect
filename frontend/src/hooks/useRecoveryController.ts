import { useCallback, useEffect, useRef, useState } from "react";
import { recoveryService } from "../services/recoveryService";
import type {
  CarvingOptions,
  RecoveryResult,
  DiskInfo,
  VolumeInfo,
  RawImageSource,
} from "../types/recovery";
import { useCatalogSelection } from "../pages/catalog/useCatalogSelection";
import { useCatalogBrowser } from "../pages/catalog/useCatalogBrowser";
import { useRecoveryOperationState } from "../pages/scan/useRecoveryOperationState";

const LAST_SELECTED_DISK_KEY = "disk-ressurect:last-selected-disk";

function diskCacheIdentity(disk: DiskInfo) {
  const serial = disk.serialNumber.trim().toLowerCase();
  const model = disk.model.trim().toLowerCase();
  return serial
    ? `serial:${serial}|${model}|${disk.sizeBytes}`
    : `device:${model}|${disk.sizeBytes}|${disk.number}`;
}

function newSessionId() {
  return window.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

export function useRecoveryController() {
  const operation = useRecoveryOperationState();
  const {
    backendStatus, isAdministrator, busy, error, status, progress, partitionScanCanResume,
    backendSessionGeneration, beginOperation, finishOperation,
    setBusy, setError, setStatus, setProgress, setPartitionScanCanResume,
    ensureAdministrator,
  } = operation;
  const [disks, setDisks] = useState<DiskInfo[]>([]);
  const [rawImage, setRawImage] = useState<RawImageSource | null>(null);
  const [selectedDiskNumber, setSelectedDiskNumber] = useState("");
  const [volumes, setVolumes] = useState<VolumeInfo[]>([]);
  const [selectedVolumeId, setSelectedVolumeId] = useState("");
  const [availableExtensions, setAvailableExtensions] = useState<string[]>([]);
  const [extensions, setExtensions] = useState<string[]>([]);
  const [minimumSizeKb, setMinimumSizeKb] = useState(0);
  const [outputDirectory, setOutputDirectory] = useState("");
  const [recoveryResult, setRecoveryResult] = useState<RecoveryResult | null>(null);
  const [sessionId, setSessionId] = useState(newSessionId);
  const browser = useCatalogBrowser(setError);
  const {
    catalog, setCatalog, preview, previewLoading, searchQuery, setSearchQuery,
    searchResult, searchingCatalog, childrenById, parentById, loadingFolderIds,
    expandedFolderIds, setRootParents, clear: clearBrowser, getGeneration,
    toggleFolder, previewFile,
  } = browser;
  const selection = useCatalogSelection(catalog, childrenById, parentById);
  const initialLoadStarted = useRef(false);
  const catalogBuildRequest = useRef(0);
  const sourceGeneration = useRef(0);
  const partitionRequestId = useRef(0);
  const diskRefreshRequestId = useRef(0);

  const clearCatalog = useCallback(() => {
    clearBrowser();
    selection.clearSelection();
    setRecoveryResult(null);
  }, [clearBrowser, selection.clearSelection]);

  const refreshDisks = useCallback(async (preserveCurrentSource = true) => {
    if (!preserveCurrentSource) {
      sourceGeneration.current += 1;
      setSessionId(newSessionId());
      setRawImage(null);
      setSelectedDiskNumber("");
      setSelectedVolumeId("");
      setVolumes([]);
      clearCatalog();
    }
    const generation = sourceGeneration.current;
    const requestId = ++diskRefreshRequestId.current;
    setBusy(true);
    setError("");
    setStatus("Checking disks through the Python service…");
    try {
      const foundDisks = await recoveryService.listDisks();
      if (requestId !== diskRefreshRequestId.current || generation !== sourceGeneration.current) return;
      setDisks(foundDisks);
      if (preserveCurrentSource) {
        setStatus(`${foundDisks.length} disk(s) found. The current source and catalog are unchanged.`);
        return;
      }
      const savedIdentity = window.localStorage.getItem(LAST_SELECTED_DISK_KEY);
      const rememberedDisk = savedIdentity
        ? foundDisks.find((disk) => diskCacheIdentity(disk) === savedIdentity)
        : undefined;
      const cachedDisks = foundDisks.filter((disk) => disk.cachedPartitions?.length);
      const restoredDisk = rememberedDisk ?? (cachedDisks.length === 1 ? cachedDisks[0] : undefined);
      if (restoredDisk) window.localStorage.setItem(LAST_SELECTED_DISK_KEY, diskCacheIdentity(restoredDisk));
      setSelectedDiskNumber(restoredDisk ? String(restoredDisk.number) : "");
      setVolumes(restoredDisk?.cachedPartitions ?? []);
      setSelectedVolumeId("");
      clearCatalog();
      if (restoredDisk?.cachedPartitions?.length) {
        const savedAt = restoredDisk.cachedPartitions.find((volume) => volume.scanSavedAt)?.scanSavedAt;
        const timestamp = savedAt ? ` (${new Date(savedAt).toLocaleString()})` : "";
        setStatus(`${restoredDisk.cachedPartitions.length} saved deep-scan candidate(s) restored${timestamp}. Select a partition to continue.`);
      } else if (restoredDisk) {
        setStatus("The previous source disk was restored. Search it for NTFS partitions.");
      } else {
        setStatus(`${foundDisks.length} disk(s) found. Choose a source disk.`);
      }
    } catch (cause) {
      if (requestId !== diskRefreshRequestId.current || generation !== sourceGeneration.current) return;
      const message = cause instanceof Error ? cause.message : String(cause);
      const runtime = await recoveryService.getBackendStatus().catch(() => null);
      if (runtime?.state === "error") {
        setError(runtime.message);
        setStatus("The Python recovery process has exited.");
      } else {
        setError(message);
        setStatus("Disk discovery failed. See the details below.");
      }
    } finally {
      if (requestId === diskRefreshRequestId.current && generation === sourceGeneration.current) setBusy(false);
    }
  }, [clearCatalog]);

  useEffect(() => {
    void recoveryService.listSupportedFileTypes().then((fileTypes) => {
      setAvailableExtensions(fileTypes);
      setExtensions((current) => current.length ? current : fileTypes);
    }).catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : String(cause));
    });
    if (!initialLoadStarted.current) {
      initialLoadStarted.current = true;
      void refreshDisks(false);
    }
  }, [refreshDisks]);

  const appliedBackendGeneration = useRef(0);
  useEffect(() => {
    if (backendSessionGeneration === appliedBackendGeneration.current) return;
    appliedBackendGeneration.current = backendSessionGeneration;
    sourceGeneration.current += 1;
    setSessionId(newSessionId());
    partitionRequestId.current += 1;
    setRawImage(null);
    setSelectedDiskNumber("");
    setSelectedVolumeId("");
    setVolumes([]);
    setRecoveryResult(null);
    clearCatalog();
    setError("");
    setStatus("The recovery service restarted. Select the source again to continue.");
    void refreshDisks(false);
  }, [backendSessionGeneration, clearCatalog, refreshDisks]);

  const selectDisk = useCallback((diskNumber: string) => {
    const selectedDisk = disks.find((disk) => String(disk.number) === diskNumber);
    const savedPartitions = selectedDisk?.cachedPartitions ?? [];
    if (selectedDisk) window.localStorage.setItem(LAST_SELECTED_DISK_KEY, diskCacheIdentity(selectedDisk));
    else window.localStorage.removeItem(LAST_SELECTED_DISK_KEY);
    setPartitionScanCanResume(Boolean(selectedDisk?.deepScanResumeAvailable));
    setRawImage(null);
    sourceGeneration.current += 1;
    setSessionId(newSessionId());
    setSelectedDiskNumber(diskNumber);
    setVolumes(savedPartitions);
    setSelectedVolumeId("");
    clearCatalog();
    setError("");
    if (savedPartitions.length) {
      const savedAt = savedPartitions.find((volume) => volume.scanSavedAt)?.scanSavedAt;
      const timestamp = savedAt ? ` (${new Date(savedAt).toLocaleString()})` : "";
      setStatus(`${savedPartitions.length} saved deep-scan candidate(s) loaded${timestamp}. Select one or run Deep scan to refresh.`);
    } else {
      setStatus(diskNumber ? "Search this disk for NTFS partitions." : "Choose a source disk.");
    }
  }, [clearCatalog, disks]);

  const selectRawImage = useCallback(async () => {
    const requestGeneration = sourceGeneration.current;
    setBusy(true); setError("");
    try {
      const selected = await recoveryService.selectRawImage();
      if (!selected || requestGeneration !== sourceGeneration.current) return;
      sourceGeneration.current += 1;
      setSessionId(newSessionId());
      setRawImage(selected);
      setSelectedDiskNumber("");
      setSelectedVolumeId("");
      setVolumes([]);
      setPartitionScanCanResume(false);
      clearCatalog();
      setStatus("Raw image selected. Search it for NTFS partitions.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setStatus("Unable to open the selected raw image.");
    } finally { setBusy(false); }
  }, [clearCatalog]);

  const findPartitions = useCallback(async (deepScan: boolean, resume = false) => {
    if (!selectedDiskNumber && !rawImage) return;
    const generation = sourceGeneration.current;
    const requestId = ++partitionRequestId.current;
    if (!rawImage && !await ensureAdministrator()) return;
    if (generation !== sourceGeneration.current || requestId !== partitionRequestId.current) return;
    setBusy(true); setError("");
    const operationId = beginOperation();
    if (!resume) setProgress(null);
    if (!resume) setPartitionScanCanResume(false);
    setStatus(resume ? "Resuming lost-partition scan…" : deepScan ? "Searching for lost NTFS partitions…" : "Scanning partitions…");
    try {
      const foundVolumes = rawImage
        ? await recoveryService.listSourcePartitions(rawImage.sourceId, deepScan, operationId)
        : await recoveryService.listPartitions(Number(selectedDiskNumber), deepScan, resume, operationId);
      if (requestId !== partitionRequestId.current || generation !== sourceGeneration.current) return;
      if (rawImage) {
        setVolumes(foundVolumes);
        setSelectedVolumeId(""); clearCatalog();
        setStatus(foundVolumes.length
          ? `${foundVolumes.length} NTFS volume(s) found in the selected image.`
          : deepScan
            ? "Deep scan found no readable NTFS volumes in the selected image."
            : "No readable NTFS volumes were found in the selected image.");
        return;
      }
      const diskNumber = Number(selectedDiskNumber);
      const disk = disks.find((item) => item.number === diskNumber);
      const savedDeepScan = disk?.cachedPartitions ?? [];
      const displayedVolumes = deepScan
        ? foundVolumes
        : [...new Map([...savedDeepScan, ...foundVolumes].map((volume) => [volume.id, volume])).values()];
      setVolumes(displayedVolumes);
      setPartitionScanCanResume(false);
      setDisks((current) => current.map((item) => item.number === diskNumber
        ? {
          ...item,
          cachedPartitions: deepScan ? foundVolumes : savedDeepScan,
          deepScanResumeAvailable: deepScan ? false : item.deepScanResumeAvailable,
        }
        : item));
      setSelectedVolumeId(""); clearCatalog();
      setStatus(displayedVolumes.length
        ? `${displayedVolumes.length} NTFS partition(s) found. Select one to build the catalog.`
        : "No readable NTFS partitions were found.");
    } catch (cause) {
      if (requestId !== partitionRequestId.current || generation !== sourceGeneration.current) return;
      setError(cause instanceof Error ? cause.message : String(cause));
      setStatus("Partition search failed. The scan position has been saved when available.");
      if (deepScan) {
        try {
          const refreshedDisks = await recoveryService.listDisks();
          setDisks(refreshedDisks);
          const previousDisk = disks.find((disk) => disk.number === Number(selectedDiskNumber));
          const selectedDisk = refreshedDisks.find((disk) => disk.number === Number(selectedDiskNumber)
            && (!previousDisk || disk.serialNumber === previousDisk.serialNumber))
            ?? (previousDisk?.serialNumber
              ? refreshedDisks.find((disk) => disk.serialNumber === previousDisk.serialNumber)
              : refreshedDisks.find((disk) => disk.model === previousDisk?.model
                && disk.sizeBytes === previousDisk.sizeBytes));
          if (selectedDisk && selectedDisk.number !== Number(selectedDiskNumber)) {
            setSelectedDiskNumber(String(selectedDisk.number));
          }
          setPartitionScanCanResume(Boolean(selectedDisk?.deepScanResumeAvailable));
          if (selectedDisk?.cachedPartitions) setVolumes(selectedDisk.cachedPartitions);
        } catch {
          setPartitionScanCanResume(false);
        }
      }
    }
    finally {
      if (requestId === partitionRequestId.current) setBusy(false);
      finishOperation(operationId);
    }
  }, [selectedDiskNumber, rawImage, disks, clearCatalog, ensureAdministrator, beginOperation, finishOperation]);

  const selectVolume = useCallback((volumeId: string) => {
    setSelectedVolumeId(volumeId); setSessionId(newSessionId()); clearCatalog();
    setStatus(volumeId ? "Build the catalog to browse the discovered files." : "Select an NTFS partition.");
  }, [clearCatalog]);

  const buildCatalog = useCallback(async (
    includeOrphaned = false,
    carvingOptions?: CarvingOptions,
    forceFreshValidation = false,
  ) => {
    if (!selectedVolumeId) return;
    const generation = getGeneration();
    if (!rawImage && !await ensureAdministrator()) return;
    if (generation !== getGeneration()) return;
    clearCatalog();
    const catalogGeneration = getGeneration();
    const requestId = ++catalogBuildRequest.current;
    const operationId = beginOperation();
    setBusy(true); setError(""); setProgress(null);
    setStatus(includeOrphaned
      ? "Reading MFT metadata and searching for orphaned entries…"
      : "Reading metadata and building the catalog…");
    try {
      const result = includeOrphaned
        ? await recoveryService.scanCatalog(
          selectedVolumeId, true, carvingOptions, forceFreshValidation, operationId,
        )
        : await recoveryService.scanCatalog(selectedVolumeId, false, undefined, false, operationId);
      if (catalogGeneration !== getGeneration() || requestId !== catalogBuildRequest.current) return;
      setCatalog(result);
      setRootParents(result.roots);
      setStatus(`Catalog ready: ${result.recordCount.toLocaleString()} MFT records.`);
    } catch (cause) {
      if (catalogGeneration === getGeneration() && requestId === catalogBuildRequest.current) {
        setError(cause instanceof Error ? cause.message : String(cause));
        setStatus("Unable to build the catalog.");
      }
    } finally {
      if (requestId === catalogBuildRequest.current) setBusy(false);
      finishOperation(operationId);
    }
  }, [selectedVolumeId, rawImage, ensureAdministrator, clearCatalog, beginOperation, finishOperation,
    getGeneration, setCatalog, setRootParents]);

  const chooseOutputDirectory = useCallback(async () => {
    try {
      const directory = await recoveryService.chooseOutputDirectory();
      if (directory) setOutputDirectory(directory);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }, []);

  const recover = useCallback(async () => {
    if (!selection.selectedIds.size || !extensions.length || !outputDirectory.trim()) {
      setError(!outputDirectory.trim() ? "Choose a destination folder to continue." : "Select files and at least one file type.");
      return;
    }
    const generation = sourceGeneration.current;
    const catalogVersion = getGeneration();
    if (!rawImage && !await ensureAdministrator()) return;
    if (generation !== sourceGeneration.current || catalogVersion !== getGeneration()) return;
    setBusy(true); setError(""); setProgress(null); setStatus("Recovering the selected items…");
    setRecoveryResult(null);
    const operationId = beginOperation();
    try {
      const result = await recoveryService.recover({
        selectedNodeIds: [...selection.selectedIds], excludedNodeIds: [...selection.excludedIds],
        outputDirectory, extensions, minimumSizeKb, operationId,
      });
      if (generation !== sourceGeneration.current || catalogVersion !== getGeneration()) return;
      setRecoveryResult(result);
      setStatus(`Completed: ${result.recoveredCount}/${result.candidateCount} files recovered.`);
      setProgress({ stage: "extract", completed: 1, total: 1, message: "Recovery completed." });
    } catch (cause) {
      if (generation === sourceGeneration.current && catalogVersion === getGeneration()) {
        setError(cause instanceof Error ? cause.message : String(cause));
        setStatus("Recovery failed.");
      }
    }
    finally {
      if (generation === sourceGeneration.current && catalogVersion === getGeneration()) setBusy(false);
      finishOperation(operationId);
    }
  }, [selection.selectedIds, selection.excludedIds, outputDirectory, extensions, minimumSizeKb,
    rawImage, ensureAdministrator, beginOperation, finishOperation, getGeneration]);

  const setExtensionSelected = useCallback((extension: string, checked: boolean) => {
    setExtensions((current) => checked
      ? [...new Set([...current, extension])]
      : current.filter((item) => item !== extension));
  }, []);

  return {
    backendStatus, isAdministrator, busy, error, status, progress, disks, rawImage, selectedDiskNumber, volumes, sessionId,
    partitionScanCanResume,
    selectedVolumeId, catalog, preview, previewLoading, searchQuery, setSearchQuery,
    searchResult, searchingCatalog, childrenById, parentById, loadingFolderIds,
    expandedFolderIds, toggleFolder, previewFile,
    ...selection, availableExtensions, extensions, minimumSizeKb, outputDirectory, recoveryResult,
    refreshDisks, selectDisk, selectRawImage, findPartitions, selectVolume, buildCatalog,
    chooseOutputDirectory,
      recover, setExtensionSelected, setMinimumSizeKb, setOutputDirectory,
    ensureAdministrator,
  };
}
