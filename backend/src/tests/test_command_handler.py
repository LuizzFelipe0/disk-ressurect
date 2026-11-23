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
from disk.deep_scan.carving_checkpoint import CarvingCheckpoint
from modules.commands.controller import RecoveryCommandHandler
from modules.catalog.service import CatalogService


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

    def deep_scan_ntfs_volumes(self, disk_number, progress_callback=None, candidate_callback=None,
        resume_checkpoint=None, checkpoint_callback=None):
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
        self.include_orphaned = False
        self.carving_options = None
        self.carving_checkpoint = None

    def build(self, volume, progress_callback=None, include_orphaned=False, phase_callback=None,
              precomputed_orphans=None, precomputed_carving_ranges=None,
              carving_ranges_truncated=False, precomputed_uncertain_carving_ranges=None,
              uncertain_carving_ranges_truncated=None, carving_options=None,
              carving_checkpoint=None, carving_checkpoint_callback=None):
        self.include_orphaned = include_orphaned
        self.carving_options = carving_options
        self.carving_checkpoint = carving_checkpoint
        self.precomputed_carving_ranges = precomputed_carving_ranges
        self.carving_ranges_truncated = carving_ranges_truncated
        self.precomputed_uncertain_carving_ranges = precomputed_uncertain_carving_ranges
        self.phase_callback = phase_callback
        if precomputed_carving_ranges is not None and carving_checkpoint_callback is not None:
            carving_checkpoint_callback(None)
        callback = None
        if progress_callback is not None:
            callback = lambda event: progress_callback(event.completed, event.total)
        return self.workflow.scan_catalog(volume, callback)

    @staticmethod
    def search(snapshot, query):
        return CatalogService.search(snapshot, query)

    @staticmethod
    def supported_extensions():
        return (".jpg", ".pdf")


