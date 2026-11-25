from dataclasses import dataclass



@dataclass(frozen=True)
class CarvingOptionsDto:
    """User-selected, bounded budgets for the trusted free-space carver."""

    scan_budget_gib: int = 64
    max_files: int = 16384
    max_retained_mib: int = 512
    max_candidate_read_mib_per_format: int = 1024

    SCAN_BUDGETS_GIB = (1, 4, 16, 64)
    FILE_COUNT_LIMITS = (256, 512, 1024, 2048, 4096, 8192, 16384)
    RETAINED_BUDGETS_MIB = (128, 256, 512)
    CANDIDATE_READ_BUDGETS_MIB_PER_FORMAT = (256, 512, 1024)

    @classmethod
    def from_payload(cls, payload):
        if not isinstance(payload, dict):
            raise ValueError("carvingOptions must be a JSON object")
        scan_budget_gib = payload.get("scanBudgetGiB", 64)
        if (isinstance(scan_budget_gib, bool) or not isinstance(scan_budget_gib, int)
                or scan_budget_gib not in cls.SCAN_BUDGETS_GIB):
            raise ValueError("carvingOptions.scanBudgetGiB must be one of 1, 4, 16 or 64")
        max_files = payload.get("maxFiles", 16384)
        if (isinstance(max_files, bool) or not isinstance(max_files, int)
                or max_files not in cls.FILE_COUNT_LIMITS):
            raise ValueError(
                "carvingOptions.maxFiles must be one of 256, 512, 1024, 2048, 4096, 8192 or 16384"
            )
        max_retained_mib = payload.get("maxRetainedMiB", 512)
        if (isinstance(max_retained_mib, bool) or not isinstance(max_retained_mib, int)
                or max_retained_mib not in cls.RETAINED_BUDGETS_MIB):
            raise ValueError("carvingOptions.maxRetainedMiB must be one of 128, 256 or 512")
        candidate_read_mib_per_format = payload.get("maxCandidateReadMiBPerFormat", 1024)
        if (isinstance(candidate_read_mib_per_format, bool)
                or not isinstance(candidate_read_mib_per_format, int)
                or candidate_read_mib_per_format not in cls.CANDIDATE_READ_BUDGETS_MIB_PER_FORMAT):
            raise ValueError(
                "carvingOptions.maxCandidateReadMiBPerFormat must be one of 256, 512 or 1024"
            )
        unknown = set(payload) - {
            "scanBudgetGiB", "maxFiles", "maxRetainedMiB", "maxCandidateReadMiBPerFormat",
        }
        if unknown:
            raise ValueError("carvingOptions contains unsupported fields")
        return cls(scan_budget_gib, max_files, max_retained_mib, candidate_read_mib_per_format)


@dataclass(frozen=True)
class VolumeSelectionRequestDto:
    volume_id: str
    include_orphaned: bool = True
    carving_options: CarvingOptionsDto = CarvingOptionsDto()
    force_fresh_validation: bool = True

    @classmethod
    def from_payload(cls, payload):
        value = payload.get("volumeId")
        if not isinstance(value, str) or not value:
            raise ValueError("volumeId must be a non-empty string")
        include_orphaned = payload.get("includeOrphaned", True)
        if not isinstance(include_orphaned, bool):
            raise ValueError("includeOrphaned must be a boolean")
        force_fresh_validation = payload.get("forceFreshValidation", True)
        if not isinstance(force_fresh_validation, bool):
            raise ValueError("forceFreshValidation must be a boolean")
        carving_options = CarvingOptionsDto.from_payload(payload.get("carvingOptions", {}))
        return cls(value, include_orphaned, carving_options, force_fresh_validation)


@dataclass(frozen=True)
class CatalogNodeRequestDto:
    node_id: str

    @classmethod
    def from_payload(cls, payload):
        value = payload.get("nodeId")
        if not isinstance(value, str) or not value:
            raise ValueError("nodeId must be a non-empty string")
        return cls(value)


@dataclass(frozen=True)
class FilePreviewRequestDto:
    node_id: str

    @classmethod
    def from_payload(cls, payload):
        value = payload.get("nodeId")
        if not isinstance(value, str) or not value:
            raise ValueError("nodeId must be a non-empty string")
        return cls(value)


