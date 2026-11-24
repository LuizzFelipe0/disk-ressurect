from modules.disk.entities import NTFSVolume


class DeepScanService:
    """Own partition-scan checkpoints and content-carving resume state."""

    def __init__(self, inventory, disk_service, disk_repository, carving_repository):
        self.inventory = inventory
        self.disk_service = disk_service
        self.disk_repository = disk_repository
        self.carving_repository = carving_repository

    def load_carving_checkpoint(self, disk, volume):
        loader = getattr(self.carving_repository, "load_carving_checkpoint", None)
        return loader(disk, volume) if loader is not None else None

    def save_carving_checkpoint(self, disk, volume, checkpoint):
        saver = getattr(self.carving_repository, "save_carving_checkpoint", None)
        return saver(disk, volume, checkpoint) if saver is not None else None

    def scan_partitions(self, disk_number: int, deep_scan: bool, progress_callback=None, resume=False):
        disk = self.disk_service.get_disk(disk_number)
        if not deep_scan:
            return tuple(self.inventory.list_ntfs_volumes(disk_number, progress_callback)), None

        previous = self.disk_repository.load(disk)
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
                self.disk_repository.save(
                    disk, tuple(saved_by_offset[offset] for offset in sorted(saved_by_offset)), checkpoint,
                )
                last_persisted_offset = checkpoint.next_offset

        def checkpoint_candidates(candidates):
            saved_by_offset.update({volume.partition_offset: volume for volume in candidates})
            saved_candidates = tuple(saved_by_offset[offset] for offset in sorted(saved_by_offset))
            self.disk_repository.save(disk, saved_candidates, latest_checkpoint)

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
                self.disk_repository.save(
                    disk, tuple(saved_by_offset[offset] for offset in sorted(saved_by_offset)), latest_checkpoint,
                )
            raise

        saved_by_offset.update({volume.partition_offset: volume for volume in volumes})
        complete_volumes = tuple(saved_by_offset[offset] for offset in sorted(saved_by_offset))
        saved_scan = self.disk_repository.save(disk, complete_volumes, checkpoint=None)
        return complete_volumes, saved_scan.scanned_at
