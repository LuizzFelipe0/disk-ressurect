"""Session-scoped raw-carving integration tests using only synthetic readers."""

import hashlib
import os
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from application.session import RecoverySession
from application.workflows.catalog_scan import CatalogScanWorkflow
from infrastructure.carving.content_carver import RawContentCarver
from infrastructure.filesystems.ntfs.catalog_builder import CatalogBuilder
from modules.catalog.dto import CarvingOptionsDto
from modules.disk.entities import NTFSVolume
from modules.storage.entities import StorageSource
from test_content_carver import jpeg
from helpers import make_recovery_workflow


IMAGE_SIZE = 8192
SCAN_BUDGET_BYTES = 2048


class SyntheticRawReader:
    def __init__(self, factory, source, *, fail_at=None):
        self.factory = factory
        self.source = source
        self.data = factory.data
        self.size = len(self.data)
        self.size_bytes = self.size
        self.bytes_per_sector = source.bytes_per_sector
        self.fail_at = fail_at
        self.closed = False
        self.read_events = []

    def read_at(self, offset, size):
        caller = sys._getframe(1).f_code.co_name
        stage = "discovery" if caller == "scan" else "validation"
        if self.fail_at is not None and offset <= self.fail_at < offset + size:
            event = (stage, offset, size, "error")
            self.factory.read_events.append(event)
            self.read_events.append(event)
            raise OSError(f"Synthetic image read failure at {self.fail_at:#x}")
        event = (stage, offset, size, "ok")
        self.factory.read_events.append(event)
        self.read_events.append(event)
        if self.factory.block_discovery:
            self.factory.block_discovery = False
            self.factory.read_entered.set()
            if not self.factory.release_read.wait(20):
                raise TimeoutError("Synthetic read release timed out")
        return bytes(self.data[offset:offset + size])

    def close(self):
        self.closed = True


class SyntheticRawSourceFactory:
    def __init__(self, data, source_id="raw-image:synthetic-v1"):
        self.data = bytearray(data)
        self.source = StorageSource(
            source_id=source_id,
            source_type="raw_image",
            display_name="Synthetic image",
            size_bytes=len(self.data),
            bytes_per_sector=512,
            locator="synthetic-fixture",
        )
        self.read_events = []
        self.readers = []
        self.fail_at = None
        self.block_discovery = False
        self.read_entered = threading.Event()
        self.release_read = threading.Event()
        self.open_lock = threading.Lock()
        self.open_count = 0

    def get_source(self, source_id):
        if source_id != self.source.source_id:
            raise ValueError("Synthetic source identity mismatch")
        return self.source

    def __call__(self, source_id):
        return self.get_source(source_id)

    def open_reader(self, source):
        if source.source_id != self.source.source_id:
            raise OSError("Synthetic source changed")
        reader = SyntheticRawReader(self, source, fail_at=self.fail_at)
        self.readers.append(reader)
        with self.open_lock:
            self.open_count += 1
        return reader

    def replace_image(self, data, source_id):
        self.data = bytearray(data)
        self.source = replace(
            self.source, source_id=source_id, size_bytes=len(self.data),
        )


class SyntheticValidationService:
    def __init__(self, source_factory, ranges=None, *, ranges_truncated=False,
                 uncertain_ranges=None):
        self.source_factory = source_factory
        self.ranges = tuple(ranges or ((0, len(source_factory.data)),))
        self.ranges_truncated = ranges_truncated
        self.uncertain_ranges = uncertain_ranges
        self.validation_calls = 0
        self.validation_event = None

    def validate_source(self, source, *_args, retain_orphans_for_offset, **_kwargs):
        if source.source_id != self.source_factory.source.source_id:
            raise OSError("Synthetic source changed during validation")
        self.validation_calls += 1
        if self.validation_event is not None:
            self.validation_event.set()
        report = {
            "orphan_records_by_partition": {retain_orphans_for_offset: {}},
            "content_carving_ranges_by_partition": {
                retain_orphans_for_offset: self.ranges,
            },
            "content_carving_ranges_truncated_by_partition": {
                retain_orphans_for_offset: self.ranges_truncated,
            },
        }
        if self.uncertain_ranges is not None:
            report["uncertain_content_carving_ranges_by_partition"] = {
                retain_orphans_for_offset: self.uncertain_ranges,
            }
        return report

    @staticmethod
    def summary(_report):
        return {"coverageStatus": "complete"}


