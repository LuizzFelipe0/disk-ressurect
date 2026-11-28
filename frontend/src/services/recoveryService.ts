import type {
  CatalogInfo,
  CatalogNode,
  CatalogSearchResult,
  CarvingOptions,
  FilePreview,
  BackendRuntimeStatus,
  DiskInfo,
  PrivilegeStatus,
  RecoveryOptions,
  RecoveryResult,
  VolumeInfo,
} from "../types/recovery";

function getApi() {
  if (!window.diskResurrect) {
    throw new Error("Electron bridge unavailable. Open this interface through the desktop application.");
  }
  return window.diskResurrect;
}

export const recoveryService = {
  listDisks: (): Promise<DiskInfo[]> => getApi().listDisks(),
  listPartitions: (diskNumber: number, deepScan = false, resume = false, operationId?: string): Promise<VolumeInfo[]> =>
    getApi().listPartitions(diskNumber, deepScan, resume, operationId),
  scanCatalog: (
    volumeId: string, includeOrphaned = false, carvingOptions?: CarvingOptions,
    forceFreshValidation = false, operationId?: string,
  ): Promise<CatalogInfo> => getApi().scanCatalog(
    volumeId, includeOrphaned, carvingOptions, forceFreshValidation, operationId,
  ),
  cancelOperation: (operationId: string): Promise<{ accepted: boolean }> =>
    getApi().cancelOperation(operationId),
  searchCatalog: (query: string): Promise<CatalogSearchResult> => getApi().searchCatalog(query),
  listSupportedFileTypes: (): Promise<string[]> => getApi().listSupportedFileTypes(),
  getChildren: (nodeId: string): Promise<CatalogNode[]> => getApi().getChildren(nodeId),
  previewFile: (nodeId: string): Promise<FilePreview> => getApi().previewFile(nodeId),
  recover: (options: RecoveryOptions): Promise<RecoveryResult> => getApi().recover(options),
  chooseOutputDirectory: (): Promise<string | null> => getApi().chooseOutputDirectory(),
  onProgress: (callback: Parameters<Window["diskResurrect"]["onProgress"]>[0]) =>
    window.diskResurrect?.onProgress(callback) ?? (() => undefined),
  getBackendStatus: (): Promise<BackendRuntimeStatus> => getApi().getBackendStatus(),
  onBackendStatus: (callback: Parameters<Window["diskResurrect"]["onBackendStatus"]>[0]) =>
    window.diskResurrect?.onBackendStatus(callback) ?? (() => undefined),
  getPrivilegeStatus: (): Promise<PrivilegeStatus> => getApi().getPrivilegeStatus(),
  requestAdministrator: () => getApi().requestAdministrator(),
};
