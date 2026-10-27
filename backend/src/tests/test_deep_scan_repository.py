import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.persistence.deep_scan_repository import JsonDeepScanRepository
from disk.models import NTFSVolume, PhysicalDisk


class DeepScanRepositoryTests(unittest.TestCase):
    def test_saved_volume_is_restored_for_same_physical_disk_after_device_number_changes(self):
        volume = NTFSVolume(
            1, 0, 4096, 1024 * 1024, 512, 4096, 1024,
            8192, 2048, ((8192, 2, 0),), "Lost NTFS", True,
        )
        original_disk = PhysicalDisk(1, "Recovery disk", 8 * 1024**3, "SERIAL-123")
        reconnected_disk = PhysicalDisk(4, "Recovery disk", 8 * 1024**3, "serial-123")

        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            cache_path = os.path.join(directory, "deep_scan_cache.json")
            JsonDeepScanRepository(cache_path).save(original_disk, [volume])

            restored = JsonDeepScanRepository(cache_path).load(reconnected_disk)

        self.assertIsNotNone(restored)
        self.assertEqual(restored.volumes[0].disk_number, 4)
        self.assertEqual(restored.volumes[0].mft_fragments, ((8192, 2, 0),))
        self.assertTrue(restored.volumes[0].partition_size_is_estimated)

    def test_cached_candidate_is_not_reused_for_a_different_physical_disk(self):
        volume = NTFSVolume(
            1, 0, 4096, 1024 * 1024, 512, 4096, 1024,
            8192, 2048, ((8192, 2, 0),), "Lost NTFS", True,
        )
        original_disk = PhysicalDisk(1, "Recovery disk", 8 * 1024**3, "SERIAL-123")
        different_disk = PhysicalDisk(1, "Recovery disk", 8 * 1024**3, "SERIAL-456")

        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            cache_path = os.path.join(directory, "deep_scan_cache.json")
            JsonDeepScanRepository(cache_path).save(original_disk, [volume])

            restored = JsonDeepScanRepository(cache_path).load(different_disk)

        self.assertIsNone(restored)

    def test_cached_candidate_outside_current_disk_capacity_is_rejected(self):
        volume = NTFSVolume(
            1, 0, 9 * 1024**3, 1024 * 1024, 512, 4096, 1024,
            9 * 1024**3, 2048, ((9 * 1024**3, 2, 0),), "Lost NTFS", True,
        )
        disk = PhysicalDisk(1, "Recovery disk", 8 * 1024**3, "SERIAL-123")

        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            cache_path = os.path.join(directory, "deep_scan_cache.json")
            JsonDeepScanRepository(cache_path).save(disk, [volume])

            restored = JsonDeepScanRepository(cache_path).load(disk)

        self.assertIsNone(restored)


if __name__ == "__main__":
    unittest.main()
