from typing import Protocol

from modules.disk_discovery.models import CachedDeepScan
from disk.models import NTFSVolume, PhysicalDisk


class DeepScanRepository(Protocol):
    def load(self, disk: PhysicalDisk) -> CachedDeepScan | None: ...

    def save(self, disk: PhysicalDisk, volumes: tuple[NTFSVolume, ...] | list[NTFSVolume], checkpoint=None) -> CachedDeepScan: ...
