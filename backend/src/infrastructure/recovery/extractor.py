import hashlib
import os
from typing import Callable, Iterable

from modules.catalog.entities import RecoveryCatalog
from modules.recovery.service import RecoveryPlanner
from modules.recovery.entities import ContentReadError, ExtractionResult
from infrastructure.formats.signature import FileSignatureValidator
from infrastructure.filesystems.recovery_output_writer import RecoveryOutputWriter, UnsafeRecoveryPath


class Extractor:
    """Stream generic content references through the recovery validation pipeline."""

    def __init__(
        self,
        source,
        vfs_nodes,
        vol_start=None,
        cluster_size=4096,
        root_nodes=None,
        *,
        content_reader=None,
        signature_validator=None,
        output_writer=None,
    ):
        self.source = source
        self.catalog = RecoveryCatalog(vfs_nodes, root_nodes)
        self.signature_validator = signature_validator or FileSignatureValidator
        self.planner = RecoveryPlanner(
            self.catalog, self.signature_validator.supported_extensions(),
        )
        self.content_reader = content_reader
        self.output_writer = output_writer or RecoveryOutputWriter()
        self.results = []

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
            recovered_count += result.status == "recovered"
            if progress_callback is not None:
                progress_callback(completed, len(targets), result)
        return recovered_count

    def _extract_one(self, out_dir, node):
        temporary_path = None
        created_directories = ()
        published = False
        bytes_written = 0
        digest = hashlib.sha256()
        candidate = node.candidate
        reference = candidate.content_reference
        extension = os.path.splitext(node.name.lower())[1]
        try:
            if reference is None or self.content_reader is None:
                raise ValueError("Candidate has no readable content reference")
            if reference.source_id != self.source.source_id:
                raise ValueError("Candidate content belongs to a different storage source")
            destination, temporary_path_template, created_directories = self.output_writer.prepare_target(
                out_dir, node.full_path,
            )
            header = bytearray()
            header_limit = self.signature_validator.header_window(extension)
            output, temporary_path = self.output_writer.open_temporary(temporary_path_template)
            with output:
                for chunk in self.content_reader.iter_chunks(reference):
                    if len(header) < header_limit:
                        header.extend(chunk[:header_limit - len(header)])
                    self.output_writer.write_chunk(output, chunk)
                    digest.update(chunk)
                    bytes_written += len(chunk)

            if bytes_written != reference.size_bytes:
                return ExtractionResult(
                    node, "incomplete_read",
                    f"Read {bytes_written} bytes; expected {reference.size_bytes}", bytes_written,
                )
            if reference.sha256 is not None and digest.hexdigest() != reference.sha256:
                return ExtractionResult(node, "content_mismatch", "Content digest does not match the catalog", bytes_written)
            if not self.signature_validator.matches(extension, bytes(header)):
                return ExtractionResult(node, "signature_mismatch", "File header does not match its extension", bytes_written)

            container_error = self.signature_validator.validate_container(
                temporary_path, extension, bytes(header),
            )
            if container_error:
                return ExtractionResult(node, "invalid_container", container_error, bytes_written)

            self.output_writer.publish(temporary_path, destination)
            published = True
            return ExtractionResult(
                node, "recovered",
                "All file bytes were read and the available signature/container checks passed",
                bytes_written,
            )
        except UnsafeRecoveryPath as exc:
            return ExtractionResult(node, "invalid_path", str(exc), bytes_written)
        except ContentReadError as exc:
            return ExtractionResult(node, exc.status, exc.reason, bytes_written)
        except OSError as exc:
            return ExtractionResult(node, "io_error", str(exc), bytes_written)
        except (ValueError, TypeError, OverflowError) as exc:
            return ExtractionResult(node, "invalid_data", str(exc), bytes_written)
        finally:
            self.output_writer.discard(temporary_path)
            if not published:
                self.output_writer.cleanup_empty_directories(created_directories)
