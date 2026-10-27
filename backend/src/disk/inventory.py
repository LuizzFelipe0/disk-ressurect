from typing import Callable

from disk.access.ports import DiskReaderFactory
from disk.enumeration.ports import DiskEnumerator
from disk.platform import create_disk_enumerator, disk_reader_factory
from disk.deep_scan.lost_partition_scanner import LostPartitionScanner
from disk.scanning.mft_anchor_scan import MFTAnchorScanner
from disk.models import NTFSVolume, PhysicalDisk
from disk.ntfs_discovery.anchor_resolver import MFTAnchorVolumeResolver
from disk.ntfs_discovery.volume_scanner import NTFSVolumeScanner


class DiskInventory:
    """Application-facing disk and NTFS volume inventory."""

    def __init__(
        self,
        enumerator: DiskEnumerator | None = None,
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
    ) -> list[NTFSVolume]:
        disk = self.disk_factory(int(disk_number))
        try:
            # A surviving $MFT record zero can locate an NTFS volume even when
            # both partition-table entries and boot sectors were overwritten.
            anchor = MFTAnchorScanner(disk).scan(progress_callback)
            if anchor is not None:
                volume = MFTAnchorVolumeResolver(disk, int(disk_number)).resolve(anchor)
                if volume is not None:
                    if candidate_callback:
                        candidate_callback((volume,))
                    return [volume]
            return LostPartitionScanner(disk, int(disk_number)).scan(
                progress_callback, candidate_callback,
            )
        finally:
            disk.close()
