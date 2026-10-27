from dataclasses import dataclass

from disk.models import NTFSVolume
from domain.recovery_catalog import RecoveryCatalog


@dataclass(frozen=True)
class RecoveryCatalogSnapshot:
    catalog: RecoveryCatalog
    volume: NTFSVolume

    @property
    def volume_start(self):
        return self.volume.partition_offset

    @property
    def cluster_size(self):
        return self.volume.cluster_size
