import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.catalog.mapper import CatalogMapper
from modules.disk_discovery.mapper import DiskDiscoveryMapper


class ModuleMapperTests(unittest.TestCase):
    def test_disk_mapper_serializes_cached_partition_and_registers_it(self):
        volume = SimpleNamespace(
            disk_number=2,
            partition_number=0,
            partition_offset=4096,
            partition_size=8192,
            partition_size_is_estimated=True,
            display_name="Lost NTFS candidate",
        )
        disk = SimpleNamespace(
            number=2,
            model="Recovery disk",
            size_bytes=16384,
            serial_number="S-2",
            display_name="Disk 2 · Recovery disk",
        )
        discovered = SimpleNamespace(
            disk=disk,
            cached_scan=SimpleNamespace(scanned_at="scan-time", volumes=(volume,)),
        )
        registered = []

        result = DiskDiscoveryMapper.disk(discovered, lambda item: registered.append(item) or "2:4096").to_dict()

        self.assertEqual(registered, [volume])
        self.assertEqual(result["cachedPartitions"][0]["id"], "2:4096")
        self.assertEqual(result["cachedPartitions"][0]["scanSavedAt"], "scan-time")

    def test_catalog_mapper_maps_root_metadata_and_extension_contract(self):
        file_node = SimpleNamespace(
            record=SimpleNamespace(name="photo.jpg", file_size=128, is_dir=False),
            full_path="Photos/photo.jpg",
            children=[],
        )
        root = SimpleNamespace(
            record=SimpleNamespace(name="Photos", file_size=0, is_dir=True),
            full_path="Photos",
            children=[file_node],
        )
        catalog = SimpleNamespace(
            root_nodes=[root],
            nodes={1: root, 2: file_node},
            available_extensions=lambda supported: [".jpg"],
        )
        snapshot = SimpleNamespace(catalog=catalog)

        result = CatalogMapper.catalog(snapshot, {id(root): "n0", id(file_node): "n1"}).to_dict()

        self.assertEqual(result["recordCount"], 2)
        self.assertEqual(result["availableExtensions"], [".jpg"])
        self.assertTrue(result["roots"][0]["hasChildren"])


if __name__ == "__main__":
    unittest.main()
