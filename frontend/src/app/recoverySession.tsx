import React, { createContext, useContext, useEffect, useMemo, useRef } from "react";
import type { useRecoveryController } from "../hooks/useRecoveryController";

type RecoveryState = ReturnType<typeof useRecoveryController>;
type Slice<Key extends keyof RecoveryState> = Pick<RecoveryState, Key>;

const OperationContext = createContext<Slice<
  "backendStatus" | "isAdministrator" | "busy" | "error"
  | "partitionScanCanResume" | "ensureAdministrator"
> | null>(null);
const ActivityContext = createContext<Slice<"status" | "progress"> | null>(null);
const StorageContext = createContext<Slice<
  "disks" | "rawImage" | "selectedDiskNumber" | "volumes" | "selectedVolumeId"
  | "sessionId" | "refreshDisks" | "selectDisk" | "selectRawImage" | "findPartitions" | "selectVolume"
> | null>(null);
const CatalogContext = createContext<Slice<
  "catalog" | "childrenById" | "loadingFolderIds" | "expandedFolderIds" | "preview"
  | "previewLoading" | "previewFile" | "searchQuery" | "searchResult" | "searchingCatalog"
  | "buildCatalog" | "toggleFolder" | "toggleSelection" | "isSelected" | "selectedIds"
  | "selectAll" | "clearSelection"
> | null>(null);
const RecoveryContext = createContext<Slice<
  "extensions" | "availableExtensions" | "minimumSizeKb" | "outputDirectory"
  | "recoveryResult" | "chooseOutputDirectory" | "recover" | "setExtensionSelected" | "setMinimumSizeKb"
  | "setOutputDirectory" | "setSearchQuery"
> | null>(null);
const CatalogScrollContext = createContext<{
  read: () => number;
  remember: (position: number) => void;
} | null>(null);

function requireContext<T>(context: React.Context<T | null>, name: string): T {
  const value = useContext(context);
  if (!value) throw new Error(`${name} must be rendered inside RecoverySessionProvider`);
  return value;
}

export const RecoverySessionProvider: React.FC<React.PropsWithChildren<{ value: RecoveryState }>> = ({ value, children }) => {
  const catalogScrollTop = useRef(0);
  useEffect(() => { catalogScrollTop.current = 0; }, [value.sessionId]);
  const scrollValue = useMemo(() => ({
    read: () => catalogScrollTop.current,
    remember: (position: number) => { catalogScrollTop.current = Math.max(0, position); },
  }), []);
  const operationValue = useMemo(() => ({
    backendStatus: value.backendStatus, isAdministrator: value.isAdministrator, busy: value.busy,
    error: value.error,
    partitionScanCanResume: value.partitionScanCanResume, ensureAdministrator: value.ensureAdministrator,
  }), [value.backendStatus, value.isAdministrator, value.busy, value.error,
    value.partitionScanCanResume, value.ensureAdministrator]);
  const activityValue = useMemo(() => ({ status: value.status, progress: value.progress }), [value.status, value.progress]);
  const storageValue = useMemo(() => ({
      disks: value.disks, rawImage: value.rawImage, selectedDiskNumber: value.selectedDiskNumber,
      volumes: value.volumes, selectedVolumeId: value.selectedVolumeId, sessionId: value.sessionId,
      refreshDisks: value.refreshDisks,
      selectDisk: value.selectDisk, selectRawImage: value.selectRawImage,
      findPartitions: value.findPartitions, selectVolume: value.selectVolume,
  }), [value.disks, value.rawImage, value.selectedDiskNumber, value.volumes, value.selectedVolumeId,
    value.sessionId, value.refreshDisks, value.selectDisk, value.selectRawImage,
    value.findPartitions, value.selectVolume]);
  const catalogValue = useMemo(() => ({
        catalog: value.catalog, childrenById: value.childrenById, loadingFolderIds: value.loadingFolderIds,
        expandedFolderIds: value.expandedFolderIds, preview: value.preview,
        previewLoading: value.previewLoading, previewFile: value.previewFile,
        searchQuery: value.searchQuery, searchResult: value.searchResult, searchingCatalog: value.searchingCatalog,
        buildCatalog: value.buildCatalog, toggleFolder: value.toggleFolder,
        toggleSelection: value.toggleSelection, isSelected: value.isSelected,
        selectedIds: value.selectedIds, selectAll: value.selectAll, clearSelection: value.clearSelection,
  }), [value.catalog, value.childrenById, value.loadingFolderIds, value.expandedFolderIds,
    value.preview, value.previewLoading, value.previewFile, value.searchQuery, value.searchResult,
    value.searchingCatalog, value.buildCatalog, value.toggleFolder, value.toggleSelection,
    value.isSelected, value.selectedIds, value.selectAll, value.clearSelection]);
  const recoveryValue = useMemo(() => ({
          extensions: value.extensions, availableExtensions: value.availableExtensions,
          minimumSizeKb: value.minimumSizeKb, outputDirectory: value.outputDirectory,
          recoveryResult: value.recoveryResult,
          chooseOutputDirectory: value.chooseOutputDirectory, recover: value.recover,
          setExtensionSelected: value.setExtensionSelected, setMinimumSizeKb: value.setMinimumSizeKb,
          setOutputDirectory: value.setOutputDirectory, setSearchQuery: value.setSearchQuery,
  }), [value.extensions, value.availableExtensions, value.minimumSizeKb, value.outputDirectory,
    value.recoveryResult, value.chooseOutputDirectory, value.recover, value.setExtensionSelected,
    value.setMinimumSizeKb, value.setOutputDirectory, value.setSearchQuery]);
  return <CatalogScrollContext.Provider value={scrollValue}>
    <OperationContext.Provider value={operationValue}>
      <ActivityContext.Provider value={activityValue}>
      <StorageContext.Provider value={storageValue}>
        <CatalogContext.Provider value={catalogValue}>
          <RecoveryContext.Provider value={recoveryValue}>{children}</RecoveryContext.Provider>
        </CatalogContext.Provider>
      </StorageContext.Provider>
      </ActivityContext.Provider>
    </OperationContext.Provider>
  </CatalogScrollContext.Provider>;
};

export const useRecoveryOperation = () => requireContext(OperationContext, "Operation page");
export const useRecoveryActivity = () => requireContext(ActivityContext, "Application layout");
export const useStorageSession = () => requireContext(StorageContext, "Storage page");
export const useCatalogSession = () => requireContext(CatalogContext, "Catalog page");
export const useRecoverySession = () => requireContext(RecoveryContext, "Recovery page");
export const useCatalogScrollPosition = () => requireContext(CatalogScrollContext, "Catalog page");
