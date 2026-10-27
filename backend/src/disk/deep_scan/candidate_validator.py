from disk.models import PartitionEntry
from disk.scanning.partition_scan import NTFSBootSectorParser


class LostPartitionCandidateValidator:
    """Pipe that validates a boot signature by checking geometry and its MFT."""

    def __init__(self, disk, volume_scanner):
        self.disk = disk
        self.volume_scanner = volume_scanner

    def __call__(self, boot_offset):
        boot = self.disk.read_at(boot_offset, max(512, self.disk.bytes_per_sector))
        geometry = NTFSBootSectorParser.parse(boot)
        if geometry is None or boot_offset % geometry.bytes_per_sector:
            return ()
        starts = (boot_offset, boot_offset - geometry.volume_size + geometry.bytes_per_sector)
        found = []
        seen = set()
        for start in starts:
            if (start < 0 or start + geometry.volume_size > self.disk.size
                    or start in seen):
                continue
            seen.add(start)
            if boot_offset not in (start, start + geometry.volume_size - geometry.bytes_per_sector):
                continue
            partition = PartitionEntry(0, start, geometry.volume_size, "Lost NTFS", "Deep scan")
            volume = self.volume_scanner._probe_partition(partition, boot_sector=boot)
            if volume is not None:
                found.append(volume)
        return tuple(found)
