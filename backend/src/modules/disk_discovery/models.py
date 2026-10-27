from dataclasses import dataclass

from disk.models import NTFSVolume, PhysicalDisk


@dataclass(frozen=True)
class CachedDeepScan:
    scanned_at: str
    volumes: tuple[NTFSVolume, ...]


@dataclass(frozen=True)
class DiscoveredDisk:
    disk: PhysicalDisk
    cached_scan: CachedDeepScan | None
