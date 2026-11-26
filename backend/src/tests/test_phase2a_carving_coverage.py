"""Synthetic coverage experiment for bounded content-carving scans."""

import hashlib
import inspect
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from application.workflows.catalog_scan import CatalogScanWorkflow
from infrastructure.carving.content_carver import RawContentCarver
from infrastructure.persistence.deep_scan_repository import JsonDeepScanRepository
from modules.disk.entities import NTFSVolume
from modules.storage.entities import PhysicalDisk
from test_content_carver import jpeg


SCAN_RANGES = ((0, 8192),)
SCAN_BUDGET = 2048
CHUNK_SIZE = 512


class InstrumentedImage:
    """In-memory reader that separates discovery, validation and restore I/O."""

    def __init__(self, data, *, fail_at=None):
        self.data = bytearray(data)
        self.size = len(data)
        self.size_bytes = len(data)
        self.bytes_per_sector = 512
        self.number = 0
        self.model = "Synthetic source"
        self.serial_number = "phase2a-fixture"
        self.fail_at = fail_at
        self.reads = []

    def read_at(self, offset, size):
        frame = inspect.currentframe().f_back
        caller = frame.f_code.co_name
        if caller == "scan":
            stage = "discovery"
        else:
            parent = frame
            stage = "candidate_validation"
            while parent is not None:
                if parent.f_code.co_name == "_restore_candidates":
                    stage = "checkpoint_restore"
                    break
                parent = parent.f_back

        if self.fail_at is not None and offset <= self.fail_at < offset + size:
            self.reads.append((stage, offset, size, "error"))
            raise OSError(f"Synthetic read failure at {self.fail_at:#x}")

        self.reads.append((stage, offset, size, "ok"))
        return bytes(self.data[offset:offset + size])


def fixture_image():
    image = InstrumentedImage(bytes(8192))
    expected = {}
    for offset, payload in (
        (128, b"before-budget"),
        (511, b"crosses-512-byte-chunk"),
        (2048, b"at-budget-frontier"),
        (2560, b"after-frontier"),
        (5000, b"beyond-second-budget"),
    ):
        content = jpeg(payload)
        image.data[offset:offset + len(content)] = content
        expected[offset] = hashlib.sha256(content).hexdigest()
    image.data[1200:1210] = b"\xff\xd8\xffgarbage"
    return image, expected


def interval_union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def interval_bytes(intervals):
    return sum(end - start for start, end in interval_union(intervals))


def scan(image, checkpoint=None):
    image.reads.clear()
    merged_ranges = RawContentCarver._merge_ranges(SCAN_RANGES, image.size)
    checkpoint_accepted = checkpoint is not None and RawContentCarver._checkpoint_matches(
        checkpoint,
        merged_ranges,
        image.size,
        image.bytes_per_sector,
        RawContentCarver._range_fingerprint(merged_ranges, image.size),
        RawContentCarver._scan_profile(),
    )
    result = RawContentCarver(
        image,
        chunk_size=CHUNK_SIZE,
        max_scan_bytes=SCAN_BUDGET,
        max_file_bytes=1024,
        max_total_file_bytes=8192,
        max_candidate_read_bytes=8192,
        max_candidate_read_bytes_per_format=8192,
        max_files=32,
    ).scan(SCAN_RANGES, resume_checkpoint=checkpoint)
    reads = {
        stage: [(start, start + size) for read_stage, start, size, status in image.reads
                if read_stage == stage and status == "ok"]
        for stage in ("discovery", "candidate_validation", "checkpoint_restore")
    }
    restored_offsets = (
        {item.offset for item in checkpoint.candidates} if checkpoint_accepted else set()
    )
    new_offsets = {item.offset for item in result.files} - restored_offsets
    discovered = sum(item.candidates_examined for item in result.format_stats)
    newly_published = len(new_offsets)
    return result, {
        "discovery_intervals": interval_union(reads["discovery"]),
        "discovery_read_bytes": sum(end - start for start, end in reads["discovery"]),
        "candidate_validation_intervals": interval_union(reads["candidate_validation"]),
        "candidate_validation_read_bytes": sum(
            end - start for start, end in reads["candidate_validation"]
        ),
        "checkpoint_restore_intervals": interval_union(reads["checkpoint_restore"]),
        "checkpoint_restore_read_bytes": sum(
            end - start for start, end in reads["checkpoint_restore"]
        ),
        "candidates_discovered": discovered,
        "candidates_rejected": max(0, discovered - newly_published),
        "new_candidates_published": newly_published,
        "published_offsets": sorted(item.offset for item in result.files),
        "scan_limit_reached": result.scan_limit_reached,
        "checkpoint_accepted": checkpoint_accepted,
        "next_offset": result.checkpoint.next_offset if result.checkpoint else None,
        "candidate_restore_bytes_read": result.candidate_restore_bytes_read,
    }


