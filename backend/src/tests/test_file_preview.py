import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.recovery.service import RecoveryWorkflow


class FakeDisk:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def make_node(name, payload, is_directory=False):
    record = SimpleNamespace(name=name, file_size=len(payload), is_dir=is_directory,
                             resident_data=payload, data_is_complete=True)
    return SimpleNamespace(record=record)


class FilePreviewTests(unittest.TestCase):
    def setUp(self):
        self.disks = []
        self.workflow = RecoveryWorkflow(disk_factory=self.open_disk)
        self.snapshot = SimpleNamespace(volume=SimpleNamespace(disk_number=3), volume_start=0, cluster_size=4096)

    def open_disk(self, number):
        self.assertEqual(number, 3)
        disk = FakeDisk()
        self.disks.append(disk)
        return disk

    def test_returns_signature_checked_jpeg_as_base64_and_closes_source(self):
        result = self.workflow.preview_file(self.snapshot, make_node("photo.JPG", b"\xff\xd8\xffdata"))

        self.assertTrue(result["available"])
        self.assertEqual(result["mimeType"], "image/jpeg")
        self.assertEqual(result["kind"], "image")
        self.assertEqual(result["dataBase64"], "/9j/ZGF0YQ==")
        self.assertTrue(self.disks[0].closed)

    def test_rejects_unsupported_file_without_opening_source(self):
        result = self.workflow.preview_file(self.snapshot, make_node("sheet.xlsx", b"data"))

        self.assertEqual(result, {"available": False, "reason": "unsupported_format"})
        self.assertEqual(self.disks, [])

    def test_rejects_invalid_signature_and_closes_source(self):
        result = self.workflow.preview_file(self.snapshot, make_node("photo.png", b"not a png"))

        self.assertEqual(result, {"available": False, "reason": "invalid_content"})
        self.assertTrue(self.disks[0].closed)

    def test_rejects_large_file_before_reading(self):
        node = make_node("large.jpg", b"\xff\xd8\xff")
        node.record.file_size = self.workflow.PREVIEW_LIMIT_BYTES + 1

        result = self.workflow.preview_file(self.snapshot, node)

        self.assertEqual(result, {"available": False, "reason": "too_large"})
        self.assertEqual(self.disks, [])

    def test_rejects_folders(self):
        with self.assertRaisesRegex(ValueError, "Folders cannot be previewed"):
            self.workflow.preview_file(self.snapshot, make_node("Photos", b"", is_directory=True))


if __name__ == "__main__":
    unittest.main()
