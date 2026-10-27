from dataclasses import dataclass


@dataclass(frozen=True)
class PartitionScanRequestDto:
    disk_number: int
    deep_scan: bool = False

    @classmethod
    def from_payload(cls, payload):
        disk_number = payload.get("diskNumber")
        deep_scan = payload.get("deepScan", False)
        if isinstance(disk_number, bool):
            raise ValueError("diskNumber must be an integer")
        try:
            disk_number = int(disk_number)
        except (TypeError, ValueError) as exc:
            raise ValueError("diskNumber must be an integer") from exc
        if disk_number < 0:
            raise ValueError("diskNumber cannot be negative")
        if not isinstance(deep_scan, bool):
            raise ValueError("deepScan must be a boolean")
        return cls(disk_number, deep_scan)


@dataclass(frozen=True)
class PartitionDto:
    id: str
    disk_number: int
    partition_number: int
    offset: int
    size_bytes: int
    estimated_size: bool
    name: str
    scan_saved_at: str | None = None

    def to_dict(self):
        result = {
            "id": self.id,
            "diskNumber": self.disk_number,
            "partitionNumber": self.partition_number,
            "offset": self.offset,
            "sizeBytes": self.size_bytes,
            "estimatedSize": self.estimated_size,
            "name": self.name,
        }
        if self.scan_saved_at:
            result["scanSavedAt"] = self.scan_saved_at
        return result


@dataclass(frozen=True)
class DiskDto:
    number: int
    model: str
    size_bytes: int
    serial_number: str
    display_name: str
    cached_partitions: tuple[PartitionDto, ...] = ()

    def to_dict(self):
        return {
            "number": self.number,
            "model": self.model,
            "sizeBytes": self.size_bytes,
            "serialNumber": self.serial_number,
            "displayName": self.display_name,
            "cachedPartitions": [item.to_dict() for item in self.cached_partitions],
        }