class FakeRepository:
    def __init__(self):
        self.entries = {}
        self.carving_entries = {}

    def load(self, disk):
        return self.entries.get(disk.number)

    def save(self, disk, volumes, checkpoint=None):
        result = CachedDeepScan("2026-01-01T00:00:00+00:00", tuple(volumes))
        self.entries[disk.number] = result
        return result

    def load_carving_checkpoint(self, disk, volume):
        return self.carving_entries.get((disk.number, volume.partition_offset))

    def save_carving_checkpoint(self, disk, volume, checkpoint):
        key = (disk.number, volume.partition_offset)
        if checkpoint is None:
            self.carving_entries.pop(key, None)
        else:
            self.carving_entries[key] = checkpoint
        return checkpoint


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

    def test_lists_supported_file_types_before_a_catalog_is_built(self):
        handler = make_handler()

        result = handler.dispatch("list_file_types", {}, lambda _message: None)

        self.assertEqual(result, [".jpg", ".pdf"])

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
            def deep_scan_ntfs_volumes(self, disk_number, progress_callback=None, candidate_callback=None,
                resume_checkpoint=None, checkpoint_callback=None):
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
        matches = session.dispatch("search_catalog", {"query": "PHOTO.JPG"}, events.append)
        children = session.dispatch("catalog_children", {"nodeId": "n0"}, events.append)

        self.assertEqual(catalog["recordCount"], 2)
        self.assertEqual(catalog["roots"][0]["name"], "Photos")
        self.assertTrue(catalog["roots"][0]["hasChildren"])
        self.assertEqual(matches["totalMatches"], 1)
        self.assertEqual(matches["results"][0]["parentId"], "n0")
        self.assertEqual(children[0]["name"], "photo.jpg")
        self.assertTrue(any(event["type"] == "progress" for event in events))

    def test_orphan_scan_flag_is_forwarded_and_reported_in_catalog_progress(self):
        workflow = FakeWorkflow()
        catalog_service = FakeCatalogService(workflow)
        handler = RecoveryCommandHandler(
            DiskDiscoveryService(FakeInventory(), FakeRepository()), catalog_service, workflow,
        )
        handler.session.volumes["1:4096"] = make_volume()
        events = []

        handler.dispatch("scan_catalog", {"volumeId": "1:4096", "includeOrphaned": True}, events.append)

        self.assertTrue(catalog_service.include_orphaned)
        self.assertTrue(any(
            event.get("payload", {}).get("message") == "Reading MFT metadata and searching for orphaned entries…"
            for event in events
        ))

    def test_orphan_scan_runs_full_disk_validation_and_returns_its_summary(self):
        order = []

        class AuditedInventory(FakeInventory):
            def validate_disk(self, disk_number, progress_callback=None, retain_orphans_for_offset=None,
                              orphan_scan_volume=None, content_carving_range_budget_bytes=None):
                order.append("audit")
                if progress_callback:
                    progress_callback(100, 100, "Reading physical disk | 100/100 bytes")
                return {
                    "disk": SimpleNamespace(number=disk_number, model="Test disk", size_bytes=100,
                        serial_number="test"),
                    "coverage": SimpleNamespace(bytes_read=100, bytes_requested=100,
                        bytes_read_total=104, issues=(), intervals_as_objects=lambda: ()),
                    "capacity_mismatch": False,
                    "unsupported_filesystems": (),
                    "ntfs_checks": ({
                        "mftRecords": {"deleted": 2},
                        "orphanedFileRecordCount": 1,
                        "bitmapAllocation": {"orphanDataAllocation": [
                            {"status": "free"}, {"status": "allocated"},
                            {"status": "partially_observed"},
                        ]},
                    },),
                    "partition_table_checks": ({"valid": True},),
                    "mbr_signature_found": True,
                    "partitions": ({"offset": 4096, "filesystem": "NTFS"},),
                    "filesystem_signatures": (),
                    "orphan_records_by_partition": {4096: {}},
                    "content_carving_ranges_by_partition": {4096: ((8192, 12288),)},
                    "content_carving_ranges_truncated_by_partition": {4096: True},
                }

        class OrderedCatalogService(FakeCatalogService):
            def build(self, volume, progress_callback=None, include_orphaned=False, phase_callback=None,
                      precomputed_orphans=None, precomputed_carving_ranges=None,
                      carving_ranges_truncated=False, precomputed_uncertain_carving_ranges=None,
                      uncertain_carving_ranges_truncated=None, carving_options=None,
                      carving_checkpoint=None, carving_checkpoint_callback=None):
                order.append("catalog")
                if phase_callback:
                    phase_callback("linking", 1, 1)
                self.precomputed_orphans = precomputed_orphans
                self.precomputed_carving_ranges = precomputed_carving_ranges
                self.carving_ranges_truncated = carving_ranges_truncated
                self.precomputed_uncertain_carving_ranges = precomputed_uncertain_carving_ranges
                return super().build(volume, progress_callback, include_orphaned,
                    phase_callback, precomputed_orphans, precomputed_carving_ranges,
                    carving_ranges_truncated, precomputed_uncertain_carving_ranges,
                    uncertain_carving_ranges_truncated, carving_options,
                    carving_checkpoint, carving_checkpoint_callback)

        inventory = AuditedInventory()
        workflow = FakeWorkflow()
        repository = FakeRepository()
        volume = make_volume()
        checkpoint = CarvingCheckpoint(
            "b" * 64, 0, 8192, inventory.list_disks()[0].size_bytes, 512, "profile-v1",
        )
        repository.save_carving_checkpoint(inventory.list_disks()[0], volume, checkpoint)
        handler = RecoveryCommandHandler(
            DiskDiscoveryService(inventory, repository),
            OrderedCatalogService(workflow), workflow,
        )
        handler.session.volumes["1:4096"] = volume
        events = []

        catalog = handler.dispatch("scan_catalog", {
            "volumeId": "1:4096", "includeOrphaned": True,
            "carvingOptions": {"scanBudgetGiB": 16, "maxFiles": 512},
        }, events.append)

        self.assertEqual(order, ["audit", "catalog"])
        self.assertEqual(catalog["diskValidation"]["coverageStatus"], "complete")
        self.assertEqual(catalog["diskValidation"]["deletedMftRecordCount"], 2)
        self.assertEqual(catalog["diskValidation"]["orphanedFileRecordCount"], 1)
        self.assertEqual(catalog["diskValidation"]["orphanRecordsByAllocationStatus"], {
            "free": 1, "allocated": 1, "mixed": 0, "unknown": 1,
        })
        self.assertEqual(handler.catalog_service.precomputed_orphans, {})
        self.assertEqual(handler.catalog_service.precomputed_carving_ranges, ((8192, 12288),))
        self.assertTrue(handler.catalog_service.carving_ranges_truncated)
        self.assertEqual(handler.catalog_service.carving_options.scan_budget_gib, 16)
        self.assertEqual(handler.catalog_service.carving_options.max_files, 512)
        self.assertEqual(handler.catalog_service.carving_checkpoint, checkpoint)
        self.assertIsNone(repository.load_carving_checkpoint(inventory.list_disks()[0], volume))
        self.assertTrue(any(
            event.get("payload", {}).get("stage") == "disk-validation"
            for event in events
        ))
        self.assertTrue(any(
            event.get("payload", {}).get("message") == "Organizing file and folder records…"
            for event in events
        ))

    def test_interrupted_carving_persists_latest_checkpoint_for_the_same_volume(self):
        inventory = FakeInventory()
        source_disk = inventory.list_disks()[0]
        volume = make_volume()
        repository = FakeRepository()

        class AuditedInventory(FakeInventory):
            def validate_disk(self, disk_number, progress_callback=None, retain_orphans_for_offset=None,
                              orphan_scan_volume=None, content_carving_range_budget_bytes=None):
                size = source_disk.size_bytes
                return {
                    "disk": source_disk,
                    "coverage": SimpleNamespace(
                        bytes_read=size, bytes_requested=size, bytes_read_total=size,
                        issues=(), intervals_as_objects=lambda: (),
                    ),
                    "capacity_mismatch": False,
                    "unsupported_filesystems": (),
                    "ntfs_checks": (),
                    "partition_table_checks": ({"valid": True},),
                    "mbr_signature_found": True,
                    "partitions": (),
                    "filesystem_signatures": (),
                    "orphan_records_by_partition": {volume.partition_offset: {}},
                    "content_carving_ranges_by_partition": {
                        volume.partition_offset: ((8192, 12288),),
                    },
                }

        checkpoint = CarvingCheckpoint(
            "c" * 64, 0, 9216, source_disk.size_bytes, 512, "profile-v2",
        )

        class InterruptingCatalogService(FakeCatalogService):
            def build(self, *args, carving_checkpoint_callback=None, **kwargs):
                carving_checkpoint_callback(checkpoint)
                raise OSError("Simulated carving interruption")

        workflow = FakeWorkflow()
        handler = RecoveryCommandHandler(
            DiskDiscoveryService(AuditedInventory([volume]), repository),
            InterruptingCatalogService(workflow), workflow,
        )
        handler.session.volumes["1:4096"] = volume

        with self.assertRaisesRegex(OSError, "Simulated carving interruption"):
            handler.dispatch("scan_catalog", {
                "volumeId": "1:4096", "includeOrphaned": True,
            }, lambda _event: None)

        self.assertEqual(
            repository.load_carving_checkpoint(source_disk, volume), checkpoint,
        )

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
