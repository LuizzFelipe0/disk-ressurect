"""Coordinate the disk audit, evidence handoff and catalog build command flow."""

from dataclasses import dataclass

from modules.catalog.entities import RecoveryCatalogSnapshot


@dataclass(frozen=True)
class CatalogScanOutcome:
    snapshot: RecoveryCatalogSnapshot
    validation_summary: dict[str, object] | None


class CatalogScanWorkflow:
    """Coordinate catalog scanning while keeping command handling at the boundary."""

    CHECKPOINT_INTERVAL_BYTES = 256 * 1024 * 1024

    def __init__(self, disk_service, deep_scan_service, validation_service, catalog_builder):
        self.disk_service = disk_service
        self.deep_scan_service = deep_scan_service
        self.validation_service = validation_service
        self.catalog_builder = catalog_builder

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
        carving_checkpoint = None
        latest_carving_checkpoint = None
        carving_checkpoint_callback = None

        if include_orphaned:
            try:
                validation_options = {}
                if force_fresh_validation:
                    validation_options["force_fresh"] = True
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

        if include_orphaned and precomputed_carving_ranges is not None:
            carving_source_disk = self.disk_service.get_disk(volume.disk_number)
            carving_checkpoint = self.deep_scan_service.load_carving_checkpoint(
                carving_source_disk, volume,
            )
            latest_carving_checkpoint = carving_checkpoint
            last_persisted_bytes = (
                carving_checkpoint.bytes_scanned if carving_checkpoint is not None else 0
            )

            def persist_carving_checkpoint(checkpoint, force=False):
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

            carving_checkpoint_callback = persist_carving_checkpoint

        try:
            if include_orphaned:
                snapshot = self.catalog_builder.build(
                    volume,
                    progress_callback,
                    include_orphaned=True,
                    precomputed_orphans=precomputed_orphans,
                    precomputed_carving_ranges=precomputed_carving_ranges,
                    carving_ranges_truncated=carving_ranges_truncated,
                    precomputed_uncertain_carving_ranges=precomputed_uncertain_carving_ranges,
                    uncertain_carving_ranges_truncated=uncertain_carving_ranges_truncated,
                    carving_options=carving_options,
                    carving_checkpoint=carving_checkpoint,
                    carving_checkpoint_callback=carving_checkpoint_callback,
                    phase_callback=phase_callback,
                )
            else:
                snapshot = self.catalog_builder.build(
                    volume,
                    progress_callback,
                    phase_callback=phase_callback,
                )
        except Exception:
            self._flush_latest_checkpoint(
                latest_carving_checkpoint,
                carving_checkpoint_callback,
            )
            raise

        self._flush_latest_checkpoint(
            latest_carving_checkpoint,
            carving_checkpoint_callback,
        )
        return CatalogScanOutcome(snapshot, validation_summary)

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
