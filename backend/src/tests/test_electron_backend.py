import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from application.recovery_workflow import RecoveryProgress
from disk.inventory import NTFSVolume
from domain.recovery_catalog import RecoveryCatalog
from electron_backend import BackendSession


def make_node(index, name, is_directory, path, children=(), parent=None, size=0):
    record = SimpleNamespace(
        index=index,
        sequence_number=1,
        name=name,
        is_dir=is_directory,
        file_size=size,
    )
    return SimpleNamespace(
        record=record,
        full_path=path,
        children=list(children),
        parent=parent,
    )


def make_volume():
    return NTFSVolume(1, 1, 4096, 1024 * 1024, 512, 4096, 1024,
                      8192, 2048, ((8192, 2, 0),))


class FakeInventory:
    def __init__(self, volumes=()):
        self.volumes = list(volumes)

    def list_disks(self):
        return [SimpleNamespace(number=1, model="Test disk", size_bytes=4096,
                                serial_number="test", display_name="Disk 1 · Test disk")]

    def list_ntfs_volumes(self, disk_number, progress_callback=None):
        if progress_callback:
            progress_callback(0, 1, "Checking partition")
        return self.volumes

    def deep_scan_ntfs_volumes(self, disk_number, progress_callback=None):
        return self.list_ntfs_volumes(disk_number, progress_callback)


class FakeWorkflow:
    def __init__(self, nodes=None, roots=None):
        self.nodes = nodes or {}
        self.roots = roots or []
        self.extraction_call = None

    def scan_catalog(self, volume, progress_callback=None):
        if progress_callback:
            progress_callback(RecoveryProgress("catalog", 1, 1, "Catalog record"))
        return SimpleNamespace(catalog=RecoveryCatalog(self.nodes, self.roots), volume=volume)

    def extract_selection(self, **kwargs):
        self.extraction_call = kwargs
        return SimpleNamespace(recovered_count=1, results=(object(),))


class ElectronBackendTests(unittest.TestCase):
    def test_lists_disks_as_json_serializable_contracts(self):
        session = BackendSession(inventory=FakeInventory())

        result = session._dispatch("list_disks", {}, lambda _message: None)

        self.assertEqual(result[0]["number"], 1)
        self.assertEqual(result[0]["displayName"], "Disk 1 · Test disk")

    def test_partition_scan_emits_progress_and_retains_volume_for_catalog(self):
        volume = make_volume()
        session = BackendSession(inventory=FakeInventory([volume]))
        emitted = []

        result = session._dispatch("list_partitions", {"diskNumber": 1}, emitted.append)

        self.assertEqual(result[0]["id"], "1:4096")
        self.assertIn("1:4096", session.volumes)
        self.assertEqual(emitted[0]["type"], "progress")

    def test_catalog_response_contains_roots_and_lazy_children(self):
        image = make_node(2, "photo.jpg", False, "Photos/photo.jpg", size=2048)
        folder = make_node(1, "Photos", True, "Photos", children=[image])
        image.parent = folder
        workflow = FakeWorkflow({1: folder, 2: image}, [folder])
        session = BackendSession(inventory=FakeInventory(), workflow=workflow)
        session.volumes["1:4096"] = make_volume()
        events = []

        catalog = session._dispatch("scan_catalog", {"volumeId": "1:4096"}, events.append)
        children = session._dispatch("catalog_children", {"nodeId": "n0"}, events.append)

        self.assertEqual(catalog["recordCount"], 2)
        self.assertEqual(catalog["roots"][0]["name"], "Photos")
        self.assertTrue(catalog["roots"][0]["hasChildren"])
        self.assertEqual(children[0]["name"], "photo.jpg")
        self.assertTrue(any(event["type"] == "progress" for event in events))

    def test_extraction_contract_preserves_exclusions_inside_checked_folders(self):
        first = make_node(2, "one.jpg", False, "Photos/one.jpg", size=2048)
        excluded = make_node(3, "two.jpg", False, "Photos/two.jpg", size=2048)
        folder = make_node(1, "Photos", True, "Photos", children=[first, excluded])
        first.parent = folder
        excluded.parent = folder
        workflow = FakeWorkflow({1: folder, 2: first, 3: excluded}, [folder])
        session = BackendSession(inventory=FakeInventory(), workflow=workflow)
        session.snapshot = SimpleNamespace(catalog=RecoveryCatalog(workflow.nodes, [folder]))
        session.snapshot.volume = make_volume()
        session.nodes = {"n0": folder, "n1": first, "n2": excluded}

        result = session._dispatch("extract", {
            "selectedNodeIds": ["n0"],
            "excludedNodeIds": ["n2"],
            "outputDirectory": "recovered",
            "extensions": [".jpg"],
            "minimumSizeKb": 0,
        }, lambda _event: None)

        self.assertEqual([node.full_path for node in workflow.extraction_call["selected_nodes"]], ["Photos/one.jpg"])
        self.assertEqual(result["recoveredCount"], 1)
        self.assertEqual(result["reportPath"], os.path.join("recovered", "Recovery_Report.txt"))


if __name__ == "__main__":
    unittest.main()
