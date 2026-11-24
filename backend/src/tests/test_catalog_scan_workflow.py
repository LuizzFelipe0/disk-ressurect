import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.deep_scan.entities import CarvingCheckpoint
from application.workflows.catalog_scan import CatalogScanWorkflow


def make_report(partition_offset, size_bytes=4096):
    disk = SimpleNamespace(
        number=2,
        model="Synthetic disk",
        size_bytes=size_bytes,
        serial_number="synthetic-2",
    )
    coverage = SimpleNamespace(
        bytes_read=size_bytes,
        bytes_requested=size_bytes,
        bytes_read_total=size_bytes,
        issues=(),
        intervals_as_objects=lambda: (),
    )
    return {
        "disk": disk,
        "coverage": coverage,
        "capacity_mismatch": False,
        "unsupported_filesystems": (),
        "ntfs_checks": (),
        "partition_table_checks": ({"valid": True},),
        "mbr_signature_found": True,
        "partitions": (),
        "filesystem_signatures": (),
        "orphan_records_by_partition": {partition_offset: {"orphan-1": object()}},
        "content_carving_ranges_by_partition": {
            partition_offset: ((1024, 2048),),
        },
        "content_carving_ranges_truncated_by_partition": {partition_offset: True},
        "uncertain_content_carving_ranges_by_partition": {
            partition_offset: {"bitmapUnobserved": ((2048, 3072),)},
        },
        "uncertain_content_carving_ranges_truncated_by_partition": {
            partition_offset: {"bitmapUnobserved": True},
        },
    }


def make_checkpoint(bytes_scanned):
    return CarvingCheckpoint(
        "a" * 64,
        0,
        1024 + bytes_scanned,
        4096,
        512,
        "synthetic-profile",
        bytes_scanned=bytes_scanned,
    )


class RecordingDiscovery:
    def __init__(self, events, report, checkpoint=None):
        self.events = events
        self.report = report
        self.checkpoint = checkpoint
        self.disk = SimpleNamespace(number=2)
        self.validation_kwargs = None

    def validate_disk(self, *args, **kwargs):
        self.events.append("audit")
        self.validation_kwargs = kwargs
        args[1](4, 8, "audit progress")
        return self.report

    def get_disk(self, disk_number):
        self.events.append("get_disk")
        self.assert_disk_number = disk_number
        return self.disk

    def load_carving_checkpoint(self, disk, volume):
        self.events.append("load_checkpoint")
        return self.checkpoint

    def save_carving_checkpoint(self, disk, volume, checkpoint):
        self.events.append("save_checkpoint")
        self.saved_checkpoint = checkpoint
        return checkpoint


class CatalogScanWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.volume = SimpleNamespace(disk_number=2, partition_offset=512)
        self.report = make_report(self.volume.partition_offset)
        self.resume_checkpoint = make_checkpoint(0)
        self.discovery = RecordingDiscovery(
            self.events, self.report, self.resume_checkpoint,
        )

    def test_audits_hands_off_evidence_loads_checkpoint_then_builds_catalog(self):
        snapshot = object()
        progress_events = []
        phase_events = []

        class CatalogService:
            def build(inner_self, volume, progress_callback, **kwargs):
                self.events.append("catalog")
                self.assertIs(volume, self.volume)
                self.assertEqual({"orphan-1"}, set(kwargs["precomputed_orphans"]))
                self.assertEqual(((1024, 2048),), kwargs["precomputed_carving_ranges"])
                self.assertTrue(kwargs["carving_ranges_truncated"])
                self.assertEqual(
                    {"bitmapUnobserved": ((2048, 3072),)},
                    kwargs["precomputed_uncertain_carving_ranges"],
                )
                self.assertEqual(
                    {"bitmapUnobserved": True},
                    kwargs["uncertain_carving_ranges_truncated"],
                )
                progress_callback("catalog-progress")
                kwargs["phase_callback"]("linking", 2, 3)
                kwargs["carving_checkpoint_callback"](make_checkpoint(10))
                return snapshot

        workflow = CatalogScanWorkflow(
            self.discovery,
            CatalogService(),
            lambda _report: {"coverageStatus": "complete"},
        )
        result = workflow.run(
            self.volume,
            include_orphaned=True,
            force_fresh_validation=True,
            carving_options=SimpleNamespace(scan_budget_gib=1),
            progress_callback=progress_events.append,
            validation_progress_callback=lambda *args: progress_events.append(args),
            phase_callback=lambda *args: phase_events.append(args),
        )

        self.assertEqual(
            ["audit", "get_disk", "load_checkpoint", "catalog", "save_checkpoint"],
            self.events,
        )
        self.assertTrue(self.discovery.validation_kwargs["force_fresh"])
        self.assertEqual(512, self.discovery.validation_kwargs["retain_orphans_for_offset"])
        self.assertEqual(1024**3, self.discovery.validation_kwargs["content_carving_range_budget_bytes"])
        self.assertEqual("audit progress", progress_events[0][2])
        self.assertEqual("catalog-progress", progress_events[1])
        self.assertEqual([("linking", 2, 3)], phase_events)
        self.assertIs(snapshot, result.snapshot)
        self.assertEqual("complete", result.validation_summary["coverageStatus"])
        self.assertEqual(10, self.discovery.saved_checkpoint.bytes_scanned)

    def test_catalog_failure_flushes_latest_checkpoint_and_preserves_exception(self):
        failure = OSError("catalog interrupted")

        class FailingCatalogService:
            def build(inner_self, volume, progress_callback, **kwargs):
                self.events.append("catalog")
                kwargs["carving_checkpoint_callback"](make_checkpoint(12))
                raise failure

        workflow = CatalogScanWorkflow(
            self.discovery,
            FailingCatalogService(),
            lambda _report: {"coverageStatus": "complete"},
        )
        with self.assertRaisesRegex(OSError, "catalog interrupted") as raised:
            workflow.run(
                self.volume,
                include_orphaned=True,
                force_fresh_validation=False,
                carving_options=SimpleNamespace(scan_budget_gib=1),
                progress_callback=lambda _event: None,
                validation_progress_callback=lambda *_args: None,
                phase_callback=lambda *_args: None,
            )

        self.assertIs(failure, raised.exception)
        self.assertEqual(
            ["audit", "get_disk", "load_checkpoint", "catalog", "save_checkpoint"],
            self.events,
        )
        self.assertEqual(12, self.discovery.saved_checkpoint.bytes_scanned)
        self.assertNotIn("force_fresh", self.discovery.validation_kwargs)

    def test_audit_failure_is_reported_as_inconclusive_and_catalog_still_builds(self):
        class FailingDiscovery(RecordingDiscovery):
            def validate_disk(inner_self, *args, **kwargs):
                self.events.append("audit")
                raise RuntimeError("audit unavailable")

        class PlainCatalogService:
            def build(inner_self, volume, progress_callback, **kwargs):
                self.events.append("catalog")
                return "snapshot"

        discovery = FailingDiscovery(self.events, self.report)
        result = CatalogScanWorkflow(
            discovery,
            PlainCatalogService(),
            lambda _report: {"coverageStatus": "complete"},
        ).run(
            self.volume,
            include_orphaned=True,
            force_fresh_validation=False,
            carving_options=SimpleNamespace(scan_budget_gib=1),
            progress_callback=lambda _event: None,
            validation_progress_callback=lambda *_args: None,
            phase_callback=lambda *_args: None,
        )

        self.assertEqual(["audit", "catalog"], self.events)
        self.assertEqual("inconclusive", result.validation_summary["assessment"])
        self.assertEqual("RuntimeError: audit unavailable", result.validation_summary["validationError"])


if __name__ == "__main__":
    unittest.main()
