from typing import Protocol

from modules.disk.entities import ScanCheckpoint
from modules.disk.entities import CachedDeepScan, NTFSVolume, PhysicalDisk


class DiskRepository(Protocol):
    def load(self, disk: PhysicalDisk) -> CachedDeepScan | None: ...

    def save(
        self, disk: PhysicalDisk, volumes: tuple[NTFSVolume, ...] | list[NTFSVolume],
        checkpoint: ScanCheckpoint | None = None,
    ) -> CachedDeepScan: ...
