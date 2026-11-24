export type {
  CarvingOptions,
  ContentCarvingSummary,
  BackendRuntimeStatus,
  CatalogInfo,
  CatalogNode,
  CatalogSearchResult,
  FilePreview,
  DiskInfo,
  ProgressInfo,
  PrivilegeStatus,
  RecoveryResult,
  RawImageSource,
  VolumeInfo,
} from "../../electron/contracts";

export type BackendStatus = "starting" | "ready" | "error";

export interface RecoveryOptions {
  selectedNodeIds: string[];
  excludedNodeIds: string[];
  outputDirectory: string;
  extensions: string[];
  minimumSizeKb: number;
  operationId?: string;
}
