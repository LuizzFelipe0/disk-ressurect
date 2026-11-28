"""Physical-source continuation through the command and extraction boundaries.

All reads in this module use an in-memory synthetic image. No OS disk reader is
constructed and no physical device is opened.
"""

import hashlib
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from application.session import RecoverySession
from application.workflows.catalog_scan import CatalogScanWorkflow
from infrastructure.filesystems.ntfs.catalog_builder import CatalogBuilder
from infrastructure.filesystems.ntfs.readers.content_reference_reader import NTFSContentReferenceReader
from infrastructure.carving.content_carver import RawContentCarver
from infrastructure.persistence.deep_scan_repository import JsonDeepScanRepository
from modules.catalog.entities import CatalogNode, PngRecoveryProgress, RecoveryCatalog, RecoveryCatalogSnapshot
from modules.catalog.dto import CarvingOptionsDto
from modules.disk.entities import NTFSVolume
from modules.deep_scan.entities import CarvedCandidateReference, CarvingCheckpoint
from modules.recovery.entities import ContentReference, RecoveryCandidate
from modules.storage.entities import PhysicalDisk
from presentation.controller import RecoveryCommandHandler
from test_raw_carving_session_resume import (
    EmptyTreeBuilder,
    SessionCappedCarver,
    SyntheticRawReader,
    SyntheticRawSourceFactory,
    make_image,
)
from test_content_carver import jpeg
from helpers import make_recovery_workflow


BITMAP_V1 = hashlib.sha256(b"physical synthetic allocation map v1").hexdigest()
BITMAP_V2 = hashlib.sha256(b"physical synthetic allocation map v2").hexdigest()


class PhysicalValidation:
    def __init__(self, source_factory, ranges, *, bitmap_sequence=None):
        self.source_factory = source_factory
        self.ranges = tuple(ranges)
        self.bitmap_sequence = tuple(bitmap_sequence or (BITMAP_V1,))
        self.disk_calls = []
        self.disk_range_budgets = []
        self.raw_calls = 0
        self.on_validate = None

    def validate_disk(self, disk_number, _progress=None, *, retain_orphans_for_offset,
                      content_carving_range_start_index=0, **kwargs):
        self.disk_calls.append((disk_number, content_carving_range_start_index))
        self.disk_range_budgets.append(
            kwargs.get("content_carving_range_budget_bytes"),
        )
        if self.on_validate is not None:
            self.on_validate(len(self.disk_calls))
        bitmap = self.bitmap_sequence[min(len(self.disk_calls) - 1,
                                          len(self.bitmap_sequence) - 1)]
        start = content_carving_range_start_index
        selected = self.ranges[start:start + 1]
        pending = max(0, len(self.ranges) - (start + len(selected)))
        page = {
            "rangeWindowStartIndex": start,
            "rangeWindowEndIndex": start + len(selected),
            "observedRangeCount": len(self.ranges),
            "pendingRangeCount": pending,
            "nextRangeIndex": start + 1 if pending else None,
            "byteLimitReached": False,
            "truncated": bool(pending),
            "retainedBytes": sum(end - begin for begin, end in selected),
            "rangeCapBytes": 8192,
        }
        offset = int(retain_orphans_for_offset)
        return {
            "ntfs_checks": ({
                "partitionOffset": offset,
                "bitmapAllocation": {"bitmapSha256": bitmap},
                "contentCarvingRangeProgress": page,
            },),
            "orphan_records_by_partition": {offset: {}},
            "content_carving_ranges_by_partition": {offset: selected},
            "content_carving_ranges_truncated_by_partition": {offset: bool(pending)},
        }

    def validate_source(self, *_args, **_kwargs):
        self.raw_calls += 1
        raise AssertionError("physical continuation must use validate_disk")

    @staticmethod
    def summary(_report):
        return {"coverageStatus": "complete"}


class SyntheticDiskService:
    def __init__(self, disk):
        self.disk = disk

    def get_disk(self, number):
        if number != self.disk.number:
            raise ValueError("Unexpected synthetic disk number")
        return self.disk


