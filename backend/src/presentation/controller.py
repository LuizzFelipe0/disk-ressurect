from modules.catalog.dto import CatalogNodeRequestDto, CatalogSearchRequestDto, FilePreviewRequestDto, VolumeSelectionRequestDto
from modules.catalog.mapper import CatalogMapper
from application.session import RecoverySession
from application.workflows.catalog_scan import CatalogScanWorkflow
from modules.disk.mapper import DiskDtoMapper
from modules.deep_scan.dto import PartitionScanRequestDto
from modules.deep_scan.service import DeepScanService
from modules.disk.service import DiskService
from modules.validation.dto import DiskValidationRequestDto
from modules.validation.service import ValidationService
from modules.recovery.dto import RecoveryRequestDto, RecoveryResultDto
from presentation.transport import (
    CommandErrorDto,
    CommandRequestDto,
    CommandResultDto,
    ProgressEventDto,
)


class RecoveryCommandHandler:
    """Validate commands, invoke feature services and map stable response DTOs."""

    def __init__(
        self, disk_service: DiskService, deep_scan_service: DeepScanService,
        validation_service: ValidationService, catalog_builder, catalog_service,
        recovery_service, session=None,
        source_resolver=None, storage_service=None,
    ):
        self.disk_service = disk_service
        self.deep_scan_service = deep_scan_service
        self.validation_service = validation_service
        self.catalog_builder = catalog_builder
        self.catalog_service = catalog_service
        self.recovery_service = recovery_service
        self.source_resolver = source_resolver
        self.storage_service = storage_service
        self.session = session if session is not None else RecoverySession()
        self.catalog_scan_workflow = CatalogScanWorkflow(
            disk_service,
            deep_scan_service,
            validation_service,
            catalog_builder,
            session=self.session,
        )

    def handle(self, message, emit):
        request_id = message.get("id") if isinstance(message, dict) else None
        try:
            request = CommandRequestDto.from_message(message)
            operation_id = request.payload.get("operationId")

            def emit_scoped(event):
                if event.get("type") == "progress" and isinstance(operation_id, str):
                    event = dict(event)
                    event["payload"] = {**event.get("payload", {}), "operationId": operation_id}
                emit(event)

            payload = self.dispatch(request.operation, request.payload, emit_scoped)
            emit(CommandResultDto(request.request_id, payload).to_dict())
        except Exception as exc:
            emit(CommandErrorDto(request_id, str(exc), type(exc).__name__).to_dict())

    def dispatch(self, operation, payload, emit):
        if operation == "register_raw_image":
            if self.storage_service is None:
                raise RuntimeError("Raw image sources are unavailable")
            source = self.storage_service.register_raw_image(payload.get("path", ""))
            return {
                "sourceId": source.source_id,
                "sourceType": source.source_type,
                "displayName": source.display_name,
                "sizeBytes": source.size_bytes,
            }
        if operation == "list_source_partitions":
            source_id = str(payload.get("sourceId", ""))
            if self.storage_service is None or not source_id:
                raise ValueError("A registered raw image source is required")
            source = self.storage_service.get_source(source_id)
            reader = self.storage_service.open_reader(source)
            try:
                if bool(payload.get("deepScan", False)):
                    from dataclasses import replace
                    from infrastructure.disk.lost_partition_scanner import LostPartitionScanner
                    volumes = LostPartitionScanner(reader, -1).scan(self._inventory_progress(emit))
                    volumes = [replace(volume, source_id=source.source_id) for volume in volumes]
                else:
                    from infrastructure.filesystems.ntfs.discovery.volume_scanner import NTFSVolumeScanner
                    volumes = NTFSVolumeScanner(
                        reader, -1, source_id=source.source_id,
                    ).scan(self._inventory_progress(emit))
            finally:
                reader.close()
            return [
                {
                    "id": self.session.register_volume(volume, source.source_id),
                    "sourceId": source.source_id,
                    "sourceType": "raw_image",
                    "diskNumber": -1,
                    "partitionNumber": volume.partition_number,
                    "offset": volume.partition_offset,
                    "sizeBytes": volume.partition_size,
                    "estimatedSize": volume.partition_size_is_estimated,
                    "name": volume.display_name,
                }
                for volume in volumes
            ]
        if operation == "list_disks":
            result = []
            for item in self.disk_service.list_disks():
                source_id = self._source_id_for_disk(item.disk)
                dto = DiskDtoMapper.disk(
                    item, lambda volume: self.session.register_volume(volume, source_id),
                )
                result.append(dto.to_dict())
            return result
        if operation == "list_partitions":
            request = PartitionScanRequestDto.from_payload(payload)
            volumes, scanned_at = self.deep_scan_service.scan_partitions(
                request.disk_number,
                request.deep_scan,
                self._inventory_progress(emit),
                resume=request.resume,
            )
            source_id = self._source_id_for_disk(self.disk_service.get_disk(request.disk_number))
            return [
                DiskDtoMapper.partition(
                    volume,
                    self.session.register_volume(volume, source_id),
                    scanned_at,
                ).to_dict()
                for volume in volumes
            ]
        if operation == "validate_disk":
            request = DiskValidationRequestDto.from_payload(payload)
            report = self.validation_service.validate_disk(
                request.disk_number,
                self._validation_progress(emit),
            )
            return self.validation_service.to_dto(report).to_dict()
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
            details = tuple({
                "name": str(getattr(item.node, "name", ""))[:260],
                "path": str(item.path)[:1024],
                "status": str(item.status)[:80],
                "reason": str(item.reason)[:512],
                "bytesWritten": int(item.bytes_written),
            } for item in summary.results[:500])
            status_counts = {}
            for item in summary.results:
                status_counts[item.status] = status_counts.get(item.status, 0) + 1
            return RecoveryResultDto(
                recovered_count=summary.recovered_count,
                candidate_count=len(summary.results),
                selected_count=len(request.selected_node_ids),
                results=details,
                results_truncated=len(summary.results) > len(details),
                status_counts=status_counts,
            ).to_dict()
        raise ValueError(f"Unknown operation: {operation}")

    def _scan_catalog(self, payload, emit):
        request = VolumeSelectionRequestDto.from_payload(payload)
        volume = self.session.get_volume(request.volume_id)
        expected_source_id = self.session.get_volume_source_id(request.volume_id)
        if expected_source_id and self.source_resolver is not None:
            current_source = (
                self.storage_service.get_source(expected_source_id)
                if expected_source_id.startswith("raw-image:") and self.storage_service is not None
                else self.source_resolver(volume.disk_number)
            )
            if current_source.source_id != expected_source_id:
                raise ValueError("Selected partition belongs to a different storage source; rescan it")
        progress_callback = self._catalog_progress(emit, include_orphaned=request.include_orphaned)
        outcome = self.catalog_scan_workflow.run(
            volume,
            include_orphaned=request.include_orphaned,
            force_fresh_validation=request.force_fresh_validation,
            carving_options=request.carving_options,
            progress_callback=progress_callback,
            validation_progress_callback=self._validation_progress(emit),
            phase_callback=self._catalog_phase_progress(emit),
        )
        ids_by_identity = self.session.set_catalog(outcome.snapshot)
        return CatalogMapper.catalog(
            outcome.snapshot, ids_by_identity, outcome.validation_summary,
        ).to_dict()

    @staticmethod
    def _source_id_for_disk(disk):
        as_source = getattr(disk, "as_storage_source", None)
        return as_source().source_id if callable(as_source) else None

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
