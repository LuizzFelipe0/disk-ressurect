from modules.catalog.dto import CatalogNodeRequestDto, VolumeSelectionRequestDto
from modules.catalog.mapper import CatalogMapper
from modules.commands.dto import CommandErrorDto, CommandRequestDto, CommandResultDto, ProgressEventDto
from modules.commands.session import RecoverySession
from modules.disk_discovery.dto import PartitionScanRequestDto
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
        if operation == "scan_catalog":
            request = VolumeSelectionRequestDto.from_payload(payload)
            volume = self.session.get_volume(request.volume_id)
            snapshot = self.catalog_service.build(volume, self._catalog_progress(emit))
            ids_by_identity = self.session.set_catalog(snapshot)
            return CatalogMapper.catalog(snapshot, ids_by_identity).to_dict()
        if operation == "catalog_children":
            request = CatalogNodeRequestDto.from_payload(payload)
            node = self.session.get_node(request.node_id)
            ids_by_identity = {id(item): node_id for node_id, item in self.session.nodes.items()}
            return [
                CatalogMapper.node(child, ids_by_identity).to_dict()
                for child in node.children
            ]
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
    def _catalog_progress(emit):
        def report(completed, total):
            emit(ProgressEventDto("catalog", completed, total, "Reading MFT records").to_dict())
        return report