class SyntheticDeepScanService:
    def __init__(self, volume, repository=None):
        self.volume = volume
        self.repository = repository
        self.saved_checkpoints = []

    def scan_partitions(self, *_args, **_kwargs):
        return (self.volume,), "synthetic-time"

    def load_carving_checkpoint(self, disk, volume):
        if self.repository is None:
            return None
        return self.repository.load_carving_checkpoint(disk, volume)

    def save_carving_checkpoint(self, _disk, _volume, checkpoint):
        self.saved_checkpoints.append(checkpoint)
        if self.repository is not None:
            self.repository.save_carving_checkpoint(_disk, _volume, checkpoint)


class SafeSyntheticOutputGuard:
    def validate_source(self, _output_directory, source):
        if source.source_type != "physical_disk" or source.locator != "synthetic-fixture":
            raise ValueError("Unexpected synthetic source identity")


class PhysicalScanContinuationTests(unittest.TestCase):
    def make_handler(self, image, ranges, *, bitmap_sequence=None, repository=None):
        disk = PhysicalDisk(2, "Synthetic physical source", len(image), "synthetic-serial")
        physical_source = disk.as_storage_source(512)
        source_factory = SyntheticRawSourceFactory(
            image, physical_source.source_id, source_type="physical_disk",
        )
        volume = NTFSVolume(
            2, 1, 0, len(image), 512, 4096, 1024, 0, 0, (),
            "Synthetic NTFS", False, None,
        )
        validation = PhysicalValidation(source_factory, ranges,
                                        bitmap_sequence=bitmap_sequence)
        disk_service = SyntheticDiskService(disk)
        deep_scan_service = SyntheticDeepScanService(volume, repository)
        session = RecoverySession()
        builder = CatalogBuilder(
            disk_factory=lambda _disk_number: SyntheticRawReader(
                source_factory, source_factory.source,
            ),
        )
        recovery = make_recovery_workflow(
            output_guard=SafeSyntheticOutputGuard(),
            content_reader_factory=lambda _source: NTFSContentReferenceReader(
                source_factory.open_reader, builder.content_reference_store,
            ),
        )
        handler = RecoveryCommandHandler(
            disk_service, deep_scan_service, validation, builder, None, recovery,
            session=session,
            source_resolver=lambda _number: handler_source_identity[0].as_storage_source(512),
        )
        handler_source_identity = [disk]
        handler.synthetic_source_identity = handler_source_identity
        handler.synthetic_deep_scan_service = deep_scan_service
        volume_id = session.register_volume(volume, physical_source.source_id)
        options = CarvingOptionsDto(
            scan_budget_gib=1, max_files=256, max_retained_mib=128,
            max_candidate_read_mib_per_format=256,
        )
        return handler, volume_id, validation, source_factory, options

    def cached_png_snapshot(self, source, volume_id):
        reference = ContentReference("synthetic-png-reference", source.source_id, 64)
        candidate = RecoveryCandidate(
            "synthetic-png-candidate", source.source_id, volume_id, "recovered.png",
            None, 64, None, ("fragment_reconstruction",), (),
            content_reference=reference,
        )
        node = CatalogNode(
            candidate.candidate_id, "recovered.png", "recovered.png", False, 64, candidate,
        )
        return RecoveryCatalogSnapshot(
            RecoveryCatalog({node.node_id: node}),
            source=source,
            source_id=source.source_id,
            volume_id=volume_id,
            content_carving_summary={"stopReason": "scope_complete"},
            png_recovery_progress=PngRecoveryProgress("a" * 64, "b" * 64),
        )

    def test_cached_png_candidate_revalidation_uses_registered_physical_source(self):
        image, _expected = make_image(((128, b"fixture"),))
        handler, volume_id, validation, source_factory, options = self.make_handler(
            image, ((0, 2048),),
        )
        physical_source = source_factory.source
        cached_snapshot = self.cached_png_snapshot(physical_source, volume_id)
        handler.session.get_scan_catalog = Mock(return_value=cached_snapshot)
        handler.session.update_raw_catalog_snapshot = Mock(return_value=True)
        validate_cached = Mock(return_value=(True, 17))
        handler.catalog_builder.raw_png_recovery_results_are_current = validate_cached
        volume = handler.session.volumes[volume_id]
        options = replace(options, enable_png_fragment_reconstruction=True)

        outcome = handler.catalog_scan_workflow.run(
            volume,
            include_orphaned=True,
            force_fresh_validation=True,
            carving_options=options,
            progress_callback=lambda *_args: None,
            validation_progress_callback=lambda *_args: None,
            phase_callback=lambda *_args: None,
            session_source_id=physical_source.source_id,
            source_identity_validator=lambda: True,
        )

        self.assertEqual(
            {"synthetic-png-candidate"}, set(outcome.snapshot.catalog.nodes),
        )
        validate_cached.assert_called_once()
        self.assertEqual(physical_source.source_id, validate_cached.call_args.args[0].source_id)
        self.assertEqual("physical_disk", validate_cached.call_args.args[0].source_type)

    def test_stale_cached_png_does_not_reuse_completed_carving_cursor(self):
        image, _expected = make_image(((128, b"fixture"),))
        handler, volume_id, validation, source_factory, options = self.make_handler(
            image, ((0, 2048),),
        )
        physical_source = source_factory.source
        cached_snapshot = replace(
            self.cached_png_snapshot(physical_source, volume_id),
            content_carving_summary={
                "stopReason": "resource_limit",
                "rangePage": {"pendingRangeCount": 1},
            },
        )
        handler.session.get_scan_catalog = Mock(return_value=cached_snapshot)
        handler.session.load_scan_range_progress = Mock(return_value={
            "nextRangeIndex": 1,
            "pendingRangeCount": 1,
            "bitmapSha256": BITMAP_V1,
            "totalScanBytes": 128,
            "totalCandidateBytesRead": 64,
            "totalCandidateRestoreBytesRead": 32,
        })
        handler.session.load_scan_checkpoint = Mock(return_value=object())
        handler.catalog_builder.raw_png_recovery_results_are_current = Mock(
            return_value=(False, 17),
        )
        handler.catalog_builder.build = Mock(
            side_effect=RuntimeError("Stop after verifying stale cursor invalidation"),
        )
        volume = handler.session.volumes[volume_id]
        options = replace(options, enable_png_fragment_reconstruction=True)

        with self.assertRaisesRegex(RuntimeError, "stale cursor invalidation"):
            handler.catalog_scan_workflow._run_page(
                volume,
                include_orphaned=True,
                force_fresh_validation=True,
                carving_options=options,
                progress_callback=lambda *_args: None,
                validation_progress_callback=lambda *_args: None,
                phase_callback=lambda *_args: None,
                session_source_id=physical_source.source_id,
                operation_budget_usage={
                    "scanBaseline": 0, "scanThisOperation": 0,
                    "candidateBaseline": 0, "candidateThisOperation": 0,
                    "restoreBaseline": 0, "restoreThisOperation": 0,
                },
            )

        handler.session.load_scan_checkpoint.assert_not_called()
        handler.catalog_builder.build.assert_called_once()
        self.assertIsNone(handler.catalog_builder.build.call_args.kwargs["carving_checkpoint"])
        self.assertEqual([1, 0], [index for _number, index in validation.disk_calls])
        self.assertEqual(((0, 2048),), handler.catalog_builder.build.call_args.kwargs[
            "precomputed_carving_ranges"
        ])

    def test_scan_candidate_and_restoration_budgets_decrease_independently(self):
        options = CarvingOptionsDto(
            scan_budget_gib=1, max_files=256, max_retained_mib=128,
            max_candidate_read_mib_per_format=256,
        )
        progress = {
            "totalScanBytes": 1024**3,
            "totalCandidateBytesRead": 300 * 1024**2,
            "totalCandidateRestoreBytesRead": 768 * 1024**2,
        }
        self.assertEqual(
            0, CatalogScanWorkflow._remaining_scan_budget_bytes(options, progress),
        )
        self.assertEqual(
            156,
            CatalogScanWorkflow._remaining_candidate_budget_options(
                options, progress,
            ).max_candidate_read_mib_per_format,
        )
        self.assertEqual(
            0, CatalogScanWorkflow._remaining_candidate_restore_budget(options, progress),
        )
        operation_usage = {
            "scanBaseline": 1024**3,
            "scanThisOperation": 0,
            "candidateBaseline": 768 * 1024**2,
            "candidateThisOperation": 0,
            "restoreBaseline": 768 * 1024**2,
            "restoreThisOperation": 0,
        }
        self.assertEqual(
            0, CatalogScanWorkflow._remaining_scan_budget_bytes(
                options, None, operation_usage,
            ),
        )
        self.assertEqual(
            0, CatalogScanWorkflow._remaining_candidate_budget_options(
                options, None, operation_usage,
            ).max_candidate_read_mib_per_format,
        )
        self.assertEqual(
            0, CatalogScanWorkflow._remaining_candidate_restore_budget(
                options, None, operation_usage,
            ),
        )
        carried_progress = CatalogScanWorkflow._next_raw_range_progress(
            "synthetic-scope", None,
            {"nextRangeIndex": 2, "pendingRangeCount": 1, "truncated": True},
            {
                "bytesScanned": 10, "rangeBytesRetained": 10,
                "candidateBytesRead": 7, "candidateRestoreBytesRead": 5,
            },
            BITMAP_V2,
            operation_budget_usage={
                "scanBaseline": 100, "scanThisOperation": 20,
                "candidateBaseline": 500, "candidateThisOperation": 10,
                "restoreBaseline": 700, "restoreThisOperation": 30,
            },
        )
        self.assertEqual(130, carried_progress["totalScanBytes"])
        self.assertEqual(517, carried_progress["totalCandidateBytesRead"])
        self.assertEqual(735, carried_progress["totalCandidateRestoreBytesRead"])

    def test_candidate_restoration_budget_fails_closed_before_publishing_partial_results(self):
        content = jpeg(b"restore-budget")
        image, _expected = make_image(((128, b"restore-budget"),))
        disk = PhysicalDisk(2, "Synthetic physical source", len(image), "restore-budget")
        source = disk.as_storage_source(512)
        source_factory = SyntheticRawSourceFactory(
            image, source.source_id, source_type="physical_disk",
        )
        reader = source_factory.open_reader(source_factory.source)
        reference = CarvedCandidateReference(
            128, ".jpg", len(content), hashlib.sha256(content).hexdigest(),
        )
        with self.assertRaisesRegex(OSError, "Candidate restoration read budget exhausted"):
            RawContentCarver(
                reader, chunk_size=512, max_candidate_restore_bytes=1,
            ).scan(
                ((0, len(image)),),
                retained_candidates=(reference,),
                retained_candidate_data={(128, reference.sha256): content},
                candidate_restore_ranges=((0, len(image)),),
                require_all_retained_candidates=True,
            )
        reader.close()

    def test_single_controller_scan_continues_to_later_physical_ranges_and_extracts(self):
        image, expected_hashes = make_image(((128, b"first"), (4224, b"second")))
        handler, volume_id, validation, source_factory, options = self.make_handler(
            image, ((0, 2048), (4096, 6144)),
        )
        events = []
        payload = {
            "volumeId": volume_id,
            "includeOrphaned": True,
            "forceFreshValidation": True,
            "operationId": "physical-scan-1",
            "carvingOptions": {
                "scanBudgetGiB": options.scan_budget_gib,
                "maxFiles": options.max_files,
                "maxRetainedMiB": options.max_retained_mib,
                "maxCandidateReadMiBPerFormat": options.max_candidate_read_mib_per_format,
            },
        }
        with patch(
            "infrastructure.filesystems.ntfs.catalog_builder.TreeBuilder", EmptyTreeBuilder,
        ), patch(
            "infrastructure.filesystems.ntfs.catalog_builder.RawContentCarver",
            SessionCappedCarver,
        ):
            handler.handle({"id": "scan", "operation": "scan_catalog", "payload": payload},
                           events.append)

        self.assertEqual("result", events[-1]["type"])
        carving = events[-1]["payload"]["contentCarving"]
        self.assertEqual(2, carving["continuation"]["passes"])
        self.assertEqual("scope_complete", carving["continuation"]["stopReason"])
        self.assertEqual([0, 1], [index for _disk, index in validation.disk_calls])
        self.assertEqual(0, validation.raw_calls)
        self.assertEqual([], handler.synthetic_deep_scan_service.saved_checkpoints)
        candidates = [
            node for node in handler.session.nodes.values()
            if node.candidate is not None and "content_carving" in node.candidate.discovery_methods
        ]
        self.assertEqual({128, 4224}, {
            int(node.name.split("_")[1].split(".")[0], 16) for node in candidates
        })
        control_reader = source_factory.open_reader(source_factory.source)
        try:
            contiguous = RawContentCarver(
                control_reader, chunk_size=512, max_scan_bytes=2048,
            ).scan(((0, 2048),))
        finally:
            control_reader.close()
        self.assertEqual({128}, {item.offset for item in contiguous.files})
        self.assertEqual(physical_source_id(source_factory),
                         candidates[0].candidate.content_reference.source_id)

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]) as output:
            result_events = []
            handler.handle({
                "id": "extract",
                "operation": "extract",
                "payload": {
                    "selectedNodeIds": [node.node_id for node in candidates],
                    "excludedNodeIds": [],
                    "outputDirectory": output,
                    "extensions": [".jpg"],
                    "minimumSizeKb": 0,
                },
            }, result_events.append)
            self.assertEqual("result", result_events[-1]["type"], result_events)
            self.assertEqual(2, result_events[-1]["payload"]["recoveredCount"])
            actual_hashes = {
                hashlib.sha256(Path(output, item["path"]).read_bytes()).hexdigest()
                for item in result_events[-1]["payload"]["results"]
            }
        self.assertEqual(set(expected_hashes.values()), actual_hashes)

    def test_restart_discards_session_progress_preserves_legacy_checkpoint_and_rescans(self):
        image, expected_hashes = make_image(((128, b"restart-first"), (4224, b"restart-second")))
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]) as state_dir:
            repository = JsonDeepScanRepository(
                Path(state_dir, "deep-scan.json"), disk_mapper=lambda _path: set(),
            )
            legacy_checkpoint = CarvingCheckpoint(
                range_fingerprint=hashlib.sha256(b"legacy physical range").hexdigest(),
                range_index=0, next_offset=0, disk_size=len(image), bytes_per_sector=512,
                scan_profile="legacy-physical-profile",
            )
            first, volume_id, first_validation, _factory, options = self.make_handler(
                image, ((0, 2048), (4096, 6144)), repository=repository,
            )
            physical_disk = first.disk_service.get_disk(2)
            repository.save_carving_checkpoint(
                physical_disk, first.deep_scan_service.volume, legacy_checkpoint,
            )
            payload = {
                "volumeId": volume_id, "includeOrphaned": True,
                "forceFreshValidation": True, "operationId": "physical-restart-1",
                "carvingOptions": {
                    "scanBudgetGiB": options.scan_budget_gib,
                    "maxFiles": options.max_files,
                    "maxRetainedMiB": options.max_retained_mib,
                    "maxCandidateReadMiBPerFormat": options.max_candidate_read_mib_per_format,
                },
            }
            with patch(
                "infrastructure.filesystems.ntfs.catalog_builder.TreeBuilder", EmptyTreeBuilder,
            ), patch(
                "infrastructure.filesystems.ntfs.catalog_builder.RawContentCarver",
                SessionCappedCarver,
            ):
                first_validation.on_validate = lambda count: (
                    first.dispatch(
                        "cancel_operation", {"operationId": "physical-restart-1"},
                        lambda _event: None,
                    ) if count == 1 else None
                )
                first_events = []
                first.handle({"id": "first-page", "operation": "scan_catalog",
                              "payload": payload}, first_events.append)
                self.assertEqual("cancelled", first_events[-1]["payload"]["contentCarving"]
                                 ["continuation"]["stopReason"])

                second, second_volume_id, second_validation, _factory2, _options2 = self.make_handler(
                    image, ((0, 2048), (4096, 6144)), repository=repository,
                )
                self.assertEqual(volume_id, second_volume_id)
                second_events = []
                second.handle({"id": "after-restart", "operation": "scan_catalog",
                               "payload": payload}, second_events.append)

            self.assertEqual("result", second_events[-1]["type"], second_events)
            self.assertEqual([0, 1], [index for _disk, index in second_validation.disk_calls])
            self.assertEqual(
                legacy_checkpoint,
                repository.load_carving_checkpoint(physical_disk,
                                                   first.deep_scan_service.volume),
            )
            candidates = [
                node for node in second.session.snapshot.catalog.nodes.values()
                if node.candidate is not None and "content_carving" in
                node.candidate.discovery_methods
            ]
            self.assertEqual(2, len(candidates))
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]) as output:
                extraction_events = []
                second.handle({
                    "id": "extract-after-restart", "operation": "extract",
                    "payload": {
                        "selectedNodeIds": [node.node_id for node in candidates],
                        "excludedNodeIds": [], "outputDirectory": output,
                        "extensions": [".jpg"], "minimumSizeKb": 0,
                    },
                }, extraction_events.append)
                self.assertEqual("result", extraction_events[-1]["type"], extraction_events)
                extracted_hashes = {
                    hashlib.sha256(Path(output, item["path"]).read_bytes()).hexdigest()
                    for item in extraction_events[-1]["payload"]["results"]
                }
            self.assertEqual(set(expected_hashes.values()), extracted_hashes)

    def test_unpaged_physical_scan_resumes_legacy_checkpoint_after_backend_restart(self):
        image, expected_hashes = make_image(
            ((128, b"legacy-resume-first"), (2304, b"legacy-resume-middle"),
             (4352, b"legacy-resume-last")),
        )
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]) as state_dir:
            repository = JsonDeepScanRepository(
                Path(state_dir, "deep-scan.json"), disk_mapper=lambda _path: set(),
            )
            scan_payload = {
                "includeOrphaned": True,
                "forceFreshValidation": True,
                "carvingOptions": {
                    "scanBudgetGiB": 1,
                    "maxFiles": 256,
                    "maxRetainedMiB": 128,
                    "maxCandidateReadMiBPerFormat": 256,
                },
            }
            observed_candidates = []
            for pass_number in range(3):
                handler, volume_id, validation, _factory, _options = self.make_handler(
                    image, ((0, len(image)),), repository=repository,
                )
                events = []
                with patch(
                    "infrastructure.filesystems.ntfs.catalog_builder.TreeBuilder",
                    EmptyTreeBuilder,
                ), patch(
                    "infrastructure.filesystems.ntfs.catalog_builder.RawContentCarver",
                    SessionCappedCarver,
                ):
                    handler.handle({
                        "id": f"physical-resume-{pass_number}",
                        "operation": "scan_catalog",
                        "payload": {**scan_payload, "volumeId": volume_id},
                    }, events.append)

                self.assertEqual("result", events[-1]["type"], events)
                self.assertEqual([0], [index for _disk, index in validation.disk_calls])
                candidates = [
                    node for node in handler.session.snapshot.catalog.nodes.values()
                    if node.candidate is not None
                    and "content_carving" in node.candidate.discovery_methods
                ]
                observed_candidates.append({
                    int(item.name.split("_")[1].split(".")[0], 16): (
                        item.candidate.content_reference.sha256
                    ) for item in candidates
                })

            self.assertEqual([128], sorted(observed_candidates[0]))
            self.assertEqual([128, 2304], sorted(observed_candidates[1]))
            self.assertEqual([128, 2304, 4352], sorted(observed_candidates[2]))
            self.assertEqual(expected_hashes, observed_candidates[-1])

    def test_cancel_before_worker_starts_publishes_first_page_as_cancelled(self):
        image, _expected_hashes = make_image(((128, b"early-cancel"),))
        handler, volume_id, _validation, _factory, options = self.make_handler(
            image, ((0, len(image)),),
        )
        scan_request = {
            "id": "early-cancel-scan", "operation": "scan_catalog",
            "payload": {
                "volumeId": volume_id,
                "includeOrphaned": True,
                "forceFreshValidation": True,
                "operationId": "early-cancel-operation",
                "carvingOptions": {
                    "scanBudgetGiB": options.scan_budget_gib,
                    "maxFiles": options.max_files,
                    "maxRetainedMiB": options.max_retained_mib,
                    "maxCandidateReadMiBPerFormat": (
                        options.max_candidate_read_mib_per_format
                    ),
                },
            },
        }
        handler.prepare_cancellation(scan_request)
        self.assertEqual(
            {"accepted": True},
            handler.dispatch("cancel_operation", {
                "operationId": "early-cancel-operation",
            }, lambda _event: None),
        )
        events = []
        with patch(
            "infrastructure.filesystems.ntfs.catalog_builder.TreeBuilder",
            EmptyTreeBuilder,
        ):
            handler.handle(scan_request, events.append)

        self.assertEqual("result", events[-1]["type"], events)
        self.assertEqual(
            "cancelled", events[-1]["payload"]["contentCarving"]["continuation"]["stopReason"],
        )

    def test_bitmap_change_restarts_physical_validation_without_using_raw_reader_path(self):
        image, _expected_hashes = make_image(((128, b"first"), (4224, b"second")))
        handler, volume_id, validation, _source_factory, options = self.make_handler(
            image, ((0, 2048), (4096, 6144)),
            bitmap_sequence=(BITMAP_V1,),
        )
        scan = {
            "volumeId": volume_id, "includeOrphaned": True,
            "forceFreshValidation": True, "operationId": "physical-scan-2",
            "carvingOptions": {
                "scanBudgetGiB": options.scan_budget_gib, "maxFiles": options.max_files,
                "maxRetainedMiB": options.max_retained_mib,
                "maxCandidateReadMiBPerFormat": options.max_candidate_read_mib_per_format,
            },
        }
        with patch(
            "infrastructure.filesystems.ntfs.catalog_builder.TreeBuilder", EmptyTreeBuilder,
        ), patch(
            "infrastructure.filesystems.ntfs.catalog_builder.RawContentCarver",
            SessionCappedCarver,
        ):
            first_events = []
            validation.on_validate = lambda count: (
                handler.dispatch("cancel_operation", {"operationId": "physical-scan-2"},
                                 lambda _event: None)
                if count >= 1 else None
            )
            handler.handle({"id": "scan1", "operation": "scan_catalog", "payload": scan},
                           first_events.append)
            self.assertEqual("cancelled", first_events[-1]["payload"]["contentCarving"]
                             ["continuation"]["stopReason"])
            self.assertEqual("result", first_events[-1]["type"])
            validation.disk_calls.clear()
            validation.disk_range_budgets.clear()
            validation.on_validate = None
            validation.bitmap_sequence = (BITMAP_V2, BITMAP_V2, BITMAP_V2)
            second_events = []
            handler.handle({"id": "scan2", "operation": "scan_catalog", "payload": scan},
                           second_events.append)

        self.assertEqual("result", second_events[-1]["type"])
        self.assertEqual([1, 0, 1], [index for _number, index in validation.disk_calls])
        self.assertTrue(all(number == 2 for number, _index in validation.disk_calls))
        self.assertEqual(0, validation.raw_calls)
        self.assertIn(0, [index for _number, index in validation.disk_calls])
        self.assertEqual(3, len(validation.disk_range_budgets))
        self.assertEqual(validation.disk_range_budgets[0], validation.disk_range_budgets[1])
        self.assertLess(validation.disk_range_budgets[0], 1024**3)
        self.assertLess(validation.disk_range_budgets[2], validation.disk_range_budgets[1])

    def test_later_page_validation_error_preserves_committed_candidates(self):
        image, expected_hashes = make_image(((128, b"first-page"), (4224, b"second-page")))
        handler, volume_id, validation, _source_factory, options = self.make_handler(
            image, ((0, 2048), (4096, 6144)),
        )
        scan = {
            "volumeId": volume_id, "includeOrphaned": True,
            "forceFreshValidation": True, "operationId": "physical-page-error",
            "carvingOptions": {
                "scanBudgetGiB": options.scan_budget_gib, "maxFiles": options.max_files,
                "maxRetainedMiB": options.max_retained_mib,
                "maxCandidateReadMiBPerFormat": options.max_candidate_read_mib_per_format,
            },
        }
        with patch(
            "infrastructure.filesystems.ntfs.catalog_builder.TreeBuilder", EmptyTreeBuilder,
        ), patch(
            "infrastructure.filesystems.ntfs.catalog_builder.RawContentCarver",
            SessionCappedCarver,
        ):
            committed_snapshots = []

            def fail_before_second_page(count):
                if count == 2:
                    committed_snapshots.append(handler.session.snapshot)
                    raise OSError("Synthetic page validation failure")

            validation.on_validate = fail_before_second_page
            second_events = []
            handler.handle({"id": "page-two", "operation": "scan_catalog", "payload": scan},
                           second_events.append)

            self.assertEqual("error", second_events[-1]["type"])
            self.assertEqual(1, len(committed_snapshots))
            committed_snapshot = committed_snapshots[0]
            committed_candidates = [
                node for node in committed_snapshot.catalog.nodes.values()
                if node.candidate is not None and "content_carving" in
                node.candidate.discovery_methods
            ]
            self.assertEqual(1, len(committed_candidates))
        self.assertIs(committed_snapshot, handler.session.snapshot)
        current_candidates = [
            node for node in handler.session.snapshot.catalog.nodes.values()
            if node.candidate is not None and "content_carving" in node.candidate.discovery_methods
        ]
        self.assertEqual(1, len(current_candidates))
        self.assertEqual(committed_candidates[0].node_id, current_candidates[0].node_id)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]) as output:
            extraction_events = []
            handler.handle({
                "id": "extract-after-page-error",
                "operation": "extract",
                "payload": {
                    "selectedNodeIds": [current_candidates[0].node_id],
                    "excludedNodeIds": [],
                    "outputDirectory": output,
                    "extensions": [".jpg"],
                    "minimumSizeKb": 0,
                },
            }, extraction_events.append)
            self.assertEqual("result", extraction_events[-1]["type"])
            self.assertEqual(1, extraction_events[-1]["payload"]["recoveredCount"])
            extracted_path = Path(output, extraction_events[-1]["payload"]["results"][0]["path"])
            self.assertEqual(
                next(iter(expected_hashes.values())),
                hashlib.sha256(extracted_path.read_bytes()).hexdigest(),
            )

    def test_one_command_stops_at_four_passes_and_reports_remaining_ranges(self):
        ranges = tuple((index * 4096, index * 4096 + 2048) for index in range(6))
        image, _expected = make_image(
            ((128, b"first-page"), (4 * 4096 + 128, b"fifth-range")),
            size=6 * 4096,
        )
        handler, volume_id, _validation, _factory, options = self.make_handler(image, ranges)
        payload = {
            "volumeId": volume_id,
            "includeOrphaned": True,
            "forceFreshValidation": True,
            "operationId": "physical-scan-bounded",
            "carvingOptions": {
                "scanBudgetGiB": options.scan_budget_gib,
                "maxFiles": options.max_files,
                "maxRetainedMiB": options.max_retained_mib,
                "maxCandidateReadMiBPerFormat": options.max_candidate_read_mib_per_format,
            },
        }
        with patch(
            "infrastructure.filesystems.ntfs.catalog_builder.TreeBuilder", EmptyTreeBuilder,
        ), patch(
            "infrastructure.filesystems.ntfs.catalog_builder.RawContentCarver",
            SessionCappedCarver,
        ):
            first_events = []
            handler.handle({"id": "bounded", "operation": "scan_catalog",
                            "payload": payload}, first_events.append)
            events = []
            handler.handle({"id": "bounded-resume", "operation": "scan_catalog",
                            "payload": payload}, events.append)
        result = events[-1]["payload"]["contentCarving"]["continuation"]
        first_result = first_events[-1]["payload"]["contentCarving"]["continuation"]
        self.assertEqual(4, first_result["passes"])
        self.assertEqual("pass_limit", first_result["stopReason"])
        self.assertEqual(2, result["passes"])
        self.assertEqual(4, result["maxPasses"])
        self.assertEqual(0, result["pendingRangeCount"])
        self.assertEqual("scope_complete", result["stopReason"])
        candidates = [
            node for node in handler.session.nodes.values()
            if node.candidate is not None and "content_carving" in node.candidate.discovery_methods
        ]
        self.assertEqual({128, 4 * 4096 + 128}, {
            int(node.name.split("_")[1].split(".")[0], 16) for node in candidates
        })

    def test_source_identity_change_stops_before_scanning_an_incompatible_page(self):
        image, _expected = make_image(((128, b"first"), (4224, b"second")))
        handler, volume_id, validation, _factory, options = self.make_handler(
            image, ((0, 2048), (4096, 6144)),
        )
        validation.on_validate = lambda count: (
            handler.synthetic_source_identity.__setitem__(
                0, PhysicalDisk(2, "Replacement synthetic source", len(image), "other-serial"),
            ) if count == 1 else None
        )
        events = []
        with patch(
            "infrastructure.filesystems.ntfs.catalog_builder.TreeBuilder", EmptyTreeBuilder,
        ), patch(
            "infrastructure.filesystems.ntfs.catalog_builder.RawContentCarver",
            SessionCappedCarver,
        ):
            handler.handle({
                "id": "changed-source", "operation": "scan_catalog",
                "payload": {
                    "volumeId": volume_id, "includeOrphaned": True,
                    "forceFreshValidation": True, "operationId": "source-changed",
                    "carvingOptions": {
                        "scanBudgetGiB": options.scan_budget_gib,
                        "maxFiles": options.max_files,
                        "maxRetainedMiB": options.max_retained_mib,
                        "maxCandidateReadMiBPerFormat": options.max_candidate_read_mib_per_format,
                    },
                },
            }, events.append)
        self.assertEqual("error", events[-1]["type"])
        self.assertIn("different storage source", events[-1]["error"])
        self.assertEqual(0, validation.raw_calls)


def physical_source_id(source_factory):
    return source_factory.source.source_id


if __name__ == "__main__":
    unittest.main(verbosity=2)
