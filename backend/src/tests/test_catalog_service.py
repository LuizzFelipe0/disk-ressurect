import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from disk.models import NTFSVolume
from modules.catalog.service import CatalogService


class FakeDisk:
    def __init__(self, _disk_number):
        self.closed = False

    def read_at(self, _offset, _size):
        return b""

    def close(self):
        self.closed = True


class CatalogServiceTests(unittest.TestCase):
    def test_builds_empty_catalog_and_closes_disk_reader(self):
        opened = []

        def disk_factory(disk_number):
            disk = FakeDisk(disk_number)
            opened.append(disk)
            return disk

        volume = NTFSVolume(3, 1, 0, 8192, 512, 4096, 1024, 0, 0, ())
        snapshot = CatalogService(disk_factory).build(volume)

        self.assertEqual(snapshot.volume, volume)
        self.assertEqual(snapshot.catalog.nodes, {})
        self.assertEqual(snapshot.catalog.root_nodes, [])
        self.assertTrue(opened[0].closed)


if __name__ == "__main__":
    unittest.main()
