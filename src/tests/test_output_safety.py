import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from disk.output_safety import OutputSafetyGuard


class OutputSafetyTests(unittest.TestCase):
    def test_allows_output_on_a_different_physical_disk(self):
        guard = OutputSafetyGuard(disk_mapper=lambda _: {0, 3})
        self.assertEqual(guard.validate(r"D:\recovery", 2), [0, 3])

    def test_rejects_output_on_source_disk(self):
        guard = OutputSafetyGuard(disk_mapper=lambda _: {2})
        with self.assertRaisesRegex(ValueError, "source disk 2"):
            guard.validate(r"D:\recovery", 2)

    def test_fails_closed_when_disk_mapping_is_unavailable(self):
        guard = OutputSafetyGuard(disk_mapper=lambda _: set())
        with self.assertRaisesRegex(OSError, "Could not identify"):
            guard.validate(r"D:\recovery", 2)


if __name__ == "__main__":
    unittest.main()
