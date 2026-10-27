from modules.disk_discovery.dto import DiskDto, PartitionDto


class DiskDiscoveryMapper:
    @staticmethod
    def disk(discovered_disk, register_volume):
        disk = discovered_disk.disk
        scan = discovered_disk.cached_scan
        partitions = tuple(
            DiskDiscoveryMapper.partition(
                volume,
                register_volume(volume),
                scan.scanned_at,
            )
            for volume in (scan.volumes if scan else ())
        )
        return DiskDto(
            number=disk.number,
            model=disk.model,
            size_bytes=disk.size_bytes,
            serial_number=disk.serial_number,
            display_name=disk.display_name,
            cached_partitions=partitions,
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
