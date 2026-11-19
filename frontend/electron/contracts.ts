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
  parentId?: string | null;
  ancestorIds?: string[];
  isDeleted?: boolean;
  isOrphaned?: boolean;
  isContentCarved?: boolean;
  contentValidation?: "signature_match" | "signature_mismatch" | "format_structure_match" | "unavailable" | "incomplete_metadata" | "invalid_size" | "unsupported";
  clusterAllocationStatus?: "free" | "allocated" | "mixed" | "partially_observed" | "unavailable" | "no_non_sparse_runs" | "bitmap_unobserved" | "possibly_reused";
  metadataConsistent?: boolean;
}

export interface ContentCarvingSummary {
  filesFound: number;
  bytesScanned: number;
  scanLimitReached: boolean;
  candidateBytesRead: number;
  candidateLimitReached: boolean;
  fileCountLimitReached: boolean;
  retainedBytesLimitReached: boolean;
  rangeCount: number;
  rangeCollectionTruncated: boolean;
  filesFoundByExtension?: Record<string, number>;
  candidatesExaminedByExtension?: Record<string, number>;
  candidateBytesReadByExtension?: Record<string, number>;
  candidateLimitReachedByExtension?: Record<string, boolean>;
  fileSizeLimitReachedByExtension?: Record<string, boolean>;
  decodedDataLimitReachedByExtension?: Record<string, boolean>;
  candidateReadCapBytes?: number;
  candidateReadCapBytesPerFormat?: number;
  maxFileBytes?: number;
  maxDecodedPngBytes?: number;
  scanByteCap?: number;
  retainedBytesCap?: number;
  fileCountCap?: number;
  rangeBytesRetained?: number;
  rangeCollectionCapBytes?: number;
  formatsAttempted?: string[];
  validationScope?: string;
}

export interface LowConfidenceCarvingTier extends ContentCarvingSummary {
  confidence: string;
  allocationStatus: "bitmap_unobserved" | "possibly_reused";
  catalogItemsAdded: number;
}

export interface LowConfidenceCarvingSummary {
  bitmapUnobserved: LowConfidenceCarvingTier;
  possiblyReused: LowConfidenceCarvingTier;
}

export interface CatalogInfo {
  recordCount: number;
  orphanedRecordCount?: number;
  contentCarvedCount?: number;
  orphanScanPerformed?: boolean;
  diskValidation?: DiskValidationSummary;
  contentCarving?: ContentCarvingSummary;
  lowConfidenceCarving?: LowConfidenceCarvingSummary;
  availableExtensions: string[];
  roots: CatalogNode[];
}

export interface DiskValidationSummary {
  coverageStatus: "complete" | "incomplete" | "unavailable";
  assessment: "evidence_collected" | "inconclusive";
  bytesRead: number;
  sizeBytes: number;
  readErrorCount: number;
  partitionCount: number;
  ntfsVolumeCount: number;
  deletedMftRecordCount: number;
  orphanedFileRecordCount: number;
  inconsistentMftRecordCount?: number;
  orphanRecordsByAllocationStatus?: { free: number; allocated: number; mixed: number; unknown: number };
  unsupportedFilesystems: string[];
  validationError?: string;
}

export interface CatalogSearchResult {
  totalMatches: number;
  results: CatalogNode[];
}

export interface FilePreview {
  available: boolean;
  reason?: "unsupported_format" | "too_large" | "invalid_content";
  name?: string;
  mimeType?: string;
  kind?: "image" | "pdf";
  sizeBytes?: number;
  dataBase64?: string;
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
  scanCatalog(volumeId: string, includeOrphaned?: boolean): Promise<CatalogInfo>;
  searchCatalog(query: string): Promise<CatalogSearchResult>;
  listSupportedFileTypes(): Promise<string[]>;
  getChildren(nodeId: string): Promise<CatalogNode[]>;
  previewFile(nodeId: string): Promise<FilePreview>;
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
