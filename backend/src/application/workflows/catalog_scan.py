"""Coordinate the disk audit, evidence handoff and catalog build command flow."""

import hashlib
import json
from contextlib import nullcontext
from dataclasses import dataclass

from modules.catalog.entities import RecoveryCatalogSnapshot


@dataclass(frozen=True)
class CatalogScanOutcome:
    snapshot: RecoveryCatalogSnapshot
    validation_summary: dict[str, object] | None


class CatalogScanWorkflow:
    """Coordinate catalog scanning while keeping command handling at the boundary."""

    CHECKPOINT_INTERVAL_BYTES = 256 * 1024 * 1024

    RAW_CHECKPOINT_IDENTITY_VERSION = 1

    def __init__(self, disk_service, deep_scan_service, validation_service, catalog_builder,
                 session=None):
        self.disk_service = disk_service
        self.deep_scan_service = deep_scan_service
        self.validation_service = validation_service
        self.catalog_builder = catalog_builder
        self.session = session

    def run(
        self,
        volume,
        *,
        include_orphaned,
        force_fresh_validation,
        carving_options,
        progress_callback,
        validation_progress_callback,
        phase_callback,
    ) -> CatalogScanOutcome:
        """Audit first, hand off its evidence, then build and checkpoint the catalog."""
        validation_summary = None
        precomputed_orphans = None
        precomputed_carving_ranges = None
        carving_ranges_truncated = False
        precomputed_uncertain_carving_ranges = None
        uncertain_carving_ranges_truncated = None
        carving_source_disk = None
        carving_source = None
        carving_checkpoint = None
        latest_carving_checkpoint = None
        carving_checkpoint_callback = None

        if include_orphaned:
            try:
                validation_options = {}
                if force_fresh_validation:
                    validation_options["force_fresh"] = True
                validate_source = getattr(volume, "source_id", None)
                if validate_source:
                    source = self.catalog_builder.source_factory.get_source(volume.source_id)
                    carving_source = source
                    report = self.validation_service.validate_source(
                        source,
                        validation_progress_callback,
                        retain_orphans_for_offset=int(volume.partition_offset),
                        orphan_scan_volume=volume,
                        content_carving_range_budget_bytes=(
                            int(carving_options.scan_budget_gib) * 1024**3
                        ),
                    )
                else:
                    report = self.validation_service.validate_disk(
                        volume.disk_number,
                        validation_progress_callback,
                        retain_orphans_for_offset=int(volume.partition_offset),
                        orphan_scan_volume=volume,
                        content_carving_range_budget_bytes=(
                            int(carving_options.scan_budget_gib) * 1024**3
                        ),
                        **validation_options,
                    )
                validation_summary = self.validation_service.summary(report)
                partition_offset = int(volume.partition_offset)
                precomputed_orphans = report.get("orphan_records_by_partition", {}).get(
                    partition_offset,
                )
                precomputed_carving_ranges = report.get(
                    "content_carving_ranges_by_partition", {},
                ).get(partition_offset)
                carving_ranges_truncated = report.get(
                    "content_carving_ranges_truncated_by_partition", {},
                ).get(partition_offset, False)
                precomputed_uncertain_carving_ranges = report.get(
                    "uncertain_content_carving_ranges_by_partition", {},
                ).get(partition_offset)
                uncertain_carving_ranges_truncated = report.get(
                    "uncertain_content_carving_ranges_truncated_by_partition", {},
                ).get(partition_offset)
            except Exception as exc:
                validation_summary = self._unavailable_validation_summary(exc)

        source_id = str(getattr(volume, "source_id", "") or "")
        raw_checkpointing = bool(
            include_orphaned and precomputed_carving_ranges is not None
            and source_id and self.session is not None
        )
        checkpoint_scope = (
            self.session.raw_carving_operation() if raw_checkpointing else nullcontext()
        )
        with checkpoint_scope:
            raw_candidate_references = None
            raw_candidate_data = None
            raw_candidate_locations = None
            raw_catalog_snapshot = None
            raw_session_candidate_limit = None
            raw_session_retained_byte_limit = None
            if raw_checkpointing:
                carving_profile = self.catalog_builder.carving_checkpoint_profile()
                checkpoint_owner = self._raw_checkpoint_owner(volume)
                checkpoint_identity = self._raw_checkpoint_identity(
                    carving_source, volume, precomputed_carving_ranges,
                    carving_ranges_truncated, carving_options, carving_profile,
                )
                raw_catalog_snapshot = self.session.get_raw_catalog(
                    checkpoint_owner, checkpoint_identity,
                )
                if raw_catalog_snapshot is not None:
                    stop_reason = (raw_catalog_snapshot.content_carving_summary or {}).get(
                        "stopReason",
                    )
                    if stop_reason in {"scope_complete", "session_limit", "resource_limit"}:
                        return CatalogScanOutcome(raw_catalog_snapshot, validation_summary)
                    raw_candidate_references, raw_candidate_data, raw_candidate_locations = (
                        self.catalog_builder.raw_candidate_state(raw_catalog_snapshot)
                    )

                carving_checkpoint = self.session.load_raw_carving_checkpoint(
                    checkpoint_owner, checkpoint_identity,
                )
                latest_carving_checkpoint = carving_checkpoint
                remaining_candidates, remaining_retained_bytes = (
                    self.session.raw_catalog_capacity(checkpoint_owner)
                )
                configured_candidate_limit = int(getattr(carving_options, "max_files", 16384))
                raw_session_candidate_limit = min(
                    configured_candidate_limit,
                    remaining_candidates,
                )
                configured_retained_bytes = int(getattr(
                    carving_options, "max_retained_mib", 128,
                )) * 1024**2
                raw_session_retained_byte_limit = min(
                    configured_retained_bytes,
                    remaining_retained_bytes,
                )

                def persist_raw_checkpoint(checkpoint, force=False):
                    nonlocal latest_carving_checkpoint
                    latest_carving_checkpoint = checkpoint

                carving_checkpoint_callback = persist_raw_checkpoint
            elif (include_orphaned and precomputed_carving_ranges is not None
                    and not source_id):
                carving_source_disk = self.disk_service.get_disk(volume.disk_number)
                carving_checkpoint = self.deep_scan_service.load_carving_checkpoint(
                    carving_source_disk, volume,
                )
                latest_carving_checkpoint = carving_checkpoint
                last_persisted_bytes = (
                    carving_checkpoint.bytes_scanned if carving_checkpoint is not None else 0
                )

                def persist_physical_checkpoint(checkpoint, force=False):
                    nonlocal latest_carving_checkpoint, last_persisted_bytes
                    latest_carving_checkpoint = checkpoint
                    if checkpoint is None:
                        self.deep_scan_service.save_carving_checkpoint(
                            carving_source_disk, volume, None,
                        )
                        last_persisted_bytes = 0
                    elif (force or checkpoint.bytes_scanned - last_persisted_bytes
                          >= self.CHECKPOINT_INTERVAL_BYTES):
                        self.deep_scan_service.save_carving_checkpoint(
                            carving_source_disk, volume, checkpoint,
                        )
                        last_persisted_bytes = checkpoint.bytes_scanned

                carving_checkpoint_callback = persist_physical_checkpoint

            try:
                if include_orphaned:
                    build_options = {
                        "include_orphaned": True,
                        "precomputed_orphans": precomputed_orphans,
                        "precomputed_carving_ranges": precomputed_carving_ranges,
                        "carving_ranges_truncated": carving_ranges_truncated,
                        "precomputed_uncertain_carving_ranges": (
                            precomputed_uncertain_carving_ranges
                        ),
                        "uncertain_carving_ranges_truncated": (
                            uncertain_carving_ranges_truncated
                        ),
                        "carving_options": carving_options,
                        "carving_checkpoint": carving_checkpoint,
                        "carving_checkpoint_callback": carving_checkpoint_callback,
                        "phase_callback": phase_callback,
                    }
                    if raw_checkpointing:
                        build_options.update({
                            "raw_candidate_references": raw_candidate_references,
                            "raw_session_candidate_limit": raw_session_candidate_limit,
                            "raw_session_retained_byte_limit": (
                                raw_session_retained_byte_limit
                            ),
                            "raw_candidate_data": raw_candidate_data,
                            "raw_candidate_locations": raw_candidate_locations,
                            "defer_content_reference_commit": True,
                        })
                    snapshot = self.catalog_builder.build(
                        volume,
                        progress_callback,
                        **build_options,
                    )
                else:
                    snapshot = self.catalog_builder.build(
                        volume,
                        progress_callback,
                        phase_callback=phase_callback,
                    )
            except Exception:
                if raw_checkpointing:
                    self.catalog_builder.content_reference_store.abort_catalog()
                else:
                    self._flush_latest_checkpoint(
                        latest_carving_checkpoint,
                        carving_checkpoint_callback,
                    )
                raise

            if raw_checkpointing:
                try:
                    self.session.commit_raw_catalog_generation(
                        checkpoint_owner,
                        checkpoint_identity,
                        snapshot,
                        latest_carving_checkpoint,
                        self.catalog_builder.content_reference_store,
                    )
                except Exception:
                    self.catalog_builder.content_reference_store.abort_catalog()
                    raise
            else:
                self._flush_latest_checkpoint(
                    latest_carving_checkpoint,
                    carving_checkpoint_callback,
                )
            return CatalogScanOutcome(snapshot, validation_summary)

    def _raw_checkpoint_identity(self, source, volume, ranges, ranges_truncated,
                                 carving_options, carving_profile):
        candidate_read_mib = int(getattr(
            carving_options, "max_candidate_read_mib_per_format", 256,
        ))
        payload = {
            "version": self.RAW_CHECKPOINT_IDENTITY_VERSION,
            "sourceId": source.source_id,
            "sourceSize": int(source.size_bytes),
            "sourceBytesPerSector": int(source.bytes_per_sector),
            "volume": {
                "partitionNumber": int(volume.partition_number),
                "partitionOffset": int(volume.partition_offset),
                "partitionSize": int(volume.partition_size),
                "bytesPerSector": int(volume.bytes_per_sector),
                "clusterSize": int(volume.cluster_size),
                "recordSize": int(volume.record_size),
                "mftOffset": int(volume.mft_offset),
                "mftSize": int(volume.mft_size),
            },
            "eligibleRanges": sorted((int(start), int(end)) for start, end in ranges),
            "rangesTruncated": bool(ranges_truncated),
            "carverProfile": carving_profile,
            "candidateOptions": {
                "maxFiles": int(getattr(carving_options, "max_files", 16384)),
                "maxRetainedBytes": int(getattr(
                    carving_options, "max_retained_mib", 128,
                )) * 1024**2,
                "maxCandidateReadBytesPerFormat": candidate_read_mib * 1024**2,
                "maxCandidateReadBytes": candidate_read_mib * 3 * 1024**2,
                "enablePngFragmentReconstruction": bool(getattr(
                    carving_options, "enable_png_fragment_reconstruction", False,
                )),
                "sessionMaxCandidates": int(getattr(
                    self.session, "MAX_RAW_SESSION_CANDIDATES", 16384,
                )),
                "sessionMaxRetainedBytes": int(getattr(
                    self.session, "MAX_RAW_SESSION_RETAINED_BYTES", 512 * 1024**2,
                )),
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _raw_checkpoint_owner(volume):
        return int(volume.partition_number), int(volume.partition_offset)

    @staticmethod
    def _flush_latest_checkpoint(checkpoint, checkpoint_callback):
        if checkpoint is not None and checkpoint_callback is not None:
            checkpoint_callback(checkpoint, force=True)

    @staticmethod
    def _unavailable_validation_summary(exc):
        return {
            "coverageStatus": "unavailable",
            "assessment": "inconclusive",
            "bytesRead": 0,
            "sizeBytes": 0,
            "readErrorCount": 0,
            "partitionCount": 0,
            "ntfsVolumeCount": 0,
            "deletedMftRecordCount": 0,
            "orphanedFileRecordCount": 0,
            "unsupportedFilesystems": [],
            "validationError": f"{type(exc).__name__}: {exc}",
        }
