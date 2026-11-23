"""Bounded parsers for metadata from NTFS-adjacent recovery sources.

These parsers describe evidence only. In particular, a USN Journal record is
not file content, and a Recycle Bin ``$I`` entry does not prove its paired
``$R`` content is still present or intact.

Integration contract:
* Feed the unnamed ``$DATA`` bytes of MFT entries named ``$I...`` under
  ``$Recycle.Bin`` to :class:`RecycleBinIndexParser`. Resolve the returned
  ``companion_content_name`` under the same parent record and recover that
  paired ``$R`` entry through the normal read-only MFT/runlist path.
  :class:`RecycleBinRecoveryHelper` performs the bounded ``$I`` callback read,
  same-directory token pairing and safe generated-name planning over mounted
  nodes; its association result can be mapped to a synthetic catalog node.
* Feed bytes from the named ``$DATA`` attribute ``$J`` on the ``$UsnJrnl`` MFT
  record to :class:`UsnJournalParser`, retaining the stream offset for each
  window. The named-stream reader requires the selected ``NTFSVolume``'s
  ``partition_size`` so physical runs cannot cross its boundary. MFT attribute
  lists and extension records remain unresolved and are refused as incomplete.
* Neither parser is currently called by ``CatalogService`` or shown in the UI.
  Their outputs must remain separate metadata evidence and must not be added as
  recoverable file contents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
import struct
from typing import Callable, Iterable


USN_REASON_FLAGS = (
    (0x00000001, "DATA_OVERWRITE"),
    (0x00000002, "DATA_EXTEND"),
    (0x00000004, "DATA_TRUNCATION"),
    (0x00000010, "NAMED_DATA_OVERWRITE"),
    (0x00000020, "NAMED_DATA_EXTEND"),
    (0x00000040, "NAMED_DATA_TRUNCATION"),
    (0x00000100, "FILE_CREATE"),
    (0x00000200, "FILE_DELETE"),
    (0x00000400, "EA_CHANGE"),
    (0x00000800, "SECURITY_CHANGE"),
    (0x00001000, "RENAME_OLD_NAME"),
    (0x00002000, "RENAME_NEW_NAME"),
    (0x00004000, "INDEXABLE_CHANGE"),
    (0x00008000, "BASIC_INFO_CHANGE"),
    (0x00010000, "HARD_LINK_CHANGE"),
    (0x00020000, "COMPRESSION_CHANGE"),
    (0x00040000, "ENCRYPTION_CHANGE"),
    (0x00080000, "OBJECT_ID_CHANGE"),
    (0x00100000, "REPARSE_POINT_CHANGE"),
    (0x00200000, "STREAM_CHANGE"),
    (0x00400000, "TRANSACTED_CHANGE"),
    (0x00800000, "INTEGRITY_CHANGE"),
    (0x80000000, "CLOSE"),
)

_WINDOWS_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
_MAX_USN_RECORD_BYTES = 1024 * 1024


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


class UsnJournalParser:
    """Parse bounded USN_RECORD_V2/V3 entries from a ``$UsnJrnl:$J`` stream.

    The caller supplies already-read stream bytes. Sparse areas are represented
    by zero bytes and skipped in eight-byte steps. Unknown/malformed records
    are skipped without treating their bytes as file content.
    """

    DEFAULT_MAX_BYTES = 64 * 1024 * 1024
    DEFAULT_MAX_RECORDS = 1_000_000

    def __init__(self, max_bytes=DEFAULT_MAX_BYTES, max_records=DEFAULT_MAX_RECORDS):
        self.max_bytes = max(0, int(max_bytes))
        self.max_records = max(0, int(max_records))

    def parse(self, data: bytes, *, source_offset=0) -> ArtifactScanResult:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("USN journal data must be a bytes-like value")
        source_offset = int(source_offset)
        if source_offset < 0:
            raise ValueError("source_offset must not be negative")

        raw = memoryview(data).cast("B")
        available = min(len(raw), self.max_bytes)
        cursor = 0
        records_examined = 0
        malformed = 0
        artifacts = []
        limit_reason = None

        while cursor + 8 <= available:
            if records_examined >= self.max_records:
                limit_reason = "record_budget"
                break

            record_length = struct.unpack_from("<I", raw, cursor)[0]
            if record_length == 0:
                cursor += 8
                continue
            records_examined += 1

            major, _minor = struct.unpack_from("<HH", raw, cursor + 4)
            header_length = {2: 60, 3: 76}.get(major)
            # A bad signature/length can be a sparse hole or stale bytes. Move
            # by the journal's eight-byte record alignment and attempt resync.
            if (header_length is None or record_length < header_length
                    or record_length > _MAX_USN_RECORD_BYTES
                    or record_length % 8):
                malformed += 1
                cursor += 8
                continue
            if cursor + record_length > available:
                limit_reason = "byte_budget" if available < len(raw) else "truncated_record"
                break

            file_name_length, file_name_offset = struct.unpack_from(
                "<HH", raw, cursor + (56 if major == 2 else 72),
            )
            name_start = cursor + file_name_offset
            name_end = name_start + file_name_length
            if (file_name_length == 0 or file_name_length % 2
                    or file_name_offset < header_length
                    or name_end > cursor + record_length):
                malformed += 1
                cursor += 8
                continue
            try:
                name = bytes(raw[name_start:name_end]).decode("utf-16le", errors="strict")
            except UnicodeDecodeError:
                malformed += 1
                cursor += 8
                continue

            if major == 2:
                file_ref = self._mft_reference(raw[cursor + 8:cursor + 16])
                parent_ref = self._mft_reference(raw[cursor + 16:cursor + 24])
                usn, timestamp_ticks, reason = struct.unpack_from("<q q I", raw, cursor + 24)
            else:
                file_ref = self._opaque_reference(raw[cursor + 8:cursor + 24])
                parent_ref = self._opaque_reference(raw[cursor + 24:cursor + 40])
                usn, timestamp_ticks, reason = struct.unpack_from("<q q I", raw, cursor + 40)

            flags = tuple(label for bit, label in USN_REASON_FLAGS if reason & bit)
            artifacts.append(NTFSArtifact(
                source="usn_journal",
                source_offset=source_offset + cursor,
                source_length=record_length,
                name=name,
                timestamp_utc=self._filetime(timestamp_ticks),
                file_reference=file_ref,
                parent_reference=parent_ref,
                usn=usn,
                reason_mask=reason,
                reason_flags=flags,
                format_version=major,
            ))
            cursor += record_length

        if limit_reason is None and cursor < available:
            # Fewer than eight trailing bytes cannot begin a valid record.
            if available < len(raw):
                limit_reason = "byte_budget"
            elif len(raw) - cursor >= 8:
                limit_reason = "record_budget" if records_examined >= self.max_records else None

        return ArtifactScanResult(
            artifacts=tuple(artifacts),
            bytes_examined=min(cursor, available),
            records_examined=records_examined,
            malformed_records=malformed,
            next_offset=source_offset + min(cursor, available),
            limit_reached=limit_reason in {"byte_budget", "record_budget"},
            limit_reason=limit_reason,
        )

    @staticmethod
    def _mft_reference(value) -> FileReference:
        raw = bytes(value)
        packed = int.from_bytes(raw, "little")
        return FileReference(
            raw_hex=raw.hex(),
            record_number=packed & 0x0000FFFFFFFFFFFF,
            sequence_number=(packed >> 48) & 0xFFFF,
        )

    @staticmethod
    def _opaque_reference(value) -> FileReference:
        return FileReference(raw_hex=bytes(value).hex())

    @staticmethod
    def _filetime(ticks):
        if ticks <= 0:
            return None
        try:
            return _WINDOWS_EPOCH + timedelta(microseconds=ticks // 10)
        except OverflowError:
            return None


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


@dataclass(frozen=True)
class UsnJournalEvidence:
    """Metadata-only result for one discovered ``$UsnJrnl:$J`` stream."""

    status: str
    reason: str
    journal_node: object | None
    stream_size_bytes: int
    bytes_read: int
    scan: ArtifactScanResult | None

    @property
    def events(self):
        return self.scan.artifacts if self.scan is not None else ()


class UsnJournalEvidenceScanner:
    """Find ``$UsnJrnl:$J`` named streams and return bounded metadata only."""

    MAX_STREAM_BYTES = 64 * 1024 * 1024

    def __init__(self, max_bytes=MAX_STREAM_BYTES, max_records=UsnJournalParser.DEFAULT_MAX_RECORDS):
        requested = int(max_bytes)
        if requested <= 0:
            raise ValueError("USN journal scan budget must be positive")
        self.max_bytes = min(requested, self.MAX_STREAM_BYTES)
        self.parser = UsnJournalParser(self.max_bytes, max_records)

    def scan(
        self,
        nodes: Iterable[object],
        read_named_stream: Callable[[object, str, int], bytes],
    ) -> tuple[UsnJournalEvidence, ...]:
        journal_nodes = [
            node for node in nodes
            if str(getattr(getattr(node, "record", None), "name", "") or "").casefold()
            == "$usnjrnl"
            and has_path_component(node, "$extend")
        ]
        if not journal_nodes:
            named_journals = [
                node for node in nodes
                if str(getattr(getattr(node, "record", None), "name", "") or "").casefold()
                == "$usnjrnl"
            ]
            if named_journals:
                return tuple(UsnJournalEvidence(
                    "incomplete_stream", "journal_parent_path_not_verified",
                    node, 0, 0, None,
                ) for node in named_journals)
            return (UsnJournalEvidence(
                "not_found", "journal_record_not_in_mft_catalog", None, 0, 0, None,
            ),)

        results = []
        for journal_node in journal_nodes:
            record = getattr(journal_node, "record", None)
            streams = getattr(record, "named_data_streams", {}) or {}
            stream = streams.get("$j")
            if stream is None:
                if (getattr(record, "has_attribute_list", False)
                        or getattr(record, "is_extension_record", False)):
                    results.append(UsnJournalEvidence(
                        "incomplete_stream", "journal_stream_may_be_in_unresolved_extension",
                        journal_node, 0, 0, None,
                    ))
                    continue
                results.append(UsnJournalEvidence(
                    "missing_stream", "named_j_stream_not_present", journal_node,
                    0, 0, None,
                ))
                continue
            try:
                stream_size = int(stream.file_size)
            except (AttributeError, TypeError, ValueError, OverflowError):
                results.append(UsnJournalEvidence(
                    "invalid_stream", "named_j_size_invalid", journal_node,
                    0, 0, None,
                ))
                continue
            if stream_size < 0:
                results.append(UsnJournalEvidence(
                    "invalid_stream", "named_j_size_invalid", journal_node,
                    0, 0, None,
                ))
                continue
            if not bool(getattr(stream, "is_complete", False)):
                results.append(UsnJournalEvidence(
                    "incomplete_stream", "named_j_mapping_not_proven_complete",
                    journal_node, stream_size, 0, None,
                ))
                continue
            try:
                data = read_named_stream(journal_node, "$J", self.max_bytes)
            except Exception:
                # The reader may report incomplete runs with its own domain
                # exception. Preserve other journals and surface no fake result.
                results.append(UsnJournalEvidence(
                    "read_error", "named_j_read_failed", journal_node,
                    stream_size, 0, None,
                ))
                continue
            if not isinstance(data, (bytes, bytearray, memoryview)):
                results.append(UsnJournalEvidence(
                    "read_error", "named_j_reader_returned_non_bytes", journal_node,
                    stream_size, 0, None,
                ))
                continue
            if len(data) > self.max_bytes or len(data) > stream_size:
                results.append(UsnJournalEvidence(
                    "read_error", "named_j_reader_exceeded_bounds", journal_node,
                    stream_size, len(data), None,
                ))
                continue

            scan = self.parser.parse(data, source_offset=0)
            full_stream_read = len(data) == stream_size
            expected_prefix = min(stream_size, self.max_bytes)
            complete_prefix_read = len(data) == expected_prefix
            if scan.limit_reached:
                status, reason = "partial", f"journal_{scan.limit_reason}_reached"
            elif scan.limit_reason == "truncated_record":
                status, reason = "partial", "journal_ends_with_truncated_record"
            elif full_stream_read and complete_prefix_read:
                status, reason = "complete", "journal_stream_read_within_budget"
            elif complete_prefix_read:
                status, reason = "partial", "journal_stream_exceeds_scan_budget"
            else:
                status, reason = "partial", "journal_stream_prefix_read_incomplete"
            results.append(UsnJournalEvidence(
                status, reason, journal_node, stream_size, len(data), scan,
            ))
        return tuple(results)