def persist_and_reload_physical_checkpoint(checkpoint):
    disk = PhysicalDisk(0, "Synthetic physical source", 8192, "phase2a-fixture")
    volume = NTFSVolume(0, 1, 0, 8192, 512, 4096, 1024, 0, 0, ())
    with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
        path = os.path.join(directory, "carving-checkpoint.json")
        mapper = lambda _path: {1}  # C: is the confirmed safe work disk.
        JsonDeepScanRepository(path, disk_mapper=mapper).save_carving_checkpoint(
            disk, volume, checkpoint,
        )
        return JsonDeepScanRepository(path, disk_mapper=mapper).load_carving_checkpoint(
            disk, volume,
        )


def raw_catalog_rebuilds(image):
    class FakeSourceFactory:
        def get_source(self, _source_id):
            return SimpleNamespace(source_id="raw-image:synthetic")

    class FakeValidation:
        def validate_source(self, *_args, **_kwargs):
            return {
                "content_carving_ranges_by_partition": {4096: SCAN_RANGES},
                "content_carving_ranges_truncated_by_partition": {4096: False},
            }

        @staticmethod
        def summary(_report):
            return {"coverageStatus": "complete"}

    class FakeCheckpointService:
        load_calls = 0
        save_calls = 0

        def load_carving_checkpoint(self, *_args):
            self.load_calls += 1
            return None

        def save_carving_checkpoint(self, *_args):
            self.save_calls += 1

    class FakeBuilder:
        source_factory = FakeSourceFactory()

        def __init__(self):
            self.checkpoints = []
            self.results = []

        def build(self, _volume, *_args, carving_checkpoint=None,
                  carving_checkpoint_callback=None, **_kwargs):
            self.checkpoints.append(carving_checkpoint)
            result, metrics = scan(image, carving_checkpoint)
            self.results.append((result, metrics))
            if carving_checkpoint_callback is not None:
                carving_checkpoint_callback(result.checkpoint)
            return SimpleNamespace()

    image.reads.clear()
    service = FakeCheckpointService()
    builder = FakeBuilder()
    workflow = CatalogScanWorkflow(
        SimpleNamespace(), service, FakeValidation(), builder,
    )
    volume = SimpleNamespace(
        source_id="raw-image:synthetic", partition_offset=4096, disk_number=-1,
    )
    for _ in range(2):
        workflow.run(
            volume,
            include_orphaned=True,
            force_fresh_validation=True,
            carving_options=SimpleNamespace(scan_budget_gib=1),
            progress_callback=None,
            validation_progress_callback=None,
            phase_callback=None,
        )
    return service, builder


def run_experiment():
    image, expected = fixture_image()
    first, first_metrics = scan(image)
    persisted = persist_and_reload_physical_checkpoint(first.checkpoint)
    second_valid, valid_metrics = scan(image, persisted)
    second_missing, missing_metrics = scan(image)
    invalid_checkpoint = replace(first.checkpoint, scan_profile="deliberately-invalid")
    second_invalid, invalid_metrics = scan(image, invalid_checkpoint)
    raw_service, raw_builder = raw_catalog_rebuilds(image)

    return {
        "eligible_intervals": SCAN_RANGES,
        "expected_hashes": expected,
        "first_run": (first, first_metrics),
        "valid_checkpoint_run": (second_valid, valid_metrics),
        "missing_checkpoint_run": (second_missing, missing_metrics),
        "invalid_checkpoint_run": (second_invalid, invalid_metrics),
        "raw_checkpoint_load_calls": raw_service.load_calls,
        "raw_checkpoint_save_calls": raw_service.save_calls,
        "raw_checkpoints_passed": raw_builder.checkpoints,
        "raw_runs": raw_builder.results,
    }


