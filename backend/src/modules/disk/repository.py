from typing import Protocol

from modules.storage.entities import ScanCheckpoint
from modules.storage.entities import PhysicalDisk
from modules.disk.entities import CachedDeepScan, NTFSVolume


class DiskRepository(Protocol):
    def load(self, disk: PhysicalDisk) -> CachedDeepScan | None: ...

    def save(
        self, disk: PhysicalDisk, volumes: tuple[NTFSVolume, ...] | list[NTFSVolume],
        checkpoint: ScanCheckpoint | None = None,
    ) -> CachedDeepScan: ...
