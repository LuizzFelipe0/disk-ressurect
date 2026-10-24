import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