class Phase2ACarvingCoverageTests(unittest.TestCase):
    def test_two_scans_measure_repeat_or_resume_and_hash_expected_files(self):
        experiment = run_experiment()
        expected = experiment["expected_hashes"]
        first, first_metrics = experiment["first_run"]
        valid, valid_metrics = experiment["valid_checkpoint_run"]
        missing, missing_metrics = experiment["missing_checkpoint_run"]
        invalid, invalid_metrics = experiment["invalid_checkpoint_run"]

        self.assertEqual(first_metrics["discovery_intervals"], ((0, 2048),))
        self.assertEqual(first_metrics["published_offsets"], [128, 511])
        self.assertEqual(first_metrics["candidates_discovered"], 3)
        self.assertEqual(first_metrics["candidates_rejected"], 1)
        self.assertTrue(first_metrics["scan_limit_reached"])
        self.assertEqual(first.checkpoint.next_offset, SCAN_BUDGET)

        expected_first = {128, 511}
        self.assertEqual(
            {item.offset: hashlib.sha256(item.data).hexdigest() for item in first.files},
            {offset: expected[offset] for offset in expected_first},
        )
        self.assertEqual(valid_metrics["discovery_intervals"], ((2048, 4096),))
        self.assertEqual(valid_metrics["published_offsets"], [128, 511, 2048, 2560])
        self.assertEqual(valid_metrics["candidate_restore_bytes_read"],
                         valid_metrics["checkpoint_restore_read_bytes"])
        self.assertEqual(
            {item.offset: hashlib.sha256(item.data).hexdigest() for item in valid.files},
            {offset: expected[offset] for offset in (128, 511, 2048, 2560)},
        )
        self.assertEqual(missing_metrics["discovery_intervals"], ((0, 2048),))
        self.assertEqual(invalid_metrics["discovery_intervals"], ((0, 2048),))
        self.assertEqual(missing_metrics["published_offsets"], [128, 511])
        self.assertEqual(invalid_metrics["published_offsets"], [128, 511])
        self.assertTrue(valid_metrics["checkpoint_accepted"])
        self.assertFalse(invalid_metrics["checkpoint_accepted"])
        self.assertEqual(missing.bytes_scanned, SCAN_BUDGET)
        self.assertEqual(invalid.bytes_scanned, SCAN_BUDGET)

        valid_union = interval_union(
            first_metrics["discovery_intervals"] + valid_metrics["discovery_intervals"],
        )
        repeated_union = interval_union(
            first_metrics["discovery_intervals"] + missing_metrics["discovery_intervals"],
        )
        self.assertEqual(interval_bytes(valid_union), 4096)
        self.assertEqual(interval_bytes(repeated_union), SCAN_BUDGET)
        self.assertEqual(interval_bytes(SCAN_RANGES) - interval_bytes(valid_union), 4096)
        self.assertEqual(interval_bytes(SCAN_RANGES) - interval_bytes(repeated_union), 6144)

    def test_new_raw_catalog_builds_do_not_load_or_save_persistent_carving_checkpoints(self):
        experiment = run_experiment()
        service = SimpleNamespace(
            load_calls=experiment["raw_checkpoint_load_calls"],
            save_calls=experiment["raw_checkpoint_save_calls"],
        )
        self.assertEqual(service.load_calls, 0)
        self.assertEqual(service.save_calls, 0)
        self.assertEqual(experiment["raw_checkpoints_passed"], [None, None])
        self.assertEqual(
            [item[1]["discovery_intervals"] for item in experiment["raw_runs"]],
            [((0, 2048),), ((0, 2048),)],
        )

    def test_synthetic_read_error_aborts_without_claiming_budget_completion(self):
        image, _expected = fixture_image()
        image.fail_at = 1024
        with self.assertRaisesRegex(OSError, "Synthetic read failure"):
            scan(image)
        self.assertEqual(
            interval_union((start, start + size) for stage, start, size, status in image.reads
                           if stage == "discovery" and status == "ok"),
            ((0, 1024),),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
