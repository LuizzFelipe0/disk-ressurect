import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SRC_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC_ROOT))

from infrastructure.storage.factory import create_block_reader
from infrastructure.storage.image.reader import RawImageReader
from infrastructure.persistence.deep_scan_repository import JsonDeepScanRepository
from modules.storage.entities import PhysicalDisk, StorageSource
from modules.storage.service import StorageService


class StorageFactoryTests(unittest.TestCase):
    def test_storage_service_lists_and_opens_sources_without_filesystem_policy(self):
        disk = PhysicalDisk(2, "Model A", 4096, "SERIAL")
        reader = object()

        class Inventory:
            def list_disks(self):
                return [disk]

        service = StorageService(Inventory(), lambda source: reader)
        sources = service.list_sources()

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].source_type, "physical_disk")
        self.assertIs(service.open_reader(sources[0]), reader)

    def test_physical_disk_source_preserves_the_existing_cache_identity(self):
        disk = PhysicalDisk(2, "Model A", 4096, "SERIAL")
        source = disk.as_storage_source()
        self.assertEqual(source.source_type, "physical_disk")
        self.assertEqual(
            source.source_id,
            "physical-disk:" + JsonDeepScanRepository.disk_key(disk),
        )
        self.assertNotEqual(
            PhysicalDisk(2, "Model A", 4096).as_storage_source().source_id,
            PhysicalDisk(3, "Model A", 4096).as_storage_source().source_id,
        )
        self.assertEqual(source.locator, "2")

    def test_factory_selects_the_physical_reader_by_source_type(self):
        disk = PhysicalDisk(2, "Model A", 4096, "SERIAL")
        source = disk.as_storage_source()
        reader = object()
        with patch("infrastructure.storage.factory.create_disk_reader", return_value=reader) as create:
            self.assertIs(create_block_reader(source), reader)
        create.assert_called_once_with(2)

    def test_factory_reports_both_capacities_and_closes_reader_on_size_mismatch(self):
        source = PhysicalDisk(2, "Model A", 4096, "SERIAL").as_storage_source()

        class Reader:
            size_bytes = 8192

            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        reader = Reader()
        with patch("infrastructure.storage.factory.create_disk_reader", return_value=reader):
            with self.assertRaisesRegex(
                OSError,
                r"selected: 4096 bytes, device reports: 8192 bytes",
            ):
                create_block_reader(source)
        self.assertTrue(reader.closed)

    def test_factory_opens_a_raw_image_from_its_storage_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disk.img"
            path.write_bytes(b"image")
            probe = RawImageReader(path)
            source = probe.source
            probe.close()

            with create_block_reader(source) as reader:
                self.assertEqual(reader.read_at(0, 5), b"image")

    def test_factory_rejects_unknown_source_types(self):
        source = StorageSource("other:test", "other", "unknown", 0, 512, "")
        with self.assertRaisesRegex(ValueError, "Unsupported storage source type"):
            create_block_reader(source)


if __name__ == "__main__":
    unittest.main()
