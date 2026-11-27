import os
import base64
import hashlib
from typing import Callable

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
        output_guard,
        content_reader_factory,
        signature_validator,
        extractor_factory,
    ):
        self.output_guard = output_guard
        self.content_reader_factory = content_reader_factory
        self.signature_validator = signature_validator
        self.extractor_factory = extractor_factory

    def preview_file(self, snapshot, node):
        """Return a bounded preview read from the same source as the catalog."""
        if node.is_directory:
            raise ValueError("Folders cannot be previewed")
        candidate = node.candidate
        reference = candidate.content_reference
        extension = os.path.splitext(node.name)[1].casefold()
        preview_type = self.PREVIEW_TYPES.get(extension)
        if preview_type is None:
            return {"available": False, "reason": "unsupported_format"}
        expected_size = int(reference.size_bytes) if reference is not None else -1
        if expected_size < 0 or expected_size > self.PREVIEW_LIMIT_BYTES:
            return {"available": False, "reason": "too_large"}
        source = self._snapshot_source(snapshot)
        if reference is None or reference.source_id != source.source_id:
            return {"available": False, "reason": "invalid_content"}
        reader = self.content_reader_factory(source)
        content = bytearray()
        digest = hashlib.sha256()
        for chunk in reader.iter_chunks(reference):
            if len(content) + len(chunk) > self.PREVIEW_LIMIT_BYTES:
                return {"available": False, "reason": "too_large"}
            content.extend(chunk)
            digest.update(chunk)
        if (len(content) != expected_size
                or (reference.sha256 is not None and digest.hexdigest() != reference.sha256)
                or not self.signature_validator.matches(
                    extension, bytes(content[:self.signature_validator.header_window(extension)]),
                )):
            return {"available": False, "reason": "invalid_content"}
        mime_type, kind = preview_type
        return {"available": True, "name": node.name, "mimeType": mime_type,
                "kind": kind, "sizeBytes": len(content),
                "dataBase64": base64.b64encode(content).decode("ascii")}

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
        source = self._snapshot_source(snapshot)
        self.output_guard.validate_source(output_directory, source)
        extractor = self.extractor_factory(
            source,
            snapshot.catalog.nodes,
            root_nodes=snapshot.catalog.root_nodes,
            content_reader=self.content_reader_factory(source),
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
        results = list(extractor.results)
        return ExtractionSummary(recovered_count, tuple(results))

    @staticmethod
    def _snapshot_source(snapshot):
        if snapshot.source is None:
            raise ValueError("Catalog has no storage source identity")
        if snapshot.source_id and snapshot.source.source_id != snapshot.source_id:
            raise ValueError("Catalog storage source identity is inconsistent")
        return snapshot.source

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
