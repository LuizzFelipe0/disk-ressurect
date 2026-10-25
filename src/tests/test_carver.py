import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from disk.carver import Carver


class FakeDisk:
    def __init__(self, data):
        self.data = data

    def read_at(self, offset, size):
        return self.data[offset:offset + size]


class CarverTests(unittest.TestCase):
    def make_carver(self, disk):
        carver = Carver(disk, cluster_size=4)
        carver.chunk_size = carver.max_file_size + len(disk.data)
        return carver

    def test_recovers_jpeg_from_fake_disk(self):
        jpeg = b"\xFF\xD8\xFFimage-data\xFF\xD9"
        disk = FakeDisk(b"xxxx" + jpeg)
        carver = self.make_carver(disk)
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        with tempfile.TemporaryDirectory(dir=repo_root) as output_dir:
            carver.carve(0, len(disk.data), output_dir)

            recovered_path = os.path.join(output_dir, "RAW_00000.jpg")
            with open(recovered_path, "rb") as recovered_file:
                self.assertEqual(recovered_file.read(), jpeg)

    def test_skips_jpeg_in_blacklisted_cluster(self):
        jpeg = b"\xFF\xD8\xFFimage-data\xFF\xD9"
        disk = FakeDisk(b"xxxx" + jpeg)
        carver = self.make_carver(disk)
        carver.set_blacklist({1})
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        with tempfile.TemporaryDirectory(dir=repo_root) as output_dir:
            carver.carve(0, len(disk.data), output_dir)

            self.assertEqual(os.listdir(output_dir), [])

    def test_surfaces_output_write_errors_instead_of_counting_failed_files(self):
        jpeg = b"\xFF\xD8\xFFimage-data\xFF\xD9"
        disk = FakeDisk(b"xxxx" + jpeg)
        carver = self.make_carver(disk)
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        with tempfile.TemporaryDirectory(dir=repo_root) as output_dir:
            with patch("builtins.open", side_effect=PermissionError("write denied")):
                with self.assertRaisesRegex(PermissionError, "write denied"):
                    carver.carve(0, len(disk.data), output_dir)


if __name__ == "__main__":
    unittest.main()
