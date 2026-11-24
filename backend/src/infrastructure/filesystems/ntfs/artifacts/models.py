"""Shared data contracts for bounded NTFS recovery evidence."""

from dataclasses import dataclass
from datetime import datetime
import re


def has_path_component(node, component: str) -> bool:
    """Check a catalog node path/parent chain for one exact NTFS component."""
    target = str(component).casefold()
    path = str(getattr(node, "full_path", "") or "")
    if target in {item.casefold() for item in re.split(r"[\\/]+", path) if item}:
        return True
    current = node
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = str(getattr(getattr(current, "record", None), "name", "") or "")
        if name.casefold() == target:
            return True
        current = getattr(current, "parent", None)
    return False

@dataclass(frozen=True)
class FileReference:
    """A preserved NTFS file reference, split when the record version allows."""

    raw_hex: str
    record_number: int | None = None
    sequence_number: int | None = None

@dataclass(frozen=True)
class NTFSArtifact:
    """A bounded metadata observation from a journal or Recycle Bin index."""

    source: str
    source_offset: int
    source_length: int
    name: str | None = None
    original_path: str | None = None
    timestamp_utc: datetime | None = None
    size_bytes: int | None = None
    file_reference: FileReference | None = None
    parent_reference: FileReference | None = None
    usn: int | None = None
    reason_mask: int | None = None
    reason_flags: tuple[str, ...] = ()
    format_version: int | None = None
    companion_content_name: str | None = None

    @property
    def indicates_delete(self) -> bool:
        """True only for an explicit USN delete reason or a Recycle Bin index."""
        return self.source == "recycle_bin_index" or "FILE_DELETE" in self.reason_flags

@dataclass(frozen=True)
class ArtifactScanResult:
    artifacts: tuple[NTFSArtifact, ...]
    bytes_examined: int
    records_examined: int
    malformed_records: int
    next_offset: int
    limit_reached: bool
    limit_reason: str | None = None
