import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from disk.models import NTFSVolume, PhysicalDisk
from disk.scanning.partition_scan import ScanCheckpoint
from infrastructure.persistence.deep_scan_repository import JsonDeepScanRepository
from modules.disk_discovery.service import DiskDiscoveryService


class InterruptibleInventory:
    def __init__(self):
        self.disk = PhysicalDisk(3, "USB recovery disk", 8 * 1024**3, "USB-SERIAL")
        self.resume_checkpoint = None
        self.fail_scan = True

    def list_disks(self):
        return [self.disk]

    def deep_scan_ntfs_volumes(self, disk_number, progress_callback=None, candidate_callback=None,
                               resume_checkpoint=None, checkpoint_callback=None):
        self.resume_checkpoint = resume_checkpoint
        if self.fail_scan:
            checkpoint_callback(ScanCheckpoint(0, 4 * 1024**3, self.disk.size_bytes, 512))
            raise OSError("USB disconnected")
        return [NTFSVolume(
            disk_number, 0, 1024 * 1024, 2 * 1024**3, 512, 4096, 1024,
            1024 * 1024 + 8192, 4096, ((1024 * 1024 + 8192, 1, 0),), "Lost NTFS", True,
        )]

    def list_ntfs_volumes(self, disk_number, progress_callback=None):
        return []


class DiskDiscoveryServiceCheckpointTests(unittest.TestCase):
    def test_interrupted_deep_scan_resumes_from_saved_checkpoint(self):
        inventory = InterruptibleInventory()
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            repository = JsonDeepScanRepository(os.path.join(directory, "scans.json"))
            service = DiskDiscoveryService(inventory, repository)

            with self.assertRaisesRegex(OSError, "USB disconnected"):
                service.scan_partitions(3, True)

            saved = repository.load(inventory.disk)
            self.assertEqual(saved.checkpoint.next_offset, 4 * 1024**3)

            inventory.fail_scan = False
            volumes, _ = service.scan_partitions(3, True, resume=True)

            self.assertEqual(inventory.resume_checkpoint, saved.checkpoint)
            self.assertEqual(len(volumes), 1)
            self.assertIsNone(repository.load(inventory.disk).checkpoint)


if __name__ == "__main__":
    unittest.main()
