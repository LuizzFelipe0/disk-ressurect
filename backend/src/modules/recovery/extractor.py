import os
from typing import Callable, Iterable

from modules.recovery.planner import RecoveryPlanner
from modules.recovery.models import ExtractionResult
from domain.recovery_catalog import RecoveryCatalog
from ntfs.file_content_reader import FileContentError, NTFSFileContentReader
from ntfs.file_signature_validator import FileSignatureValidator
from ntfs.recovery_output_writer import RecoveryOutputWriter, UnsafeRecoveryPath


class Extractor:
    """Extraction facade composed from planner, reader, validator and writer."""

    def __init__(
        self,
        disk,
        vfs_nodes,
        vol_start,
        cluster_size=4096,
        root_nodes=None,
        *,
        content_reader=None,
        signature_validator=None,
        output_writer=None,
    ):
        self.catalog = RecoveryCatalog(vfs_nodes, root_nodes)
        self.signature_validator = (
            signature_validator if signature_validator is not None else FileSignatureValidator
        )
        supported_extensions = self.signature_validator.supported_extensions()
        self.results = []
        self.planner = RecoveryPlanner(self.catalog, supported_extensions)
        self.content_reader = content_reader if content_reader is not None else NTFSFileContentReader(disk, vol_start, cluster_size)
        self.output_writer = output_writer if output_writer is not None else RecoveryOutputWriter()

    def set_filters(self, exts=None, min_kb=0):
        self.planner.set_filters(exts, min_kb)

    def candidate_nodes(self):
        return self.planner.candidates()

    @classmethod
    def supported_extensions(cls):
        return FileSignatureValidator.supported_extensions()

    def plan_selection(self, selected_nodes, excluded_nodes=()):
        return self.planner.plan(selected_nodes, excluded_nodes)

    def extract(
        self,
        out_dir,
        selected_nodes: Iterable[object] | None = None,
        progress_callback: Callable[[int, int, ExtractionResult], None] | None = None,
        excluded_nodes: Iterable[object] | None = None,
    ):
        """Extract candidates, optionally limiting work to selected tree nodes.

        ``selected_nodes=None`` extracts all candidates that pass the active
        filters. The desktop interface passes checked folders and files here.
        """
        candidates = self.candidate_nodes()
        if selected_nodes is None:
            targets = candidates if not excluded_nodes else self.planner.plan(candidates, excluded_nodes)
        else:
            targets = self.plan_selection(selected_nodes, excluded_nodes or ())

        self.results = []
        recovered_count = 0

        for completed, node in enumerate(targets, 1):
            result = self._extract_one(out_dir, node)
            self.results.append(result)
            if result.status == "recovered":
                recovered_count += 1
            if progress_callback is not None:
                progress_callback(completed, len(targets), result)

        return recovered_count

    def _extract_one(self, out_dir, node):
        temporary_path = None
        bytes_written = 0
        extension = os.path.splitext(node.record.name.lower())[1]
        try:
            destination, temporary_path = self.output_writer.prepare_target(out_dir, node.full_path)
            header = bytearray()
            header_limit = self.signature_validator.header_window(extension)
            with open(temporary_path, "wb") as output:
                for chunk in self.content_reader.iter_chunks(node):
                    if len(header) < header_limit:
                        header.extend(chunk[:header_limit - len(header)])
                    self.output_writer.write_chunk(output, chunk)
                    bytes_written += len(chunk)

            header = bytes(header)
            if not self.signature_validator.matches(extension, header):
                return ExtractionResult(node, "signature_mismatch", "File header does not match its extension", bytes_written)

            container_error = self.signature_validator.validate_container(temporary_path, extension, header)
            if container_error:
                return ExtractionResult(node, "invalid_container", container_error, bytes_written)

            self.output_writer.publish(temporary_path, destination)
            return ExtractionResult(
                node,
                "recovered",
                "All file bytes were read and the available signature/container checks passed",
                bytes_written,
            )
        except UnsafeRecoveryPath as exc:
            return ExtractionResult(node, "invalid_path", str(exc), bytes_written)
        except FileContentError as exc:
            return ExtractionResult(node, exc.status, exc.reason, bytes_written)
        except OSError as exc:
            return ExtractionResult(node, "io_error", str(exc), bytes_written)
        except (ValueError, TypeError, OverflowError) as exc:
            return ExtractionResult(node, "invalid_data", str(exc), bytes_written)
        finally:
            self.output_writer.discard(temporary_path)