@dataclass(frozen=True)
class CatalogSearchRequestDto:
    query: str

    @classmethod
    def from_payload(cls, payload):
        value = payload.get("query", "")
        if not isinstance(value, str):
            raise ValueError("query must be a string")
        return cls(value.strip())


@dataclass(frozen=True)
class CatalogNodeDto:
    id: str
    name: str
    path: str
    is_directory: bool
    size_bytes: int
    has_children: bool
    parent_id: str | None = None
    ancestor_ids: tuple[str, ...] | None = None
    is_deleted: bool = False
    is_orphaned: bool = False
    is_content_carved: bool = False
    content_validation: str | None = None
    cluster_allocation_status: str | None = None
    metadata_consistent: bool | None = None
    recovery_source: str | None = None
    original_path: str | None = None
    deletion_timestamp_utc: str | None = None
    original_size_bytes: int | None = None
    data_extent_resolution: str | None = None
    data_extent_resolution_reason: str | None = None
    data_extent_count: int | None = None

    def to_dict(self):
        result = {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "isDirectory": self.is_directory,
            "sizeBytes": self.size_bytes,
            "hasChildren": self.has_children,
            "parentId": self.parent_id,
            "isDeleted": self.is_deleted,
            "isOrphaned": self.is_orphaned,
            "isContentCarved": self.is_content_carved,
        }
        if self.content_validation is not None:
            result["contentValidation"] = self.content_validation
        if self.cluster_allocation_status is not None:
            result["clusterAllocationStatus"] = self.cluster_allocation_status
        if self.metadata_consistent is not None:
            result["metadataConsistent"] = self.metadata_consistent
        if self.recovery_source is not None:
            result["recoverySource"] = self.recovery_source
        if self.original_path is not None:
            result["originalPath"] = self.original_path
        if self.deletion_timestamp_utc is not None:
            result["deletionTimestampUtc"] = self.deletion_timestamp_utc
        if self.original_size_bytes is not None:
            result["originalSizeBytes"] = self.original_size_bytes
        if self.data_extent_resolution is not None:
            result["dataExtentResolution"] = self.data_extent_resolution
        if self.data_extent_resolution_reason is not None:
            result["dataExtentResolutionReason"] = self.data_extent_resolution_reason
        if self.data_extent_count is not None:
            result["dataExtentCount"] = self.data_extent_count
        if self.ancestor_ids is not None:
            result["ancestorIds"] = list(self.ancestor_ids)
        return result


@dataclass(frozen=True)
class CatalogDto:
    record_count: int
    available_extensions: tuple[str, ...]
    roots: tuple[CatalogNodeDto, ...]
    orphaned_record_count: int = 0
    orphan_scan_performed: bool = False
    disk_validation: dict | None = None
    content_carving: dict | None = None
    content_carved_count: int = 0
    low_confidence_carving: dict | None = None
    recycle_bin_recovery: dict | None = None
    usn_journal_evidence: dict | None = None
    ntfs_log_file_evidence: dict | None = None

    def to_dict(self):
        result = {
            "recordCount": self.record_count,
            "orphanedRecordCount": self.orphaned_record_count,
            "contentCarvedCount": self.content_carved_count,
            "orphanScanPerformed": self.orphan_scan_performed,
            "availableExtensions": list(self.available_extensions),
            "roots": [node.to_dict() for node in self.roots],
        }
        if self.disk_validation is not None:
            result["diskValidation"] = self.disk_validation
        if self.content_carving is not None:
            result["contentCarving"] = self.content_carving
        if self.low_confidence_carving is not None:
            result["lowConfidenceCarving"] = self.low_confidence_carving
        if self.recycle_bin_recovery is not None:
            result["recycleBinRecovery"] = self.recycle_bin_recovery
        if self.usn_journal_evidence is not None:
            result["usnJournalEvidence"] = self.usn_journal_evidence
        if self.ntfs_log_file_evidence is not None:
            result["ntfsLogFileEvidence"] = self.ntfs_log_file_evidence
        return result


@dataclass(frozen=True)
class CatalogSearchDto:
    total_matches: int
    results: tuple[CatalogNodeDto, ...]

    def to_dict(self):
        return {
            "totalMatches": self.total_matches,
            "results": [node.to_dict() for node in self.results],
        }
