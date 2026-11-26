import { useCallback, useEffect, useRef, useState } from "react";
import { recoveryService } from "../services/recoveryService";
import type { DiskInfo, RawImageSource, VolumeInfo } from "../types/recovery";
import type { useRecoveryOperationState } from "./useRecoveryOperationState";

const LAST_SELECTED_DISK_KEY = "disk-ressurect:last-selected-disk";

function diskCacheIdentity(disk: DiskInfo) {
  const serial = disk.serialNumber.trim().toLowerCase();
  const model = disk.model.trim().toLowerCase();
  return serial
    ? `serial:${serial}|${model}|${disk.sizeBytes}`
    : `device:${model}|${disk.sizeBytes}|${disk.number}`;
}

type RecoveryOperation = ReturnType<typeof useRecoveryOperationState>;

export function useRecoverySource(
  clearCatalog: () => void,
  operation: RecoveryOperation,
) {
  const {
    backendSessionGeneration, setBusy, setError, setStatus, setProgress,
    setPartitionScanCanResume, ensureAdministrator, beginOperation, finishOperation,
  } = operation;
  const [disks, setDisks] = useState<DiskInfo[]>([]);
  const [rawImage, setRawImage] = useState<RawImageSource | null>(null);
  const [selectedDiskNumber, setSelectedDiskNumber] = useState("");
  const [volumes, setVolumes] = useState<VolumeInfo[]>([]);
  const [selectedVolumeId, setSelectedVolumeId] = useState("");
  const sourceGeneration = useRef(0);
  const partitionRequestId = useRef(0);
  const diskRefreshRequestId = useRef(0);
  const partitionScanInFlight = useRef(false);

  const refreshDisks = useCallback(async (preserveCurrentSource = true) => {
    if (!preserveCurrentSource) {
      sourceGeneration.current += 1;
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
  }, [clearCatalog, setBusy, setError, setStatus]);

  useEffect(() => {
    void refreshDisks(false);
  }, [refreshDisks]);

  const appliedBackendGeneration = useRef(0);
  useEffect(() => {
    if (backendSessionGeneration === appliedBackendGeneration.current) return;
    appliedBackendGeneration.current = backendSessionGeneration;
    sourceGeneration.current += 1;
    partitionRequestId.current += 1;
    setRawImage(null);
    setSelectedDiskNumber("");
    setSelectedVolumeId("");
    setVolumes([]);
    clearCatalog();
    setError("");
    setStatus("The recovery service restarted. Select the source again to continue.");
    void refreshDisks(false);
  }, [backendSessionGeneration, clearCatalog, refreshDisks, setError, setStatus]);

  const selectDisk = useCallback((diskNumber: string) => {
    const selectedDisk = disks.find((disk) => String(disk.number) === diskNumber);
    const savedPartitions = selectedDisk?.cachedPartitions ?? [];
    if (selectedDisk) window.localStorage.setItem(LAST_SELECTED_DISK_KEY, diskCacheIdentity(selectedDisk));
    else window.localStorage.removeItem(LAST_SELECTED_DISK_KEY);
    setPartitionScanCanResume(Boolean(selectedDisk?.deepScanResumeAvailable));
    setRawImage(null);
    sourceGeneration.current += 1;
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
  }, [clearCatalog, disks, setError, setPartitionScanCanResume, setStatus]);

  const selectRawImage = useCallback(async () => {
    const requestGeneration = sourceGeneration.current;
    setBusy(true);
    setError("");
    try {
      const selected = await recoveryService.selectRawImage();
      if (!selected || requestGeneration !== sourceGeneration.current) return;
      sourceGeneration.current += 1;
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
    } finally {
      setBusy(false);
    }
  }, [clearCatalog, setBusy, setError, setPartitionScanCanResume, setStatus]);

  const findPartitions = useCallback(async (deepScan: boolean, resume = false) => {
    if ((!selectedDiskNumber && !rawImage) || partitionScanInFlight.current) return;
    partitionScanInFlight.current = true;
    setBusy(true);
    const generation = sourceGeneration.current;
    const requestId = ++partitionRequestId.current;
    if (!rawImage && !await ensureAdministrator()) {
      partitionScanInFlight.current = false;
      setBusy(false);
      return;
    }
    if (generation !== sourceGeneration.current || requestId !== partitionRequestId.current) {
      partitionScanInFlight.current = false;
      setBusy(false);
      return;
    }
    setError("");
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
        setSelectedVolumeId("");
        clearCatalog();
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
        ? { ...item, cachedPartitions: deepScan ? foundVolumes : savedDeepScan,
          deepScanResumeAvailable: deepScan ? false : item.deepScanResumeAvailable }
        : item));
      setSelectedVolumeId("");
      clearCatalog();
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
    } finally {
      if (requestId === partitionRequestId.current) setBusy(false);
      finishOperation(operationId);
      partitionScanInFlight.current = false;
    }
  }, [selectedDiskNumber, rawImage, disks, clearCatalog, ensureAdministrator,
    beginOperation, finishOperation, setBusy, setError, setProgress, setPartitionScanCanResume, setStatus]);

  const selectVolume = useCallback((volumeId: string) => {
    setSelectedVolumeId(volumeId);
    clearCatalog();
    setStatus(volumeId ? "Build the catalog to browse the discovered files." : "Select an NTFS partition.");
  }, [clearCatalog, setStatus]);

  const getGeneration = useCallback(() => sourceGeneration.current, []);

  return {
    disks, rawImage, selectedDiskNumber, volumes, selectedVolumeId,
    refreshDisks, selectDisk, selectRawImage, findPartitions, selectVolume, getGeneration,
  };
}
