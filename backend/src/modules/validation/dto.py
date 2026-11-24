from dataclasses import dataclass

from modules.disk.dto import DiskDto


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

    @classmethod
    def from_report(cls, report):
        disk = report["disk"]
        coverage = report["coverage"]
        cached_snapshot_used = bool(report.get("validation_snapshot_used", False))
        is_complete = (not cached_snapshot_used
                       and coverage.bytes_read == int(disk.size_bytes)
                       and not coverage.issues)
        unsupported = tuple(report["unsupported_filesystems"])
        assessment = "inconclusive" if not is_complete or report["capacity_mismatch"] else "evidence_collected"
        ntfs_checks = tuple(report["ntfs_checks"])
        metadata_problem = any(
            item.get("validationError")
            or not item.get("mftRecordZeroValid")
            or not item.get("mftMirrorMatchesFirstRecords")
            or not item.get("bitmapRecordValid")
            or not item.get("primaryAndBackupBootMatch")
            or not item.get("mftReadComplete")
            or int(item.get("mftRecords", {}).get("invalidFileRecords", 0)) > 0
            or int(item.get("mftRecords", {}).get("metadataInconsistent", 0)) > 0
            for item in ntfs_checks
        )
        metadata_problem = metadata_problem or any(
            not item.get("valid") for item in report["partition_table_checks"]
        )
        if not report["mbr_signature_found"] and not any(
            item.get("valid") for item in report["partition_table_checks"]
        ):
            metadata_problem = True
        candidates_found = any(
            int(item.get("orphanedFileRecordCount", 0)) > 0
            or int(item.get("mftRecords", {}).get("deleted", 0)) > 0
            for item in ntfs_checks
        )
        if (unsupported or metadata_problem or not ntfs_checks or candidates_found) and assessment == "evidence_collected":
            assessment = "inconclusive"
        return cls(
            number=disk.number,
            model=disk.model,
            size_bytes=disk.size_bytes,
            serial_number=disk.serial_number,
            coverage_status=("cached_snapshot" if cached_snapshot_used else
                "complete" if is_complete else "incomplete"),
            evidence_freshness=("cached_snapshot" if cached_snapshot_used else "fresh"),
            evidence_scanned_at=report.get("validation_snapshot_scanned_at"),
            assessment=assessment,
            bytes_requested=coverage.bytes_requested,
            bytes_read=coverage.bytes_read,
            io_bytes_read=coverage.bytes_read_total,
            read_intervals=tuple(interval.to_dict() for interval in coverage.intervals_as_objects()),
            read_errors=tuple(issue.to_dict() for issue in coverage.issues),
            partitions=tuple(report["partitions"]),
            mbr_signature_found=bool(report["mbr_signature_found"]),
            partition_table_checks=tuple(report["partition_table_checks"]),
            ntfs_checks=tuple(report["ntfs_checks"]),
            unsupported_filesystems=unsupported,
            filesystem_signatures=tuple(report["filesystem_signatures"]),
            interpretation=(
                ("Physical read coverage is a historical cached snapshot from "
                 f"{report.get('validation_snapshot_scanned_at')}; it was not re-read now. "
                 if cached_snapshot_used else "")
                + "This audit does not prove the disk contains no recoverable data. "
                + ("Review partition and NTFS findings and scan supported file systems."
                    if assessment == "evidence_collected"
                    else "Some disk areas or structures could not be fully validated; treat the result as inconclusive.")
            ),
        )
