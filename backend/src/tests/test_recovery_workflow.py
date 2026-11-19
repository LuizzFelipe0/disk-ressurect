import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from modules.catalog.models import RecoveryCatalogSnapshot
from modules.recovery.service import RecoveryWorkflow
from disk.models import NTFSVolume
from domain.recovery_catalog import RecoveryCatalog


class FakeDisk:
    def __init__(self, disk_number):
        self.disk_number = disk_number
        self.closed = False

    def read_at(self, offset, size):
        return b""

    def close(self):
        self.closed = True


class FakeOutputGuard:
    def __init__(self):
        self.calls = []

    def validate(self, output_directory, source_disk_number):
        self.calls.append((output_directory, source_disk_number))
        return [0]


class RecoveryWorkflowTests(unittest.TestCase):
    def test_rejects_empty_output_path_before_opening_source_disk(self):
        volume = NTFSVolume(2, 1, 0, 1024 * 1024, 512, 4096, 1024, 8192, 1024,
                            ((8192, 1, 0),))
        snapshot = RecoveryCatalogSnapshot(RecoveryCatalog({}, []), volume)
        opened_disks = []
        workflow = RecoveryWorkflow(
            disk_factory=lambda disk_number: opened_disks.append(disk_number),
            output_guard=FakeOutputGuard(),
        )

        with self.assertRaisesRegex(ValueError, "Choose a recovery destination"):
            workflow.extract_selection(snapshot, [], "   ", {".pdf"})

        self.assertEqual(opened_disks, [])

    def test_extracts_only_the_selected_nodes_and_emits_progress(self):
        content = b"%PDF-workflow"
        record = SimpleNamespace(
            index=42,
            sequence_number=1,
            name="notes.pdf",
            is_dir=False,
            is_allocated=False,
            file_size=len(content),
            resident_data=content,
            data_runs=[],
            data_is_complete=True,
        )
        node = SimpleNamespace(
            record=record,
            full_path="selected folder/notes.pdf",
            parent=None,
            children=[],
        )
        catalog = RecoveryCatalog({42: node}, [node])
        volume = NTFSVolume(2, 1, 0, 1024 * 1024, 512, 4096, 1024, 8192, 1024,
                            ((8192, 1, 0),))
        snapshot = RecoveryCatalogSnapshot(catalog, volume)
        opened_disks = []

        def disk_factory(disk_number):
            disk = FakeDisk(disk_number)
            opened_disks.append(disk)
            return disk

        output_guard = FakeOutputGuard()
        workflow = RecoveryWorkflow(disk_factory=disk_factory, output_guard=output_guard)
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        progress = []
        with tempfile.TemporaryDirectory(dir=repo_root) as output_directory:
            summary = workflow.extract_selection(
                snapshot,
                [node],
                output_directory,
                {".pdf"},
                progress_callback=progress.append,
            )
            recovered_path = os.path.join(output_directory, "selected folder", "notes.pdf")
            with open(recovered_path, "rb") as recovered_file:
                self.assertEqual(recovered_file.read(), content)
            self.assertFalse(os.path.exists(os.path.join(output_directory, "Recovery_Report.txt")))

        self.assertEqual(summary.recovered_count, 1)
        self.assertEqual(summary.results[0].status, "recovered")
        self.assertEqual(output_guard.calls, [(output_directory, 2)])
        self.assertTrue(opened_disks[0].closed)
        self.assertEqual(progress[0].stage, "extract")
        self.assertEqual(progress[0].completed, 1)

    def test_failed_orphan_recovery_does_not_leave_empty_record_directories(self):
        content = b"not a JPEG"
        record = SimpleNamespace(
            index=-2049,
            sequence_number=1,
            name="[DELETED]_photo.jpg",
            is_dir=False,
            is_allocated=False,
            file_size=len(content),
            resident_data=content,
            data_runs=[],
            data_is_complete=True,
        )
        orphan_path = os.path.join("Lost_Files_DeepScan", "0000000000000800", record.name)
        node = SimpleNamespace(record=record, full_path=orphan_path, parent=None, children=[])
        catalog = RecoveryCatalog({record.index: node}, [node])
        volume = NTFSVolume(2, 1, 0, 1024 * 1024, 512, 4096, 1024, 8192, 1024,
                            ((8192, 1, 0),))
        snapshot = RecoveryCatalogSnapshot(catalog, volume)
        workflow = RecoveryWorkflow(
            disk_factory=lambda disk_number: FakeDisk(disk_number),
            output_guard=FakeOutputGuard(),
        )
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        with tempfile.TemporaryDirectory(dir=repo_root) as output_directory:
            summary = workflow.extract_selection(snapshot, [node], output_directory, {".jpg"})

            self.assertEqual(summary.results[0].status, "signature_mismatch")
            self.assertEqual(os.listdir(output_directory), [])


if __name__ == "__main__":
    unittest.main()
