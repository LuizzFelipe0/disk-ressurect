import base64
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from helpers import make_recovery_workflow
from modules.catalog.entities import CatalogNode, RecoveryCatalog, RecoveryCatalogSnapshot
from modules.recovery.entities import ContentReference, RecoveryCandidate
from modules.storage.entities import StorageSource


class MemoryContentReader:
    def __init__(self, payload):
        self.payload = payload
        self.reads = 0

    def iter_chunks(self, reference):
        self.reads += 1
        yield self.payload


def make_node(source, name, payload, is_directory=False):
    if is_directory:
        return CatalogNode("folder", name, name, True, 0)
    candidate_id = hashlib.sha256(f"{source.source_id}:{name}".encode()).hexdigest()
    reference = ContentReference(
        candidate_id, source.source_id, len(payload), hashlib.sha256(payload).hexdigest(),
    )
    candidate = RecoveryCandidate(
        candidate_id, source.source_id, "test-volume", name, name, len(payload),
        "synthetic", ("test",), (), integrity_state="validated",
        recoverability="recoverable", content_reference=reference,
    )
    return CatalogNode(candidate_id, name, name, False, len(payload), candidate)


class FilePreviewTests(unittest.TestCase):
    def setUp(self):
        self.source = StorageSource("test-source", "raw_image", "test image", 4096, 512, "unused")
        self.reader = MemoryContentReader(b"\xff\xd8\xffdata")
        self.workflow = make_recovery_workflow(content_reader_factory=lambda _source: self.reader)
        self.snapshot = RecoveryCatalogSnapshot(RecoveryCatalog({}), source=self.source)

    def test_returns_signature_checked_jpeg_as_base64(self):
        result = self.workflow.preview_file(
            self.snapshot, make_node(self.source, "photo.JPG", b"\xff\xd8\xffdata"),
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["mimeType"], "image/jpeg")
        self.assertEqual(result["kind"], "image")
        self.assertEqual(result["dataBase64"], base64.b64encode(b"\xff\xd8\xffdata").decode())
        self.assertEqual(self.reader.reads, 1)

    def test_rejects_unsupported_file_without_reading_content(self):
        result = self.workflow.preview_file(self.snapshot, make_node(self.source, "sheet.xlsx", b"data"))
        self.assertEqual(result, {"available": False, "reason": "unsupported_format"})
        self.assertEqual(self.reader.reads, 0)

    def test_rejects_invalid_signature(self):
        self.reader.payload = b"not a png"
        result = self.workflow.preview_file(self.snapshot, make_node(self.source, "photo.png", b"not a png"))
        self.assertEqual(result, {"available": False, "reason": "invalid_content"})

    def test_rejects_large_file_before_reading(self):
        node = make_node(self.source, "large.jpg", b"\xff\xd8\xff")
        reference = node.candidate.content_reference
        object.__setattr__(reference, "size_bytes", self.workflow.PREVIEW_LIMIT_BYTES + 1)
        result = self.workflow.preview_file(self.snapshot, node)
        self.assertEqual(result, {"available": False, "reason": "too_large"})
        self.assertEqual(self.reader.reads, 0)

    def test_rejects_folders(self):
        with self.assertRaisesRegex(ValueError, "Folders cannot be previewed"):
            self.workflow.preview_file(self.snapshot, make_node(self.source, "Photos", b"", is_directory=True))


if __name__ == "__main__":
    unittest.main()
