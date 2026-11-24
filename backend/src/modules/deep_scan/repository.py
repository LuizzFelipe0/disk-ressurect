from typing import Protocol

from modules.deep_scan.entities import CarvingCheckpoint
from modules.storage.entities import PhysicalDisk
from modules.disk.entities import NTFSVolume


class CarvingCheckpointRepository(Protocol):
    def load_carving_checkpoint(
        self, disk: PhysicalDisk, volume: NTFSVolume,
    ) -> CarvingCheckpoint | None: ...

    def save_carving_checkpoint(
        self, disk: PhysicalDisk, volume: NTFSVolume, checkpoint: CarvingCheckpoint | None,
    ) -> CarvingCheckpoint | None: ...
