import os
import hashlib

from disk.platform import disk_reader_factory
from domain.recovery_catalog import RecoveryCatalog
from modules.catalog.models import RecoveryCatalogSnapshot
from disk.access.ports import DiskReaderFactory
from disk.deep_scan.ghost_mft_carver import GhostMFTCarver
from disk.deep_scan.content_carver import RawContentCarver
from modules.catalog.carved_content_record import CarvedContentRecord
from modules.catalog.content_validation import CatalogContentValidator
from ntfs.cluster_allocation import ClusterAllocationEvidence
from ntfs.tree_builder import FileNode, TreeBuilder


class CatalogService:
    LOW_CONFIDENCE_MAX_SCAN_BYTES = 128 * 1024 * 1024
    LOW_CONFIDENCE_MAX_CANDIDATE_READ_BYTES = 48 * 1024 * 1024
    LOW_CONFIDENCE_MAX_CANDIDATE_READ_BYTES_PER_FORMAT = 16 * 1024 * 1024
    LOW_CONFIDENCE_MAX_FILE_BYTES = 16 * 1024 * 1024
    LOW_CONFIDENCE_MAX_TOTAL_FILE_BYTES = 32 * 1024 * 1024
    LOW_CONFIDENCE_MAX_FILES = 64

    def __init__(self, disk_factory: DiskReaderFactory | None = None):
        self.disk_factory = disk_factory if disk_factory is not None else disk_reader_factory()

    def build(self, volume, progress_callback=None, include_orphaned=False, phase_callback=None,
              precomputed_orphans=None, precomputed_carving_ranges=None,
              carving_ranges_truncated=False, precomputed_uncertain_carving_ranges=None,
              uncertain_carving_ranges_truncated=None):
        disk = self.disk_factory(volume.disk_number)
        try:
            builder = TreeBuilder(
                disk,
                volume.fragments_as_dicts(),
                volume.partition_offset,
                volume.record_size,
            )
            nodes = builder.build(progress_callback=progress_callback, phase_callback=phase_callback)
            content_carving_summary = None
            low_confidence_carving_summary = None
            if include_orphaned:
                from modules.recovery.extractor import Extractor

                if precomputed_orphans is None:
                    ghosts = GhostMFTCarver(disk).hunt(
                        volume,
                        allowed_extensions=Extractor.supported_extensions(),
                        existing_records=(node.record for node in nodes.values()),
                        progress_callback=progress_callback,
                        phase_callback=phase_callback,
                    )
                else:
                    allowed_extensions = {item.casefold() for item in Extractor.supported_extensions()}
                    existing_fingerprints = {
                        bytes(node.record.raw_data)
                        for node in nodes.values()
                        if getattr(node.record, "is_valid", False)
                    }
                    ghosts = {
                        synthetic_id: record for synthetic_id, record in precomputed_orphans.items()
                        if os.path.splitext(record.name)[1].casefold() in allowed_extensions
                        and bytes(record.raw_data) not in existing_fingerprints
                    }
                content_validator = CatalogContentValidator(
                    disk,
                    volume.partition_offset,
                    volume.partition_offset + volume.partition_size,
                    volume.cluster_size,
                )
                ghosts = self._validate_orphan_content(ghosts, content_validator)
                builder.inject_ghosts(ghosts)
                if precomputed_carving_ranges is not None:
                    def report_carving_progress(completed, total):
                        if phase_callback is not None:
                            phase_callback("content_carving", completed, total)

                    carving = RawContentCarver(disk).scan(
                        precomputed_carving_ranges,
                        progress_callback=report_carving_progress if phase_callback is not None else None,
                    )
                    retained_content_digests = set()
                    retained_content_offsets = set()
                    for candidate in carving.files:
                        retained_content_digests.add(hashlib.sha256(candidate.data).digest())
                        retained_content_offsets.add(int(candidate.offset))
                        synthetic_id = -(int(disk.size) + int(candidate.offset) + 1)
                        while synthetic_id in builder.nodes:
                            synthetic_id -= 1
                        record = CarvedContentRecord(
                            index=synthetic_id,
                            offset=int(candidate.offset),
                            name=f"Carved_{int(candidate.offset):016X}{candidate.extension}",
                            resident_data=candidate.data,
                        )
                        node = FileNode(record, is_orphaned=True, is_content_carved=True)
                        node.full_path = os.path.join(
                            "Lost_Files_DeepScan", "ContentCarving", record.name,
                        )
                        builder.nodes[synthetic_id] = node
                        builder.root_nodes.append(node)
                    content_carving_summary = {
                        "filesFound": len(carving.files),
                        "filesFoundByExtension": {
                            item.extension: item.files_found for item in carving.format_stats
                        },
                        "candidatesExaminedByExtension": {
                            item.extension: item.candidates_examined for item in carving.format_stats
                        },
                        "candidateBytesReadByExtension": {
                            item.extension: item.candidate_bytes_read for item in carving.format_stats
                        },
                        "candidateLimitReachedByExtension": {
                            item.extension: item.candidate_limit_reached for item in carving.format_stats
                        },
                        "fileSizeLimitReachedByExtension": {
                            item.extension: item.file_size_limit_reached for item in carving.format_stats
                        },
                        "decodedDataLimitReachedByExtension": {
                            item.extension: item.decoded_data_limit_reached for item in carving.format_stats
                        },
                        "candidateReadCapBytes": carving.candidate_read_cap_bytes,
                        "candidateReadCapBytesPerFormat": carving.candidate_read_cap_bytes_per_format,
                        "maxFileBytes": carving.max_file_bytes,
                        "maxDecodedPngBytes": carving.max_decoded_png_bytes,
                        "scanByteCap": carving.max_scan_bytes,
                        "retainedBytesCap": carving.max_total_file_bytes,
                        "fileCountCap": carving.max_files,
                        "formatsAttempted": [item.extension for item in carving.format_stats],
                        "validationScope": "contiguous_structure_and_signature",
                        "bytesScanned": carving.bytes_scanned,
                        "scanLimitReached": carving.scan_limit_reached,
                        "candidateBytesRead": carving.candidate_bytes_read,
                        "candidateLimitReached": carving.candidate_limit_reached,
                        "fileCountLimitReached": carving.file_count_limit_reached,
                        "retainedBytesLimitReached": carving.retained_bytes_limit_reached,
                        "rangeCount": len(precomputed_carving_ranges),
                        "rangeCollectionTruncated": bool(carving_ranges_truncated),
                            "confidence": "trusted_free_space",
                    }
                    if precomputed_uncertain_carving_ranges is not None:
                        low_confidence_carving_summary = {}
                        truncation = uncertain_carving_ranges_truncated or {}
                        for key, allocation_status, folder_name, phase_name in (
                            ("bitmapUnobserved", "bitmap_unobserved", "BitmapUnobserved",
                                "content_carving_unobserved"),
                            ("possiblyReused", "possibly_reused", "PossiblyReused",
                                "content_carving_reused"),
                        ):
                            ranges = tuple(precomputed_uncertain_carving_ranges.get(key, ()))
                            def report_low_confidence_progress(completed, total, phase=phase_name):
                                if phase_callback is not None:
                                    phase_callback(phase, completed, total)

                            low_carver = RawContentCarver(
                                disk,
                                max_scan_bytes=self.LOW_CONFIDENCE_MAX_SCAN_BYTES,
                                max_candidate_read_bytes=self.LOW_CONFIDENCE_MAX_CANDIDATE_READ_BYTES,
                                max_candidate_read_bytes_per_format=(
                                    self.LOW_CONFIDENCE_MAX_CANDIDATE_READ_BYTES_PER_FORMAT
                                ),
                                max_file_bytes=self.LOW_CONFIDENCE_MAX_FILE_BYTES,
                                max_total_file_bytes=self.LOW_CONFIDENCE_MAX_TOTAL_FILE_BYTES,
                                max_files=self.LOW_CONFIDENCE_MAX_FILES,
                            )
                            low_carving = low_carver.scan(
                                ranges,
                                progress_callback=report_low_confidence_progress
                                if phase_callback is not None else None,
                            )
                            added = 0
                            for candidate in low_carving.files:
                                digest = hashlib.sha256(candidate.data).digest()
                                if (digest in retained_content_digests
                                        or int(candidate.offset) in retained_content_offsets):
                                    continue
                                retained_content_digests.add(digest)
                                retained_content_offsets.add(int(candidate.offset))
                                synthetic_id = -(int(disk.size) + int(candidate.offset) + 1)
                                while synthetic_id in builder.nodes:
                                    synthetic_id -= 1
                                record = CarvedContentRecord(
                                    index=synthetic_id,
                                    offset=int(candidate.offset),
                                    name=f"Carved_{int(candidate.offset):016X}{candidate.extension}",
                                    resident_data=candidate.data,
                                    cluster_allocation_status=allocation_status,
                                    catalog_content_validation_reason=(
                                        "Contiguous format structure passed validation; allocation "
                                        "is unknown or may describe current/reused data"
                                    ),
                                )
                                node = FileNode(record, is_orphaned=True, is_content_carved=True)
                                node.full_path = os.path.join(
                                    "Lost_Files_DeepScan", "LowConfidence", folder_name, record.name,
                                )
                                builder.nodes[synthetic_id] = node
                                builder.root_nodes.append(node)
                                added += 1
                            low_confidence_carving_summary[key] = self._carving_summary(
                                low_carving,
                                ranges,
                                bool(truncation.get(key, False)),
                                confidence="low",
                                allocation_status=allocation_status,
                                catalog_items_added=added,
                            )
                            low_confidence_carving_summary[key]["rangeBytesRetained"] = sum(
                                end - start for start, end in ranges
                            )
                            low_confidence_carving_summary[key]["rangeCollectionCapBytes"] = (
                                ClusterAllocationEvidence.DEFAULT_UNCERTAIN_RANGE_BYTES
                            )
                nodes = builder.nodes
            return RecoveryCatalogSnapshot(
                catalog=RecoveryCatalog(nodes, builder.root_nodes),
                volume=volume,
                orphan_scan_performed=bool(include_orphaned),
                content_carving_summary=content_carving_summary,
                parent_reference_issue_count=int(builder.parent_reference_issue_count),
                low_confidence_carving_summary=low_confidence_carving_summary,
            )
        finally:
            disk.close()

    @staticmethod
    def supported_extensions():
        from modules.recovery.extractor import Extractor

        return Extractor.supported_extensions()

    @staticmethod
    def _validate_orphan_content(ghosts, validator):
        """Filter known-bad headers and retain bounded evidence on each candidate."""
        validated = {}
        for synthetic_id, record in ghosts.items():
            evidence = validator.validate(record)
            record.catalog_content_validation = evidence.status
            record.catalog_content_validation_reason = evidence.reason
            if evidence.status != "signature_mismatch":
                validated[synthetic_id] = record
        return validated

    @staticmethod
    def _carving_summary(
        carving, ranges, range_collection_truncated, *, confidence, allocation_status,
        catalog_items_added,
    ):
        return {
            "filesFound": len(carving.files),
            "filesFoundByExtension": {
                item.extension: item.files_found for item in carving.format_stats
            },
            "candidatesExaminedByExtension": {
                item.extension: item.candidates_examined for item in carving.format_stats
            },
            "candidateBytesReadByExtension": {
                item.extension: item.candidate_bytes_read for item in carving.format_stats
            },
            "candidateLimitReachedByExtension": {
                item.extension: item.candidate_limit_reached for item in carving.format_stats
            },
            "fileSizeLimitReachedByExtension": {
                item.extension: item.file_size_limit_reached for item in carving.format_stats
            },
            "decodedDataLimitReachedByExtension": {
                item.extension: item.decoded_data_limit_reached for item in carving.format_stats
            },
            "formatsAttempted": [item.extension for item in carving.format_stats],
            "validationScope": "contiguous_structure_and_signature",
            "confidence": confidence,
            "allocationStatus": allocation_status,
            "catalogItemsAdded": catalog_items_added,
            "bytesScanned": carving.bytes_scanned,
            "scanLimitReached": carving.scan_limit_reached,
            "candidateBytesRead": carving.candidate_bytes_read,
            "candidateReadCapBytes": carving.candidate_read_cap_bytes,
            "candidateReadCapBytesPerFormat": carving.candidate_read_cap_bytes_per_format,
            "maxFileBytes": carving.max_file_bytes,
            "maxDecodedPngBytes": carving.max_decoded_png_bytes,
            "scanByteCap": carving.max_scan_bytes,
            "retainedBytesCap": carving.max_total_file_bytes,
            "fileCountCap": carving.max_files,
            "candidateLimitReached": carving.candidate_limit_reached,
            "fileCountLimitReached": carving.file_count_limit_reached,
            "retainedBytesLimitReached": carving.retained_bytes_limit_reached,
            "rangeCount": len(ranges),
            "rangeCollectionTruncated": bool(range_collection_truncated),
        }

    @staticmethod
    def search(snapshot, query, limit=500):
        normalized = query.casefold()
        if not normalized:
            return (), 0
        matches = [
            node for node in snapshot.catalog.nodes.values()
            if normalized in node.record.name.casefold()
            or normalized in node.full_path.casefold()
        ]
        matches.sort(key=lambda node: (node.full_path.casefold(), node.full_path))
        return tuple(matches[:limit]), len(matches)
