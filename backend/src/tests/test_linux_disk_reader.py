import os
import re
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from disk.access.linux_disk import LinuxDiskReader


class LinuxDiskReaderTests(unittest.TestCase):
    def setUp(self):
        self.device = SimpleNamespace(name="sda", logical_sector_size=512, size_bytes=4096)
        self.catalog = SimpleNamespace(
            device_path="/dev",
            get_device=lambda number: self.device if number == 2 else None,
        )

    def test_reads_a_bounded_range_with_positional_io(self):
        with (
            patch("disk.access.linux_disk.sys.platform", "linux"),
            patch("disk.access.linux_disk.os.open", return_value=41),
            patch.object(LinuxDiskReader, "_read_device_size", return_value=4096),
            patch.object(LinuxDiskReader, "_read_sector_size", return_value=512),
            patch.object(os, "pread", return_value=b"disk-data", create=True) as pread,
            patch("disk.access.linux_disk.os.close") as close,
        ):
            reader = LinuxDiskReader(2, self.catalog)
            result = reader.read_at(4000, 512)
            reader.close()

        self.assertEqual(result, b"disk-data")
        pread.assert_called_once_with(41, 96, 4000)
        close.assert_called_once_with(41)

    def test_requires_linux_runtime(self):
        with patch("disk.access.linux_disk.sys.platform", "win32"):
            with self.assertRaisesRegex(OSError, "only available on Linux"):
                LinuxDiskReader(2, self.catalog)

    def test_reports_permission_errors_with_the_device_path(self):
        with (
            patch("disk.access.linux_disk.sys.platform", "linux"),
            patch("disk.access.linux_disk.os.open", side_effect=PermissionError("denied")),
        ):
            expected_path = os.path.join("/dev", "sda")
            with self.assertRaisesRegex(PermissionError, re.escape(expected_path)):
                LinuxDiskReader(2, self.catalog)


if __name__ == "__main__":
    unittest.main()
