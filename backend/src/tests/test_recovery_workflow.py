import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from helpers import make_recovery_workflow
from modules.catalog.entities import CatalogNode, RecoveryCatalog, RecoveryCatalogSnapshot
from modules.recovery.entities import ContentReference, RecoveryCandidate
from modules.storage.entities import StorageSource


class MemoryContentReader:
    def __init__(self, contents):
        self.contents = contents

    def iter_chunks(self, reference):
        yield self.contents[reference.reference_id]


class FakeOutputGuard:
    def __init__(self):
        self.calls = []

    def validate_source(self, output_directory, source):
        self.calls.append((output_directory, source.source_id))


def file_node(source, name, path, content, *, deleted=False):
    candidate_id = hashlib.sha256(f"{source.source_id}:{path}".encode()).hexdigest()
    reference = ContentReference(
        candidate_id, source.source_id, len(content), hashlib.sha256(content).hexdigest(),
    )
    candidate = RecoveryCandidate(
        candidate_id=candidate_id, source_id=source.source_id, volume_id="test-volume",
        name=name, original_path=path, size_bytes=len(content), filesystem_id="synthetic",
        discovery_methods=("test",), evidence=(), deletion_state="deleted" if deleted else "not_deleted",
        integrity_state="validated", recoverability="recoverable", content_reference=reference,
    )
    return CatalogNode(candidate_id, name, path, False, len(content), candidate)


class RecoveryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source = StorageSource("test-source", "raw_image", "test image", 4096, 512, "unused")
        self.output_guard = FakeOutputGuard()

    def test_rejects_empty_output_path_before_opening_content_reader(self):
        created = []
        workflow = make_recovery_workflow(
            output_guard=self.output_guard,
            content_reader_factory=lambda source: created.append(source),
        )
        snapshot = RecoveryCatalogSnapshot(RecoveryCatalog({}), source=self.source)

        with self.assertRaisesRegex(ValueError, "Choose a recovery destination"):
            workflow.extract_selection(snapshot, [], "   ", {".pdf"})
        self.assertEqual(created, [])
        self.assertEqual(self.output_guard.calls, [])

    def test_extracts_selected_candidates_and_emits_progress(self):
        content = b"%PDF-workflow"
        node = file_node(self.source, "notes.pdf", "selected folder/notes.pdf", content, deleted=True)
        folder = CatalogNode("folder", "selected folder", "selected folder", True, 0)
        folder.children.append(node)
        node.parent = folder
        catalog = RecoveryCatalog({folder.node_id: folder, node.node_id: node}, [folder])
        snapshot = RecoveryCatalogSnapshot(catalog, source=self.source, source_id=self.source.source_id)
        workflow = make_recovery_workflow(
            output_guard=self.output_guard,
            content_reader_factory=lambda _source: MemoryContentReader({node.candidate.candidate_id: content}),
        )
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        progress = []
        with tempfile.TemporaryDirectory(dir=repo_root) as output_directory:
            summary = workflow.extract_selection(
                snapshot, [folder], output_directory, {".pdf"}, progress_callback=progress.append,
            )
            recovered_path = Path(output_directory) / "selected folder" / "notes.pdf"
            self.assertEqual(recovered_path.read_bytes(), content)
            self.assertFalse((Path(output_directory) / "Recovery_Report.txt").exists())

        self.assertEqual(summary.recovered_count, 1)
        self.assertEqual(summary.results[0].status, "recovered")
        self.assertEqual(self.output_guard.calls, [(output_directory, self.source.source_id)])
        self.assertEqual(progress[0].stage, "extract")
        self.assertEqual(progress[0].completed, 1)

    def test_signature_failure_does_not_leave_empty_record_directories(self):
        content = b"not a JPEG"
        path = os.path.join("Lost_Files_DeepScan", "0000000000000800", "[DELETED]_photo.jpg")
        node = file_node(self.source, "[DELETED]_photo.jpg", path, content, deleted=True)
        snapshot = RecoveryCatalogSnapshot(
            RecoveryCatalog({node.node_id: node}, [node]), source=self.source,
        )
        workflow = make_recovery_workflow(
            output_guard=self.output_guard,
            content_reader_factory=lambda _source: MemoryContentReader({node.candidate.candidate_id: content}),
        )
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with tempfile.TemporaryDirectory(dir=repo_root) as output_directory:
            summary = workflow.extract_selection(snapshot, [node], output_directory, {".jpg"})
            self.assertEqual(summary.results[0].status, "signature_mismatch")
            self.assertEqual(os.listdir(output_directory), [])


if __name__ == "__main__":
    unittest.main()
