import os
import base64
from typing import Callable
from modules.disk.service import DiskReaderFactory

from modules.disk.entities import NTFSVolume

from modules.catalog.entities import RecoveryCatalogSnapshot
from modules.catalog.entities import RecoveryCatalog
from modules.recovery.entities import ExtractionSummary, RecoveryProgress


ProgressCallback = Callable[[RecoveryProgress], None]


class RecoveryWorkflow:
    """Validates and executes selected-file recovery."""

    PREVIEW_LIMIT_BYTES = 15 * 1024 * 1024
    PREVIEW_TYPES = {
        ".jpg": ("image/jpeg", "image"), ".jpeg": ("image/jpeg", "image"),
        ".png": ("image/png", "image"), ".pdf": ("application/pdf", "pdf"),
    }

    def __init__(
        self,
        disk_factory: DiskReaderFactory,
        output_guard,
        content_reader_factory,
        signature_validator,
        extractor_factory,
    ):
        self.disk_factory = disk_factory
        self.output_guard = output_guard
        self.content_reader_factory = content_reader_factory
        self.signature_validator = signature_validator
        self.extractor_factory = extractor_factory

    def preview_file(self, snapshot, node):
        """Return a bounded preview read from the same source as the catalog."""
        if node.record.is_dir:
            raise ValueError("Folders cannot be previewed")
        extension = os.path.splitext(node.record.name)[1].casefold()
        preview_type = self.PREVIEW_TYPES.get(extension)
        if preview_type is None:
            return {"available": False, "reason": "unsupported_format"}
        expected_size = int(node.record.file_size)
        if expected_size < 0 or expected_size > self.PREVIEW_LIMIT_BYTES:
            return {"available": False, "reason": "too_large"}
        disk = self.disk_factory(snapshot.volume.disk_number)
        try:
            reader = self.content_reader_factory(disk, snapshot.volume_start, snapshot.cluster_size)
            content = bytearray()
            for chunk in reader.iter_chunks(node):
                if len(content) + len(chunk) > self.PREVIEW_LIMIT_BYTES:
                    return {"available": False, "reason": "too_large"}
                content.extend(chunk)
            if len(content) != expected_size or not self.signature_validator.matches(
                extension, bytes(content[:self.signature_validator.header_window(extension)]),
            ):
                return {"available": False, "reason": "invalid_content"}
            mime_type, kind = preview_type
            return {"available": True, "name": node.record.name, "mimeType": mime_type,
                    "kind": kind, "sizeBytes": len(content),
                    "dataBase64": base64.b64encode(content).decode("ascii")}
        finally:
            disk.close()

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
            extractor = self.extractor_factory(
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






class RecoveryPlanner:
    def __init__(self, catalog: RecoveryCatalog, supported_extensions):
        self.catalog = catalog
        self.supported_extensions = frozenset(extension.casefold() for extension in supported_extensions)
        self.extensions = set(self.supported_extensions)
        self.minimum_size_bytes = 0

    def set_filters(self, extensions=None, minimum_size_kb=0):
        self.extensions = self.supported_extensions if extensions is None else {
            extension.casefold() for extension in extensions
        }
        self.minimum_size_bytes = max(0, int(minimum_size_kb)) * 1024

    def is_eligible(self, node):
        return self.catalog.is_eligible(
            node,
            self.supported_extensions.intersection(self.extensions),
            self.minimum_size_bytes,
        )

    def candidates(self):
        return self.catalog.eligible_files(
            self.supported_extensions,
            self.extensions,
            self.minimum_size_bytes,
        )

    def plan(self, selected_nodes, excluded_nodes=()):
        eligible = self.candidates()
        selected = self.catalog.plan_selection(selected_nodes, eligible)
        if not excluded_nodes:
            return selected
        excluded_keys = {
            self.catalog.node_key(node)
            for node in self.catalog.plan_selection(excluded_nodes, eligible)
        }
        return [node for node in selected if self.catalog.node_key(node) not in excluded_keys]
