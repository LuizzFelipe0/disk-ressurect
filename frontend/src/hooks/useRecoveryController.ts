import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { recoveryService } from "../services/recoveryService";
import type {
  BackendStatus,
  CatalogInfo,
  CatalogNode,
  CatalogSearchResult,
  DiskInfo,
  ProgressInfo,
  VolumeInfo,
} from "../types/recovery";
import { isTreeNodeSelected, updateTreeSelection } from "../utils/selection";

const LAST_SELECTED_DISK_KEY = "disk-ressurect:last-selected-disk";

function diskCacheIdentity(disk: DiskInfo) {
  const serial = disk.serialNumber.trim().toLowerCase();
  const model = disk.model.trim().toLowerCase();
  return serial
    ? `serial:${serial}|${model}|${disk.sizeBytes}`
    : `device:${model}|${disk.sizeBytes}|${disk.number}`;
}

export function useRecoveryController() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("starting");
  const [isAdministrator, setIsAdministrator] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Starting the Python recovery service…");
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const [partitionScanCanResume, setPartitionScanCanResume] = useState(false);
  const [disks, setDisks] = useState<DiskInfo[]>([]);
  const [selectedDiskNumber, setSelectedDiskNumber] = useState("");
  const [volumes, setVolumes] = useState<VolumeInfo[]>([]);
  const [selectedVolumeId, setSelectedVolumeId] = useState("");
  const [catalog, setCatalog] = useState<CatalogInfo | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResult, setSearchResult] = useState<CatalogSearchResult | null>(null);
  const [searchingCatalog, setSearchingCatalog] = useState(false);
  const [childrenById, setChildrenById] = useState<Record<string, CatalogNode[]>>({});
  const [parentById, setParentById] = useState<Map<string, string | null>>(new Map());
  const [loadingFolderIds, setLoadingFolderIds] = useState<Set<string>>(new Set());
  const [expandedFolderIds, setExpandedFolderIds] = useState<Set<string>>(new Set());
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [excludedIds, setExcludedIds] = useState<Set<string>>(new Set());
  const [availableExtensions, setAvailableExtensions] = useState<string[]>([]);
  const [extensions, setExtensions] = useState<string[]>([]);
  const [minimumSizeKb, setMinimumSizeKb] = useState(0);
  const [outputDirectory, setOutputDirectory] = useState("");
  const initialLoadStarted = useRef(false);

  const clearCatalog = useCallback(() => {
    setCatalog(null);
    setSearchQuery("");
    setSearchResult(null);
    setSearchingCatalog(false);
    setChildrenById({});
    setParentById(new Map());
    setExpandedFolderIds(new Set());
    setLoadingFolderIds(new Set());
    setSelectedIds(new Set());
    setExcludedIds(new Set());
  }, []);

  const refreshDisks = useCallback(async () => {
    setBusy(true);
    setError("");
    setStatus("Checking disks through the Python service…");
    try {
      const foundDisks = await recoveryService.listDisks();
      setDisks(foundDisks);
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
      setBackendStatus("ready");
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
      const message = cause instanceof Error ? cause.message : String(cause);
      const runtime = await recoveryService.getBackendStatus().catch(() => null);
      if (runtime?.state === "error") {
        setBackendStatus("error");
        setError(runtime.message);
        setStatus("The Python recovery process has exited.");
      } else {
        setError(message);
        setStatus("Disk discovery failed. See the details below.");
      }
    } finally { setBusy(false); }
  }, [clearCatalog]);

  useEffect(() => {
    const unsubscribe = recoveryService.onProgress((event) => {
      setProgress(event);
      if (event.message) setStatus(event.message);
    });
    const unsubscribeBackend = recoveryService.onBackendStatus((runtime) => {
      setBackendStatus(runtime.state);
      if (runtime.state === "error") {
        setError(runtime.message);
        setStatus("The Python recovery process has exited.");
      }
    });
    void recoveryService.getBackendStatus().then((runtime) => {
      setBackendStatus(runtime.state);
      if (runtime.state === "error") {
        setError(runtime.message);
        setStatus("The Python recovery process has exited.");
      }
    }).catch((cause: unknown) => {
      setBackendStatus("error");
      setError(cause instanceof Error ? cause.message : String(cause));
      setStatus("Unable to check the Python service status.");
    });
    void recoveryService.getPrivilegeStatus().then((privileges) => {
      setIsAdministrator(privileges.isAdministrator);
    }).catch((cause: unknown) => {
      setIsAdministrator(false);
      setError(cause instanceof Error ? cause.message : String(cause));
    });
    void recoveryService.listSupportedFileTypes().then((fileTypes) => {
      setAvailableExtensions(fileTypes);
      setExtensions((current) => current.length ? current : fileTypes);
    }).catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : String(cause));
    });
    if (!initialLoadStarted.current) {
      initialLoadStarted.current = true;
      void refreshDisks();
    }
    return () => { unsubscribe(); unsubscribeBackend(); };
  }, [refreshDisks]);

  const ensureAdministrator = useCallback(async () => {
    try {
      const privilege = await recoveryService.getPrivilegeStatus();
      setIsAdministrator(privilege.isAdministrator);
      if (privilege.isAdministrator) return true;
      setStatus("Reading physical disks requires elevated permission.");
      setError("");
      const result = await recoveryService.requestAdministrator();
      if (result.accessGranted) {
        setIsAdministrator(true);
        setStatus("Disk access permission was granted.");
        return true;
      }
      if (result.relaunched) {
        setStatus("The application is restarting with elevated permissions.");
      } else {
        setStatus("The scan was canceled because disk access permission was not granted.");
        setError("Authorize the system permission request to read physical disks.");
      }
      return false;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setStatus("Unable to request elevated disk access.");
      return false;
    }
  }, []);

  const selectDisk = useCallback((diskNumber: string) => {
    const selectedDisk = disks.find((disk) => String(disk.number) === diskNumber);
    const savedPartitions = selectedDisk?.cachedPartitions ?? [];
    if (selectedDisk) window.localStorage.setItem(LAST_SELECTED_DISK_KEY, diskCacheIdentity(selectedDisk));
    else window.localStorage.removeItem(LAST_SELECTED_DISK_KEY);
    setPartitionScanCanResume(Boolean(selectedDisk?.deepScanResumeAvailable));
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

  const findPartitions = useCallback(async (deepScan: boolean, resume = false) => {
    if (!selectedDiskNumber) return;
    if (!await ensureAdministrator()) return;
    setBusy(true); setError("");
    if (!resume) setProgress(null);
    if (!resume) setPartitionScanCanResume(false);
    setStatus(resume ? "Resuming lost-partition scan…" : deepScan ? "Searching for lost NTFS partitions…" : "Scanning partitions…");
    try {
      const foundVolumes = await recoveryService.listPartitions(Number(selectedDiskNumber), deepScan, resume);
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
    finally { setBusy(false); }
  }, [selectedDiskNumber, disks, clearCatalog, ensureAdministrator]);

  const selectVolume = useCallback((volumeId: string) => {
    setSelectedVolumeId(volumeId); clearCatalog();
    setStatus(volumeId ? "Build the catalog to browse the discovered files." : "Select an NTFS partition.");
  }, [clearCatalog]);

  const buildCatalog = useCallback(async () => {
    if (!selectedVolumeId) return;
    if (!await ensureAdministrator()) return;
    setBusy(true); setError(""); setProgress(null);
    setStatus("Reading metadata and building the catalog…");
    try {
      const result = await recoveryService.scanCatalog(selectedVolumeId);
      const parents = new Map<string, string | null>();
      result.roots.forEach((node) => parents.set(node.id, node.parentId ?? null));
      setCatalog(result); setParentById(parents);
      setSearchQuery("");
      setSearchResult(null);
      setStatus(`Catalog ready: ${result.recordCount.toLocaleString()} MFT records.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); setStatus("Unable to build the catalog."); }
    finally { setBusy(false); }
  }, [selectedVolumeId, ensureAdministrator]);

  const searchRequestId = useRef(0);
  useEffect(() => {
    const query = searchQuery.trim();
    if (!catalog || !query) {
      searchRequestId.current += 1;
      setSearchResult(null);
      setSearchingCatalog(false);
      return undefined;
    }

    const requestId = ++searchRequestId.current;
    setSearchingCatalog(true);
    const timeout = window.setTimeout(() => {
      void recoveryService.searchCatalog(query).then((result) => {
        if (searchRequestId.current !== requestId) return;
        setSearchResult(result);
        setParentById((current) => {
          const next = new Map(current);
          result.results.forEach((node) => {
            let parentId: string | null = null;
            (node.ancestorIds ?? []).forEach((ancestorId) => {
              next.set(ancestorId, parentId);
              parentId = ancestorId;
            });
            next.set(node.id, node.parentId ?? parentId);
          });
          return next;
        });
      }).catch((cause: unknown) => {
        if (searchRequestId.current === requestId) {
          setSearchResult({ totalMatches: 0, results: [] });
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      }).finally(() => {
        if (searchRequestId.current === requestId) setSearchingCatalog(false);
      });
    }, 220);
    return () => window.clearTimeout(timeout);
  }, [catalog, searchQuery]);

  const toggleFolder = useCallback(async (node: CatalogNode) => {
    if (expandedFolderIds.has(node.id)) {
      setExpandedFolderIds((current) => { const next = new Set(current); next.delete(node.id); return next; });
      return;
    }
    if (childrenById[node.id]) {
      setExpandedFolderIds((current) => new Set(current).add(node.id));
      return;
    }
    setLoadingFolderIds((current) => new Set(current).add(node.id)); setError("");
    try {
      const children = await recoveryService.getChildren(node.id);
      setChildrenById((current) => ({ ...current, [node.id]: children }));
      setParentById((current) => {
        const next = new Map(current);
        children.forEach((child) => next.set(child.id, node.id));
        return next;
      });
      setExpandedFolderIds((current) => new Set(current).add(node.id));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoadingFolderIds((current) => { const next = new Set(current); next.delete(node.id); return next; }); }
  }, [childrenById, expandedFolderIds]);

  const descendantsById = useMemo(() => {
    const descendants = new Map<string, string[]>();
    Object.entries(childrenById).forEach(([id, children]) => descendants.set(id, children.map((child) => child.id)));
    return descendants;
  }, [childrenById]);

  const toggleSelection = useCallback((nodeId: string, checked: boolean) => {
    const next = updateTreeSelection(nodeId, checked,
      { selectedIds, excludedIds }, parentById, descendantsById);
    setSelectedIds(next.selectedIds); setExcludedIds(next.excludedIds);
  }, [selectedIds, excludedIds, parentById, descendantsById]);

  const isSelected = useCallback((nodeId: string) =>
    isTreeNodeSelected(nodeId, { selectedIds, excludedIds }, parentById),
  [selectedIds, excludedIds, parentById]);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(catalog?.roots.map((node) => node.id) ?? []));
    setExcludedIds(new Set());
  }, [catalog]);

  const clearSelection = useCallback(() => { setSelectedIds(new Set()); setExcludedIds(new Set()); }, []);

  const chooseOutputDirectory = useCallback(async () => {
    try {
      const directory = await recoveryService.chooseOutputDirectory();
      if (directory) setOutputDirectory(directory);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }, []);

  const recover = useCallback(async () => {
    if (!selectedIds.size || !extensions.length || !outputDirectory.trim()) {
      setError(!outputDirectory.trim() ? "Choose a destination folder to continue." : "Select files and at least one file type.");
      return;
    }
    if (!await ensureAdministrator()) return;
    setBusy(true); setError(""); setProgress(null); setStatus("Recovering the selected items…");
    try {
      const result = await recoveryService.recover({
        selectedNodeIds: [...selectedIds], excludedNodeIds: [...excludedIds],
        outputDirectory, extensions, minimumSizeKb,
      });
      setStatus(`Completed: ${result.recoveredCount}/${result.candidateCount} files recovered.`);
      setProgress({ stage: "extract", completed: 1, total: 1, message: "Recovery completed." });
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); setStatus("Recovery failed."); }
    finally { setBusy(false); }
  }, [selectedIds, excludedIds, outputDirectory, extensions, minimumSizeKb, ensureAdministrator]);

  const setExtensionSelected = useCallback((extension: string, checked: boolean) => {
    setExtensions((current) => checked
      ? [...new Set([...current, extension])]
      : current.filter((item) => item !== extension));
  }, []);

  return {
    backendStatus, isAdministrator, busy, error, status, progress, disks, selectedDiskNumber, volumes,
    partitionScanCanResume,
    selectedVolumeId, catalog, childrenById, loadingFolderIds, expandedFolderIds,
    selectedIds, availableExtensions, extensions, minimumSizeKb, outputDirectory,
    searchQuery, searchResult, searchingCatalog,
    refreshDisks, selectDisk, findPartitions, selectVolume, buildCatalog, toggleFolder,
    toggleSelection, isSelected, selectAll, clearSelection, chooseOutputDirectory,
    recover, setExtensionSelected, setMinimumSizeKb, setOutputDirectory, setSearchQuery,
    ensureAdministrator,
  };
}
