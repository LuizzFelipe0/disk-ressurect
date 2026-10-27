import type {
  CatalogInfo,
  CatalogNode,
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
  listPartitions: (diskNumber: number, deepScan = false, resume = false): Promise<VolumeInfo[]> =>
    getApi().listPartitions(diskNumber, deepScan, resume),
  scanCatalog: (volumeId: string): Promise<CatalogInfo> => getApi().scanCatalog(volumeId),
  getChildren: (nodeId: string): Promise<CatalogNode[]> => getApi().getChildren(nodeId),
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
