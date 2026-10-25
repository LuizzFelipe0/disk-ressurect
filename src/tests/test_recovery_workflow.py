import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from application.recovery_workflow import RecoveryCatalogSnapshot, RecoveryWorkflow
from disk.inventory import NTFSVolume
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

        self.assertEqual(summary.recovered_count, 1)
        self.assertEqual(summary.results[0].status, "recovered")
        self.assertEqual(output_guard.calls, [(output_directory, 2)])
        self.assertTrue(opened_disks[0].closed)
        self.assertEqual(progress[0].stage, "extract")
        self.assertEqual(progress[0].completed, 1)


if __name__ == "__main__":
    unittest.main()
