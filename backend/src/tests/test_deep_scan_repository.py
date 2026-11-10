import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.persistence.deep_scan_repository import JsonDeepScanRepository
from disk.models import NTFSVolume, PhysicalDisk
from disk.scanning.partition_scan import ScanCheckpoint
from unittest.mock import patch


class DeepScanRepositoryTests(unittest.TestCase):
    def test_cache_files_and_data_directory_keep_the_pkexec_users_ownership(self):
        disk = PhysicalDisk(1, "Recovery disk", 8 * 1024**3, "SERIAL-123")
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            path = os.path.join(directory, "nested", "deep_scan_cache.json")
            with patch("infrastructure.persistence.deep_scan_repository.set_pkexec_user_ownership_fd") as set_owner_fd:
                JsonDeepScanRepository(path).save(disk, [])
                self.assertTrue(os.path.isdir(os.path.dirname(path)))
                set_owner_fd.assert_called_once()
                self.assertGreaterEqual(set_owner_fd.call_args.args[0], 0)

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux no-follow file opens")
    def test_cache_reader_rejects_symlinks_instead_of_reading_their_targets(self):
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            target = os.path.join(directory, "external.json")
            cache = os.path.join(directory, "deep_scan_cache.json")
            with open(target, "w", encoding="utf-8") as target_file:
                target_file.write('{"version":1,"disks":{"external":{"volumes":[]}}}')
            os.symlink(target, cache)

            document = JsonDeepScanRepository(cache)._read_document()

        self.assertEqual(document, {"version": 1, "disks": {}})

    def test_checkpoint_is_persisted_and_restored_with_disk_scan(self):
        disk = PhysicalDisk(1, "Recovery disk", 8 * 1024**3, "SERIAL-123")
        checkpoint = ScanCheckpoint(1, 7 * 1024**3, disk.size_bytes, 512)

        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            repository = JsonDeepScanRepository(os.path.join(directory, "deep_scan_cache.json"))
            repository.save(disk, [], checkpoint)
            restored = repository.load(disk)

        self.assertEqual(restored.checkpoint, checkpoint)

    def test_scan_results_are_readable_from_a_new_repository_instance(self):
        volume = NTFSVolume(
            1, 0, 4096, 1024 * 1024, 512, 4096, 1024,
            8192, 2048, ((8192, 2, 0),), "Lost NTFS", True,
        )
        disk = PhysicalDisk(1, "Recovery disk", 8 * 1024**3, "SERIAL-123")

        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            path = os.path.join(directory, "deep_scan_cache.json")
            JsonDeepScanRepository(path).save(disk, [volume])
            restored = JsonDeepScanRepository(path).load(disk)

        self.assertIsNotNone(restored)
        self.assertEqual(restored.volumes, (volume,))

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
