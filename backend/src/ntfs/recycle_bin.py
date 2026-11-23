"""Bounded parsing and safe pairing for Windows Recycle Bin records."""

from dataclasses import dataclass
import hashlib
import re
import struct
from typing import Callable, Iterable

from ntfs.artifact_models import NTFSArtifact
from ntfs.usn_journal import UsnJournalParser


class RecycleBinIndexParser:
    """Parse Windows Vista+ ``$Recycle.Bin`` ``$I`` index metadata.

    The paired ``$R`` file holds the bytes and must be recovered separately;
    its existence is not inferred by this parser.
    """

    MAX_PATH_CODE_UNITS = 32_768

    def __init__(self, max_path_code_units=MAX_PATH_CODE_UNITS):
        self.max_path_code_units = max(0, int(max_path_code_units))

    def parse(self, data: bytes, *, artifact_name=None, source_offset=0) -> NTFSArtifact:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("Recycle Bin index data must be a bytes-like value")
        raw = memoryview(data).cast("B")
        source_offset = int(source_offset)
        if source_offset < 0:
            raise ValueError("source_offset must not be negative")
        if len(raw) < 24:
            raise ValueError("Truncated Recycle Bin $I header")

        version, original_size, deleted_ticks = struct.unpack_from("<Q Q Q", raw, 0)
        if version not in (1, 2):
            raise ValueError("Unsupported Recycle Bin $I format version")

        if version == 1:
            path_start = 24
            path_end = self._find_utf16_terminator(raw, path_start, self.max_path_code_units)
            if path_end is None:
                if len(raw) - path_start > self.max_path_code_units * 2:
                    raise ValueError("Recycle Bin path exceeds the configured limit")
                raise ValueError("Recycle Bin $I v1 path is not terminated")
            path_bytes = bytes(raw[path_start:path_end])
            consumed = path_end + 2
        else:
            if len(raw) < 28:
                raise ValueError("Truncated Recycle Bin $I v2 path header")
            path_code_units = struct.unpack_from("<I", raw, 24)[0]
            if path_code_units <= 0 or path_code_units > self.max_path_code_units:
                raise ValueError("Recycle Bin path length is outside the configured limit")
            path_start = 28
            path_end = path_start + path_code_units * 2
            if path_end > len(raw):
                raise ValueError("Truncated Recycle Bin $I v2 path")
            path_bytes = bytes(raw[path_start:path_end])
            if path_bytes.endswith(b"\x00\x00"):
                path_bytes = path_bytes[:-2]
            consumed = path_end

        try:
            original_path = path_bytes.decode("utf-16le", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("Recycle Bin path is not valid UTF-16LE") from exc
        if not original_path or "\x00" in original_path:
            raise ValueError("Recycle Bin path is empty or contains an embedded NUL")

        filename = str(artifact_name or "").replace("/", "\\").rsplit("\\", 1)[-1]
        companion = None
        if filename.startswith("$I") and len(filename) > 2:
            companion = "$R" + filename[2:]
        name = original_path.replace("/", "\\").rsplit("\\", 1)[-1]
        return NTFSArtifact(
            source="recycle_bin_index",
            source_offset=source_offset,
            source_length=consumed,
            name=name,
            original_path=original_path,
            timestamp_utc=UsnJournalParser._filetime(deleted_ticks),
            size_bytes=original_size,
            reason_flags=("MOVED_TO_RECYCLE_BIN",),
            format_version=int(version),
            companion_content_name=companion,
        )

    @staticmethod
    def _find_utf16_terminator(raw, start, max_path_code_units):
        end_limit = min(len(raw) - 1, start + (max_path_code_units + 1) * 2)
        for position in range(start, end_limit, 2):
            if raw[position] == 0 and raw[position + 1] == 0:
                return position
        return None

@dataclass(frozen=True)
class RecycleBinAssociation:
    """A parsed ``$I`` record and its same-directory ``$R`` sibling, if any."""

    status: str
    reason: str
    index_node: object
    content_node: object | None
    metadata: NTFSArtifact | None
    target_name: str | None

class RecycleBinRecoveryHelper:
    """Boundedly read ``$I`` siblings and safely associate their ``$R`` data.

    ``read_index(node, max_bytes)`` must return the complete unnamed ``$DATA``
    stream for that node. The callback must use the application's read-only
    NTFS data reader; this helper rejects truncation and oversized results.
    The returned target is a filename only. The original path is forensic
    metadata and is never used as an output path.
    """

    DEFAULT_MAX_INDEX_BYTES = 128 * 1024
    MAX_ALLOWED_INDEX_BYTES = 1024 * 1024
    MAX_TARGET_BASENAME_CHARS = 120

    def __init__(self, max_index_bytes=DEFAULT_MAX_INDEX_BYTES):
        requested = int(max_index_bytes)
        if requested < 24:
            raise ValueError("max_index_bytes must be at least the $I header size")
        self.max_index_bytes = min(requested, self.MAX_ALLOWED_INDEX_BYTES)
        self.index_parser = RecycleBinIndexParser()

    def associate(
        self,
        nodes: Iterable[object],
        read_index: Callable[[object, int], bytes],
    ) -> tuple[RecycleBinAssociation, ...]:
        """Return one explicit result per plausible ``$I`` node.

        Pairing requires the token after ``$I``/``$R`` to match and a known
        common parent (node identity or MFT parent reference). Ambiguous pairs
        and original-size mismatches are returned as diagnostics, not accepted.
        """
        node_list = tuple(nodes)
        by_sibling_key: dict[tuple[tuple, str], list[object]] = {}
        for node in node_list:
            name = self._node_name(node)
            parent_key = self._parent_key(node)
            if not name or parent_key is None:
                continue
            by_sibling_key.setdefault((parent_key, name.casefold()), []).append(node)

        results = []
        for index_node in node_list:
            index_name = self._node_name(index_node)
            if not index_name or len(index_name) <= 2 or not index_name.casefold().startswith("$i"):
                continue

            parent_key = self._parent_key(index_node)
            if parent_key is None:
                results.append(self._result(
                    "unpaired", "parent_reference_unavailable", index_node,
                ))
                continue

            expected_size = self._node_file_size(index_node)
            if expected_size < 24:
                results.append(self._result("invalid_index", "index_too_small", index_node))
                continue
            if expected_size > self.max_index_bytes:
                results.append(self._result("limited", "index_exceeds_read_limit", index_node))
                continue

            try:
                data = read_index(index_node, self.max_index_bytes)
            except Exception:
                # A callback wraps physical reads and may raise a domain-level
                # incomplete-data error instead of OSError. Keep one bad $I
                # record from failing the full catalog build.
                results.append(self._result("read_error", "index_read_failed", index_node))
                continue
            if not isinstance(data, (bytes, bytearray, memoryview)):
                results.append(self._result("invalid_index", "reader_returned_non_bytes", index_node))
                continue
            if len(data) != expected_size or len(data) > self.max_index_bytes:
                results.append(self._result("incomplete", "index_read_size_mismatch", index_node))
                continue

            try:
                metadata = self.index_parser.parse(
                    data,
                    artifact_name=index_name,
                    source_offset=int(getattr(index_node.record, "mft_offset", 0) or 0),
                )
            except (TypeError, ValueError, struct.error):
                results.append(self._result("invalid_index", "index_format_invalid", index_node))
                continue

            sibling_name = metadata.companion_content_name
            matches = by_sibling_key.get((parent_key, sibling_name.casefold()), ())
            if len(matches) != 1:
                status = "ambiguous" if matches else "missing_content"
                reason = "multiple_content_siblings" if matches else "content_sibling_not_found"
                results.append(self._result(status, reason, index_node, metadata=metadata))
                continue

            content_node = matches[0]
            content_size = self._node_file_size(content_node)
            target_name = self._target_name(metadata.original_path, index_name)
            if self._is_directory(content_node):
                # Directories do not have a file-content stream to size-check.
                results.append(RecycleBinAssociation(
                    "paired", "directory_sibling_paired", index_node, content_node,
                    metadata, target_name,
                ))
            elif content_size != metadata.size_bytes:
                results.append(RecycleBinAssociation(
                    "metadata_mismatch", "original_and_content_sizes_differ",
                    index_node, content_node, metadata, target_name,
                ))
            else:
                results.append(RecycleBinAssociation(
                    "paired", "index_and_content_sibling_match",
                    index_node, content_node, metadata, target_name,
                ))

        return tuple(results)

    @staticmethod
    def _node_name(node):
        return str(getattr(getattr(node, "record", None), "name", "") or "")

    @staticmethod
    def _node_file_size(node):
        try:
            return max(0, int(getattr(getattr(node, "record", None), "file_size", 0)))
        except (TypeError, ValueError, OverflowError):
            return 0

    @staticmethod
    def _is_directory(node):
        return bool(getattr(getattr(node, "record", None), "is_dir", False))

    @staticmethod
    def _parent_key(node):
        parent = getattr(node, "parent", None)
        if parent is not None:
            return ("node", id(parent))
        record = getattr(node, "record", None)
        parent_index = getattr(record, "parent_index", None)
        if parent_index is not None:
            parent_sequence = getattr(record, "parent_sequence_number", None)
            return ("mft_reference", int(parent_index), parent_sequence)
        return None

    @staticmethod
    def _result(status, reason, index_node, *, metadata=None):
        return RecycleBinAssociation(
            status, reason, index_node, None, metadata, None,
        )

    @classmethod
    def _target_name(cls, original_path, index_name):
        # Use only the original basename as a display hint. Never join the
        # original path into a destination path or trust its directory parts.
        path_parts = re.split(r"[\\/]", str(original_path or ""))
        original_basename = path_parts[-1] if path_parts else ""
        safe_basename = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "_", original_basename)
        safe_basename = safe_basename.strip().rstrip(". ")
        if safe_basename in {"", ".", ".."}:
            safe_basename = "recovered-file"
        digest = hashlib.sha256(index_name.casefold().encode("utf-8", errors="replace"))
        suffix = digest.hexdigest()[:12]
        if len(safe_basename) > cls.MAX_TARGET_BASENAME_CHARS:
            stem, dot, extension = safe_basename.rpartition(".")
            if dot:
                ext = extension[:24]
                safe_basename = f"{stem[:cls.MAX_TARGET_BASENAME_CHARS - len(ext) - 1]}.{ext}"
            else:
                safe_basename = safe_basename[:cls.MAX_TARGET_BASENAME_CHARS]
        return f"Recovered_{suffix}_{safe_basename}"
