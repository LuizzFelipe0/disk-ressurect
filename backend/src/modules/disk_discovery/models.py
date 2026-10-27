from dataclasses import dataclass

from disk.models import NTFSVolume, PhysicalDisk
from disk.scanning.partition_scan import ScanCheckpoint


@dataclass(frozen=True)
class CachedDeepScan:
    scanned_at: str
    volumes: tuple[NTFSVolume, ...]
    checkpoint: ScanCheckpoint | None = None


@dataclass(frozen=True)
class DiscoveredDisk:
    disk: PhysicalDisk
    cached_scan: CachedDeepScan | None
