import os
import copy
import hashlib
import json
import uuid
from dataclasses import dataclass

from infrastructure.disk.factory import disk_reader_factory
from modules.catalog.entities import RecoveryCatalog
from modules.catalog.entities import RecoveryCatalogSnapshot
from modules.disk.service import DiskReaderFactory
from infrastructure.filesystems.ntfs.discovery.orphan_mft_carver import GhostMFTCarver
from infrastructure.carving.content_carver import RawContentCarver
from modules.deep_scan.entities import CarvedCandidateReference


from infrastructure.filesystems.ntfs.allocation.cluster_allocation import ClusterAllocationEvidence
from infrastructure.filesystems.ntfs.artifacts.models import has_path_component
from infrastructure.filesystems.ntfs.readers.file_content_reader import NTFSFileContentReader
from infrastructure.filesystems.ntfs.discovery.tree_builder import FileNode, TreeBuilder
from infrastructure.filesystems.ntfs.artifacts.recycle_bin import RecycleBinRecoveryHelper
from infrastructure.filesystems.ntfs.artifacts.usn_journal import UsnJournalEvidenceScanner
from infrastructure.filesystems.ntfs.artifacts.usn_mft_correlator import UsnMftCorrelator
from infrastructure.filesystems.ntfs.artifacts.logfile import NTFSLogFileEvidenceScanner
from infrastructure.formats.signature import FileSignatureValidator
from modules.catalog.entities import CatalogNode
from modules.recovery.entities import (
    ContentReference,
    RecoveryCandidate,
    RecoveryEvidence,
    stable_candidate_id,
)
from modules.storage.entities import StorageSource
from infrastructure.filesystems.ntfs.readers.content_reference_store import NTFSContentReferenceStore


@dataclass(frozen=True)
class CarvedContentRecord:
    """NTFS catalog adapter record for bounded raw carving results."""

    index: int
    offset: int
    name: str
    resident_data: bytes
    cluster_allocation_status: str = "free"
    sequence_number: int = 0
    is_valid: bool = True
    is_allocated: bool = True
    is_dir: bool = False
    file_size: int = 0
    data_is_complete: bool = True
    data_runs: tuple = ()
    raw_data: bytes = b""
    catalog_content_validation: str = "format_structure_match"
    catalog_content_validation_reason: str = (
        "Contiguous file structure and format markers passed validation"
    )
    fragment_reconstruction_evidence: dict | None = None

    def __post_init__(self):
        content = bytes(self.resident_data)
        object.__setattr__(self, "resident_data", content)
        object.__setattr__(self, "file_size", len(content))


