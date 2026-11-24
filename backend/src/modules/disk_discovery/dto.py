from dataclasses import dataclass


@dataclass(frozen=True)
class PartitionScanRequestDto:
    disk_number: int
    deep_scan: bool = False
    resume: bool = False

    @classmethod
    def from_payload(cls, payload):
        disk_number = payload.get("diskNumber")
        deep_scan = payload.get("deepScan", False)
        resume = payload.get("resume", False)
        if isinstance(disk_number, bool):
            raise ValueError("diskNumber must be an integer")
        try:
            disk_number = int(disk_number)
        except (TypeError, ValueError) as exc:
            raise ValueError("diskNumber must be an integer") from exc
        if disk_number < 0:
            raise ValueError("diskNumber cannot be negative")
        if not isinstance(deep_scan, bool):
            raise ValueError("deepScan must be a boolean")
        if not isinstance(resume, bool):
            raise ValueError("resume must be a boolean")
        if resume and not deep_scan:
            raise ValueError("resume requires deepScan")
        return cls(disk_number, deep_scan, resume)


@dataclass(frozen=True)
class DiskValidationRequestDto:
    disk_number: int

    @classmethod
    def from_payload(cls, payload):
        disk_number = payload.get("diskNumber")
        if isinstance(disk_number, bool):
            raise ValueError("diskNumber must be an integer")
        try:
            disk_number = int(disk_number)
        except (TypeError, ValueError) as exc:
            raise ValueError("diskNumber must be an integer") from exc
        if disk_number < 0:
            raise ValueError("diskNumber cannot be negative")
        return cls(disk_number)


@dataclass(frozen=True)
class PartitionDto:
    id: str
    disk_number: int
    partition_number: int
    offset: int
    size_bytes: int
    estimated_size: bool
    name: str
    scan_saved_at: str | None = None

    def to_dict(self):
        result = {
            "id": self.id,
            "diskNumber": self.disk_number,
            "partitionNumber": self.partition_number,
            "offset": self.offset,
            "sizeBytes": self.size_bytes,
            "estimatedSize": self.estimated_size,
            "name": self.name,
        }
        if self.scan_saved_at:
            result["scanSavedAt"] = self.scan_saved_at
        return result


@dataclass(frozen=True)
class DiskDto:
    """Common physical-disk identity carried by disk-level response DTOs."""

    number: int
    model: str
    size_bytes: int
    serial_number: str

    def identity_dict(self):
        return {
            "number": self.number,
            "model": self.model,
            "sizeBytes": self.size_bytes,
            "serialNumber": self.serial_number,
        }


@dataclass(frozen=True)
class DiscoveredDiskDto(DiskDto):
    display_name: str
    cached_partitions: tuple[PartitionDto, ...] = ()
    deep_scan_resume_available: bool = False

    def to_dict(self):
        return {
            **self.identity_dict(),
            "displayName": self.display_name,
            "cachedPartitions": [item.to_dict() for item in self.cached_partitions],
            "deepScanResumeAvailable": self.deep_scan_resume_available,
        }


@dataclass(frozen=True)
class DiskValidationDto(DiskDto):
    coverage_status: str
    evidence_freshness: str
    evidence_scanned_at: str | None
    assessment: str
    bytes_requested: int
    bytes_read: int
    io_bytes_read: int
    read_intervals: tuple[dict, ...]
    read_errors: tuple[dict, ...]
    partitions: tuple[dict, ...]
    mbr_signature_found: bool
    partition_table_checks: tuple[dict, ...]
    ntfs_checks: tuple[dict, ...]
    unsupported_filesystems: tuple[str, ...] = ()
    filesystem_signatures: tuple[dict, ...] = ()
    interpretation: str = ""

    def to_dict(self):
        return {
            **self.identity_dict(),
            "coverageStatus": self.coverage_status,
            "evidenceFreshness": self.evidence_freshness,
            "evidenceScannedAt": self.evidence_scanned_at,
            "assessment": self.assessment,
            "bytesRequested": self.bytes_requested,
            "bytesRead": self.bytes_read,
            "ioBytesRead": self.io_bytes_read,
            "readIntervals": list(self.read_intervals),
            "readErrors": list(self.read_errors),
            "partitions": list(self.partitions),
            "mbrSignatureFound": self.mbr_signature_found,
            "partitionTableChecks": list(self.partition_table_checks),
            "ntfsChecks": list(self.ntfs_checks),
            "unsupportedFilesystems": list(self.unsupported_filesystems),
            "filesystemSignatures": list(self.filesystem_signatures),
            "interpretation": self.interpretation,
        }
