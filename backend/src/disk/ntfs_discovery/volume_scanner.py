from ntfs.mft_parser import MFTRecord
from disk.models import NTFSVolume
from disk.partition_table.scanner import PartitionTableScanner
from disk.scanning.partition_scan import NTFSBootSectorParser


class NTFSVolumeScanner:
    """Find NTFS volumes and map their MFT runlists into physical disk extents."""

    def __init__(self, disk, disk_number, partition_scanner=None):
        self.disk = disk
        self.disk_number = int(disk_number)
        self.partition_scanner = partition_scanner or PartitionTableScanner(disk)

    def scan(self, progress_callback=None):
        partitions = self.partition_scanner.partitions()
        volumes = []
        total = len(partitions)
        for position, partition in enumerate(partitions, 1):
            if progress_callback:
                progress_callback(position - 1, total, f"Checking partition {partition.number}")
            volume = self._probe_partition(partition)
            if volume is not None:
                volumes.append(volume)
            if progress_callback:
                progress_callback(position, total, f"Checked partition {partition.number}")
        return volumes

    def _probe_partition(self, partition, boot_sector=None):
        boot = boot_sector or self.disk.read_at(partition.offset, max(512, self.disk.bytes_per_sector))
        geometry = NTFSBootSectorParser.parse(boot)
        if geometry is None or geometry.volume_size > partition.size_bytes:
            return None
        if partition.offset < 0 or partition.offset + geometry.volume_size > self.disk.size:
            return None
        mft_offset = partition.offset + geometry.mft_lcn * geometry.cluster_size
        raw_record = self.disk.read_at(mft_offset, geometry.record_size)
        if len(raw_record) != geometry.record_size:
            return None
        record = MFTRecord(raw_record, 0, self.disk, mft_offset, geometry.record_size)
        if not record.is_valid or not record.data_runs or record.file_size <= 0 or not record.data_is_complete:
            return None
        fragments = self._mft_fragments(partition, geometry.cluster_size, geometry.record_size, record)
        if not fragments:
            return None
        return NTFSVolume(
            disk_number=self.disk_number,
            partition_number=partition.number,
            partition_offset=partition.offset,
            partition_size=partition.size_bytes,
            bytes_per_sector=geometry.bytes_per_sector,
            cluster_size=geometry.cluster_size,
            record_size=geometry.record_size,
            mft_offset=mft_offset,
            mft_size=record.file_size,
            mft_fragments=tuple(fragments),
            partition_name=partition.name,
        )

    @staticmethod
    def _mft_fragments(partition, cluster_size, record_size, mft_record):
        records_needed = (mft_record.file_size + record_size - 1) // record_size
        base_index = 0
        fragments = []
        for lcn, cluster_count in mft_record.data_runs:
            byte_count = cluster_count * cluster_size
            record_count = byte_count // record_size
            if record_count <= 0:
                continue
            record_count = min(record_count, records_needed - base_index)
            if record_count <= 0:
                break
            if lcn is not None:
                fragments.append({
                    "phys": partition.offset + lcn * cluster_size,
                    "count": record_count,
                    "base_idx": base_index,
                })
            base_index += record_count
            if base_index >= records_needed:
                break
        if base_index < records_needed:
            return []
        return [
            (fragment["phys"], fragment["count"], fragment["base_idx"])
            for fragment in fragments
        ]
