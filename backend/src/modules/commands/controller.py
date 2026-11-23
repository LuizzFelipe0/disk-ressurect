from modules.catalog.dto import CatalogNodeRequestDto, CatalogSearchRequestDto, FilePreviewRequestDto, VolumeSelectionRequestDto
from modules.catalog.mapper import CatalogMapper
from modules.commands.dto import CommandErrorDto, CommandRequestDto, CommandResultDto, ProgressEventDto
from modules.commands.session import RecoverySession
from modules.disk_discovery.dto import DiskValidationRequestDto, PartitionScanRequestDto
from modules.disk_discovery.mapper import DiskDiscoveryMapper
from modules.disk_discovery.service import DiskDiscoveryService
from modules.recovery.dto import RecoveryRequestDto, RecoveryResultDto


class RecoveryCommandHandler:
    """Validate commands, invoke feature services and map stable response DTOs."""

    def __init__(self, disk_discovery: DiskDiscoveryService, catalog_service, recovery_service, session=None):
        self.disk_discovery = disk_discovery
        self.catalog_service = catalog_service
        self.recovery_service = recovery_service
        self.session = session if session is not None else RecoverySession()

    def handle(self, message, emit):
        request_id = message.get("id") if isinstance(message, dict) else None
        try:
            request = CommandRequestDto.from_message(message)
            payload = self.dispatch(request.operation, request.payload, emit)
            emit(CommandResultDto(request.request_id, payload).to_dict())
        except Exception as exc:
            emit(CommandErrorDto(request_id, str(exc), type(exc).__name__).to_dict())

    def dispatch(self, operation, payload, emit):
        if operation == "list_disks":
            result = []
            for item in self.disk_discovery.list_disks():
                dto = DiskDiscoveryMapper.disk(item, self.session.register_volume)
                result.append(dto.to_dict())
            return result
        if operation == "list_partitions":
            request = PartitionScanRequestDto.from_payload(payload)
            volumes, scanned_at = self.disk_discovery.scan_partitions(
                request.disk_number,
                request.deep_scan,
                self._inventory_progress(emit),
                resume=request.resume,
            )
            return [
                DiskDiscoveryMapper.partition(
                    volume,
                    self.session.register_volume(volume),
                    scanned_at,
                ).to_dict()
                for volume in volumes
            ]
        if operation == "validate_disk":
            request = DiskValidationRequestDto.from_payload(payload)
            report = self.disk_discovery.validate_disk(
                request.disk_number,
                self._validation_progress(emit),
            )
            return DiskDiscoveryMapper.validation(report).to_dict()
        if operation == "scan_catalog":
            return self._scan_catalog(payload, emit)
        if operation == "search_catalog":
            request = CatalogSearchRequestDto.from_payload(payload)
            snapshot = self.session.require_snapshot()
            nodes, total_matches = self.catalog_service.search(snapshot, request.query)
            return CatalogMapper.search(
                snapshot, nodes, total_matches, self.session.node_ids_by_identity(),
            ).to_dict()
        if operation == "list_file_types":
            return list(self.catalog_service.supported_extensions())
        if operation == "catalog_children":
            request = CatalogNodeRequestDto.from_payload(payload)
            node = self.session.get_node(request.node_id)
            ids_by_identity = self.session.node_ids_by_identity()
            return [
                CatalogMapper.node(child, ids_by_identity).to_dict()
                for child in node.children
            ]
        if operation == "preview_file":
            request = FilePreviewRequestDto.from_payload(payload)
            snapshot = self.session.require_snapshot()
            return self.recovery_service.preview_file(snapshot, self.session.get_node(request.node_id))
        if operation == "extract":
            request = RecoveryRequestDto.from_payload(payload)
            snapshot = self.session.require_snapshot()
            selected = [self.session.get_node(node_id) for node_id in request.selected_node_ids]
            excluded = [self.session.get_node(node_id) for node_id in request.excluded_node_ids]
            summary = self.recovery_service.extract_selection(
                snapshot=snapshot,
                selected_nodes=selected,
                excluded_nodes=excluded,
                output_directory=request.output_directory,
                extensions=request.extensions,
                min_file_size_kb=request.minimum_size_kb,
                progress_callback=self._progress(emit),
            )
            return RecoveryResultDto(
                recovered_count=summary.recovered_count,
                candidate_count=len(summary.results),
            ).to_dict()
        raise ValueError(f"Unknown operation: {operation}")

    def _scan_catalog(self, payload, emit):
        request = VolumeSelectionRequestDto.from_payload(payload)
        volume = self.session.get_volume(request.volume_id)
        progress_callback = self._catalog_progress(emit, include_orphaned=request.include_orphaned)
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
        if request.include_orphaned:
            try:
                report = self.disk_discovery.validate_disk(
                    volume.disk_number,
                    self._validation_progress(emit),
                    retain_orphans_for_offset=int(volume.partition_offset),
                    orphan_scan_volume=volume,
                    content_carving_range_budget_bytes=(
                        int(request.carving_options.scan_budget_gib) * 1024**3
                    ),
                )
                validation_summary = self._validation_summary(
                    DiskDiscoveryMapper.validation(report).to_dict(),
                )
                partition_offset = int(volume.partition_offset)
                precomputed_orphans = report.get("orphan_records_by_partition", {}).get(partition_offset)
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
                validation_summary = {
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
        if request.include_orphaned and precomputed_carving_ranges is not None:
            carving_source_disk = self.disk_discovery.get_disk(volume.disk_number)
            carving_checkpoint = self.disk_discovery.load_carving_checkpoint(
                carving_source_disk, volume,
            )
            latest_carving_checkpoint = carving_checkpoint
            last_persisted_bytes = (
                carving_checkpoint.bytes_scanned if carving_checkpoint is not None else 0
            )
            checkpoint_interval = 256 * 1024 * 1024

            def persist_carving_checkpoint(checkpoint, force=False):
                nonlocal latest_carving_checkpoint, last_persisted_bytes
                latest_carving_checkpoint = checkpoint
                if checkpoint is None:
                    self.disk_discovery.save_carving_checkpoint(
                        carving_source_disk, volume, None,
                    )
                    last_persisted_bytes = 0
                elif (force or checkpoint.bytes_scanned - last_persisted_bytes
                        >= checkpoint_interval):
                    self.disk_discovery.save_carving_checkpoint(
                        carving_source_disk, volume, checkpoint,
                    )
                    last_persisted_bytes = checkpoint.bytes_scanned

            carving_checkpoint_callback = persist_carving_checkpoint

        try:
            if request.include_orphaned:
                snapshot = self.catalog_service.build(
                    volume,
                    progress_callback,
                    include_orphaned=True,
                    precomputed_orphans=precomputed_orphans,
                    precomputed_carving_ranges=precomputed_carving_ranges,
                    carving_ranges_truncated=carving_ranges_truncated,
                    precomputed_uncertain_carving_ranges=precomputed_uncertain_carving_ranges,
                    uncertain_carving_ranges_truncated=uncertain_carving_ranges_truncated,
                    carving_options=request.carving_options,
                    carving_checkpoint=carving_checkpoint,
                    carving_checkpoint_callback=carving_checkpoint_callback,
                    phase_callback=self._catalog_phase_progress(emit),
                )
            else:
                snapshot = self.catalog_service.build(
                    volume,
                    progress_callback,
                    phase_callback=self._catalog_phase_progress(emit),
                )
        except Exception:
            if latest_carving_checkpoint is not None and carving_source_disk is not None:
                persist_carving_checkpoint(latest_carving_checkpoint, force=True)
            raise
        if latest_carving_checkpoint is not None and carving_source_disk is not None:
            persist_carving_checkpoint(latest_carving_checkpoint, force=True)
        ids_by_identity = self.session.set_catalog(snapshot)
        return CatalogMapper.catalog(snapshot, ids_by_identity, validation_summary).to_dict()

    @staticmethod
    def _progress(emit):
        def report(event):
            emit(ProgressEventDto(event.stage, event.completed, event.total, event.message).to_dict())
        return report

    @staticmethod
    def _inventory_progress(emit):
        def report(completed, total, message):
            emit(ProgressEventDto("partition-scan", completed, total, message).to_dict())
        return report

    @staticmethod
    def _validation_progress(emit):
        def report(completed, total, message):
            emit(ProgressEventDto("disk-validation", completed, total, message).to_dict())
        return report

    @staticmethod
    def _catalog_progress(emit, include_orphaned=False):
        message = (
            "Reading MFT metadata and searching for orphaned entries…"
            if include_orphaned else "Reading MFT records"
        )

        def report(completed, total):
            emit(ProgressEventDto("catalog", completed, total, message).to_dict())
        return report

    @staticmethod
    def _catalog_phase_progress(emit):
        phase_messages = {
            "linking": "Organizing file and folder records…",
            "hierarchy": "Checking folder links…",
            "paths": "Building file paths…",
            "orphans": "Searching unused volume areas for deleted MFT records…",
            "content_carving": "Searching trusted free space for validated file candidates…",
            "content_carving_unobserved": "Searching ranges with unobserved allocation bitmap for file candidates…",
            "content_carving_reused": "Searching possibly reused data ranges for file candidates…",
        }

        def report(phase, completed, total):
            emit(ProgressEventDto(
                "catalog",
                completed,
                total,
                phase_messages.get(phase, "Building the recovery catalog…"),
            ).to_dict())
        return report

    @staticmethod
    def _validation_summary(report):
        ntfs_checks = report.get("ntfsChecks", [])
        return {
            "coverageStatus": report["coverageStatus"],
            "assessment": report["assessment"],
            "bytesRead": report["bytesRead"],
            "sizeBytes": report["sizeBytes"],
            "readErrorCount": len(report.get("readErrors", [])),
            "partitionCount": len(report.get("partitions", [])),
            "ntfsVolumeCount": len(ntfs_checks),
            "deletedMftRecordCount": sum(
                int(item.get("mftRecords", {}).get("deleted", 0)) for item in ntfs_checks
            ),
            "orphanedFileRecordCount": sum(
                int(item.get("orphanedFileRecordCount", 0)) for item in ntfs_checks
            ),
            "inconsistentMftRecordCount": sum(
                int(item.get("mftRecords", {}).get("metadataInconsistent", 0))
                for item in ntfs_checks
            ),
            "orphanRecordsByAllocationStatus": RecoveryCommandHandler._orphan_record_allocation_counts(ntfs_checks),
            "unsupportedFilesystems": list(report.get("unsupportedFilesystems", [])),
        }

    @staticmethod
    def _orphan_record_allocation_counts(ntfs_checks):
        counts = {"free": 0, "allocated": 0, "mixed": 0, "unknown": 0}
        for check in ntfs_checks:
            evidence = check.get("bitmapAllocation", {}).get("orphanDataAllocation", [])
            for item in evidence:
                status = item.get("status")
                if status in ("partially_observed", "unavailable", "no_non_sparse_runs"):
                    counts["unknown"] += 1
                elif status in counts:
                    counts[status] += 1
        return counts
