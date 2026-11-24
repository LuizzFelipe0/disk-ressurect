import os
from dataclasses import dataclass, field

from modules.storage.entities import StorageSource


SUPPORTED_CATALOG_EXTENSIONS = (
    ".doc", ".docm", ".docx", ".jpeg", ".jpg", ".mp4",
    ".pdf", ".png", ".rtf", ".xls", ".xlsm", ".xlsx",
)


@dataclass
class CatalogNode:
    """Filesystem-neutral tree entry; files carry a recovery candidate."""

    node_id: str
    name: str
    full_path: str
    is_directory: bool
    size_bytes: int
    candidate: object | None = None
    properties: dict = field(default_factory=dict)
    parent: "CatalogNode | None" = field(default=None, repr=False)
    children: list["CatalogNode"] = field(default_factory=list, repr=False)

    def __post_init__(self):
        if not self.node_id:
            raise ValueError("Catalog node identity is required")
        if self.size_bytes < 0:
            raise ValueError("Catalog node size cannot be negative")
        if self.is_directory and self.candidate is not None:
            raise ValueError("Directory nodes cannot be recovery candidates")
        if not self.is_directory and self.candidate is None:
            raise ValueError("File nodes require a recovery candidate")


class RecoveryCatalog:
    def __init__(self, nodes, root_nodes=None):
        values = nodes.values() if hasattr(nodes, "values") else nodes
        self.nodes = {node.node_id: node for node in values}
        self.root_nodes = list(root_nodes or ())
        if not self.root_nodes:
            self.root_nodes = [node for node in self.nodes.values() if node.parent is None]
        self.file_nodes = [node for node in self.nodes.values() if not node.is_directory]
        self._files_by_extension = {}
        for node in self.file_nodes:
            extension = os.path.splitext(node.name)[1].casefold()
            self._files_by_extension.setdefault(extension, []).append(node)

    @staticmethod
    def node_key(node):
        return node.node_id

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
            if int(node.size_bytes) >= threshold
        }
        return [node for node in self.file_nodes if self.node_key(node) in eligible_keys]

    @staticmethod
    def is_eligible(node, allowed_extensions, min_file_size=0):
        if node.is_directory:
            return False
        extension = os.path.splitext(node.name)[1].casefold()
        return extension in allowed_extensions and int(node.size_bytes) >= min_file_size

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
            pending.extend(reversed(tuple(node.children)))
        return [node for key, node in eligible_by_key.items() if key in selected_keys]


@dataclass(frozen=True)
class RecoveryCatalogSnapshot:
    catalog: RecoveryCatalog
    source: StorageSource | None = None
    source_id: str = ""
    volume_id: str = ""
    filesystem_id: str | None = None
    orphan_scan_performed: bool = False
    content_carving_summary: dict | None = None
    parent_reference_issue_count: int = 0
    low_confidence_carving_summary: dict | None = None
    recycle_bin_summary: dict | None = None
    usn_journal_summary: dict | None = None
    ntfs_log_file_summary: dict | None = None
