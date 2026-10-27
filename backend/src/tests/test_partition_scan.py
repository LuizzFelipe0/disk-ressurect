import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from disk.scanning.partition_scan import (
    AlignedSignaturePipe,
    DiskChunk,
    DiskChunkSource,
    DiskRange,
    NTFSBootSectorParser,
)


class MemoryDisk:
    def __init__(self, data, sector_size=512):
        self.data = data
        self.size = len(data)
        self.bytes_per_sector = sector_size
        self.reads = []

    def read_at(self, offset, size):
        self.reads.append((offset, size))
        return self.data[offset:offset + size]


class PartitionScanPipeTests(unittest.TestCase):
    def test_signature_pipe_finds_aligned_sector_signature_across_chunk_boundary(self):
        data = bytearray(1024)
        data[515:523] = b"NTFS    "
        chunks = (
            DiskChunk(0, bytes(data[:518]), 518, 1024, "test"),
            DiskChunk(518, bytes(data[518:]), 1024, 1024, "test"),
        )
        pipe = AlignedSignaturePipe(b"NTFS    ", alignment=512, signature_offset=3)

        self.assertEqual(list(pipe(chunks)), [512])

    def test_signature_pipe_ignores_unaligned_hits_and_does_not_join_range_gaps(self):
        pipe = AlignedSignaturePipe(b"NTFS    ", alignment=512, signature_offset=3)
        unaligned = bytearray(1024)
        unaligned[103:111] = b"NTFS    "
        first = DiskChunk(0, bytes(unaligned[:108]), 108, 1024, "tail")
        second = DiskChunk(2048, b"FS    " + bytes(400), 508, 1024, "start")

        self.assertEqual(list(pipe((first, second))), [])

    def test_chunk_source_reads_prioritized_ranges_sequentially_and_reports_progress(self):
        disk = MemoryDisk(bytes(range(256)) * 32)
        source = DiskChunkSource(disk, chunk_size=1024)
        events = []
        ranges = (DiskRange("tail", 4096, 6144), DiskRange("rest", 0, 4096))

        chunks = list(source(ranges, lambda done, total, message: events.append((done, total, message))))

        self.assertEqual([(chunk.offset, len(chunk.data)) for chunk in chunks],
                         [(4096, 1024), (5120, 1024), (0, 1024), (1024, 1024),
                          (2048, 1024), (3072, 1024)])
        self.assertEqual(events[-1][0:2], (6144, 6144))
        self.assertTrue(events[0][2].startswith("tail"))

    def test_ntfs_boot_parser_extracts_geometry_and_rejects_invalid_sector(self):
        boot = bytearray(512)
        boot[3:11] = b"NTFS    "
        boot[11:13] = (512).to_bytes(2, "little")
        boot[13] = 8
        boot[40:48] = (10000).to_bytes(8, "little")
        boot[48:56] = (4).to_bytes(8, "little")
        boot[64:65] = (-10).to_bytes(1, "little", signed=True)
        boot[510:512] = b"\x55\xAA"

        geometry = NTFSBootSectorParser.parse(boot)

        self.assertEqual(geometry.bytes_per_sector, 512)
        self.assertEqual(geometry.cluster_size, 4096)
        self.assertEqual(geometry.volume_size, 5_120_000)
        self.assertEqual(geometry.mft_lcn, 4)
        self.assertEqual(geometry.record_size, 1024)
        boot[13] = 3
        self.assertIsNone(NTFSBootSectorParser.parse(boot))


if __name__ == "__main__":
    unittest.main()
