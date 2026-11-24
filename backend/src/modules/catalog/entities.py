from dataclasses import dataclass
import os

from modules.disk.entities import NTFSVolume

SUPPORTED_CATALOG_EXTENSIONS = (
    ".doc", ".docm", ".docx", ".jpeg", ".jpg", ".mp4",
    ".pdf", ".png", ".rtf", ".xls", ".xlsm", ".xlsx",
)


import os


class RecoveryCatalog:
    def __init__(self, nodes, root_nodes=None):
        self.nodes = nodes
        self.root_nodes = list(root_nodes or ())
        if not self.root_nodes:
            self.root_nodes = [node for node in nodes.values() if getattr(node, "parent", None) is None]
        self.file_nodes = []
        self._files_by_extension = {}
        for node in nodes.values():
            if node.record.is_dir:
                continue
            extension = os.path.splitext(node.record.name)[1].casefold()
            self.file_nodes.append(node)
            self._files_by_extension.setdefault(extension, []).append(node)

    @staticmethod
    def node_key(node):
        record = node.record
        return (
            getattr(record, "index", None),
            getattr(record, "sequence_number", None),
            os.path.normcase(getattr(node, "full_path", "")),
        )

    def available_extensions(self, supported_extensions):
        supported = {extension.casefold() for extension in supported_extensions}
        return sorted(extension for extension in self._files_by_extension if extension in supported)

    def eligible_files(self, supported_extensions, extensions=None, min_file_size=0):
        supported = {extension.casefold() for extension in supported_extensions}
        selected = supported if extensions is None else {extension.casefold() for extension in extensions}
        threshold = max(0, int(min_file_size))
        eligible_keys = {
            self.node_key(node)
            for extension in supported.intersection(selected)
            for node in self._files_by_extension.get(extension, ())
            if int(node.record.file_size) >= threshold
        }
        return [
            node for node in self.file_nodes
            if self.node_key(node) in eligible_keys
        ]

    @staticmethod
    def is_eligible(node, allowed_extensions, min_file_size=0):
        if node.record.is_dir:
            return False
        extension = os.path.splitext(node.record.name)[1].casefold()
        return extension in allowed_extensions and int(node.record.file_size) >= min_file_size

    def plan_selection(self, selected_nodes, eligible_files):
        """Expand selected folders to eligible files and deduplicate nested checks."""
        eligible_by_key = {self.node_key(node): node for node in eligible_files}
        selected_keys = set()
        visited = set()
        pending = list(reversed(tuple(selected_nodes)))
        while pending:
            node = pending.pop()
            key = self.node_key(node)
            if key in visited:
                continue
            visited.add(key)
            if key in eligible_by_key:
                selected_keys.add(key)
            pending.extend(reversed(tuple(getattr(node, "children", ()))))
        return [node for key, node in eligible_by_key.items() if key in selected_keys]


@dataclass(frozen=True)
class RecoveryCatalogSnapshot:
    catalog: RecoveryCatalog
    volume: NTFSVolume
    orphan_scan_performed: bool = False
    content_carving_summary: dict | None = None
    parent_reference_issue_count: int = 0
    low_confidence_carving_summary: dict | None = None
    recycle_bin_summary: dict | None = None
    usn_journal_summary: dict | None = None
    ntfs_log_file_summary: dict | None = None

    @property
    def volume_start(self):
        return self.volume.partition_offset

    @property
    def cluster_size(self):
        return self.volume.cluster_size


@dataclass(frozen=True)
class CarvedContentRecord:
    """Catalog-facing candidate with bytes found outside filesystem metadata."""

    index: int
    offset: int
    name: str
    resident_data: bytes
    cluster_allocation_status: str = "free"
    sequence_number: int = 0
    is_valid: bool = True
    # Raw carving cannot prove this file was deleted; do not label it as such.
    is_allocated: bool = True
    is_dir: bool = False
    file_size: int = 0
    data_is_complete: bool = True
    data_runs: tuple = ()
    raw_data: bytes = b""
    catalog_content_validation: str = "format_structure_match"
    catalog_content_validation_reason: str = (
        "Contiguous file structure and format markers passed validation"
    )

    def __post_init__(self):
        data = bytes(self.resident_data)
        object.__setattr__(self, "resident_data", data)
        object.__setattr__(self, "file_size", len(data))
