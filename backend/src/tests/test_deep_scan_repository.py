import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.persistence.deep_scan_repository import JsonDeepScanRepository
from modules.storage.entities import PhysicalDisk
from modules.disk.entities import NTFSVolume
from modules.storage.entities import ScanCheckpoint
from modules.deep_scan.entities import CarvedCandidateReference, CarvingCheckpoint
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

        self.assertEqual(document, {
            "version": 2, "disks": {}, "carving": {}, "validation": {},
        })

    def test_checkpoint_is_persisted_and_restored_with_disk_scan(self):
        disk = PhysicalDisk(1, "Recovery disk", 8 * 1024**3, "SERIAL-123")
        checkpoint = ScanCheckpoint(1, 7 * 1024**3, disk.size_bytes, 512)

        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            repository = JsonDeepScanRepository(os.path.join(directory, "deep_scan_cache.json"))
            repository.save(disk, [], checkpoint)
            restored = repository.load(disk)

        self.assertEqual(restored.checkpoint, checkpoint)

    def test_carving_checkpoint_persists_cursor_carry_and_candidate_references(self):
        volume = NTFSVolume(
            1, 0, 4096, 1024 * 1024, 512, 4096, 1024,
            8192, 2048, ((8192, 2, 0),), "Lost NTFS", True,
        )
        disk = PhysicalDisk(1, "Recovery disk", 8 * 1024**3, "SERIAL-123")
        candidate = CarvedCandidateReference(
            offset=64, extension=".jpg", size_bytes=128, sha256="a" * 64,
        )
        checkpoint = CarvingCheckpoint(
            range_fingerprint="b" * 64,
            range_index=2,
            next_offset=4096,
            disk_size=disk.size_bytes,
            bytes_per_sector=volume.bytes_per_sector,
            scan_profile="profile-v1",
            candidates=(candidate,),
            bytes_scanned=1024**3,
            signature_carry=b"\xff\xd8\xff",
            processed_range_fingerprint="c" * 64,
        )

        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            path = os.path.join(directory, "deep_scan_cache.json")
            repository = JsonDeepScanRepository(path)
            repository.save(disk, [])
            repository.save_carving_checkpoint(disk, volume, checkpoint)
            restored = JsonDeepScanRepository(path).load_carving_checkpoint(disk, volume)

        self.assertEqual(restored, checkpoint)

    def test_carving_checkpoint_is_scoped_to_disk_and_volume_identity(self):
        volume = NTFSVolume(
            1, 0, 4096, 1024 * 1024, 512, 4096, 1024,
            8192, 2048, ((8192, 2, 0),), "Lost NTFS", True,
        )
        disk = PhysicalDisk(1, "Recovery disk", 8 * 1024**3, "SERIAL-123")
        other_disk = PhysicalDisk(2, "Recovery disk", 8 * 1024**3, "SERIAL-456")
        checkpoint = CarvingCheckpoint(
            "b" * 64, 0, 8192, disk.size_bytes, 512, "profile-v1",
        )
        repository = JsonDeepScanRepository()
        repository.save_carving_checkpoint(disk, volume, checkpoint)

        self.assertEqual(repository.load_carving_checkpoint(disk, volume), checkpoint)
        self.assertIsNone(repository.load_carving_checkpoint(other_disk, volume))

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

    def test_validation_snapshot_persists_by_disk_identity_and_can_be_invalidated(self):
        disk = PhysicalDisk(1, "Recovery disk", 8 * 1024**3, "SERIAL-123")
        reconnected_disk = PhysicalDisk(4, "Recovery disk", 8 * 1024**3, "serial-123")
        other_disk = PhysicalDisk(1, "Recovery disk", 8 * 1024**3, "SERIAL-456")
        snapshot = {
            "version": 1,
            "scannedAt": "2026-11-23T12:00:00+00:00",
            "identity": JsonDeepScanRepository._disk_identity(disk),
            "diskSize": disk.size_bytes,
            "bytesPerSector": 512,
            "intervals": [[0, disk.size_bytes]],
            "issues": [],
            "bytesRequested": disk.size_bytes,
            "bytesReadTotal": disk.size_bytes,
            "ntfsBootOffsets": [],
            "gptHeaderOffsets": [],
            "filesystemSignatures": [],
        }

        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            path = os.path.join(directory, "deep_scan_cache.json")
            first = JsonDeepScanRepository(path)
            first.save_validation_snapshot(disk, snapshot)
            second = JsonDeepScanRepository(path)

            self.assertEqual(second.load_validation_snapshot(reconnected_disk), snapshot)
            self.assertIsNone(second.load_validation_snapshot(other_disk))
            second.invalidate_validation_snapshot(disk)
            self.assertIsNone(first.load_validation_snapshot(disk))


if __name__ == "__main__":
    unittest.main()
