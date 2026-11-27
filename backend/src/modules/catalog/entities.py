import os
import sys
from dataclasses import dataclass, field

from modules.storage.entities import StorageSource


SUPPORTED_CATALOG_EXTENSIONS = (
    ".doc", ".docm", ".docx", ".jpeg", ".jpg", ".mov", ".mp4",
    ".pdf", ".png", ".rtf", ".xls", ".xlsm", ".xlsx",
)


@dataclass(frozen=True)
class PngPartialRecovery:
    """Decoded PNG pixel rows kept separate from complete-file candidates."""

    recovery_id: str
    source_id: str
    volume_id: str
    signature_offset: int
    source_ranges: tuple[tuple[int, int], ...]
    width: int
    height: int
    channels: int
    rows: tuple[bytes, ...]
    stop_reason: str
    valid_idat_crc_count: int
    idat_crc_unknown: bool
    idat_crc_invalid: bool
    zlib_complete: bool
    iend_valid: bool
    source_content_size: int = 0
    source_content_sha256: str = ""

    def __post_init__(self):
        if (len(self.recovery_id) != 64
                or any(character not in "0123456789abcdef" for character in self.recovery_id)
                or not self.source_id or not self.volume_id):
            raise ValueError("Partial PNG recovery and source identities are required")
        if self.signature_offset < 0 or self.width <= 0 or self.height <= 0:
            raise ValueError("Partial PNG origin and dimensions must be positive")
        if self.channels not in (3, 4):
            raise ValueError("Partial PNG pixel layout must be RGB or RGBA")
        if (self.source_content_size < 0
                or self.source_content_sha256 and (
                    len(self.source_content_sha256) != 64
                    or any(character not in "0123456789abcdef"
                           for character in self.source_content_sha256)
                )):
            raise ValueError("Partial PNG source validation identity is invalid")
        rows = tuple(bytes(row) for row in self.rows)
        if not rows or len(rows) > self.height:
            raise ValueError("Partial PNG recovery row count exceeds image dimensions")
        if any(len(row) != self.width * self.channels for row in rows):
            raise ValueError("Partial PNG row size does not match its pixel layout")
        ranges = tuple((int(start), int(end)) for start, end in self.source_ranges)
        if (not ranges or any(start < self.signature_offset or end <= start
                              for start, end in ranges)):
            raise ValueError("Partial PNG source ranges are invalid")
        if (tuple(sorted(ranges)) != ranges
                or any(left[1] > right[0] for left, right in zip(ranges, ranges[1:]))):
            raise ValueError("Partial PNG source ranges must be ordered and non-overlapping")
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "source_ranges", ranges)

    @property
    def recovered_row_count(self):
        return len(self.rows)

    @property
    def pixel_layout(self):
        return "RGB" if self.channels == 3 else "RGBA"

    @property
    def missing_row_range(self):
        return len(self.rows), self.height


@dataclass(frozen=True)
class PngSignatureOutcome:
    """Bounded terminal evidence for one signature in the active window."""

    offset: int
    status: str
    reason: str
    bytes_read: int = 0
    elapsed_seconds: float = 0.0

    def __post_init__(self):
        allowed = {
            "completed", "partial_result", "already_complete", "unsupported",
            "hypothesis", "ambiguous", "resource_limited", "retryable_error",
        }
        if self.offset < 0 or self.status not in allowed:
            raise ValueError("PNG signature outcome is invalid")
        if self.bytes_read < 0 or self.elapsed_seconds < 0:
            raise ValueError("PNG signature resource accounting is invalid")


@dataclass(frozen=True)
class PngRecoveryProgress:
    """Session-only PNG cursors and cumulative budgets for one recovery scope."""

    scope_identity: str
    signature_window_identity: str
    window_signature_count: int = 0
    discovered_signatures: int = 0
    completed_windows: int = 0
    partial_next_index: int = 0
    reconstruction_next_index: int = 0
    partial_outcomes: tuple[PngSignatureOutcome, ...] = ()
    reconstruction_outcomes: tuple[PngSignatureOutcome, ...] = ()
    partial_bytes_read: int = 0
    partial_unique_bytes_read: int = 0
    partial_elapsed_seconds: float = 0.0
    partial_retained_bytes: int = 0
    partial_signatures_considered: int = 0
    partial_signatures_rejected: int = 0
    partial_results_found: int = 0
    reconstruction_bytes_read: int = 0
    reconstruction_combinations: int = 0
    reconstruction_elapsed_seconds: float = 0.0
    reconstruction_retained_bytes: int = 0
    reconstruction_signatures_considered: int = 0
    discovery_bytes_read: int = 0
    partial_stop_reason: str = "pending"
    reconstruction_stop_reason: str = "pending"

    def __post_init__(self):
        for value in (self.scope_identity, self.signature_window_identity):
            if (len(value) != 64
                    or any(character not in "0123456789abcdef" for character in value)):
                raise ValueError("PNG continuation identity must be a lowercase SHA-256 digest")
        if (self.window_signature_count < 0 or self.window_signature_count > 256
                or self.discovered_signatures < 0 or self.completed_windows < 0
                or self.partial_next_index < 0 or self.reconstruction_next_index < 0
                or self.partial_bytes_read < 0 or self.partial_unique_bytes_read < 0
                or self.partial_retained_bytes < 0 or self.reconstruction_bytes_read < 0
                or self.reconstruction_combinations < 0
                or self.reconstruction_retained_bytes < 0 or self.discovery_bytes_read < 0
                or self.reconstruction_signatures_considered < 0
                or self.partial_signatures_considered < 0
                or self.partial_signatures_rejected < 0 or self.partial_results_found < 0
                or self.partial_elapsed_seconds < 0
                or self.reconstruction_elapsed_seconds < 0):
            raise ValueError("PNG continuation counters cannot be negative")
        if len(self.partial_outcomes) > 256 or len(self.reconstruction_outcomes) > 256:
            raise ValueError("PNG continuation outcomes exceed the retained signature window")
        if any(not isinstance(item, PngSignatureOutcome)
               for item in self.partial_outcomes + self.reconstruction_outcomes):
            raise TypeError("PNG continuation outcomes must be typed signature results")

    @property
    def estimated_retained_bytes(self):
        """Approximate in-memory size of bounded continuation metadata, not RSS."""
        outcomes = self.partial_outcomes + self.reconstruction_outcomes
        return (
            sys.getsizeof(self)
            + sys.getsizeof(self.scope_identity)
            + sys.getsizeof(self.signature_window_identity)
            + sys.getsizeof(self.partial_outcomes)
            + sys.getsizeof(self.reconstruction_outcomes)
            + sum(
                sys.getsizeof(item) + sys.getsizeof(item.status) + sys.getsizeof(item.reason)
                for item in outcomes
            )
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
            if (int(node.size_bytes) >= threshold
                and getattr(node.candidate, "recoverability", "unknown") != "unavailable")
        }
        return [node for node in self.file_nodes if self.node_key(node) in eligible_keys]

    @staticmethod
    def is_eligible(node, allowed_extensions, min_file_size=0):
        if node.is_directory:
            return False
        if getattr(node.candidate, "recoverability", "unknown") == "unavailable":
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
    partial_png_recoveries: tuple[PngPartialRecovery, ...] = ()
    png_recovery_progress: PngRecoveryProgress | None = None