class EmptyTreeBuilder:
    def __init__(self, *_args, **_kwargs):
        self.nodes = {}
        self.root_nodes = []
        self.parent_reference_issue_count = 0

    def build(self, **_kwargs):
        return self.nodes

    def inject_ghosts(self, _ghosts):
        return None

    def release_source_tree(self):
        return None


class SessionCappedCarver(RawContentCarver):
    """Keep the production scan method while reducing its test-only byte budget."""

    scan_budget_bytes = SCAN_BUDGET_BYTES
    candidate_count_cap = None

    def __init__(self, disk, **kwargs):
        kwargs["chunk_size"] = 512
        kwargs["max_scan_bytes"] = min(
            int(kwargs.get("max_scan_bytes", self.scan_budget_bytes)),
            self.scan_budget_bytes,
        )
        if self.candidate_count_cap is not None:
            kwargs["max_files"] = self.candidate_count_cap
        super().__init__(disk, **kwargs)


def make_image(files=(), size=IMAGE_SIZE):
    data = bytearray(size)
    expected = {}
    for offset, payload in files:
        content = jpeg(payload)
        if offset + len(content) > size:
            raise ValueError("Synthetic candidate exceeds the image")
        data[offset:offset + len(content)] = content
        expected[offset] = hashlib.sha256(content).hexdigest()
    return data, expected


def make_volume(source_id, size=IMAGE_SIZE, *, partition_offset=0, partition_number=1):
    return NTFSVolume(
        -1, partition_number, partition_offset, size, 512, 4096, 1024,
        0, 0, (), "Synthetic NTFS", False, source_id,
    )


class RawCatalogHarness:
    def __init__(self, image_data, *, source_id="raw-image:synthetic-v1", ranges=None,
                 ranges_truncated=False, uncertain_ranges=None, session=None):
        self.source_factory = SyntheticRawSourceFactory(image_data, source_id)
        self.validation = SyntheticValidationService(
            self.source_factory, ranges, ranges_truncated=ranges_truncated,
            uncertain_ranges=uncertain_ranges,
        )
        self.session = session or RecoverySession()
        self.builder = CatalogBuilder(source_factory=self.source_factory)
        self.workflow = CatalogScanWorkflow(
            None, None, self.validation, self.builder, session=self.session,
        )
        self.volume = make_volume(source_id, len(image_data))
        self.options = CarvingOptionsDto(
            scan_budget_gib=1,
            max_files=256,
            max_retained_mib=128,
            max_candidate_read_mib_per_format=256,
        )

    def build(self):
        with patch(
            "infrastructure.filesystems.ntfs.catalog_builder.TreeBuilder",
            EmptyTreeBuilder,
        ), patch(
            "infrastructure.filesystems.ntfs.catalog_builder.RawContentCarver",
            SessionCappedCarver,
        ):
            return self.build_without_patches()

    def build_without_patches(self):
        outcome = self.workflow.run(
            self.volume,
            include_orphaned=True,
            force_fresh_validation=True,
            carving_options=self.options,
            progress_callback=lambda *_args: None,
            validation_progress_callback=lambda *_args: None,
            phase_callback=lambda *_args: None,
        )
        self.session.set_catalog(outcome.snapshot)
        return outcome

    def carved_candidates(self, snapshot):
        result = {}
        for node in snapshot.catalog.nodes.values():
            candidate = node.candidate
            if candidate is None or "content_carving" not in candidate.discovery_methods:
                continue
            offset = int(node.name.split("_")[1].split(".")[0], 16)
            result[offset] = (node.node_id, candidate.content_reference.sha256)
        return result

    def checkpoint(self, ranges=None):
        source = self.source_factory.source
        selected_ranges = tuple(ranges or self.validation.ranges)
        identity = self.workflow._raw_checkpoint_identity(
            source, self.volume, selected_ranges, self.validation.ranges_truncated,
            self.options, self.builder.carving_checkpoint_profile(),
        )
        owner = self.workflow._raw_checkpoint_owner(self.volume)
        return self.session.load_raw_carving_checkpoint(owner, identity)

    def discovery_intervals(self, reader):
        intervals = sorted(
            (start, start + size)
            for stage, start, size, status in reader.read_events
            if stage == "discovery" and status == "ok"
        )
        merged = []
        for start, end in intervals:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return tuple(merged)


