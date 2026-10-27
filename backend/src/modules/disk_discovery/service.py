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

    def scan_partitions(self, disk_number: int, deep_scan: bool, progress_callback=None, resume=False):
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
        resume_checkpoint = previous.checkpoint if previous else None
        if resume and resume_checkpoint is None:
            raise ValueError("There is no interrupted deep scan to resume for this disk")
        if not resume:
            resume_checkpoint = None

        latest_checkpoint = resume_checkpoint
        last_persisted_offset = -1
        checkpoint_interval = 256 * 1024 * 1024
        saved_by_offset = {volume.partition_offset: volume for volume in previously_saved}

        def persist(checkpoint, force=False):
            nonlocal latest_checkpoint, last_persisted_offset
            latest_checkpoint = checkpoint
            if (force or last_persisted_offset < 0
                    or abs(checkpoint.next_offset - last_persisted_offset) >= checkpoint_interval):
                self.scan_repository.save(
                    disk, tuple(saved_by_offset[offset] for offset in sorted(saved_by_offset)), checkpoint,
                )
                last_persisted_offset = checkpoint.next_offset

        def checkpoint_candidates(candidates):
            saved_by_offset.update({volume.partition_offset: volume for volume in candidates})
            saved_candidates = tuple(saved_by_offset[offset] for offset in sorted(saved_by_offset))
            self.scan_repository.save(disk, saved_candidates, latest_checkpoint)

        try:
            volumes = tuple(self.inventory.deep_scan_ntfs_volumes(
                disk_number,
                progress_callback,
                candidate_callback=checkpoint_candidates,
                resume_checkpoint=resume_checkpoint,
                checkpoint_callback=lambda checkpoint: persist(checkpoint),
            ))
        except Exception:
            if latest_checkpoint is not None:
                self.scan_repository.save(
                    disk, tuple(saved_by_offset[offset] for offset in sorted(saved_by_offset)), latest_checkpoint,
                )
            raise

        saved_by_offset.update({volume.partition_offset: volume for volume in volumes})
        complete_volumes = tuple(saved_by_offset[offset] for offset in sorted(saved_by_offset))
        saved_scan = self.scan_repository.save(disk, complete_volumes, checkpoint=None)
        return complete_volumes, saved_scan.scanned_at
