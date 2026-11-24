"""Compatibility exports; storage entities are defined in modules.storage."""

from modules.storage.entities import (
    Partition,
    PhysicalDisk,
    ScanCheckpoint,
)

from dataclasses import dataclass


@dataclass(frozen=True)
class NTFSVolume:
    disk_number: int
    partition_number: int
    partition_offset: int
    partition_size: int
    bytes_per_sector: int
    cluster_size: int
    record_size: int
    mft_offset: int
    mft_size: int
    mft_fragments: tuple[tuple[int, int, int], ...]
    partition_name: str = ""
    partition_size_is_estimated: bool = False

    def fragments_as_dicts(self):
        return [
            {"phys": physical_offset, "count": count, "base_idx": base_index}
            for physical_offset, count, base_index in self.mft_fragments
        ]

    @property
    def display_name(self):
        gib = self.partition_size / (1024 ** 3)
        name = f" · {self.partition_name}" if self.partition_name else ""
        if self.partition_number == 0:
            estimate = " · estimated end" if self.partition_size_is_estimated else ""
            return f"Lost NTFS candidate · {gib:.1f} GB{name}{estimate} · offset 0x{self.partition_offset:X}"
        return f"Partition {self.partition_number} · NTFS · {gib:.1f} GB{name} · offset 0x{self.partition_offset:X}"


@dataclass(frozen=True)
class CachedDeepScan:
    scanned_at: str
    volumes: tuple[NTFSVolume, ...]
    checkpoint: ScanCheckpoint | None = None


@dataclass(frozen=True)
class DiscoveredDisk:
    disk: PhysicalDisk
    cached_scan: CachedDeepScan | None
