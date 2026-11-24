from dataclasses import dataclass
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

    def __post_init__(self):
        if not self.source_id:
            raise ValueError("Storage source identity is required")
        if self.size_bytes < 0:
            raise ValueError("Storage source size cannot be negative")
        if self.bytes_per_sector <= 0:
            raise ValueError("Storage source sector size must be positive")
