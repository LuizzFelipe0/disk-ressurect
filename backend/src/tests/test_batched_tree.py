import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ntfs.tree_builder import TreeBuilder


class FakeDisk:
    def __init__(self, data):
        self.data = data
        self.reads = []

    def read_at(self, offset, size):
        self.reads.append((offset, size))
        return self.data[offset:offset + size]


class BatchedTreeTests(unittest.TestCase):
    def test_reads_mft_fragment_in_batches(self):
        fragment = {"phys": 100, "count": 9000, "base_idx": 0}
        disk = FakeDisk(b"x" * (100 + 9000 * 1024))
        builder = TreeBuilder(disk, [fragment], 0)
        self.assertEqual(builder.build(), {})
        self.assertEqual(disk.reads, [(100, 4096 * 1024), (100 + 4096 * 1024, 4096 * 1024),
                                      (100 + 8192 * 1024, 808 * 1024)])

    def test_rejects_short_physical_read_instead_of_silently_skipping_records(self):
        disk = FakeDisk(b"x" * (1024 - 1))
        builder = TreeBuilder(disk, [{"phys": 100, "count": 1, "base_idx": 0}], 0)
        with self.assertRaisesRegex(OSError, "Short MFT read"):
            builder.build()

    def test_reports_batch_progress_through_callback(self):
        disk = FakeDisk(b"x" * (100 + 1024))
        builder = TreeBuilder(disk, [{"phys": 100, "count": 1, "base_idx": 0}], 0)
        events = []
        builder.build(progress_callback=lambda completed, total: events.append((completed, total)))
        self.assertEqual(events, [(1, 1)])

    def test_records_keep_their_physical_offset_instead_of_partition_start(self):
        disk = FakeDisk(bytes(4096) + b"FILE" + bytes(1020))
        parsed = SimpleNamespace(
            is_valid=True,
            name="photo.jpg",
            index=0,
            parent_index=None,
            is_allocated=True,
            is_dir=False,
        )
        builder = TreeBuilder(disk, [{"phys": 4096, "count": 1, "base_idx": 0}], 512)

        with patch("ntfs.tree_builder.MFTRecord", return_value=parsed) as parser:
            builder.build()

        self.assertEqual(parser.call_args.args[3], 4096)


if __name__ == "__main__":
    unittest.main()
