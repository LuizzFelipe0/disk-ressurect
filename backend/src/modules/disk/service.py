from typing import Callable, Protocol

from modules.disk.entities import ScanCheckpoint
from modules.disk.entities import DiscoveredDisk, NTFSVolume, PhysicalDisk
from modules.disk.repository import DiskRepository


class DiskInventoryPort(Protocol):
    """Operations the disk feature needs from platform-specific discovery."""

    def list_disks(self) -> list[PhysicalDisk]: ...

    def list_ntfs_volumes(self, disk_number: int, progress_callback=None) -> list[NTFSVolume]: ...

    def deep_scan_ntfs_volumes(
        self, disk_number: int, progress_callback=None,
        candidate_callback: Callable[[tuple[NTFSVolume, ...]], None] | None = None,
        resume_checkpoint: ScanCheckpoint | None = None,
        checkpoint_callback: Callable[[ScanCheckpoint], None] | None = None,
    ) -> list[NTFSVolume]: ...

class DiskReader(Protocol):
    size: int
    bytes_per_sector: int

    def read_at(self, offset: int, size: int) -> bytes: ...

    def close(self) -> None: ...


class DiskReaderFactory(Protocol):
    def __call__(self, disk_number: int) -> DiskReader: ...


class DiskService:
    """Expose discovered disks and previously cached NTFS volumes."""

    def __init__(self, inventory: DiskInventoryPort, scan_repository: DiskRepository):
        self.inventory = inventory
        self.scan_repository = scan_repository

    def list_disks(self) -> list[DiscoveredDisk]:
        return [
            DiscoveredDisk(disk, self.scan_repository.load(disk))
            for disk in self.inventory.list_disks()
        ]

    def get_disk(self, disk_number):
        disk = next(
            (item for item in self.inventory.list_disks() if int(item.number) == int(disk_number)),
            None,
        )
        if disk is None:
            raise ValueError(f"Physical disk {disk_number} is no longer available")
        return disk
