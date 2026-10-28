export type {
  BackendRuntimeStatus,
  CatalogInfo,
  CatalogNode,
  CatalogSearchResult,
  DiskInfo,
  ProgressInfo,
  PrivilegeStatus,
  RecoveryResult,
  VolumeInfo,
} from "../../electron/contracts";

export type BackendStatus = "starting" | "ready" | "error";

export interface RecoveryOptions {
  selectedNodeIds: string[];
  excludedNodeIds: string[];
  outputDirectory: string;
  extensions: string[];
  minimumSizeKb: number;
}
