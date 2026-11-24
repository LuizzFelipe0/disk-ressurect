from typing import Callable

from modules.disk.service import DiskReaderFactory
from infrastructure.disk.factory import create_disk_enumerator, disk_reader_factory
from infrastructure.disk.lost_partition_scanner import LostPartitionScanner
from infrastructure.filesystems.ntfs.discovery.mft_anchor_scan import MFTAnchorScanner
from modules.storage.entities import PhysicalDisk
from modules.disk.entities import NTFSVolume
from modules.storage.entities import ScanCheckpoint
from infrastructure.filesystems.ntfs.discovery.anchor_resolver import MFTAnchorVolumeResolver
from infrastructure.filesystems.ntfs.discovery.volume_scanner import NTFSVolumeScanner
from infrastructure.validation.disk_auditor import DiskValidationAuditor


class DiskInventory:
    """Application-facing disk and NTFS volume inventory."""

    def __init__(
        self,
        enumerator=None,
        disk_factory: DiskReaderFactory | None = None,
    ):
        self.enumerator = enumerator if enumerator is not None else create_disk_enumerator()
        self.disk_factory = disk_factory if disk_factory is not None else disk_reader_factory()

    def list_disks(self) -> list[PhysicalDisk]:
        return self.enumerator.list_disks()

    def list_ntfs_volumes(self, disk_number, progress_callback=None) -> list[NTFSVolume]:
        disk = self.disk_factory(int(disk_number))
        try:
            return NTFSVolumeScanner(disk, int(disk_number)).scan(progress_callback)
        finally:
            disk.close()

    def deep_scan_ntfs_volumes(
        self,
        disk_number,
        progress_callback=None,
        candidate_callback: Callable[[tuple[NTFSVolume, ...]], None] | None = None,
        resume_checkpoint: ScanCheckpoint | None = None,
        checkpoint_callback: Callable[[ScanCheckpoint], None] | None = None,
    ) -> list[NTFSVolume]:
        disk = self.disk_factory(int(disk_number))
        try:
            # A surviving $MFT record zero can locate an NTFS volume even when
            # both partition-table entries and boot sectors were overwritten.
            anchor = None if resume_checkpoint is not None else MFTAnchorScanner(disk).scan(progress_callback)
            if resume_checkpoint is None and anchor is not None:
                volume = MFTAnchorVolumeResolver(disk, int(disk_number)).resolve(anchor)
                if volume is not None:
                    if candidate_callback:
                        candidate_callback((volume,))
                    return [volume]
            return LostPartitionScanner(disk, int(disk_number)).scan(
                progress_callback, candidate_callback, resume_checkpoint, checkpoint_callback,
            )
        finally:
            disk.close()

    def validate_disk(
        self, disk_number, progress_callback=None, retain_orphans_for_offset=None,
        orphan_scan_volume=None, content_carving_range_budget_bytes=None,
    ):
        """Read and audit the entire physical disk without modifying its contents."""
        return DiskValidationAuditor(self.enumerator, self.disk_factory).validate(
            int(disk_number), progress_callback, retain_orphans_for_offset,
            orphan_scan_volume, content_carving_range_budget_bytes,
        )

    def validate_disk_with_snapshot(
        self, disk_number, progress_callback=None, retain_orphans_for_offset=None,
        orphan_scan_volume=None, content_carving_range_budget_bytes=None,
        validation_snapshot=None,
    ):
        """Revalidate metadata while reusing an explicitly historical read snapshot."""
        return DiskValidationAuditor(self.enumerator, self.disk_factory).validate(
            int(disk_number), progress_callback, retain_orphans_for_offset,
            orphan_scan_volume, content_carving_range_budget_bytes,
            validation_snapshot=validation_snapshot,
        )
