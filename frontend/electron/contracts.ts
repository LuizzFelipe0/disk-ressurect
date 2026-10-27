export interface DiskInfo {
  number: number;
  model: string;
  sizeBytes: number;
  serialNumber: string;
  displayName: string;
  cachedPartitions?: VolumeInfo[];
  deepScanResumeAvailable?: boolean;
}

export interface VolumeInfo {
  id: string;
  diskNumber: number;
  partitionNumber: number;
  offset: number;
  sizeBytes: number;
  estimatedSize: boolean;
  name: string;
  scanSavedAt?: string;
}

export interface CatalogNode {
  id: string;
  name: string;
  path: string;
  isDirectory: boolean;
  sizeBytes: number;
  hasChildren: boolean;
}

export interface CatalogInfo {
  recordCount: number;
  availableExtensions: string[];
  roots: CatalogNode[];
}

export interface ProgressInfo {
  stage: string;
  completed: number;
  total: number;
  message: string;
}

export interface RecoveryResult {
  recoveredCount: number;
  candidateCount: number;
}

export interface BackendRuntimeStatus {
  state: "starting" | "ready" | "error";
  message: string;
}

export interface PrivilegeStatus {
  isAdministrator: boolean;
}

export interface DesktopApi {
  listDisks(): Promise<DiskInfo[]>;
  listPartitions(diskNumber: number, deepScan: boolean, resume?: boolean): Promise<VolumeInfo[]>;
  scanCatalog(volumeId: string): Promise<CatalogInfo>;
  getChildren(nodeId: string): Promise<CatalogNode[]>;
  recover(options: {
    selectedNodeIds: string[];
    excludedNodeIds: string[];
    outputDirectory: string;
    extensions: string[];
    minimumSizeKb: number;
  }): Promise<RecoveryResult>;
  chooseOutputDirectory(): Promise<string | null>;
  onProgress(callback: (progress: ProgressInfo) => void): () => void;
  getBackendStatus(): Promise<BackendRuntimeStatus>;
  onBackendStatus(callback: (status: BackendRuntimeStatus) => void): () => void;
  getPrivilegeStatus(): Promise<PrivilegeStatus>;
  requestAdministrator(): Promise<{ relaunched: boolean; cancelled: boolean; accessGranted?: boolean }>;
}

declare global {
  interface Window {
    diskResurrect: DesktopApi;
  }
}
