"""Bounded USN journal parsing and scan orchestration."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import struct
from typing import Callable, Iterable

from infrastructure.filesystems.ntfs.artifacts.models import ArtifactScanResult, FileReference, NTFSArtifact, has_path_component


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