class RawCarvingSessionResumeTests(unittest.TestCase):
    def setUp(self):
        SessionCappedCarver.scan_budget_bytes = SCAN_BUDGET_BYTES
        SessionCappedCarver.candidate_count_cap = None

    def test_four_passes_complete_scope_and_fifth_reuses_extractable_catalog(self):
        data, expected = make_image((
            (128, b"before-first-budget"),
            (511, b"crosses-chunk-boundary"),
            (2048, b"first-budget-frontier"),
            (3072, b"after-first-budget"),
            (4096, b"second-budget-frontier"),
            (5000, b"after-second-budget"),
            (7000, b"last-pass-candidate"),
        ))
        harness = RawCatalogHarness(data)
        snapshots = []
        memories = []
        intervals = []
        for _ in range(4):
            result = harness.build()
            snapshots.append(result.snapshot)
            harness.session.set_catalog(result.snapshot)
            memories.append(harness.session.raw_carving_checkpoint_memory_bytes)
            intervals.append(harness.discovery_intervals(harness.source_factory.readers[-1]))

        found = [harness.carved_candidates(snapshot) for snapshot in snapshots]
        self.assertEqual(intervals, [
            ((0, 2048),), ((2048, 4096),), ((4096, 6144),), ((6144, 8192),),
        ])
        self.assertEqual([sorted(items) for items in found], [
            [128, 511], [128, 511, 2048, 3072],
            [128, 511, 2048, 3072, 4096, 5000],
            [128, 511, 2048, 3072, 4096, 5000, 7000],
        ])
        self.assertEqual(memories[:3], sorted(memories[:3]))
        self.assertEqual(memories[-1], 0)
        self.assertEqual(len(set(memories[:-1])), 1)
        self.assertEqual(harness.session.raw_catalog_candidate_count, 7)
        for offset, expected_hash in expected.items():
            for catalog in found:
                if offset in catalog:
                    self.assertEqual(catalog[offset][1], expected_hash)
        for earlier, later in zip(found, found[1:]):
            for offset in earlier:
                self.assertEqual(later[offset][0], earlier[offset][0])
        for result in snapshots[:3]:
            self.assertEqual(result.content_carving_summary["stopReason"], "budget_exhausted")
        self.assertEqual(snapshots[3].content_carving_summary["stopReason"], "scope_complete")
        self.assertIsNone(harness.checkpoint())
        unique_coverage = {(0, 6144), (6144, 8192)}
        self.assertEqual(sum(end - start for start, end in unique_coverage), IMAGE_SIZE)

        candidates = [
            node for node in snapshots[3].catalog.nodes.values()
            if node.candidate is not None
            and "content_carving" in node.candidate.discovery_methods
        ]
        recovered_content = {
            node.candidate.content_reference.reference_id:
                harness.builder.content_reference_store.resolve(
                    node.candidate.content_reference.reference_id,
                )[2].record.resident_data
            for node in candidates
        }

        class ResidentCandidateReader:
            def iter_chunks(self, reference):
                yield recovered_content[reference.reference_id]

        class SafeSyntheticOutputGuard:
            def validate_source(self, _output_directory, _source):
                return None

        workflow = make_recovery_workflow(
            output_guard=SafeSyntheticOutputGuard(),
            content_reader_factory=lambda _source: ResidentCandidateReader(),
        )
        with tempfile.TemporaryDirectory() as output_directory:
            extraction = workflow.extract_selection(
                snapshots[3], candidates, output_directory, {".jpg"},
            )
            self.assertEqual(extraction.recovered_count, len(expected))
            for result in extraction.results:
                recovered_path = Path(output_directory, result.path)
                actual_hash = hashlib.sha256(recovered_path.read_bytes()).hexdigest()
                expected_hash = next(
                    digest for candidate_id, digest in found[3].values()
                    if candidate_id == result.node.candidate.candidate_id
                )
                self.assertEqual(actual_hash, expected_hash)

        reader_count = harness.source_factory.open_count
        fifth = harness.build()
        self.assertIs(fifth.snapshot, snapshots[3])
        self.assertEqual(fifth.snapshot.content_carving_summary["stopReason"], "scope_complete")
        self.assertEqual(harness.source_factory.open_count, reader_count)
        self.assertEqual(harness.session.raw_carving_checkpoint_memory_bytes, 0)
        self.assertEqual(harness.carved_candidates(fifth.snapshot), found[3])

    def test_signature_crossing_budget_frontier_uses_saved_carry_without_discovery_reread(self):
        data, expected = make_image(((2047, b"crosses-budget-frontier"),))
        self.assertEqual(set(expected), {2047})
        harness = RawCatalogHarness(data)
        first = harness.build().snapshot
        first_reader = harness.source_factory.readers[-1]
        self.assertEqual(harness.carved_candidates(first), {})

        second = harness.build().snapshot
        second_reader = harness.source_factory.readers[-1]
        candidates = harness.carved_candidates(second)
        self.assertEqual(set(candidates), {2047})
        self.assertEqual(candidates[2047][1], expected[2047])
        self.assertTrue(candidates[2047][0])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(harness.discovery_intervals(first_reader), ((0, 2048),))
        self.assertEqual(harness.discovery_intervals(second_reader), ((2048, 4096),))
        self.assertTrue(any(
            stage == "validation" and start <= 2047 < start + size
            for stage, start, size, status in harness.source_factory.read_events
            if status == "ok"
        ))

    def test_signature_carry_survives_read_error_at_budget_frontier(self):
        data, expected = make_image(((2047, b"crosses-frontier-after-error"),))
        harness = RawCatalogHarness(data)
        harness.build()
        checkpoint_before_error = harness.checkpoint()
        self.assertEqual(checkpoint_before_error.next_offset, 2048)
        self.assertIn(b"\xff", checkpoint_before_error.signature_carry)

        harness.source_factory.fail_at = 2048
        with self.assertRaisesRegex(OSError, "Synthetic image read failure"):
            harness.build()
        self.assertEqual(harness.checkpoint(), checkpoint_before_error)

        harness.source_factory.fail_at = None
        recovered = harness.build().snapshot
        candidates = harness.carved_candidates(recovered)
        self.assertEqual(set(candidates), {2047})
        self.assertEqual(candidates[2047][1], expected[2047])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            harness.discovery_intervals(harness.source_factory.readers[-1]),
            ((2048, 4096),),
        )

    def test_low_confidence_candidates_survive_resume_with_path_and_allocation_evidence(self):
        data, expected = make_image(((128, b"trusted"), (8192, b"low-confidence")), 12288)
        harness = RawCatalogHarness(
            data,
            ranges=((0, 2048), (4096, 8192)),
            uncertain_ranges={"bitmapUnobserved": ((8192, 10240),)},
        )
        first = harness.build().snapshot
        first_low = next(
            node for node in first.catalog.nodes.values()
            if node.candidate is not None and "LowConfidence" in node.full_path
        )
        first_low_path = first_low.full_path
        first_low_status = first_low.properties["clusterAllocationStatus"]

        second = harness.build().snapshot
        second_low = next(
            node for node in second.catalog.nodes.values()
            if node.candidate is not None and "LowConfidence" in node.full_path
        )
        self.assertEqual(second_low.node_id, first_low.node_id)
        self.assertEqual(second_low.full_path, first_low_path)
        self.assertEqual(
            second_low.properties["clusterAllocationStatus"],
            first_low_status,
        )
        self.assertEqual(
            harness.builder.content_reference_store.resolve(
                second_low.candidate.content_reference.reference_id,
            )[2].record.resident_data,
            harness.builder.content_reference_store.resolve(
                first_low.candidate.content_reference.reference_id,
            )[2].record.resident_data,
        )
        self.assertEqual(len(harness.carved_candidates(second)), 2)
        self.assertEqual(
            second_low.candidate.content_reference.sha256,
            expected[8192],
        )

    def test_source_volume_ranges_and_candidate_profile_changes_invalidate_checkpoint(self):
        data, _expected = make_image(((128, b"identity-bound-candidate"),))
        scenarios = ("source", "truncation", "content_change", "volume", "ranges", "profile", "options")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                harness = RawCatalogHarness(data)
                harness.build()
                old_volume = harness.volume
                selected_ranges = harness.validation.ranges
                expected_start = 0

                if scenario == "source":
                    harness.source_factory.replace_image(data, "raw-image:replacement")
                    harness.volume = replace(old_volume, source_id="raw-image:replacement")
                elif scenario == "truncation":
                    shorter = bytes(data[:4096])
                    harness.source_factory.replace_image(shorter, "raw-image:truncated")
                    harness.volume = replace(
                        old_volume, source_id="raw-image:truncated", partition_size=4096,
                    )
                    harness.validation.ranges = ((0, 4096),)
                    selected_ranges = harness.validation.ranges
                elif scenario == "content_change":
                    changed = bytearray(data)
                    changed[128:128 + len(jpeg(b"changed-content"))] = jpeg(b"changed-content")
                    harness.source_factory.replace_image(changed, "raw-image:changed-stat-identity")
                    harness.volume = replace(old_volume, source_id="raw-image:changed-stat-identity")
                elif scenario == "volume":
                    harness.volume = replace(old_volume, partition_size=IMAGE_SIZE - 512)
                elif scenario == "ranges":
                    harness.validation.ranges = ((1024, IMAGE_SIZE),)
                    selected_ranges = harness.validation.ranges
                    expected_start = 1024
                elif scenario == "profile":
                    harness.builder.carving_checkpoint_profile = lambda: {
                        "signatureProfile": "changed-profile",
                    }
                elif scenario == "options":
                    harness.options = replace(harness.options, max_files=512)

                harness.build()
                discovery = harness.discovery_intervals(harness.source_factory.readers[-1])
                self.assertTrue(discovery)
                self.assertEqual(discovery[0][0], expected_start)

    def test_read_error_preserves_previous_generation_then_retry_repeats_uncommitted_range(self):
        data, _expected = make_image((
            (128, b"before-error"), (2048, b"after-resume"), (3072, b"fault-frontier"),
        ))
        harness = RawCatalogHarness(data)
        harness.build()
        first_snapshot = harness.session.require_snapshot()
        first_checkpoint = harness.checkpoint()
        self.assertEqual(first_checkpoint.next_offset, 2048)

        harness.source_factory.fail_at = 3072
        with self.assertRaisesRegex(OSError, "Synthetic image read failure"):
            harness.build()
        partial_checkpoint = harness.checkpoint()
        self.assertEqual(partial_checkpoint, first_checkpoint)
        self.assertIs(harness.session.require_snapshot(), first_snapshot)

        harness.source_factory.fail_at = None
        harness.source_factory.read_events.clear()
        harness.build()
        self.assertEqual(
            harness.discovery_intervals(harness.source_factory.readers[-1]),
            ((2048, 4096),),
        )

    def test_small_cursor_checkpoint_limit_allows_progress_without_candidate_manifest_growth(self):
        data, _expected = make_image((
            (128, b"first"), (2048, b"second"), (4096, b"third"),
        ))
        harness = RawCatalogHarness(data)
        first = harness.build()
        first_checkpoint = harness.checkpoint()
        checkpoint_bytes = harness.session.raw_carving_checkpoint_memory_bytes
        self.assertEqual(first_checkpoint.candidates, ())
        harness.session.MAX_RAW_CARVING_CHECKPOINT_BYTES = checkpoint_bytes + 32

        second = harness.build()
        second_checkpoint = harness.checkpoint()
        third = harness.build()
        third_checkpoint = harness.checkpoint()

        self.assertEqual(first_checkpoint.candidates, ())
        self.assertEqual(second_checkpoint.candidates, ())
        self.assertEqual(third_checkpoint.candidates, ())
        self.assertEqual(second_checkpoint.next_offset, 4096)
        self.assertEqual(third_checkpoint.next_offset, 6144)
        self.assertEqual(
            harness.session.raw_carving_checkpoint_memory_bytes,
            checkpoint_bytes,
        )
        self.assertEqual(harness.session.raw_catalog_candidate_count, 3)
        self.assertGreater(harness.session.raw_catalog_retained_bytes, 0)
        self.assertEqual(
            harness.discovery_intervals(harness.source_factory.readers[-1]),
            ((4096, 6144),),
        )

    def test_session_candidate_limit_stops_with_usable_catalog_and_no_repeat_attempt(self):
        data, _expected = make_image((
            (128, b"first"), (2048, b"second"), (4096, b"third"),
        ))
        harness = RawCatalogHarness(data)
        harness.session.MAX_RAW_SESSION_CANDIDATES = 1
        first = harness.build()
        self.assertEqual(first.snapshot.content_carving_summary["stopReason"], "session_limit")
        self.assertEqual(harness.session.raw_catalog_candidate_count, 1)
        self.assertEqual(len(harness.carved_candidates(first.snapshot)), 1)
        confirmed_checkpoint = harness.checkpoint()
        read_count = harness.source_factory.open_count

        second = harness.build()
        self.assertIs(second.snapshot, first.snapshot)
        self.assertEqual(second.snapshot.content_carving_summary["stopReason"], "session_limit")
        self.assertEqual(harness.source_factory.open_count, read_count)
        self.assertEqual(harness.checkpoint(), confirmed_checkpoint)

    def test_session_capacity_accounts_for_other_raw_catalogs(self):
        data, _expected = make_image(((128, b"first"),))
        harness = RawCatalogHarness(data)
        harness.session.MAX_RAW_SESSION_CANDIDATES = 3
        harness.session.MAX_RAW_SESSION_RETAINED_BYTES = 4096
        result = harness.build()

        capacity = harness.session.raw_catalog_capacity(("another-volume",))
        self.assertEqual(capacity[0], 2)
        self.assertEqual(
            capacity[1],
            4096 - harness.session.raw_catalog_retained_bytes,
        )
        self.assertEqual(
            harness.session.raw_catalog_candidate_count,
            RecoverySession.raw_catalog_candidate_metrics(result.snapshot)[0],
        )

    def test_session_retained_byte_limit_is_reported_and_does_not_repeat(self):
        data, _expected = make_image(((128, b"first"), (2048, b"second")))
        harness = RawCatalogHarness(data)
        harness.session.MAX_RAW_SESSION_RETAINED_BYTES = len(jpeg(b"first"))
        first = harness.build()
        self.assertEqual(first.snapshot.content_carving_summary["stopReason"], "session_limit")
        self.assertEqual(
            harness.session.raw_catalog_retained_bytes,
            len(jpeg(b"first")),
        )
        read_count = harness.source_factory.open_count

        second = harness.build()
        self.assertIs(second.snapshot, first.snapshot)
        self.assertEqual(harness.source_factory.open_count, read_count)

    def test_failure_after_candidate_incorporation_preserves_generation_and_retries_range(self):
        data, _expected = make_image(((128, b"first"), (2048, b"second")))
        harness = RawCatalogHarness(data)
        first = harness.build()
        checkpoint = harness.checkpoint()
        generation = harness.session.raw_catalog_generation(
            harness.workflow._raw_checkpoint_owner(harness.volume),
            harness.workflow._raw_checkpoint_identity(
                harness.source_factory.source, harness.volume, harness.validation.ranges,
                False, harness.options, harness.builder.carving_checkpoint_profile(),
            ),
        )
        original = harness.builder._to_recovery_catalog

        def incorporate_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("Injected failure after candidate incorporation")

        with patch.object(harness.builder, "_to_recovery_catalog", side_effect=incorporate_then_fail):
            with self.assertRaisesRegex(RuntimeError, "after candidate incorporation"):
                harness.build()

        self.assertIs(harness.session.require_snapshot(), first.snapshot)
        self.assertEqual(harness.checkpoint(), checkpoint)
        self.assertEqual(harness.session.raw_catalog_generation(
            harness.workflow._raw_checkpoint_owner(harness.volume),
            harness.workflow._raw_checkpoint_identity(
                harness.source_factory.source, harness.volume, harness.validation.ranges,
                False, harness.options, harness.builder.carving_checkpoint_profile(),
            ),
        ), generation)
        old_candidate = next(
            node.candidate for node in first.snapshot.catalog.nodes.values()
            if node.candidate is not None
            and "content_carving" in node.candidate.discovery_methods
        )
        _, _, retained_node = harness.builder.content_reference_store.resolve(
            old_candidate.content_reference.reference_id,
        )
        self.assertEqual(
            hashlib.sha256(retained_node.record.resident_data).hexdigest(),
            old_candidate.content_reference.sha256,
        )

        harness.source_factory.read_events.clear()
        retried = harness.build()
        self.assertEqual(
            harness.discovery_intervals(harness.source_factory.readers[-1]),
            ((2048, 4096),),
        )
        self.assertEqual(len(harness.carved_candidates(retried.snapshot)), 2)

    def test_cursor_confirmation_failure_keeps_prior_generation_and_retries(self):
        data, _expected = make_image(((128, b"first"), (2048, b"second")))
        harness = RawCatalogHarness(data)
        first = harness.build()
        checkpoint = harness.checkpoint()
        with patch.object(
            harness.session,
            "commit_raw_catalog_generation",
            side_effect=RuntimeError("Injected cursor confirmation failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "cursor confirmation"):
                harness.build()

        self.assertIs(harness.session.require_snapshot(), first.snapshot)
        self.assertEqual(harness.checkpoint(), checkpoint)
        harness.source_factory.read_events.clear()
        retried = harness.build()
        self.assertEqual(
            harness.discovery_intervals(harness.source_factory.readers[-1]),
            ((2048, 4096),),
        )
        self.assertEqual(len(harness.carved_candidates(retried.snapshot)), 2)

    def test_checkpoint_metadata_limit_failure_preserves_old_generation(self):
        data, _expected = make_image(((128, b"first"), (2048, b"second")))
        harness = RawCatalogHarness(data)
        first = harness.build()
        prior_checkpoint = harness.checkpoint()
        accounted_bytes = harness.session.raw_carving_checkpoint_memory_bytes
        harness.session.MAX_RAW_CARVING_CHECKPOINT_BYTES = accounted_bytes - 1

        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "checkpoint limit reached"):
                harness.build()
            self.assertIs(harness.session.require_snapshot(), first.snapshot)
            self.assertEqual(harness.checkpoint(), prior_checkpoint)
        self.assertEqual(harness.session.raw_catalog_candidate_count, 1)

    def test_raw_flow_never_calls_physical_checkpoint_repository_and_scope_completion_releases_state(self):
        data, _expected = make_image(((128, b"complete-range"),))
        harness = RawCatalogHarness(data, ranges=((0, 1024),))

        class PhysicalRepositoryMustNotBeUsed:
            def load_carving_checkpoint(self, *_args):
                raise AssertionError("Raw scans must not load physical-disk checkpoints")

            def save_carving_checkpoint(self, *_args):
                raise AssertionError("Raw scans must not persist checkpoints to disk")

        harness.workflow.deep_scan_service = PhysicalRepositoryMustNotBeUsed()
        result = harness.build()
        self.assertEqual(result.snapshot.content_carving_summary["stopReason"], "scope_complete")
        self.assertEqual(harness.session.raw_carving_checkpoint_memory_bytes, 0)

    def test_resource_stop_is_distinct_from_budget_and_scope_completion(self):
        data, _expected = make_image(((128, b"first"), (1024, b"second")))
        harness = RawCatalogHarness(data)
        SessionCappedCarver.candidate_count_cap = 1
        result = harness.build().snapshot
        self.assertEqual(result.content_carving_summary["stopReason"], "resource_limit")

    def test_same_raw_checkpoint_is_serialized_across_concurrent_catalog_builds(self):
        data, _expected = make_image((
            (128, b"one"), (2048, b"two"), (4096, b"three"),
        ))
        harness = RawCatalogHarness(data)
        harness.source_factory.block_discovery = True
        validation_second_call = threading.Event()
        original_validate = harness.validation.validate_source
        original_build = harness.builder.build
        raw_operation_threads = []
        original_raw_operation = harness.session.raw_carving_operation

        def track_raw_operation():
            raw_operation_threads.append(threading.get_ident())
            return original_raw_operation()

        harness.session.raw_carving_operation = track_raw_operation
        build_state_lock = threading.Lock()
        active_builds = 0
        max_active_builds = 0

        def build_with_activity(*args, **kwargs):
            nonlocal active_builds, max_active_builds
            with build_state_lock:
                active_builds += 1
                max_active_builds = max(max_active_builds, active_builds)
            try:
                return original_build(*args, **kwargs)
            finally:
                with build_state_lock:
                    active_builds -= 1

        harness.builder.build = build_with_activity

        def validate_with_signal(*args, **kwargs):
            report = original_validate(*args, **kwargs)
            if harness.validation.validation_calls >= 2:
                validation_second_call.set()
            return report

        harness.validation.validate_source = validate_with_signal
        outcomes = []
        errors = []

        def build():
            try:
                outcomes.append(harness.build_without_patches())
            except Exception as exc:  # captured for assertion in the parent test
                errors.append(exc)

        first = threading.Thread(target=build)
        second = threading.Thread(target=build)
        with patch(
            "infrastructure.filesystems.ntfs.catalog_builder.TreeBuilder",
            EmptyTreeBuilder,
        ), patch(
            "infrastructure.filesystems.ntfs.catalog_builder.RawContentCarver",
            SessionCappedCarver,
        ):
            first.start()
            self.assertTrue(
                harness.source_factory.read_entered.wait(3),
                f"open={harness.source_factory.open_count}, events={harness.source_factory.read_events}, "
                f"errors={errors}",
            )
            second.start()
            self.assertTrue(validation_second_call.wait(5))
            harness.source_factory.release_read.set()
            first.join(5)
            second.join(5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(outcomes), 2)
        self.assertTrue(all(outcome.snapshot.content_carving_summary for outcome in outcomes))
        self.assertEqual(
            max_active_builds, 1,
            (raw_operation_threads, harness.volume.source_id,
             harness.validation.validation_calls,
             [o.validation_summary for o in outcomes],
            ),
        )
        self.assertEqual(harness.source_factory.open_count, 2)
        self.assertEqual(
            [reader.closed for reader in harness.source_factory.readers], [True, True],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
