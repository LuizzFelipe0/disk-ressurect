import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from disk.access.raw_disk import RawDisk


class RawDiskReadValidationTests(unittest.TestCase):
    def test_aligns_unaligned_requests_to_physical_sector_boundaries(self):
        aligned_offset, aligned_size, slice_offset, logical_size = (
            RawDisk._aligned_read_parameters(1003, 1037, 512, 16384)
        )
        self.assertEqual((aligned_offset, aligned_size), (512, 1536))
        self.assertEqual((slice_offset, logical_size), (491, 1037))
        self.assertEqual(aligned_offset % 512, 0)
        self.assertEqual(aligned_size % 512, 0)

    def test_clamps_a_read_to_the_end_of_the_disk(self):
        result = RawDisk._aligned_read_parameters(15300, 2000, 512, 16384)
        self.assertEqual(result, (14848, 1536, 452, 1084))

    def test_returns_empty_range_when_read_starts_at_or_after_disk_end(self):
        self.assertEqual(RawDisk._aligned_read_parameters(16384, 512, 512, 16384), (16384, 0, 0, 0))

    def test_accepts_a_complete_read(self):
        self.assertEqual(RawDisk._validated_read_length(True, 512, 512), 512)

    def test_preserves_a_legitimate_short_read_count(self):
        self.assertEqual(RawDisk._validated_read_length(True, 8, 512), 8)

    def test_raises_when_win32_read_fails(self):
        with self.assertRaisesRegex(OSError, "ReadFile failed"):
            RawDisk._validated_read_length(False, 0, 512)

    def test_rejects_impossible_byte_count(self):
        with self.assertRaisesRegex(OSError, "invalid byte count"):
            RawDisk._validated_read_length(True, 513, 512)


if __name__ == "__main__":
    unittest.main()
