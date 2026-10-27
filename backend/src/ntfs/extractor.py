import os
import zlib
import zipfile
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable

from domain.recovery_catalog import RecoveryCatalog


@dataclass(frozen=True)
class ExtractionResult:
    """Outcome for one file, shared by the recovery workflow and report."""

    node: object
    status: str
    reason: str
    bytes_written: int

    @property
    def path(self):
        return self.node.full_path

    @property
    def extension(self):
        return os.path.splitext(self.node.record.name.lower())[1]


class Extractor:
    """Plans and extracts selected files from the virtual file-system tree."""
    ZIP_SIGNATURE = b"PK\x03\x04"
    OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
    READ_CHUNK_SIZE = 4 * 1024 * 1024
    PDF_HEADER_WINDOW = 1024
    ZIP_DOCUMENT_MEMBERS = {
        ".docx": "word/document.xml",
        ".docm": "word/document.xml",
        ".xlsx": "xl/workbook.xml",
        ".xlsm": "xl/workbook.xml",
    }
    SIGNATURES = {
        ".jpg": ((0, b"\xFF\xD8\xFF"),),
        ".jpeg": ((0, b"\xFF\xD8\xFF"),),
        ".png": ((0, b"\x89PNG\r\n\x1a\n"),),
        ".pdf": ((0, b"%PDF-"),),
        ".doc": ((0, OLE_SIGNATURE),),
        ".xls": ((0, OLE_SIGNATURE),),
        ".docx": ((0, ZIP_SIGNATURE), (0, OLE_SIGNATURE)),
        ".docm": ((0, ZIP_SIGNATURE), (0, OLE_SIGNATURE)),
        ".xlsx": ((0, ZIP_SIGNATURE), (0, OLE_SIGNATURE)),
        ".xlsm": ((0, ZIP_SIGNATURE), (0, OLE_SIGNATURE)),
        ".rtf": ((0, b"{\\rtf"),),
        ".mp4": ((4, b"ftyp"),),
    }

    def __init__(self, disk, vfs_nodes, vol_start, cluster_size=4096, root_nodes=None):
        self.disk = disk
        self.nodes = vfs_nodes
        self.catalog = RecoveryCatalog(vfs_nodes, root_nodes)
        self.vol_start = vol_start
        self.c_size = cluster_size
        self.filters = {"ext": set(self.SIGNATURES), "min_kb": 0}
        self.results = []
        self.stats_by_extension = {}

    def set_filters(self, exts=None, min_kb=0):
        self.filters["ext"] = set(self.SIGNATURES) if exts is None else {
            extension.casefold() for extension in exts
        }
        self.filters["min_kb"] = max(0, int(min_kb))

    def _should_extract(self, node):
        return self.catalog.is_eligible(
            node,
            set(self.SIGNATURES).intersection(self.filters["ext"]),
            self.filters["min_kb"] * 1024,
        )

    def candidate_nodes(self):
        """Return eligible files while retaining their parent/child tree links.

        A GUI can use the tree nodes as hierarchical checkbox items, then pass
        the checked descendant files to ``extract`` as ``selected_nodes``.
        """
        return self.catalog.eligible_files(
            self.SIGNATURES,
            self.filters["ext"],
            self.filters["min_kb"] * 1024,
        )

    @classmethod
    def supported_extensions(cls):
        return tuple(sorted(cls.SIGNATURES))

    def plan_selection(self, selected_nodes):
        """Expand checked files/folders into an ordered, deduplicated file plan.

        This is the backend contract for hierarchical GUI checkboxes: selecting
        a folder includes eligible descendants, while selecting a file includes
        only that file. The returned nodes still carry their VFS parent links.
        """
        return self.catalog.plan_selection(selected_nodes, self.candidate_nodes())

    def extract(
        self,
        out_dir,
        selected_nodes: Iterable[object] | None = None,
        progress_callback: Callable[[int, int, ExtractionResult], None] | None = None,
    ):
        """Extract candidates, optionally limiting work to selected tree nodes.

        ``selected_nodes=None`` extracts all candidates that pass the active
        filters. The desktop interface passes checked folders and files here.
        """
        candidates = self.candidate_nodes()
        if selected_nodes is None:
            targets = candidates
        else:
            targets = self.plan_selection(selected_nodes)

        self.results = []
        self.stats_by_extension = {}
        recovered_count = 0

        for completed, node in enumerate(targets, 1):
            result = self._extract_one(out_dir, node)
            self.results.append(result)
            extension_stats = self.stats_by_extension.setdefault(result.extension, Counter())
            extension_stats[result.status] += 1
            if result.status == "recovered":
                recovered_count += 1
            if progress_callback is not None:
                progress_callback(completed, len(targets), result)

        return recovered_count

    def _extract_one(self, out_dir, node):
        destination = None
        temporary_path = None
        bytes_written = 0
        extension = os.path.splitext(node.record.name.lower())[1]
        try:
            if getattr(node.record, "data_is_complete", True) is False:
                return ExtractionResult(node, "incomplete_mft", "MFT data attributes are incomplete", 0)

            root = os.path.abspath(out_dir)
            destination = os.path.abspath(os.path.join(root, node.full_path))
            try:
                is_within_root = os.path.commonpath((root, destination)) == root
            except ValueError:
                is_within_root = False
            if not is_within_root:
                return ExtractionResult(node, "invalid_path", "Output path escapes the recovery directory", 0)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            real_root = os.path.realpath(root)
            real_parent = os.path.realpath(os.path.dirname(destination))
            try:
                real_parent_is_safe = os.path.commonpath((real_root, real_parent)) == real_root
            except ValueError:
                real_parent_is_safe = False
            if not real_parent_is_safe:
                return ExtractionResult(node, "invalid_path", "Output path resolves outside the recovery directory", 0)
            temporary_path = destination + ".partial"
            expected_size = int(node.record.file_size)

            with open(temporary_path, "wb") as output:
                resident_data = node.record.resident_data
                if resident_data is not None:
                    payload = bytes(resident_data)
                    self._write_chunk(output, payload)
                    bytes_written = len(payload)
                    if len(payload) != expected_size:
                        return ExtractionResult(node, "incomplete_read", "Resident data length does not match the MFT size", bytes_written)
                    header = payload[:self._header_window(extension)]
                else:
                    runs = node.record.data_runs
                    if not runs:
                        return ExtractionResult(node, "missing_data_runs", "No data runs are available", 0)
                    header = bytearray()
                    remaining_file_bytes = expected_size
                    for lcn, cluster_count in runs:
                        if remaining_file_bytes <= 0:
                            break
                        if cluster_count <= 0:
                            return ExtractionResult(node, "invalid_runlist", "A data run has a non-positive length", bytes_written)

                        run_remaining = min(cluster_count * self.c_size, remaining_file_bytes)
                        run_offset = 0
                        while run_remaining:
                            read_size = min(run_remaining, self.READ_CHUNK_SIZE)
                            if lcn is None:
                                chunk = bytes(read_size)
                            else:
                                disk_offset = self.vol_start + lcn * self.c_size + run_offset
                                chunk = self.disk.read_at(disk_offset, read_size)
                                if len(chunk) != read_size:
                                    self._write_chunk(output, chunk)
                                    bytes_written += len(chunk)
                                    return ExtractionResult(
                                        node, "incomplete_read",
                                        f"Read {len(chunk)} of {read_size} bytes at disk offset {disk_offset}",
                                        bytes_written,
                                    )

                            header_limit = self._header_window(extension)
                            if len(header) < header_limit:
                                header.extend(chunk[:header_limit - len(header)])
                            self._write_chunk(output, chunk)
                            bytes_written += len(chunk)
                            remaining_file_bytes -= len(chunk)
                            run_remaining -= len(chunk)
                            run_offset += len(chunk)

                    if remaining_file_bytes:
                        return ExtractionResult(
                            node, "incomplete_data",
                            f"Data runs ended with {remaining_file_bytes} bytes missing", bytes_written,
                        )
                    header = bytes(header)

            if not self._signature_matches(extension, header):
                return ExtractionResult(node, "signature_mismatch", "File header does not match its extension", bytes_written)

            container_error = self._validate_container(temporary_path, extension, header)
            if container_error:
                return ExtractionResult(node, "invalid_container", container_error, bytes_written)

            os.replace(temporary_path, destination)
            return ExtractionResult(
                node,
                "recovered",
                "All file bytes were read and the available signature/container checks passed",
                bytes_written,
            )
        except OSError as exc:
            return ExtractionResult(node, "io_error", str(exc), bytes_written)
        except (ValueError, TypeError, OverflowError) as exc:
            return ExtractionResult(node, "invalid_data", str(exc), bytes_written)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass

    @classmethod
    def _header_window(cls, extension):
        return cls.PDF_HEADER_WINDOW if extension == ".pdf" else 8

    @staticmethod
    def _write_chunk(output, data):
        if data and output.write(data) != len(data):
            raise OSError(f"Short output write: wrote fewer than {len(data)} bytes")

    @classmethod
    def _signature_matches(cls, extension, header):
        signatures = cls.SIGNATURES.get(extension)
        if not signatures:
            return True
        if extension == ".pdf":
            return any(signature in header[:cls.PDF_HEADER_WINDOW] for _, signature in signatures)
        return any(header[offset:offset + len(signature)] == signature for offset, signature in signatures)

    @classmethod
    def _validate_container(cls, path, extension, header):
        required_member = cls.ZIP_DOCUMENT_MEMBERS.get(extension)
        if required_member is None or header.startswith(cls.OLE_SIGNATURE):
            return ""
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:
                    return "ZIP container has a corrupt member"
                if required_member not in archive.namelist():
                    return f"ZIP container is missing {required_member}"
        except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error):
            return "ZIP container is incomplete or invalid"
        return ""
