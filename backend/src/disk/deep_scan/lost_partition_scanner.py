from disk.scanning.partition_scan import (
    AlignedSignaturePipe,
    DiskChunkSource,
    DiskRange,
    ScanCheckpoint,
    NTFSBootSectorParser,
)
from disk.models import PartitionEntry
from disk.ntfs_discovery.volume_scanner import NTFSVolumeScanner
from disk.deep_scan.candidate_validator import LostPartitionCandidateValidator


class LostPartitionScanner:
    """Find lost NTFS partition boot sectors without writing to the source disk."""

    DEFAULT_CHUNK_SIZE = 64 * 1024 * 1024
    PRIORITY_TAIL_BYTES = 1024 * 1024 * 1024

    def __init__(self, disk, disk_number, chunk_size=DEFAULT_CHUNK_SIZE,
                 priority_tail_bytes=PRIORITY_TAIL_BYTES):
        self.disk = disk
        self.disk_number = int(disk_number)
        self.chunk_source = DiskChunkSource(disk, chunk_size)
        self.priority_tail_bytes = max(0, int(priority_tail_bytes))
        self.signature_pipe = AlignedSignaturePipe(
            NTFSBootSectorParser.SIGNATURE,
            disk.bytes_per_sector,
            signature_offset=3,
        )
        self.volume_scanner = NTFSVolumeScanner(disk, disk_number)
        self.candidate_validator = LostPartitionCandidateValidator(
            disk,
            self.volume_scanner,
        )

    def scan(self, progress_callback=None, candidate_callback=None, checkpoint=None,
             checkpoint_callback=None):
        return self.scan_ranges(
            self._scan_ranges(), progress_callback, candidate_callback,
            checkpoint, checkpoint_callback,
        )

    def scan_ranges(self, ranges, progress_callback=None, candidate_callback=None,
                    checkpoint: ScanCheckpoint | None = None, checkpoint_callback=None):
        """Run the same discovery pipeline against selected byte ranges."""
        volumes_by_offset = {}
        overlap = len(NTFSBootSectorParser.SIGNATURE) + 3 - 1
        chunks = self.chunk_source(
            ranges, progress_callback, checkpoint, checkpoint_callback, overlap,
        )
        for boot_offset in self.signature_pipe(chunks):
            for volume in self.candidate_validator(boot_offset):
                if volume.partition_offset not in volumes_by_offset:
                    volumes_by_offset[volume.partition_offset] = volume
                    if candidate_callback:
                        candidates = tuple(sorted(volumes_by_offset.values(), key=lambda item: item.partition_offset))
                        candidate_callback(candidates)
        return sorted(volumes_by_offset.values(), key=lambda volume: volume.partition_offset)

    def _scan_ranges(self):
        disk_size = int(self.disk.size)
        tail_size = min(self.priority_tail_bytes, disk_size // 8)
        tail_size -= tail_size % int(self.disk.bytes_per_sector)
        tail_start = disk_size - tail_size
        ranges = []
        if tail_start < disk_size:
            ranges.append(DiskRange("Priority disk-tail scan", tail_start, disk_size))
        if tail_start > 0:
            ranges.append(DiskRange("Full-disk scan", 0, tail_start))
        return tuple(ranges)
