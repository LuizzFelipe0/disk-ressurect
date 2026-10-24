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
        disk = FakeDisk(b"x" * (9000 * 1024))
        builder = TreeBuilder(disk, [fragment], 0)
        self.assertEqual(builder.build(), {})
        self.assertEqual(disk.reads, [(100, 4096 * 1024), (100 + 4096 * 1024, 4096 * 1024),
                                      (100 + 8192 * 1024, 808 * 1024)])


if __name__ == "__main__":
    unittest.main()
