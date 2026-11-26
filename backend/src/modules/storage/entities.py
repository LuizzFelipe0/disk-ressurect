from dataclasses import dataclass
import hashlib
import json
from typing import Literal


StorageType = Literal["physical_disk", "raw_image"]


@dataclass(frozen=True)
class StorageSource:
    """Stable identity and basic geometry of a readable storage source."""

    source_id: str
    source_type: StorageType
    display_name: str
    size_bytes: int
    bytes_per_sector: int
    locator: str = ""

    def __post_init__(self):
        if not self.source_id:
            raise ValueError("Storage source identity is required")
        if self.size_bytes < 0:
            raise ValueError("Storage source size cannot be negative")
        if self.bytes_per_sector <= 0:
            raise ValueError("Storage source sector size must be positive")


@dataclass(frozen=True)
class PhysicalDisk:
    number: int
    model: str
    size_bytes: int
    serial_number: str = ""
    identity_size_bytes: int | None = None

    @property
    def display_name(self):
        size_gib = self.size_bytes / (1024 ** 3)
        suffix = f" · {self.serial_number}" if self.serial_number else ""
        return f"Disk {self.number} · {self.model} · {size_gib:.1f} GB{suffix}"

    def as_storage_source(self, bytes_per_sector=512):
        serial = str(self.serial_number or "").strip().casefold()
        identity_size = self.identity_size_bytes
        if identity_size is None:
            identity_size = self.size_bytes
        identity = [str(self.model or "").strip().casefold(), int(identity_size), serial]
        if not serial:
            identity.append(int(self.number))
        digest = hashlib.sha256(
            json.dumps(identity, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return StorageSource(
            source_id=f"physical-disk:{digest}",
            source_type="physical_disk",
            display_name=self.display_name,
            size_bytes=int(self.size_bytes),
            bytes_per_sector=int(bytes_per_sector),
            locator=str(int(self.number)),
        )


@dataclass(frozen=True)
class Partition:
    number: int
    offset: int
    size_bytes: int
    table_type: str
    name: str = ""
    source_id: str = ""


# Temporary name alias for call sites migrated in the storage step.
Partition = Partition


@dataclass(frozen=True)
class ScanCheckpoint:
    range_index: int
    next_offset: int
    disk_size: int
    bytes_per_sector: int
