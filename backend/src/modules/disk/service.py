from typing import Callable, Protocol

from disk.scanning.partition_scan import ScanCheckpoint
from modules.disk.entities import DiscoveredDisk, NTFSVolume, PhysicalDisk
from modules.disk.repository import DeepScanRepository


class DiskInventoryPort(Protocol):
    """Operations the disk feature needs from platform-specific discovery."""

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


class DiskDiscoveryService:
    def __init__(self, inventory: DiskInventoryPort, scan_repository: DeepScanRepository):
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

    def load_carving_checkpoint(self, disk, volume):
        loader = getattr(self.scan_repository, "load_carving_checkpoint", None)
        return loader(disk, volume) if loader is not None else None

    def save_carving_checkpoint(self, disk, volume, checkpoint):
        saver = getattr(self.scan_repository, "save_carving_checkpoint", None)
        return saver(disk, volume, checkpoint) if saver is not None else None

    def validate_disk(
        self, disk_number: int, progress_callback=None, retain_orphans_for_offset=None,
        orphan_scan_volume: NTFSVolume | None = None, content_carving_range_budget_bytes=None,
        force_fresh=False,
    ):
        validator = getattr(self.inventory, "validate_disk", None)
        if validator is None:
            raise NotImplementedError("This disk inventory does not support full-disk validation")
        snapshot_loader = getattr(self.scan_repository, "load_validation_snapshot", None)
        disk = self.get_disk(disk_number) if snapshot_loader is not None else None
        invalidator = getattr(self.scan_repository, "invalidate_validation_snapshot", None)
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

        snapshot_saver = getattr(self.scan_repository, "save_validation_snapshot", None)
        cache_snapshot = report.get("validation_scan_snapshot")
        if snapshot_saver is not None and cache_snapshot is not None and disk is not None:
            snapshot_saver(disk, cache_snapshot)
        return report

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

    def scan_partitions(self, disk_number: int, deep_scan: bool, progress_callback=None, resume=False):
        disk = self.get_disk(disk_number)
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
