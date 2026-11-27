export type {
  CarvingOptions,
  ContentCarvingSummary,
  FragmentReconstructionEvidence,
  PartialPngRecoveryInfo,
  PNGFragmentReconstructionSummary,
  BackendRuntimeStatus,
  CatalogInfo,
  CatalogNode,
  CatalogSearchResult,
  FilePreview,
  DiskInfo,
  ProgressInfo,
  PrivilegeStatus,
  RecoveryResult,
  VolumeInfo,
} from "../../electron/contracts";

export type BackendStatus = "starting" | "ready" | "error";

export interface RecoveryOptions {
  selectedNodeIds: string[];
  selectedPartialPngIds: string[];
  excludedNodeIds: string[];
  outputDirectory: string;
  extensions: string[];
  minimumSizeKb: number;
  operationId?: string;
}
