"""Coordinate the disk audit, evidence handoff and catalog build command flow."""

import hashlib
import json
from contextlib import nullcontext
from dataclasses import dataclass, replace

from modules.catalog.entities import RecoveryCatalogSnapshot


@dataclass(frozen=True)
class CatalogScanOutcome:
    snapshot: RecoveryCatalogSnapshot
    validation_summary: dict[str, object] | None


class CatalogScanWorkflow:
    """Coordinate catalog scanning while keeping command handling at the boundary."""

    CHECKPOINT_INTERVAL_BYTES = 256 * 1024 * 1024

    RAW_CHECKPOINT_IDENTITY_VERSION = 3
    MAX_CONTINUATION_PASSES = 4

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
        session_source_id=None,
        cancellation_requested=None,
        source_identity_validator=None,
    ) -> CatalogScanOutcome:
        """Run a bounded number of compatible session pages in one catalog request."""
        if (not include_orphaned or self.session is None or not session_source_id):
            return self._run_page(
                volume,
                include_orphaned=include_orphaned,
                force_fresh_validation=force_fresh_validation,
                carving_options=carving_options,
                progress_callback=progress_callback,
                validation_progress_callback=validation_progress_callback,
                phase_callback=phase_callback,
                session_source_id=session_source_id,
            )

        continuation_source_id = str(session_source_id)
        if not continuation_source_id:
            return self._run_page(
                volume,
                include_orphaned=include_orphaned,
                force_fresh_validation=force_fresh_validation,
                carving_options=carving_options,
                progress_callback=progress_callback,
                validation_progress_callback=validation_progress_callback,
                phase_callback=phase_callback,
            )

        owner_key = self._raw_checkpoint_owner(volume)
        range_scope_key = self._session_range_scope_key(
            continuation_source_id, volume, carving_options,
        )
        latest = None
        passes = 0
        stop_reason = "scope_complete"
        operation_budget_usage = None
        with self.session.catalog_scan_operation():
            while passes < self.MAX_CONTINUATION_PASSES:
                if source_identity_validator is not None and not source_identity_validator():
                    raise ValueError("Selected partition belongs to a different storage source; rescan it")

                previous_progress = self.session.load_scan_range_progress(
                    owner_key, range_scope_key,
                )
                if operation_budget_usage is None:
                    operation_budget_usage = {
                        "scanBaseline": int((previous_progress or {}).get("totalScanBytes", 0)),
                        "scanThisOperation": 0,
                        "candidateBaseline": int((previous_progress or {}).get(
                            "totalCandidateBytesRead", 0,
                        )),
                        "candidateThisOperation": 0,
                        "restoreBaseline": int((previous_progress or {}).get(
                            "totalCandidateRestoreBytesRead", 0,
                        )),
                        "restoreThisOperation": 0,
                    }
                start_index = int((previous_progress or {}).get("nextRangeIndex", 0))
                latest = self._run_page(
                    volume,
                    include_orphaned=include_orphaned,
                    force_fresh_validation=force_fresh_validation,
                    carving_options=carving_options,
                    progress_callback=progress_callback,
                    validation_progress_callback=validation_progress_callback,
                    phase_callback=phase_callback,
                    session_source_id=continuation_source_id,
                    operation_budget_usage=operation_budget_usage,
                    abort_on_validation_error=True,
                )
                passes += 1
                summary = latest.snapshot.content_carving_summary or {}
                operation_budget_usage["scanThisOperation"] += max(
                    0, int(summary.get("bytesScanned", 0)),
                )
                operation_budget_usage["candidateThisOperation"] += max(
                    0, int(summary.get("candidateBytesRead", 0)),
                )
                operation_budget_usage["restoreThisOperation"] += max(
                    0, int(summary.get("candidateRestoreBytesRead", 0)),
                )
                if cancellation_requested is not None and cancellation_requested():
                    stop_reason = "cancelled"
                    break
                page = summary.get("rangePage") or {}
                current_progress = self.session.load_scan_range_progress(
                    owner_key, range_scope_key,
                )
                actual_start_index = int(page.get("rangeWindowStartIndex", start_index))
                if (previous_progress and current_progress
                        and previous_progress.get("bitmapSha256")
                        != current_progress.get("bitmapSha256")):
                    # A changed allocation bitmap invalidates the old cursor;
                    # compare progress against the page actually rescanned.
                    actual_start_index = 0
                next_index = int((current_progress or {}).get("nextRangeIndex", start_index))
                pending = int((current_progress or {}).get(
                    "pendingRangeCount", page.get("pendingRangeCount", 0),
                ))
                cap_stalled = self._range_collection_byte_cap_stalled(
                    latest.snapshot,
                )
                png_stop = str((summary.get("pngFragmentReconstruction") or {}).get(
                    "stopReason", "",
                ))
                if png_stop in {
                    "signature_limit", "combination_limit", "read_limit", "time_limit",
                    "memory_limit", "cumulative_combination_limit",
                    "cumulative_time_limit",
                }:
                    stop_reason = "resource_limit"
                    break
                if png_stop in {"read_error", "search_error", "range_error"}:
                    stop_reason = "error"
                    break
                if (summary.get("stopReason") == "advanced_recovery_pending"
                        and pending <= 0):
                    stop_reason = "advanced_recovery_pending"
                    break
                page_resource_limited = any(bool(summary.get(key)) for key in (
                    "scanLimitReached", "candidateLimitReached",
                    "fileCountLimitReached", "retainedBytesLimitReached",
                ))
                if page_resource_limited:
                    stop_reason = "resource_limit"
                    break
                if pending <= 0 and page.get("collectionScopeComplete", True):
                    stop_reason = "scope_complete"
                    break
                if not current_progress:
                    stop_reason = "cursor_unavailable"
                    break
                if cap_stalled or next_index <= actual_start_index:
                    stop_reason = "non_progress"
                    break
            else:
                stop_reason = "pass_limit"

        if latest is None:
            raise RuntimeError("Catalog continuation stopped before publishing a page")
        final_summary = dict(latest.snapshot.content_carving_summary or {})
        final_summary["continuation"] = {
            "passes": passes,
            "stopReason": stop_reason,
            "pendingRangeCount": int((
                self.session.load_scan_range_progress(owner_key, range_scope_key) or {}
            ).get("pendingRangeCount", (latest.snapshot.content_carving_summary or {}).get(
                "rangePage", {},
            ).get("pendingRangeCount", 0))),
            "maxPasses": self.MAX_CONTINUATION_PASSES,
        }
        final_snapshot = replace(latest.snapshot, content_carving_summary=final_summary)
        self.session.replace_scan_catalog_snapshot(
            owner_key, latest.snapshot, final_snapshot,
        )
        return CatalogScanOutcome(final_snapshot, latest.validation_summary)

    def _run_page(
        self,
        volume,
        *,
        include_orphaned,
        force_fresh_validation,
        carving_options,
        progress_callback,
        validation_progress_callback,
        phase_callback,
        session_source_id=None,
        operation_budget_usage=None,
        abort_on_validation_error=False,
    ) -> CatalogScanOutcome:
        """Audit one bounded evidence page, then publish its catalog generation."""
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
        png_recovery_progress = None
        range_scope_key = None
        range_progress = None
        range_progress_invalidated = False
        range_start_index = 0
        bitmap_sha256 = None
        carving_range_progress = {}
        session_source_id = str(
            session_source_id or getattr(volume, "source_id", "") or "",
        )
        session_source = None
        source = None
        if session_source_id and self.session is not None:
            session_source = self._session_source_metadata(volume, session_source_id)
            range_scope_key = self._session_range_scope_key(
                session_source_id, volume, carving_options,
                source_size=int(session_source.size_bytes),
                source_bytes_per_sector=int(session_source.bytes_per_sector),
            )
            range_progress = self.session.load_scan_range_progress(
                self._raw_checkpoint_owner(volume), range_scope_key,
            )
            if range_progress is not None:
                range_start_index = int(range_progress.get("nextRangeIndex", 0))

        if include_orphaned:
            try:
                validation_options = {}
                if force_fresh_validation:
                    validation_options["force_fresh"] = True
                validate_source = getattr(volume, "source_id", None)
                if validate_source:
                    source = self.catalog_builder.source_factory.get_source(volume.source_id)
                    carving_source = source
                    range_kwargs = ({
                        "content_carving_range_start_index": range_start_index,
                    } if range_start_index else {})
                    report = self.validation_service.validate_source(
                        source,
                        validation_progress_callback,
                        retain_orphans_for_offset=int(volume.partition_offset),
                        orphan_scan_volume=volume,
                        content_carving_range_budget_bytes=self._remaining_scan_budget_bytes(
                            carving_options, range_progress, operation_budget_usage,
                        ),
                        **range_kwargs,
                    )
                else:
                    range_kwargs = ({
                        "content_carving_range_start_index": range_start_index,
                    } if range_start_index else {})
                    report = self.validation_service.validate_disk(
                        volume.disk_number,
                        validation_progress_callback,
                        retain_orphans_for_offset=int(volume.partition_offset),
                        orphan_scan_volume=volume,
                        content_carving_range_budget_bytes=self._remaining_scan_budget_bytes(
                            carving_options, range_progress, operation_budget_usage,
                        ),
                        **validation_options,
                        **range_kwargs,
                    )
                check = next((
                    item for item in report.get("ntfs_checks", ())
                    if int(item.get("partitionOffset", -1)) == int(volume.partition_offset)
                ), {})
                bitmap_sha256 = (check.get("bitmapAllocation") or {}).get("bitmapSha256")
                carving_range_progress = dict(
                    check.get("contentCarvingRangeProgress") or {},
                )
                if bitmap_sha256:
                    carving_range_progress["bitmapSha256"] = bitmap_sha256
                expected_bitmap_sha256 = (range_progress or {}).get("bitmapSha256")
                if (range_start_index and expected_bitmap_sha256
                        and bitmap_sha256 != expected_bitmap_sha256):
                    # The allocation map changed. Discard the stale cursor and
                    # recollect the first window before any carving is performed.
                    range_start_index = 0
                    range_progress = None
                    range_progress_invalidated = True
                    range_kwargs = {"content_carving_range_start_index": 0}
                    if source is not None:
                        report = self.validation_service.validate_source(
                            source,
                            validation_progress_callback,
                            retain_orphans_for_offset=int(volume.partition_offset),
                            orphan_scan_volume=volume,
                            content_carving_range_budget_bytes=(
                                self._remaining_scan_budget_bytes(
                                    carving_options, None, operation_budget_usage,
                                )
                            ),
                            **range_kwargs,
                        )
                    else:
                        report = self.validation_service.validate_disk(
                            volume.disk_number,
                            validation_progress_callback,
                            retain_orphans_for_offset=int(volume.partition_offset),
                            orphan_scan_volume=volume,
                            content_carving_range_budget_bytes=(
                                self._remaining_scan_budget_bytes(
                                    carving_options, None, operation_budget_usage,
                                )
                            ),
                            **validation_options,
                            **range_kwargs,
                        )
                    check = next((
                        item for item in report.get("ntfs_checks", ())
                        if int(item.get("partitionOffset", -1)) == int(volume.partition_offset)
                    ), {})
                    bitmap_sha256 = (check.get("bitmapAllocation") or {}).get("bitmapSha256")
                    carving_range_progress = dict(
                        check.get("contentCarvingRangeProgress") or {},
                    )
                    if bitmap_sha256:
                        carving_range_progress["bitmapSha256"] = bitmap_sha256
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
                if abort_on_validation_error:
                    raise
                validation_summary = self._unavailable_validation_summary(exc)

        source_id = str(getattr(volume, "source_id", "") or "")
        session_cataloging = bool(
            include_orphaned and precomputed_carving_ranges is not None
            and session_source_id and self.session is not None
        )
        checkpoint_scope = (
            self.session.catalog_scan_operation() if session_cataloging else nullcontext()
        )
        with checkpoint_scope:
            raw_candidate_references = None
            raw_candidate_data = None
            raw_candidate_locations = None
            raw_catalog_snapshot = None
            raw_session_candidate_limit = None
            raw_session_retained_byte_limit = None
            page_carving_options = carving_options
            candidate_restore_budget_bytes = None
            cached_generation_invalidated = False
            persist_legacy_physical_checkpoint = False
            legacy_physical_disk = None
            if session_cataloging:
                latest_range_progress = (
                    range_progress if range_progress_invalidated else
                    self.session.load_scan_range_progress(
                        self._raw_checkpoint_owner(volume), range_scope_key,
                    )
                )
                progress_changed_under_lock = latest_range_progress != range_progress
                if progress_changed_under_lock:
                    # Validation ran before the session scan lock. A concurrent
                    # scan may have advanced the page while this operation waited.
                    range_progress = latest_range_progress
                    range_start_index = int(
                        (range_progress or {}).get("nextRangeIndex", 0),
                    )
                if source_id:
                    if progress_changed_under_lock and not range_progress_invalidated:
                        # Another raw-image scan published while this command
                        # waited; re-audit only when the selected page changed.
                        report = self.validation_service.validate_source(
                            carving_source,
                            validation_progress_callback,
                            retain_orphans_for_offset=int(volume.partition_offset),
                            orphan_scan_volume=volume,
                            content_carving_range_budget_bytes=(
                                self._remaining_scan_budget_bytes(
                                    carving_options, range_progress, operation_budget_usage,
                                )
                            ),
                            content_carving_range_start_index=range_start_index,
                        )
                        check = next((
                            item for item in report.get("ntfs_checks", ())
                            if int(item.get("partitionOffset", -1))
                            == int(volume.partition_offset)
                        ), {})
                        bitmap_sha256 = (
                            (check.get("bitmapAllocation") or {}).get("bitmapSha256")
                        )
                        carving_range_progress = dict(
                            check.get("contentCarvingRangeProgress") or {},
                        )
                        if bitmap_sha256:
                            carving_range_progress["bitmapSha256"] = bitmap_sha256
                        validation_summary = self.validation_service.summary(report)
                        partition_offset = int(volume.partition_offset)
                        precomputed_orphans = report.get(
                            "orphan_records_by_partition", {},
                        ).get(partition_offset)
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
                elif progress_changed_under_lock and not range_progress_invalidated:
                    # Physical sessions hold the workflow lock across this
                    # validation and page build. Refresh only when a concurrent
                    # operation advanced the cursor before the lock was acquired.
                    report = self.validation_service.validate_disk(
                        volume.disk_number,
                        validation_progress_callback,
                        retain_orphans_for_offset=int(volume.partition_offset),
                        orphan_scan_volume=volume,
                        content_carving_range_budget_bytes=(
                            self._remaining_scan_budget_bytes(
                                carving_options, range_progress, operation_budget_usage,
                            )
                        ),
                        content_carving_range_start_index=range_start_index,
                    )
                    check = next((
                        item for item in report.get("ntfs_checks", ())
                        if int(item.get("partitionOffset", -1))
                        == int(volume.partition_offset)
                    ), {})
                    bitmap_sha256 = (
                        (check.get("bitmapAllocation") or {}).get("bitmapSha256")
                    )
                    carving_range_progress = dict(
                        check.get("contentCarvingRangeProgress") or {},
                    )
                    if bitmap_sha256:
                        carving_range_progress["bitmapSha256"] = bitmap_sha256
                    if (range_start_index and range_progress
                            and bitmap_sha256 != range_progress.get("bitmapSha256")):
                        range_progress = None
                        range_start_index = 0
                        range_progress_invalidated = True
                        range_kwargs = {
                            "content_carving_range_budget_bytes": (
                                self._remaining_scan_budget_bytes(
                                    carving_options, None, operation_budget_usage,
                                )
                            ),
                            "content_carving_range_start_index": 0,
                        }
                        if source is not None:
                            report = self.validation_service.validate_source(
                                source, validation_progress_callback,
                                retain_orphans_for_offset=int(volume.partition_offset),
                                orphan_scan_volume=volume,
                                **range_kwargs,
                            )
                        else:
                            report = self.validation_service.validate_disk(
                                volume.disk_number, validation_progress_callback,
                                retain_orphans_for_offset=int(volume.partition_offset),
                                orphan_scan_volume=volume,
                                **range_kwargs,
                            )
                        check = next((
                            item for item in report.get("ntfs_checks", ())
                            if int(item.get("partitionOffset", -1))
                            == int(volume.partition_offset)
                        ), {})
                        bitmap_sha256 = (
                            (check.get("bitmapAllocation") or {}).get("bitmapSha256")
                        )
                        carving_range_progress = dict(
                            check.get("contentCarvingRangeProgress") or {},
                        )
                        if bitmap_sha256:
                            carving_range_progress["bitmapSha256"] = bitmap_sha256
                    validation_summary = self.validation_service.summary(report)
                    partition_offset = int(volume.partition_offset)
                    precomputed_orphans = report.get(
                        "orphan_records_by_partition", {},
                    ).get(partition_offset)
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
                page_carving_options = self._remaining_candidate_budget_options(
                    carving_options, range_progress, operation_budget_usage,
                )
                if not source_id:
                    candidate_restore_budget_bytes = self._remaining_candidate_restore_budget(
                        carving_options, range_progress, operation_budget_usage,
                    )
                carving_profile = self.catalog_builder.carving_checkpoint_profile()
                checkpoint_owner = self._raw_checkpoint_owner(volume)
                checkpoint_identity = self._scan_checkpoint_identity(
                session_source, volume, precomputed_carving_ranges,
                    carving_ranges_truncated, carving_options, carving_profile,
                    bitmap_sha256=bitmap_sha256,
                )
                raw_catalog_snapshot = self.session.get_scan_catalog(
                    checkpoint_owner, checkpoint_identity,
                )
                if raw_catalog_snapshot is not None:
                    stop_reason = (raw_catalog_snapshot.content_carving_summary or {}).get(
                        "stopReason",
                    )
                    if (stop_reason in {"scope_complete", "session_limit", "resource_limit"}
                            or self._range_collection_byte_cap_stalled(raw_catalog_snapshot)):
                        png_strategies_enabled = bool(
                            getattr(carving_options, "enable_png_fragment_reconstruction", False)
                        )
                        if (png_strategies_enabled
                                and raw_catalog_snapshot.png_recovery_progress is not None):
                            still_current, fragment_validation_bytes = (
                                self.catalog_builder.raw_png_recovery_results_are_current(
                                    carving_source or session_source,
                                    raw_catalog_snapshot,
                                    precomputed_carving_ranges,
                                    volume_start=int(volume.partition_offset),
                                    volume_end=(int(volume.partition_offset)
                                                + int(volume.partition_size)),
                                )
                            )
                            if still_current:
                                if fragment_validation_bytes:
                                    previous_progress = raw_catalog_snapshot.png_recovery_progress
                                    updated_progress = replace(
                                        previous_progress,
                                        reconstruction_bytes_read=(
                                            previous_progress.reconstruction_bytes_read
                                            + fragment_validation_bytes
                                        ),
                                    )
                                    updated_summary = dict(
                                        raw_catalog_snapshot.content_carving_summary or {},
                                    )
                                    if fragment_validation_bytes:
                                        fragment_summary = dict(
                                            updated_summary.get("pngFragmentReconstruction") or {},
                                        )
                                        fragment_summary["bytesRead"] = (
                                            updated_progress.reconstruction_bytes_read
                                        )
                                        updated_summary["pngFragmentReconstruction"] = fragment_summary
                                    validated_snapshot = replace(
                                        raw_catalog_snapshot,
                                        png_recovery_progress=updated_progress,
                                        content_carving_summary=updated_summary,
                                    )
                                    self.session.update_raw_catalog_snapshot(
                                        checkpoint_owner,
                                        checkpoint_identity,
                                        raw_catalog_snapshot,
                                        validated_snapshot,
                                    )
                                    raw_catalog_snapshot = validated_snapshot
                                return CatalogScanOutcome(raw_catalog_snapshot, validation_summary)
                            # Same source identity and size do not prove the bytes
                            # remain unchanged; rebuild without reusing stale results.
                            raw_catalog_snapshot = None
                            cached_generation_invalidated = True
                            stale_range_progress = range_progress
                            range_progress = None
                            range_start_index = 0
                            range_progress_invalidated = True
                            if int((stale_range_progress or {}).get("nextRangeIndex", 0)) > 0:
                                refresh_kwargs = {
                                    "retain_orphans_for_offset": int(volume.partition_offset),
                                    "orphan_scan_volume": volume,
                                    "content_carving_range_budget_bytes": (
                                        self._remaining_scan_budget_bytes(
                                            carving_options, None, operation_budget_usage,
                                        )
                                    ),
                                    "content_carving_range_start_index": 0,
                                }
                                if source is not None:
                                    report = self.validation_service.validate_source(
                                        source,
                                        validation_progress_callback,
                                        **refresh_kwargs,
                                    )
                                else:
                                    report = self.validation_service.validate_disk(
                                        volume.disk_number,
                                        validation_progress_callback,
                                        **refresh_kwargs,
                                    )
                                check = next((
                                    item for item in report.get("ntfs_checks", ())
                                    if int(item.get("partitionOffset", -1))
                                    == int(volume.partition_offset)
                                ), {})
                                bitmap_sha256 = (
                                    (check.get("bitmapAllocation") or {}).get("bitmapSha256")
                                )
                                carving_range_progress = dict(
                                    check.get("contentCarvingRangeProgress") or {},
                                )
                                if bitmap_sha256:
                                    carving_range_progress["bitmapSha256"] = bitmap_sha256
                                validation_summary = self.validation_service.summary(report)
                                partition_offset = int(volume.partition_offset)
                                precomputed_orphans = report.get(
                                    "orphan_records_by_partition", {},
                                ).get(partition_offset)
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
                        else:
                            return CatalogScanOutcome(raw_catalog_snapshot, validation_summary)
                    if raw_catalog_snapshot is not None:
                        png_recovery_progress = raw_catalog_snapshot.png_recovery_progress
                        raw_candidate_references, raw_candidate_data, raw_candidate_locations = (
                            self.catalog_builder.raw_candidate_state(raw_catalog_snapshot)
                        )

                carving_checkpoint = (
                    None if cached_generation_invalidated else
                    self.session.load_scan_checkpoint(checkpoint_owner, checkpoint_identity)
                )
                latest_carving_checkpoint = carving_checkpoint
                persist_legacy_physical_checkpoint = bool(
                    not source_id
                    and raw_catalog_snapshot is None
                    and range_progress is None
                    and range_start_index == 0
                    and not carving_ranges_truncated
                    and not carving_range_progress.get("truncated", False)
                    and int(carving_range_progress.get("pendingRangeCount", 0)) == 0
                )
                if persist_legacy_physical_checkpoint:
                    legacy_physical_disk = self.disk_service.get_disk(volume.disk_number)
                    if carving_checkpoint is None:
                        carving_checkpoint = self.deep_scan_service.load_carving_checkpoint(
                            legacy_physical_disk, volume,
                        )
                        latest_carving_checkpoint = carving_checkpoint
                remaining_candidates, remaining_retained_bytes = (
                    self.session.scan_catalog_capacity(checkpoint_owner)
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

                def retain_session_checkpoint(checkpoint, force=False):
                    nonlocal latest_carving_checkpoint
                    latest_carving_checkpoint = checkpoint

                carving_checkpoint_callback = retain_session_checkpoint
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
                        "carving_options": page_carving_options,
                        "carving_checkpoint": carving_checkpoint,
                        "carving_checkpoint_callback": carving_checkpoint_callback,
                        "phase_callback": phase_callback,
                    }
                    if session_cataloging:
                        build_options.update({
                            "raw_candidate_references": raw_candidate_references,
                            "raw_session_candidate_limit": raw_session_candidate_limit,
                            "raw_session_retained_byte_limit": (
                                raw_session_retained_byte_limit
                            ),
                            "raw_candidate_data": raw_candidate_data,
                            "raw_candidate_locations": raw_candidate_locations,
                            "defer_content_reference_commit": True,
                        "png_recovery_progress": png_recovery_progress,
                        "previous_raw_catalog_snapshot": raw_catalog_snapshot,
                        "png_scope_identity": checkpoint_identity,
                        "raw_range_progress": range_progress,
                        "range_page_progress": carving_range_progress,
                        "range_scope_key": range_scope_key,
                        "range_start_index": range_start_index,
                            "candidate_restore_budget_bytes": candidate_restore_budget_bytes,
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
                if session_cataloging:
                    self.catalog_builder.content_reference_store.abort_catalog()
                else:
                    self._flush_latest_checkpoint(
                        latest_carving_checkpoint,
                        carving_checkpoint_callback,
                    )
                raise

            if session_cataloging:
                try:
                    committed_range_progress = self._next_raw_range_progress(
                        range_scope_key,
                        range_progress,
                        carving_range_progress,
                        snapshot.content_carving_summary or {},
                        bitmap_sha256,
                        operation_budget_usage=operation_budget_usage,
                    )
                    if persist_legacy_physical_checkpoint:
                        # Preserve the existing single-page physical resume contract.
                        # Multi-page continuation stays session-only because its cursor
                        # is not represented by the legacy physical checkpoint format.
                        self.deep_scan_service.save_carving_checkpoint(
                            legacy_physical_disk, volume, latest_carving_checkpoint,
                        )
                    self.session.commit_scan_generation(
                        checkpoint_owner,
                        checkpoint_identity,
                        snapshot,
                        latest_carving_checkpoint,
                        self.catalog_builder.content_reference_store,
                        range_progress=committed_range_progress,
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

    def _scan_checkpoint_identity(self, source, volume, ranges, ranges_truncated,
                                  carving_options, carving_profile, *, bitmap_sha256=None):
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
            "allocationEvidenceIdentity": self._raw_range_identity(
                bitmap_sha256, ranges, ranges_truncated,
            ),
            "carverProfile": carving_profile,
            "candidateOptions": {
                "scanBudgetGiB": int(getattr(carving_options, "scan_budget_gib", 1)),
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

    def _raw_checkpoint_identity(self, source, volume, ranges, ranges_truncated,
                                 carving_options, carving_profile, *, bitmap_sha256=None):
        """Compatibility alias for callers that still name the raw session cursor."""
        return self._scan_checkpoint_identity(
            source, volume, ranges, ranges_truncated, carving_options, carving_profile,
            bitmap_sha256=bitmap_sha256,
        )

    @staticmethod
    def _raw_range_identity(bitmap_sha256, ranges, ranges_truncated):
        if bitmap_sha256:
            return {"bitmapSha256": str(bitmap_sha256)}
        return {
            "eligibleRanges": sorted((int(start), int(end)) for start, end in ranges),
            "rangesTruncated": bool(ranges_truncated),
        }

    @staticmethod
    def _range_collection_byte_cap_stalled(snapshot):
        """Stop replaying a truncated run when the collector has no inner cursor."""
        summary = getattr(snapshot, "content_carving_summary", None) or {}
        page = summary.get("rangePage") or {}
        return (
            summary.get("stopReason") == "range_collection_truncated"
            and bool(page.get("byteLimitReached"))
            and int(page.get("pendingRangeCount", 0)) > 0
        )

    @staticmethod
    def _remaining_scan_budget_bytes(carving_options, range_progress,
                                    operation_budget_usage=None):
        configured = max(0, int(getattr(carving_options, "scan_budget_gib", 1))) * 1024**3
        consumed = max(0, int((range_progress or {}).get("totalScanBytes", 0)))
        if operation_budget_usage:
            consumed = max(
                consumed,
                int(operation_budget_usage.get("scanBaseline", 0))
                + int(operation_budget_usage.get("scanThisOperation", 0)),
            )
        return max(0, configured - consumed)

    @staticmethod
    def _remaining_candidate_budget_options(carving_options, range_progress,
                                            operation_budget_usage=None):
        if carving_options is None:
            return None
        per_format_mib = int(getattr(
            carving_options, "max_candidate_read_mib_per_format", 256,
        ))
        configured_aggregate = per_format_mib * 3 * 1024**2
        consumed = max(0, int((range_progress or {}).get("totalCandidateBytesRead", 0)))
        if operation_budget_usage:
            consumed = max(
                consumed,
                int(operation_budget_usage.get("candidateBaseline", 0))
                + int(operation_budget_usage.get("candidateThisOperation", 0)),
            )
        remaining_per_format = max(0, configured_aggregate - consumed) // (3 * 1024**2)
        return replace(
            carving_options,
            max_candidate_read_mib_per_format=min(per_format_mib, remaining_per_format),
        )

    @staticmethod
    def _remaining_candidate_restore_budget(carving_options, range_progress,
                                            operation_budget_usage=None):
        configured_per_format = int(getattr(
            carving_options, "max_candidate_read_mib_per_format", 256,
        ))
        configured_aggregate = configured_per_format * 3 * 1024**2
        consumed = max(0, int((range_progress or {}).get(
            "totalCandidateRestoreBytesRead", 0,
        )))
        if operation_budget_usage:
            consumed = max(
                consumed,
                int(operation_budget_usage.get("restoreBaseline", 0))
                + int(operation_budget_usage.get("restoreThisOperation", 0)),
            )
        return max(0, configured_aggregate - consumed)

    def _session_source_metadata(self, volume, source_id):
        """Resolve source identity without changing the volume's access modality."""
        if getattr(volume, "source_id", None):
            source = self.catalog_builder.source_factory.get_source(volume.source_id)
        else:
            disk = self.disk_service.get_disk(volume.disk_number)
            source_factory = getattr(disk, "as_storage_source", None)
            if not callable(source_factory):
                raise ValueError("Physical disk identity is unavailable for session continuation")
            source = source_factory(volume.bytes_per_sector)
        if source.source_id != source_id:
            raise ValueError("Selected partition belongs to a different storage source; rescan it")
        return source

    def _session_range_scope_key(
        self, source_id, volume, carving_options, *, source_size=None,
        source_bytes_per_sector=None,
    ):
        """Bind in-session paging to source, volume geometry and recovery options."""
        source = None
        if source_size is None or source_bytes_per_sector is None:
            source = self._session_source_metadata(volume, source_id)
        payload = {
            "version": 1,
            "sourceId": source_id,
            "sourceSize": int(source_size if source_size is not None else source.size_bytes),
            "sourceBytesPerSector": int(
                source_bytes_per_sector if source_bytes_per_sector is not None
                else source.bytes_per_sector
            ),
            "partitionNumber": int(volume.partition_number),
            "partitionOffset": int(volume.partition_offset),
            "partitionSize": int(volume.partition_size),
            "bytesPerSector": int(volume.bytes_per_sector),
            "clusterSize": int(volume.cluster_size),
            "recordSize": int(volume.record_size),
            "scanBudgetGiB": int(getattr(carving_options, "scan_budget_gib", 1)),
            "maxFiles": int(getattr(carving_options, "max_files", 16384)),
            "maxRetainedMiB": int(getattr(carving_options, "max_retained_mib", 128)),
            "maxCandidateReadMiBPerFormat": int(getattr(
                carving_options, "max_candidate_read_mib_per_format", 256,
            )),
            "pngReconstruction": bool(getattr(
                carving_options, "enable_png_fragment_reconstruction", False,
            )),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _raw_range_scope_key(self, source, volume, carving_options):
        """Compatibility alias for the historical raw-range scope helper."""
        return self._session_range_scope_key(
            source.source_id, volume, carving_options,
            source_size=int(getattr(source, "size_bytes", getattr(source, "size", 0))),
            source_bytes_per_sector=int(getattr(source, "bytes_per_sector", 512)),
        )

    @staticmethod
    def _next_raw_range_progress(scope_key, previous, page, summary, bitmap_sha256,
                                 *, operation_budget_usage=None):
        if not scope_key or not bitmap_sha256 or not page:
            return None
        previous = previous or {}
        scanned_before = int(previous.get("totalScanBytes", 0))
        scanned_now = max(0, int(summary.get("bytesScanned", 0)))
        candidate_bytes_before = int(previous.get("totalCandidateBytesRead", 0))
        candidate_bytes_now = max(0, int(summary.get("candidateBytesRead", 0)))
        restore_bytes_before = int(previous.get("totalCandidateRestoreBytesRead", 0))
        restore_bytes_now = max(0, int(summary.get("candidateRestoreBytesRead", 0)))
        if operation_budget_usage:
            scanned_before = max(
                scanned_before,
                int(operation_budget_usage.get("scanBaseline", 0))
                + int(operation_budget_usage.get("scanThisOperation", 0)),
            )
            candidate_bytes_before = max(
                candidate_bytes_before,
                int(operation_budget_usage.get("candidateBaseline", 0))
                + int(operation_budget_usage.get("candidateThisOperation", 0)),
            )
            restore_bytes_before = max(
                restore_bytes_before,
                int(operation_budget_usage.get("restoreBaseline", 0))
                + int(operation_budget_usage.get("restoreThisOperation", 0)),
            )
        stop_reason = str(summary.get("stopReason", ""))
        page_complete = (
            scanned_now >= int(summary.get("rangeBytesRetained", 0))
            and not summary.get("scanLimitReached", False)
            and not summary.get("candidateLimitReached", False)
            and not summary.get("fileCountLimitReached", False)
            and not summary.get("retainedBytesLimitReached", False)
            and stop_reason not in {
                "session_limit", "resource_limit", "budget_exhausted",
            }
        )
        next_index = page.get("nextRangeIndex")
        pending_ranges = int(page.get("pendingRangeCount", 0))
        if (page_complete and pending_ranges > 0 and next_index is not None
                and not page.get("byteLimitReached", False)):
            cursor = int(next_index)
        elif (page_complete and pending_ranges == 0
              and not page.get("truncated", False)
              and not page.get("byteLimitReached", False)):
            return None
        else:
            cursor = int(previous.get(
                "nextRangeIndex", page.get("rangeWindowStartIndex", 0),
            ))
        return {
            "scopeKey": scope_key,
            "bitmapSha256": str(bitmap_sha256),
            "nextRangeIndex": cursor,
            "totalScanBytes": scanned_before + scanned_now,
            "totalCandidateBytesRead": candidate_bytes_before + candidate_bytes_now,
            "totalCandidateRestoreBytesRead": restore_bytes_before + restore_bytes_now,
            "pendingRangeCount": pending_ranges,
            "stopReason": stop_reason or "incomplete_page",
        }

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
