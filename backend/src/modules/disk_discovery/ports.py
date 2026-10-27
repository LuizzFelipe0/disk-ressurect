from __future__ import annotations

from typing import Callable, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from disk.models import NTFSVolume, PhysicalDisk
    from disk.scanning.partition_scan import ScanCheckpoint

class DiskInventoryPort(Protocol):
    def list_disks(self) -> list[PhysicalDisk]: ...

    def list_ntfs_volumes(self, disk_number: int, progress_callback=None) -> list[NTFSVolume]: ...

    def deep_scan_ntfs_volumes(
        self,
        disk_number: int,
        progress_callback=None,
        candidate_callback: Callable[[tuple[NTFSVolume, ...]], None] | None = None,
        resume_checkpoint: ScanCheckpoint | None = None,
        checkpoint_callback: Callable[[ScanCheckpoint], None] | None = None,
    ) -> list[NTFSVolume]: ...
