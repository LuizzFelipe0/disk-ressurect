import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.recovery.models import RecoveryProgress
from modules.disk_discovery.models import CachedDeepScan
from modules.disk_discovery.service import DiskDiscoveryService
from disk.models import NTFSVolume
from domain.recovery_catalog import RecoveryCatalog
from infrastructure.persistence.deep_scan_repository import JsonDeepScanRepository
from modules.commands.controller import RecoveryCommandHandler


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
        return [SimpleNamespace(number=1, model="Test disk", size_bytes=16 * 1024 * 1024,
                                serial_number="test", display_name="Disk 1 · Test disk")]

    def list_ntfs_volumes(self, disk_number, progress_callback=None):
        if progress_callback:
            progress_callback(0, 1, "Checking partition")
        return self.volumes

    def deep_scan_ntfs_volumes(self, disk_number, progress_callback=None, candidate_callback=None):
        if candidate_callback:
            candidate_callback(tuple(self.volumes))
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


class FakeCatalogService:
    def __init__(self, workflow):
        self.workflow = workflow

    def build(self, volume, progress_callback=None):
        callback = None
        if progress_callback is not None:
            callback = lambda event: progress_callback(event.completed, event.total)
        return self.workflow.scan_catalog(volume, callback)


class FakeRepository:
    def __init__(self):
        self.entries = {}

    def load(self, disk):
        return self.entries.get(disk.number)

    def save(self, disk, volumes):
        result = CachedDeepScan("2026-01-01T00:00:00+00:00", tuple(volumes))
        self.entries[disk.number] = result
        return result


def make_handler(inventory=None, workflow=None, repository=None):
    workflow = workflow or FakeWorkflow()
    return RecoveryCommandHandler(
        DiskDiscoveryService(inventory or FakeInventory(), repository or FakeRepository()),
        FakeCatalogService(workflow),
        workflow,
    )


class RecoveryCommandHandlerTests(unittest.TestCase):
    def test_lists_disks_as_json_serializable_contracts(self):
        session = make_handler()

        result = session.dispatch("list_disks", {}, lambda _message: None)

        self.assertEqual(result[0]["number"], 1)
        self.assertEqual(result[0]["displayName"], "Disk 1 · Test disk")

    def test_partition_scan_emits_progress_and_retains_volume_for_catalog(self):
        volume = make_volume()
        session = make_handler(inventory=FakeInventory([volume]))
        emitted = []

        result = session.dispatch("list_partitions", {"diskNumber": 1}, emitted.append)

        self.assertEqual(result[0]["id"], "1:4096")
        self.assertIn("1:4096", session.session.volumes)
        self.assertEqual(emitted[0]["type"], "progress")

    def test_deep_scan_candidates_survive_an_interrupted_scan_and_backend_restart(self):
        class InterruptedInventory(FakeInventory):
            def deep_scan_ntfs_volumes(self, disk_number, progress_callback=None, candidate_callback=None):
                candidate_callback(tuple(self.volumes))
                raise OSError("Simulated interruption after finding a candidate")

        volume = make_volume()
        volume = NTFSVolume(
            volume.disk_number, 0, volume.partition_offset, volume.partition_size,
            volume.bytes_per_sector, volume.cluster_size, volume.record_size,
            volume.mft_offset, volume.mft_size, volume.mft_fragments,
            "Lost NTFS", True,
        )
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as data_directory:
            inventory = InterruptedInventory([volume])
            repository_path = os.path.join(data_directory, "deep_scan_cache.json")
            session = make_handler(inventory, repository=JsonDeepScanRepository(repository_path))
            with self.assertRaisesRegex(OSError, "Simulated interruption"):
                session.dispatch("list_partitions", {"diskNumber": 1, "deepScan": True}, lambda _event: None)

            restarted = make_handler(inventory, repository=JsonDeepScanRepository(repository_path))
            disks = restarted.dispatch("list_disks", {}, lambda _event: None)

        self.assertEqual(len(disks[0]["cachedPartitions"]), 1)
        self.assertEqual(disks[0]["cachedPartitions"][0]["id"], "1:4096")
        self.assertTrue(disks[0]["cachedPartitions"][0]["scanSavedAt"])
        self.assertEqual(restarted.session.volumes["1:4096"].mft_fragments, ((8192, 2, 0),))

    def test_catalog_response_contains_roots_and_lazy_children(self):
        image = make_node(2, "photo.jpg", False, "Photos/photo.jpg", size=2048)
        folder = make_node(1, "Photos", True, "Photos", children=[image])
        image.parent = folder
        workflow = FakeWorkflow({1: folder, 2: image}, [folder])
        session = make_handler(workflow=workflow)
        session.session.volumes["1:4096"] = make_volume()
        events = []

        catalog = session.dispatch("scan_catalog", {"volumeId": "1:4096"}, events.append)
        children = session.dispatch("catalog_children", {"nodeId": "n0"}, events.append)

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
        session = make_handler(workflow=workflow)
        session.session.snapshot = SimpleNamespace(catalog=RecoveryCatalog(workflow.nodes, [folder]))
        session.session.snapshot.volume = make_volume()
        session.session.nodes = {"n0": folder, "n1": first, "n2": excluded}

        result = session.dispatch("extract", {
            "selectedNodeIds": ["n0"],
            "excludedNodeIds": ["n2"],
            "outputDirectory": "recovered",
            "extensions": [".jpg"],
            "minimumSizeKb": 0,
        }, lambda _event: None)

        self.assertEqual([node.full_path for node in workflow.extraction_call["selected_nodes"]], ["Photos"])
        self.assertEqual([node.full_path for node in workflow.extraction_call["excluded_nodes"]], ["Photos/two.jpg"])
        self.assertEqual(result["recoveredCount"], 1)
        self.assertEqual(result, {"recoveredCount": 1, "candidateCount": 1})


if __name__ == "__main__":
    unittest.main()
