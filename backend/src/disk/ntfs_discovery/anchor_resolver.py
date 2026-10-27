from disk.models import NTFSVolume, PartitionEntry
from disk.scanning.mft_anchor_scan import MFTAnchor
from disk.ntfs_discovery.volume_scanner import NTFSVolumeScanner


class MFTAnchorVolumeResolver:
    """Infer a volume start and MFT mapping from a validated $MFT record zero."""

    MIN_CLUSTER_SIZE = 512
    MAX_CLUSTER_SIZE = 2 * 1024 * 1024

    def __init__(self, disk, disk_number):
        self.disk = disk
        self.disk_number = int(disk_number)

    def resolve(self, anchor: MFTAnchor):
        record = anchor.record
        if (not record.is_valid or record.name != "$MFT" or not record.data_runs
                or not record.data_is_complete or record.file_size <= 0
                or record.allocated_size <= 0):
            return None
        physical_runs = [(lcn, count) for lcn, count in record.data_runs
                         if lcn is not None and count > 0]
        if len(physical_runs) != len(record.data_runs) or not physical_runs:
            return None
        total_clusters = sum(count for _, count in physical_runs)
        if total_clusters <= 0 or record.allocated_size % total_clusters:
            return None
        cluster_size = record.allocated_size // total_clusters
        sector_size = int(self.disk.bytes_per_sector)
        if (cluster_size < max(self.MIN_CLUSTER_SIZE, sector_size)
                or cluster_size > self.MAX_CLUSTER_SIZE
                or cluster_size & (cluster_size - 1)
                or cluster_size % sector_size):
            return None

        first_lcn = physical_runs[0][0]
        mft_offset = int(anchor.physical_offset)
        partition_offset = mft_offset - first_lcn * cluster_size
        if (partition_offset < 0 or partition_offset % cluster_size
                or partition_offset + record.file_size > self.disk.size):
            return None
        for lcn, count in physical_runs:
            run_start = partition_offset + lcn * cluster_size
            run_end = run_start + count * cluster_size
            if run_start < partition_offset or run_end > self.disk.size:
                return None
        if partition_offset + first_lcn * cluster_size != mft_offset:
            return None

        partition = PartitionEntry(0, partition_offset, self.disk.size - partition_offset,
                                   "MFT-derived", "$MFT anchor; partition end estimated")
        fragments = NTFSVolumeScanner._mft_fragments(
            partition, cluster_size, record.record_size, record
        )
        if not fragments or fragments[0][0] != mft_offset:
            return None
        return NTFSVolume(
            disk_number=self.disk_number,
            partition_number=0,
            partition_offset=partition_offset,
            partition_size=partition.size_bytes,
            bytes_per_sector=sector_size,
            cluster_size=cluster_size,
            record_size=record.record_size,
            mft_offset=mft_offset,
            mft_size=record.file_size,
            mft_fragments=tuple(fragments),
            partition_name=partition.name,
            partition_size_is_estimated=True,
        )
