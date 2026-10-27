import os
from typing import Callable
from disk.access.ports import DiskReaderFactory

from disk.safety.output_safety import OutputSafetyGuard
from disk.platform import disk_reader_factory
from disk.models import NTFSVolume
from modules.recovery.extractor import Extractor
from modules.catalog.models import RecoveryCatalogSnapshot
from modules.recovery.models import ExtractionSummary, RecoveryProgress


ProgressCallback = Callable[[RecoveryProgress], None]


class RecoveryWorkflow:
    """Validates and executes selected-file recovery."""

    def __init__(
        self,
        disk_factory: DiskReaderFactory | None = None,
        output_guard=None,
    ):
        self.disk_factory = disk_factory if disk_factory is not None else disk_reader_factory()
        self.output_guard = output_guard if output_guard is not None else OutputSafetyGuard()

    def extract_selection(
        self,
        snapshot: RecoveryCatalogSnapshot,
        selected_nodes,
        output_directory,
        extensions,
        min_file_size_kb=0,
        progress_callback: ProgressCallback | None = None,
        excluded_nodes=(),
    ):
        if not isinstance(output_directory, (str, os.PathLike)) or not os.fspath(output_directory).strip():
            raise ValueError("Choose a recovery destination folder before extracting files")
        self.output_guard.validate(output_directory, snapshot.volume.disk_number)
        disk = self.disk_factory(snapshot.volume.disk_number)
        try:
            extractor = Extractor(
                disk,
                snapshot.catalog.nodes,
                snapshot.volume_start,
                snapshot.cluster_size,
                snapshot.catalog.root_nodes,
            )
            extractor.set_filters(extensions, min_file_size_kb)
            result_callback = None
            if progress_callback is not None:
                result_callback = lambda completed, total, result: self._notify(
                    progress_callback,
                    "extract",
                    completed,
                    total,
                    f"{result.status}: {result.path}",
                )

            recovered_count = extractor.extract(
                output_directory,
                selected_nodes=selected_nodes,
                progress_callback=result_callback,
                excluded_nodes=excluded_nodes,
            )
            return ExtractionSummary(recovered_count, tuple(extractor.results))
        finally:
            disk.close()

    @staticmethod
    def _notify(callback, stage, completed, total, message):
        if callback is not None:
            callback(RecoveryProgress(stage, completed, total, message))
