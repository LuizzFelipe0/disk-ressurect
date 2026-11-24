from modules.disk.entities import NTFSVolume
from modules.validation.dto import DiskValidationDto
from modules.validation.repository import ValidationSnapshotRepository


class ValidationService:
    """Coordinate physical-disk validation and its historical read snapshot."""

    def __init__(self, inventory, disk_service, repository: ValidationSnapshotRepository):
        self.inventory = inventory
        self.disk_service = disk_service
        self.repository = repository

    def validate_disk(
        self, disk_number: int, progress_callback=None, retain_orphans_for_offset=None,
        orphan_scan_volume: NTFSVolume | None = None, content_carving_range_budget_bytes=None,
        force_fresh=False,
    ):
        validator = getattr(self.inventory, "validate_disk", None)
        if validator is None:
            raise NotImplementedError("This disk inventory does not support full-disk validation")
        snapshot_loader = getattr(self.repository, "load_validation_snapshot", None)
        disk = self.disk_service.get_disk(disk_number) if snapshot_loader is not None else None
        invalidator = getattr(self.repository, "invalidate_validation_snapshot", None)
        if force_fresh and invalidator is not None and disk is not None:
            invalidator(disk)
        snapshot = (
            snapshot_loader(disk)
            if snapshot_loader is not None and not force_fresh else None
        )
        snapshot_validator = getattr(self.inventory, "validate_disk_with_snapshot", None)
        if snapshot is not None and snapshot_validator is not None:
            report = snapshot_validator(
                disk_number,
                progress_callback,
                retain_orphans_for_offset,
                orphan_scan_volume,
                content_carving_range_budget_bytes,
                validation_snapshot=snapshot,
            )
            if report.get("validation_snapshot_mismatch"):
                if invalidator is not None:
                    invalidator(disk)
                report = self._validate_fresh(
                    validator,
                    disk_number,
                    progress_callback,
                    retain_orphans_for_offset,
                    orphan_scan_volume,
                    content_carving_range_budget_bytes,
                )
        else:
            report = self._validate_fresh(
                validator,
                disk_number,
                progress_callback,
                retain_orphans_for_offset,
                orphan_scan_volume,
                content_carving_range_budget_bytes,
            )

        snapshot_saver = getattr(self.repository, "save_validation_snapshot", None)
        cache_snapshot = report.get("validation_scan_snapshot")
        if snapshot_saver is not None and cache_snapshot is not None and disk is not None:
            snapshot_saver(disk, cache_snapshot)
        return report

    def validate_source(
        self, source, progress_callback=None, retain_orphans_for_offset=None,
        orphan_scan_volume=None, content_carving_range_budget_bytes=None,
    ):
        validator = getattr(self.inventory, "validate_source", None)
        if validator is None:
            raise NotImplementedError("This inventory does not support source validation")
        return validator(
            source, progress_callback, retain_orphans_for_offset, orphan_scan_volume,
            content_carving_range_budget_bytes,
        )

    @staticmethod
    def _validate_fresh(
        validator, disk_number, progress_callback, retain_orphans_for_offset,
        orphan_scan_volume, content_carving_range_budget_bytes,
    ):
        if retain_orphans_for_offset is None:
            return validator(disk_number, progress_callback)
        return validator(
            disk_number, progress_callback, retain_orphans_for_offset, orphan_scan_volume,
            content_carving_range_budget_bytes=content_carving_range_budget_bytes,
        )

    @staticmethod
    def to_dto(report):
        return DiskValidationDto.from_report(report)

    @classmethod
    def summary(cls, report):
        dto = cls.to_dto(report).to_dict()
        ntfs_checks = dto.get("ntfsChecks", [])
        return {
            "coverageStatus": dto["coverageStatus"],
            "evidenceFreshness": dto.get("evidenceFreshness", "fresh"),
            "evidenceScannedAt": dto.get("evidenceScannedAt"),
            "assessment": dto["assessment"],
            "bytesRead": dto["bytesRead"],
            "sizeBytes": dto["sizeBytes"],
            "readErrorCount": len(dto.get("readErrors", [])),
            "partitionCount": len(dto.get("partitions", [])),
            "ntfsVolumeCount": len(ntfs_checks),
            "deletedMftRecordCount": sum(
                int(item.get("mftRecords", {}).get("deleted", 0)) for item in ntfs_checks
            ),
            "orphanedFileRecordCount": sum(
                int(item.get("orphanedFileRecordCount", 0)) for item in ntfs_checks
            ),
            "inconsistentMftRecordCount": sum(
                int(item.get("mftRecords", {}).get("metadataInconsistent", 0))
                for item in ntfs_checks
            ),
            "orphanRecordsByAllocationStatus": cls._orphan_record_allocation_counts(ntfs_checks),
            "unsupportedFilesystems": list(dto.get("unsupportedFilesystems", [])),
        }

    @staticmethod
    def _orphan_record_allocation_counts(ntfs_checks):
        counts = {"free": 0, "allocated": 0, "mixed": 0, "unknown": 0}
        for check in ntfs_checks:
            for orphan in check.get("bitmapAllocation", {}).get("orphanDataAllocation", []):
                status = orphan.get("status")
                if status in ("partially_observed", "unavailable", "no_non_sparse_runs"):
                    status = "unknown"
                counts[status if status in counts else "unknown"] += 1
        return counts
