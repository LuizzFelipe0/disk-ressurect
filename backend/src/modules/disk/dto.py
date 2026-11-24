from dataclasses import dataclass


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
    """Common physical-disk identity carried by disk-level response DTOs."""

    number: int
    model: str
    size_bytes: int
    serial_number: str

    def identity_dict(self):
        return {
            "number": self.number,
            "model": self.model,
            "sizeBytes": self.size_bytes,
            "serialNumber": self.serial_number,
        }


@dataclass(frozen=True)
class DiscoveredDiskDto(DiskDto):
    display_name: str
    cached_partitions: tuple[PartitionDto, ...] = ()
    deep_scan_resume_available: bool = False

    def to_dict(self):
        return {
            **self.identity_dict(),
            "displayName": self.display_name,
            "cachedPartitions": [item.to_dict() for item in self.cached_partitions],
            "deepScanResumeAvailable": self.deep_scan_resume_available,
        }


class DiskDtoMapper:
    @staticmethod
    def disk(discovered_disk, register_volume):
        disk = discovered_disk.disk
        scan = discovered_disk.cached_scan
        partitions = tuple(
            DiskDtoMapper.partition(
                volume,
                register_volume(volume),
                scan.scanned_at,
            )
            for volume in (scan.volumes if scan else ())
        )
        return DiscoveredDiskDto(
            number=disk.number,
            model=disk.model,
            size_bytes=disk.size_bytes,
            serial_number=disk.serial_number,
            display_name=disk.display_name,
            cached_partitions=partitions,
            deep_scan_resume_available=bool(scan and getattr(scan, "checkpoint", None)),
        )

    @staticmethod
    def partition(volume, volume_id, scanned_at=None):
        return PartitionDto(
            id=volume_id,
            disk_number=volume.disk_number,
            partition_number=volume.partition_number,
            offset=volume.partition_offset,
            size_bytes=volume.partition_size,
            estimated_size=volume.partition_size_is_estimated,
            name=volume.display_name,
            scan_saved_at=scanned_at,
        )