class CatalogBuilder:
    LOW_CONFIDENCE_MAX_SCAN_BYTES = 128 * 1024 * 1024
    LOW_CONFIDENCE_MAX_CANDIDATE_READ_BYTES = 48 * 1024 * 1024
    LOW_CONFIDENCE_MAX_CANDIDATE_READ_BYTES_PER_FORMAT = 16 * 1024 * 1024
    LOW_CONFIDENCE_MAX_FILE_BYTES = 16 * 1024 * 1024
    LOW_CONFIDENCE_MAX_TOTAL_FILE_BYTES = 32 * 1024 * 1024
    LOW_CONFIDENCE_MAX_FILES = 64

    def __init__(self, disk_factory: DiskReaderFactory | None = None,
                 source_resolver=None, content_reference_store=None, source_factory=None):
        self.disk_factory = disk_factory if disk_factory is not None else disk_reader_factory()
        self.source_resolver = source_resolver
        self.source_factory = source_factory
        self.content_reference_store = (
            content_reference_store if content_reference_store is not None
            else NTFSContentReferenceStore()
        )

    @staticmethod
    def carving_checkpoint_profile():
        """Expose the carver semantics used to invalidate session checkpoints."""
        return {
            "signatureProfile": RawContentCarver._scan_profile(),
            "maxFileBytes": RawContentCarver.DEFAULT_MAX_FILE_BYTES,
            "maxDecodedPngBytes": RawContentCarver.DEFAULT_MAX_DECODED_PNG_BYTES,
        }

    def raw_candidate_state(self, snapshot):
        """Build a transient resume manifest from the committed catalog."""
        references = []
        retained_data = {}
        locations = {}
        for node in snapshot.catalog.nodes.values():
            candidate = node.candidate
            path = str(node.full_path).replace("\\", "/").casefold()
            if (candidate is None or "content_carving" not in candidate.discovery_methods
                    or not str(node.name).startswith("Carved_")
                    or "lost_files_deepscan/" not in path):
                continue
            stem, extension = os.path.splitext(node.name)
            encoded_offset = stem.removeprefix("Carved_")
            if (not encoded_offset
                    or any(character not in "0123456789abcdefABCDEF"
                           for character in encoded_offset)):
                raise ValueError("Committed carved candidate has an invalid offset identity")
            content = candidate.content_reference
            if content is None or content.sha256 is None:
                raise ValueError("Committed carved candidate has no integrity reference")
            offset = int(encoded_offset, 16)
            _, _, retained_node = self.content_reference_store.resolve(content.reference_id)
            record = getattr(retained_node, "record", None)
            data = getattr(record, "resident_data", None)
            if (data is None or len(data) != content.size_bytes
                    or hashlib.sha256(data).hexdigest() != content.sha256):
                raise ValueError("Committed carved candidate data is unavailable or changed")
            key = (offset, content.sha256)
            retained_data[key] = data
            references.append(CarvedCandidateReference(
                offset=offset,
                extension=extension.casefold(),
                size_bytes=int(content.size_bytes),
                sha256=content.sha256,
            ))
            path_parts = tuple(
                part for part in str(node.full_path).replace("\\", "/").split("/") if part
            )
            if path_parts and path_parts[-1].casefold() == node.name.casefold():
                path_parts = path_parts[:-1]
            locations[key] = (
                path_parts,
                node.properties.get("clusterAllocationStatus"),
            )
        return tuple(references), retained_data, locations

    def build(self, volume, progress_callback=None, include_orphaned=False, phase_callback=None,
              precomputed_orphans=None, precomputed_carving_ranges=None,
              carving_ranges_truncated=False, precomputed_uncertain_carving_ranges=None,
              uncertain_carving_ranges_truncated=None, carving_options=None,
              carving_checkpoint=None, carving_checkpoint_callback=None,
              raw_candidate_references=None, raw_session_candidate_limit=None,
              raw_session_retained_byte_limit=None,
              raw_candidate_data=None,
              raw_candidate_locations=None,
              defer_content_reference_commit=False):
        source = None
        if getattr(volume, "source_id", None) and self.source_factory is not None:
            source = self.source_factory(volume.source_id)
            disk = self.source_factory.open_reader(source)
        else:
            disk = self.disk_factory(volume.disk_number)
        try:
            self.content_reference_store.begin_catalog()
            source = getattr(disk, "source", None)
            if source is None and self.source_resolver is not None:
                source = self.source_resolver(volume.disk_number)
            if source is None:
                source = StorageSource(
                    source_id=f"physical-device:{int(volume.disk_number)}",
                    source_type="physical_disk",
                    display_name=f"Physical disk {volume.disk_number}",
                    size_bytes=int(getattr(disk, "size_bytes", disk.size)),
                    bytes_per_sector=int(getattr(disk, "bytes_per_sector", 512)),
                    locator=str(int(volume.disk_number)),
                )
            source_id = source.source_id
            volume_id = self._volume_identity(source_id, volume)
            builder = TreeBuilder(
                disk,
                volume.fragments_as_dicts(),
                volume.partition_offset,
                volume.record_size,
                cluster_size=volume.cluster_size,
                volume_size_bytes=volume.partition_size,
            )
            nodes = builder.build(progress_callback=progress_callback, phase_callback=phase_callback)
            content_carving_summary = None
            low_confidence_carving_summary = None
            recycle_bin_summary = None
            usn_journal_summary = None
            ntfs_log_file_summary = None
            if include_orphaned:
                from infrastructure.recovery.extractor import Extractor

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
                evidence_reader = NTFSFileContentReader(
                    disk,
                    volume.partition_offset,
                    volume.cluster_size,
                    volume_size_bytes=volume.partition_size,
                )
                ntfs_log_file_summary = NTFSLogFileEvidenceScanner().scan(
                    builder.nodes.values(), evidence_reader.iter_chunks,
                ).to_dict()
                recycle_bin_summary = self._add_recycle_bin_aliases(
                    builder, evidence_reader,
                )
                usn_journal_summary, usn_delete_events = self._scan_usn_journal(
                    builder.nodes.values(), evidence_reader,
                )
                usn_journal_summary.update(UsnMftCorrelator().correlate(
                    usn_delete_events,
                    builder,
                    content_validator,
                    Extractor.supported_extensions(),
                ))
                if precomputed_carving_ranges is not None:
                    (content_carving_summary, low_confidence_carving_summary) = (
                        self._scan_content_carving(
                            disk,
                            builder,
                            precomputed_carving_ranges,
                            carving_ranges_truncated,
                            carving_options,
                            carving_checkpoint,
                            carving_checkpoint_callback,
                            precomputed_uncertain_carving_ranges,
                            uncertain_carving_ranges_truncated,
                            phase_callback,
                            raw_candidate_references,
                            raw_session_candidate_limit,
                            raw_session_retained_byte_limit,
                            raw_candidate_data,
                            raw_candidate_locations,
                            volume.partition_offset,
                            volume.partition_offset + volume.partition_size,
                            volume.cluster_size,
                        )
                    )
                nodes = builder.nodes
            recovery_catalog = self._to_recovery_catalog(
                nodes, builder.root_nodes, source, volume, volume_id,
            )
            snapshot = RecoveryCatalogSnapshot(
                catalog=recovery_catalog,
                source=source,
                source_id=source_id,
                volume_id=volume_id,
                filesystem_id="ntfs",
                orphan_scan_performed=bool(include_orphaned),
                content_carving_summary=content_carving_summary,
                parent_reference_issue_count=int(builder.parent_reference_issue_count),
                low_confidence_carving_summary=low_confidence_carving_summary,
                recycle_bin_summary=recycle_bin_summary,
                usn_journal_summary=usn_journal_summary,
                ntfs_log_file_summary=ntfs_log_file_summary,
            )
            builder.release_source_tree()
            if not defer_content_reference_commit:
                self.content_reference_store.commit_catalog()
            return snapshot
        except Exception:
            self.content_reference_store.abort_catalog()
            raise
        finally:
            disk.close()

    @staticmethod
    def _volume_identity(source_id, volume):
        identity = [
            source_id,
            "ntfs",
            int(volume.partition_number),
            int(volume.partition_size),
            str(volume.partition_name or "").casefold(),
        ]
        encoded = json.dumps(identity, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _to_recovery_catalog(self, source_nodes, source_roots, source, volume, volume_id):
        source_id = source.source_id
        used_node_ids = set()
        converted = {}
        for source_node in source_nodes.values():
            record = source_node.record
            is_directory = bool(record.is_dir)
            properties = self._catalog_properties(source_node, record)
            candidate = None
            if not is_directory:
                resident_data = getattr(record, "resident_data", None)
                digest = hashlib.sha256(bytes(resident_data)).hexdigest() if resident_data is not None else None
                logical_identity = getattr(record, "original_path", None)
                if not logical_identity and not self._is_generated_recovery_path(source_node.full_path):
                    logical_identity = source_node.full_path
                if not logical_identity and digest is None:
                    candidate_id = uuid.uuid4().hex
                else:
                    candidate_id = stable_candidate_id(
                        source_id,
                        volume_id,
                        logical_identity,
                        int(record.file_size),
                        digest,
                    )
                if candidate_id in used_node_ids:
                    candidate_id = uuid.uuid4().hex
                used_node_ids.add(candidate_id)
                allocation = self._allocation_state(record)
                fragment_reconstruction = bool(
                    getattr(source_node, "is_fragment_reconstructed", False)
                )
                complete = bool(getattr(record, "data_is_complete", False))
                valid = bool(getattr(record, "is_valid", True))
                consistent = getattr(record, "is_metadata_consistent", True)
                reference = ContentReference(
                    reference_id=candidate_id,
                    source_id=source_id,
                    size_bytes=int(record.file_size),
                    sha256=digest,
                )
                self.content_reference_store.register(
                    candidate_id, source, volume, source_node,
                )
                provenance = getattr(record, "fragment_reconstruction_evidence", None)
                if fragment_reconstruction and isinstance(provenance, dict):
                    evidence = RecoveryEvidence(
                        "fragment_reconstruction",
                        str(provenance.get("strategy", "png_idat")),
                        tuple(sorted((
                            ("signatureOffset", provenance.get("signatureOffset")),
                            ("sourceOffsets", ",".join(map(
                                str, provenance.get("sourceRanges", ()),
                            ))),
                            ("validation", provenance.get("validation")),
                        ))),
                    )
                else:
                    evidence = RecoveryEvidence(
                        "filesystem_metadata",
                        str(getattr(record, "recovery_source", None) or "ntfs"),
                        tuple(sorted((
                            ("recordNumber", getattr(record, "index", None)),
                            ("sequenceNumber", getattr(record, "sequence_number", None)),
                            ("physicalOffset", getattr(record, "mft_offset", None)),
                        ))),
                    )
                candidate = RecoveryCandidate(
                    candidate_id=candidate_id,
                    source_id=source_id,
                    volume_id=volume_id,
                    name=record.name,
                    original_path=getattr(record, "original_path", None),
                    size_bytes=int(record.file_size),
                    filesystem_id="ntfs",
                    discovery_methods=(self._discovery_method(source_node),),
                    evidence=(evidence,),
                    deletion_state=(
                        "unknown" if fragment_reconstruction else
                        "deleted" if not getattr(record, "is_allocated", True) else "not_deleted"
                    ),
                    allocation_state=allocation,
                    integrity_state=(
                        "unknown" if fragment_reconstruction else
                        "validated" if valid and consistent is not False else "partial"
                    ),
                    recoverability=("recoverable" if complete else "partial"),
                    content_reference=reference,
                )
                node_id = candidate_id
            else:
                node_id = self._folder_identity(source_id, volume_id, source_node.full_path)
                if node_id in used_node_ids:
                    node_id = "folder:" + uuid.uuid4().hex
                used_node_ids.add(node_id)
            converted[id(source_node)] = CatalogNode(
                node_id=node_id,
                name=record.name,
                full_path=source_node.full_path,
                is_directory=is_directory,
                size_bytes=int(record.file_size),
                candidate=candidate,
                properties=properties,
            )

        for source_node in source_nodes.values():
            node = converted[id(source_node)]
            node.parent = converted.get(id(source_node.parent)) if source_node.parent else None
            node.children.extend(
                converted[id(child)] for child in source_node.children
                if id(child) in converted
            )
        by_id = {node.node_id: node for node in converted.values()}
        roots = [converted[id(node)] for node in source_roots if id(node) in converted]
        return RecoveryCatalog(by_id, roots)

    @staticmethod
    def _folder_identity(source_id, volume_id, path):
        payload = json.dumps(
            [source_id, volume_id, os.path.normcase(path).replace("\\", "/").casefold()],
            separators=(",", ":"),
        ).encode("utf-8")
        return "folder:" + hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _is_generated_recovery_path(path):
        normalized = str(path).replace("\\", "/").casefold()
        return normalized.startswith("lost_files_deepscan/")

    @staticmethod
    def _discovery_method(node):
        if getattr(node, "is_fragment_reconstructed", False):
            return "fragment_reconstruction"
        if getattr(node, "is_content_carved", False):
            return "content_carving"
        if getattr(node, "is_orphaned", False):
            return "orphan_mft"
        return "filesystem_metadata"

    @staticmethod
    def _allocation_state(record):
        evidence = getattr(record, "cluster_allocation_evidence", None)
        status = evidence.get("status") if isinstance(evidence, dict) else None
        status = status or getattr(record, "cluster_allocation_status", None)
        return status if status in {"free", "allocated", "mixed"} else "unknown"

    @classmethod
    def _catalog_properties(cls, node, record):
        extent_resolution = getattr(record, "data_extent_resolution", None)
        raw_allocation = getattr(record, "cluster_allocation_status", None)
        allocation_evidence = getattr(record, "cluster_allocation_evidence", None)
        if isinstance(allocation_evidence, dict):
            raw_allocation = allocation_evidence.get("status") or raw_allocation
        if raw_allocation not in {
            "free", "allocated", "mixed", "unknown", "bitmap_unobserved", "possibly_reused",
        }:
            raw_allocation = cls._allocation_state(record)
        return {
            "isDeleted": not bool(getattr(record, "is_allocated", True)),
            "isOrphaned": bool(getattr(node, "is_orphaned", False)),
            "isContentCarved": bool(getattr(node, "is_content_carved", False)),
            "contentValidation": getattr(record, "catalog_content_validation", None),
            "clusterAllocationStatus": raw_allocation,
            "metadataConsistent": getattr(record, "is_metadata_consistent", None),
            "recoverySource": getattr(record, "recovery_source", None),
            "originalPath": getattr(record, "original_path", None),
            "deletionTimestampUtc": getattr(record, "deletion_timestamp_utc", None),
            "originalSizeBytes": getattr(record, "recycle_bin_original_size_bytes", None),
            "dataExtentResolution": extent_resolution,
            "dataExtentResolutionReason": getattr(record, "data_extent_resolution_reason", None),
            "dataExtentCount": getattr(record, "data_extent_count", None),
            "fragmentReconstruction": getattr(record, "fragment_reconstruction_evidence", None),
        }

    def _scan_content_carving(
        self, disk, builder, ranges, ranges_truncated, options, checkpoint,
        checkpoint_callback, uncertain_ranges, uncertain_ranges_truncated,
        phase_callback, raw_candidate_references=None, raw_session_candidate_limit=None,
        raw_session_retained_byte_limit=None, raw_candidate_data=None,
        raw_candidate_locations=None, volume_start=0, volume_end=None, cluster_size=4096,
    ):
        """Run trusted and bounded low-confidence carving passes for one volume."""
        carver_options = {}
        if options is not None:
            candidate_read_bytes_per_format = (
                int(getattr(options, "max_candidate_read_mib_per_format", 256))
                * 1024**2
            )
            carver_options = {
                "max_scan_bytes": int(options.scan_budget_gib) * 1024**3,
                "max_files": min(
                    int(options.max_files), int(raw_session_candidate_limit),
                ) if raw_session_candidate_limit is not None else int(options.max_files),
                "max_total_file_bytes": int(
                    getattr(options, "max_retained_mib", 128)
                ) * 1024**2,
                "max_candidate_read_bytes_per_format": candidate_read_bytes_per_format,
                "max_candidate_read_bytes": candidate_read_bytes_per_format * 3,
            }
        if raw_session_retained_byte_limit is not None:
            carver_options["max_total_file_bytes"] = min(
                carver_options.get("max_total_file_bytes", 128 * 1024**2),
                int(raw_session_retained_byte_limit),
            )
        reconstruction_enabled = bool(getattr(
            options, "enable_png_fragment_reconstruction", False,
        ))
        if reconstruction_enabled:
            from infrastructure.carving.png_idat_fragment_reconstructor import (
                PNGIDATFragmentReconstructor,
            )

        carving = RawContentCarver(disk, **carver_options).scan(
            ranges,
            progress_callback=self._phase_progress(phase_callback, "content_carving"),
            resume_checkpoint=checkpoint,
            retained_candidates=raw_candidate_references,
            retained_candidate_data=raw_candidate_data,
            candidate_restore_ranges=(
                tuple(ranges) + tuple(
                    interval
                    for intervals in (uncertain_ranges or {}).values()
                    for interval in intervals
                ) if raw_candidate_references is not None else None
            ),
            require_all_retained_candidates=raw_candidate_references is not None,
            checkpoint_callback=checkpoint_callback,
            ranges_truncated=bool(ranges_truncated),
            collect_png_signatures=reconstruction_enabled,
        )
        candidate_catalog = CarvedCandidateCatalog(
            builder,
            disk.size,
            max_files=raw_session_candidate_limit,
            max_retained_bytes=raw_session_retained_byte_limit,
            retained_candidate_data=raw_candidate_data,
            retained_candidate_locations=raw_candidate_locations,
        )
        candidate_catalog.add(carving.files, ("Lost_Files_DeepScan", "ContentCarving"))
        reconstruction_summary = None
        if reconstruction_enabled:
            signature_offsets = carving.png_signature_offsets
            signatures = tuple(
                offset for offset in signature_offsets
                if not any(item.offset == offset and item.extension == ".png" for item in carving.files)
            )
            reconstruction = PNGIDATFragmentReconstructor(
                disk,
                volume_start=volume_start,
                volume_end=volume_end,
                cluster_size=cluster_size,
            ).reconstruct(signatures, ranges)
            candidate_catalog.add(
                reconstruction.candidates,
                ("Lost_Files_DeepScan", "PNGFragmentHypotheses"),
                allocation_status="free",
            )
            reconstruction_summary = {
                "enabled": True,
                "strategy": "aligned_complete_idat_chunks",
                "signaturesSeen": len(signature_offsets),
                "signaturesExamined": reconstruction.signatures_examined,
                "signatureDiscoveryComplete": (
                    carving.checkpoint is None and not carving.scan_limit_reached
                    and not carving.png_signature_set_truncated
                    and not ranges_truncated
                ),
                "candidatesFound": len(reconstruction.candidates),
                "structuralHypotheses": len(reconstruction.candidates),
                "signaturesRejected": (
                    max(0, reconstruction.signatures_examined - len({
                        item.evidence.get("signatureOffset")
                        for item in reconstruction.candidates if item.evidence
                    })) if reconstruction.stop_reason == "search_exhausted" else None
                ),
                "combinationsEvaluated": reconstruction.combinations,
                "bytesRead": reconstruction.bytes_read,
                "elapsedSeconds": reconstruction.elapsed_seconds,
                "retainedBytesEstimate": reconstruction.retained_bytes_estimate,
                "retainedMemoryDefinition": (
                    "Estimated search frontier, compressed payloads, hypotheses and "
                    "metadata plus an 8 MiB transient validation buffer allowance; not RSS"
                ),
                "stopReason": reconstruction.stop_reason,
                "searchScope": (
                    "Up to four observed PNG signatures; complete IDAT chunks at cluster-aligned "
                    "starts within the trusted free ranges; up to four IDAT chunks plus IEND"
                ),
                "integrity": "unknown_without_independent_original_hash",
                "limits": {
                    "combinationsPerPass": PNGIDATFragmentReconstructor.PAIRS_PER_PASS,
                    "passes": PNGIDATFragmentReconstructor.MAX_PASSES,
                    "combinations": PNGIDATFragmentReconstructor.PAIRS_PER_PASS
                    * PNGIDATFragmentReconstructor.MAX_PASSES,
                    "bytesReadPerPass": PNGIDATFragmentReconstructor.READS_PER_PASS,
                    "bytesRead": PNGIDATFragmentReconstructor.READS_PER_PASS
                    * PNGIDATFragmentReconstructor.MAX_PASSES,
                    "candidateBytes": PNGIDATFragmentReconstructor.MAX_CANDIDATE_BYTES,
                    "secondsPerPass": PNGIDATFragmentReconstructor.SECONDS_PER_PASS,
                    "seconds": PNGIDATFragmentReconstructor.SECONDS_PER_PASS
                    * PNGIDATFragmentReconstructor.MAX_PASSES,
                    "retainedBytes": PNGIDATFragmentReconstructor.RETAINED_BYTES,
                },
            }
            status_counts = {}
            for candidate in reconstruction.candidates:
                status = (candidate.evidence or {}).get("hypothesisStatus", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
            reconstruction_summary["hypothesesByStatus"] = status_counts
        budget_gib = options.scan_budget_gib if options is not None else 1
        retained_budget_mib = (
            getattr(options, "max_retained_mib", 128) if options is not None else 128
        )
        trusted_summary = {
            "filesFound": len(carving.files),
            **self._format_metrics(carving),
            "candidateReadCapBytes": carving.candidate_read_cap_bytes,
            "candidateReadCapBytesPerFormat": carving.candidate_read_cap_bytes_per_format,
            "maxFileBytes": carving.max_file_bytes,
            "maxDecodedPngBytes": carving.max_decoded_png_bytes,
            "scanByteCap": carving.max_scan_bytes,
            "scanBudgetGiB": budget_gib,
            "rangeCollectionCapBytes": budget_gib * 1024**3,
            "retainedBudgetMiB": retained_budget_mib,
            "rangeBytesRetained": sum(end - start for start, end in ranges),
            "retainedBytesCap": carving.max_total_file_bytes,
            "fileCountCap": carving.max_files,
            "bytesScanned": carving.bytes_scanned,
            "cumulativeBytesScanned": carving.cumulative_bytes_scanned,
            "resumeAvailable": carving.checkpoint is not None,
            "candidateRestoreBytesRead": carving.candidate_restore_bytes_read,
            "scanLimitReached": carving.scan_limit_reached,
            "candidateBytesRead": carving.candidate_bytes_read,
            "candidateLimitReached": carving.candidate_limit_reached,
            "fileCountLimitReached": carving.file_count_limit_reached,
            "retainedBytesLimitReached": carving.retained_bytes_limit_reached,
            "rangeCount": len(ranges),
            "rangeCollectionTruncated": bool(ranges_truncated),
            "confidence": "trusted_free_space",
            "stopReason": self._carving_stop_reason(
                carving, ranges_truncated,
                session_limit_reached=(candidate_catalog.session_limit_reached
                    or (carving.file_count_limit_reached
                        and raw_session_candidate_limit is not None
                        and carving.max_files == int(raw_session_candidate_limit))
                    or (carving.retained_bytes_limit_reached
                        and raw_session_retained_byte_limit is not None
                        and carving.max_total_file_bytes == int(raw_session_retained_byte_limit))),
            ),
        }
        if reconstruction_summary is not None:
            trusted_summary["pngFragmentReconstruction"] = reconstruction_summary
            if (carving.png_signature_set_truncated
                    or len(signature_offsets) > PNGIDATFragmentReconstructor.MAX_SIGNATURES):
                trusted_summary["pngFragmentReconstruction"]["signatureSetTruncated"] = True
                if trusted_summary["pngFragmentReconstruction"]["stopReason"] == "search_exhausted":
                    trusted_summary["pngFragmentReconstruction"]["stopReason"] = "signature_limit"
        low_confidence_summary = None
        if uncertain_ranges is not None:
            low_confidence_summary = self._scan_low_confidence_ranges(
                disk,
                candidate_catalog,
                uncertain_ranges,
                uncertain_ranges_truncated or {},
                phase_callback,
            )
            if candidate_catalog.session_limit_reached:
                trusted_summary["stopReason"] = "session_limit"
                trusted_summary["sessionLimitReached"] = True
        return trusted_summary, low_confidence_summary

    def _scan_low_confidence_ranges(
        self, disk, candidate_catalog, uncertain_ranges, truncation, phase_callback,
    ):
        summary = {}
        passes = (
            ("bitmapUnobserved", "bitmap_unobserved", "BitmapUnobserved",
             "content_carving_unobserved"),
            ("possiblyReused", "possibly_reused", "PossiblyReused",
             "content_carving_reused"),
        )
        for key, allocation_status, folder_name, phase_name in passes:
            ranges = tuple(uncertain_ranges.get(key, ()))
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
                progress_callback=self._phase_progress(phase_callback, phase_name),
            )
            added = candidate_catalog.add(
                low_carving.files,
                ("Lost_Files_DeepScan", "LowConfidence", folder_name),
                allocation_status=allocation_status,
            )
            summary[key] = self._carving_summary(
                low_carving,
                ranges,
                bool(truncation.get(key, False)),
                confidence="low",
                allocation_status=allocation_status,
                catalog_items_added=added,
            )
            summary[key]["rangeBytesRetained"] = sum(
                end - start for start, end in ranges
            )
            summary[key]["rangeCollectionCapBytes"] = (
                ClusterAllocationEvidence.DEFAULT_UNCERTAIN_RANGE_BYTES
            )
            if candidate_catalog.session_limit_reached:
                summary[key]["stopReason"] = "session_limit"
                summary[key]["sessionLimitReached"] = True
        return summary

    @staticmethod
    def _phase_progress(phase_callback, phase_name):
        if phase_callback is None:
            return None

        def report(completed, total):
            phase_callback(phase_name, completed, total)

        return report

    @staticmethod
    def supported_extensions():
        from infrastructure.recovery.extractor import Extractor

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
    def _add_recycle_bin_aliases(builder, reader):
        """Expose supported, size-matched $R data under generated safe paths."""
        from infrastructure.recovery.extractor import Extractor

        supported = {extension.casefold() for extension in Extractor.supported_extensions()}
        helper = RecycleBinRecoveryHelper()

        def read_index(node, _max_bytes):
            return b"".join(reader.iter_chunks(node))

        recycle_bin_nodes = tuple(
            node for node in builder.nodes.values()
            if has_path_component(node, "$Recycle.Bin")
        )
        associations = helper.associate(recycle_bin_nodes, read_index)
        counts = {
            "indexCount": len(associations),
            "aliasesAdded": 0,
            "pairedCount": 0,
            "missingContentCount": 0,
            "ambiguousContentCount": 0,
            "metadataMismatchCount": 0,
            "invalidIndexCount": 0,
            "readErrorCount": 0,
            "limitedIndexCount": 0,
            "incompleteContentCount": 0,
            "unsupportedExtensionCount": 0,
            "directoryContentCount": 0,
        }
        inconclusive_statuses = {
            "missing_content", "ambiguous", "metadata_mismatch", "invalid_index",
            "read_error", "incomplete", "limited", "unpaired",
        }
        inconclusive = not associations
        for association in associations:
            status_key = {
                "missing_content": "missingContentCount",
                "ambiguous": "ambiguousContentCount",
                "metadata_mismatch": "metadataMismatchCount",
                "invalid_index": "invalidIndexCount",
                "read_error": "readErrorCount",
                "incomplete": "invalidIndexCount",
                "limited": "limitedIndexCount",
                "unpaired": "invalidIndexCount",
            }.get(association.status)
            if status_key is not None:
                counts[status_key] += 1
            if association.status in inconclusive_statuses:
                inconclusive = True
            if association.status != "paired" or association.content_node is None:
                continue

            counts["pairedCount"] += 1
            source_record = association.content_node.record
            if bool(getattr(source_record, "is_dir", False)):
                counts["directoryContentCount"] += 1
                continue
            if getattr(source_record, "data_is_complete", True) is False:
                counts["incompleteContentCount"] += 1
                inconclusive = True
                continue

            extension = os.path.splitext(association.metadata.name or "")[1].casefold()
            if extension not in supported:
                counts["unsupportedExtensionCount"] += 1
                continue
            if not association.target_name:
                counts["invalidIndexCount"] += 1
                inconclusive = True
                continue

            alias_record = copy.copy(source_record)
            alias_record.name = association.target_name
            alias_record.recovery_source = "recycle_bin"
            alias_record.original_path = association.metadata.original_path
            alias_record.deletion_timestamp_utc = (
                association.metadata.timestamp_utc.isoformat()
                if association.metadata.timestamp_utc is not None else None
            )
            alias_record.recycle_bin_original_size_bytes = association.metadata.size_bytes
            source_index = int(getattr(source_record, "index", 0) or 0)
            synthetic_id = -(abs(source_index) + 1)
            while synthetic_id in builder.nodes:
                synthetic_id -= 1
            alias_record.index = synthetic_id
            alias_node = FileNode(alias_record)
            alias_node.is_recycle_bin_alias = True
            alias_node.full_path = os.path.join(
                "Lost_Files_DeepScan", "RecycleBin", association.target_name,
            )
            builder.nodes[synthetic_id] = alias_node
            builder.root_nodes.append(alias_node)
            counts["aliasesAdded"] += 1

        status = "inconclusive" if inconclusive else "complete"
        return {
            "status": status,
            "inconclusive": inconclusive,
            "reason": "no_recycle_bin_index_found" if not associations else None,
            **counts,
        }

    @staticmethod
    def _scan_usn_journal(nodes, reader):
        """Summarize bounded USN metadata without exposing journal events."""
        try:
            evidence = UsnJournalEvidenceScanner().scan(nodes, reader.read_named_stream)
        except Exception:
            return {
                "status": "inconclusive",
                "inconclusive": True,
                "journalCount": 0,
                "streamCount": 0,
                "bytesRead": 0,
                "recordsExamined": 0,
                "parsedRecords": 0,
                "deletedEvents": 0,
                "malformedRecords": 0,
                "limitReached": False,
                "errorCount": 1,
            }, ()

        scans = [item.scan for item in evidence if item.scan is not None]
        inconclusive = any(item.status != "complete" for item in evidence)
        summary = {
            "status": "inconclusive" if inconclusive else "complete",
            "inconclusive": inconclusive,
            "journalCount": sum(item.journal_node is not None for item in evidence),
            "streamCount": len(scans),
            "bytesRead": sum(item.bytes_read for item in evidence),
            "recordsExamined": sum(item.records_examined for item in scans),
            "parsedRecords": sum(len(item.artifacts) for item in scans),
            "deletedEvents": sum(
                artifact.indicates_delete
                for scan in scans for artifact in scan.artifacts
            ),
            "malformedRecords": sum(item.malformed_records for item in scans),
            "limitReached": any(
                item.status == "partial" or item.scan is not None and item.scan.limit_reached
                for item in evidence
            ),
            "errorCount": sum(item.status in {"read_error", "invalid_stream"} for item in evidence),
        }
        delete_events = tuple(
            artifact for item in evidence for artifact in item.events
            if artifact.indicates_delete
        )
        return summary, delete_events

    @staticmethod
    def _format_metrics(carving):
        """Build the shared per-format diagnostics for every carving tier."""
        return {
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
        }

    @staticmethod
    def _carving_summary(
        carving, ranges, range_collection_truncated, *, confidence, allocation_status,
        catalog_items_added,
    ):
        return {
            "filesFound": len(carving.files),
            **CatalogBuilder._format_metrics(carving),
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
            "stopReason": CatalogBuilder._carving_stop_reason(
                carving, range_collection_truncated,
            ),
        }

    @staticmethod
    def _carving_stop_reason(carving, ranges_truncated, session_limit_reached=False):
        """Separate session caps, resource caps, exhausted budgets and completion."""
        if session_limit_reached:
            return "session_limit"
        per_format_candidate_limit = any(
            item.candidate_limit_reached for item in carving.format_stats
        )
        if (carving.candidate_limit_reached or carving.file_count_limit_reached
                or carving.retained_bytes_limit_reached or per_format_candidate_limit):
            return "resource_limit"
        if carving.scan_limit_reached:
            return "budget_exhausted"
        if ranges_truncated:
            return "range_collection_truncated"
        return "scope_complete"

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



class CarvedCandidateCatalog:
    """Keep carving deduplication and synthetic-node construction in one place."""

    def __init__(self, builder, disk_size, max_files=None, max_retained_bytes=None,
                 retained_candidate_data=None, retained_candidate_locations=None):
        self.builder = builder
        self.disk_size = int(disk_size)
        self.max_files = None if max_files is None else max(0, int(max_files))
        self.max_retained_bytes = (
            None if max_retained_bytes is None else max(0, int(max_retained_bytes))
        )
        self.retained_candidate_data = retained_candidate_data or {}
        self.retained_candidate_locations = retained_candidate_locations or {}
        self.content_digests = set()
        self.physical_offsets = set()
        self.added_count = 0
        self.retained_bytes = 0
        self.session_limit_reached = False
        self.reconstruction_offsets = {}

    def add(self, candidates, path_parts, allocation_status=None):
        added = 0
        for candidate in candidates:
            digest = hashlib.sha256(candidate.data).digest()
            offset = int(candidate.offset)
            is_reconstructed = candidate.strategy == "png_fragment_reconstruction"
            if digest in self.content_digests or (
                not is_reconstructed and offset in self.physical_offsets
            ):
                continue
            content = self.retained_candidate_data.get((offset, digest.hex()), candidate.data)
            if (self.max_files is not None and self.added_count >= self.max_files
                    or self.max_retained_bytes is not None
                    and self.retained_bytes + len(content) > self.max_retained_bytes):
                self.session_limit_reached = True
                continue
            self.content_digests.add(digest)
            self.physical_offsets.add(offset)

            retained_location = self.retained_candidate_locations.get(
                (offset, digest.hex()),
            )
            candidate_path_parts, candidate_allocation_status = (
                retained_location if retained_location is not None
                else (path_parts, allocation_status)
            )

            synthetic_id = -(self.disk_size + offset + 1)
            while synthetic_id in self.builder.nodes:
                synthetic_id -= 1
            if is_reconstructed:
                alternative = self.reconstruction_offsets.get(offset, 0) + 1
                self.reconstruction_offsets[offset] = alternative
                name = f"Carved_{offset:016X}_Hypothesis_{alternative}{candidate.extension}"
            else:
                name = f"Carved_{offset:016X}{candidate.extension}"
            record = CarvedContentRecord(
                index=synthetic_id,
                offset=offset,
                name=name,
                resident_data=content,
                cluster_allocation_status=candidate_allocation_status or "free",
                catalog_content_validation=(
                    "fragment_structure_hypothesis" if is_reconstructed
                    else "format_structure_match"
                ),
                catalog_content_validation_reason=(
                    "PNG structure checks passed for a fragment reconstruction hypothesis; "
                    "the original file integrity is unknown"
                    if is_reconstructed else
                    "Contiguous format structure passed validation; allocation "
                    "is unknown or may describe current/reused data"
                    if allocation_status is not None else
                    "Contiguous file structure and format markers passed validation"
                ),
                fragment_reconstruction_evidence=(
                    dict(candidate.evidence or {}) if is_reconstructed else None
                ),
            )
            node = FileNode(record, is_orphaned=True, is_content_carved=True)
            node.is_fragment_reconstructed = is_reconstructed
            node.full_path = os.path.join(*candidate_path_parts, record.name)
            self.builder.nodes[synthetic_id] = node
            self.builder.root_nodes.append(node)
            added += 1
            self.added_count += 1
            self.retained_bytes += len(content)
        return added


@dataclass(frozen=True)
class CandidateContentValidation:
    """Bounded signature evidence gathered while building the catalog."""

    status: str
    reason: str


class CatalogContentValidator:
    """Check only the header window; full file/container validation stays in extraction."""

    def __init__(self, disk, volume_start, volume_end, cluster_size):
        self.disk = disk
        self.volume_start = int(volume_start)
        self.volume_end = int(volume_end)
        self.cluster_size = int(cluster_size)

    def validate(self, record):
        extension = self._extension(record.name)
        if extension not in FileSignatureValidator.supported_extensions():
            return CandidateContentValidation("unsupported", "No signature rule is available")
        if not getattr(record, "data_is_complete", True):
            return CandidateContentValidation("incomplete_metadata", "MFT data attributes are incomplete")

        size = int(record.file_size)
        if size <= 0:
            return CandidateContentValidation("invalid_size", "File has no content bytes")
        window_size = min(size, FileSignatureValidator.header_window(extension))
        try:
            header = self._read_prefix(record, window_size)
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            return CandidateContentValidation("unavailable", str(exc))

        if len(header) != window_size:
            return CandidateContentValidation("unavailable", "File data runs ended before the signature window")
        if not FileSignatureValidator.matches(extension, header):
            return CandidateContentValidation("signature_mismatch", "File header does not match its extension")
        return CandidateContentValidation("signature_match", "File header matches its extension")

    def _read_prefix(self, record, size):
        resident_data = getattr(record, "resident_data", None)
        if resident_data is not None:
            return bytes(resident_data[:size])

        runs = tuple(getattr(record, "data_runs", ()))
        if not runs:
            raise ValueError("No data runs are available")
        if self.cluster_size <= 0:
            raise ValueError("Invalid NTFS cluster size")

        header = bytearray()
        remaining = size
        for lcn, cluster_count in runs:
            if remaining <= 0:
                break
            cluster_count = int(cluster_count)
            if cluster_count <= 0:
                raise ValueError("A data run has a non-positive length")
            run_size = min(cluster_count * self.cluster_size, remaining)
            if lcn is None:
                header.extend(bytes(run_size))
            else:
                run_start = self.volume_start + int(lcn) * self.cluster_size
                run_end = run_start + run_size
                if run_start < self.volume_start or run_end > self.volume_end:
                    raise ValueError("A file data run is outside the selected volume")
                chunk = self.disk.read_at(run_start, run_size)
                if len(chunk) != run_size:
                    raise OSError(f"Short header read at {run_start:#x}: {len(chunk)} of {run_size} bytes")
                header.extend(chunk)
            remaining -= run_size
        return bytes(header)

    @staticmethod
    def _extension(name):
        return os.path.splitext(str(name))[1].casefold()
