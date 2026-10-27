from modules.disk_discovery.models import DiscoveredDisk
from modules.disk_discovery.repository import DeepScanRepository
from modules.disk_discovery.ports import DiskInventoryPort
from disk.models import NTFSVolume


class DiskDiscoveryService:
    def __init__(self, inventory: DiskInventoryPort, scan_repository: DeepScanRepository):
        self.inventory = inventory
        self.scan_repository = scan_repository

    def list_disks(self) -> list[DiscoveredDisk]:
        return [
            DiscoveredDisk(disk, self.scan_repository.load(disk))
            for disk in self.inventory.list_disks()
        ]

    def scan_partitions(self, disk_number: int, deep_scan: bool, progress_callback=None):
        disk = next(
            (item for item in self.inventory.list_disks() if item.number == disk_number),
            None,
        )
        if disk is None:
            raise ValueError(f"Physical disk {disk_number} is no longer available")
        if not deep_scan:
            return tuple(self.inventory.list_ntfs_volumes(disk_number, progress_callback)), None

        previous = self.scan_repository.load(disk)
        previously_saved = previous.volumes if previous else ()

        def checkpoint_candidates(candidates):
            by_offset = {volume.partition_offset: volume for volume in previously_saved}
            by_offset.update({volume.partition_offset: volume for volume in candidates})
            checkpoint = tuple(by_offset[offset] for offset in sorted(by_offset))
            self.scan_repository.save(disk, checkpoint)

        volumes = tuple(self.inventory.deep_scan_ntfs_volumes(
            disk_number,
            progress_callback,
            candidate_callback=checkpoint_candidates,
        ))
        saved_scan = self.scan_repository.save(disk, volumes)
        return volumes, saved_scan.scanned_at
