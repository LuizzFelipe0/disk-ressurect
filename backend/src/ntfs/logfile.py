"""Bounded structural inspection of NTFS ``$LogFile`` pages.

This module deliberately reports page-level evidence only. It does not replay
NTFS transactions or infer that a historical file's content is recoverable.
"""

from dataclasses import dataclass
from typing import Callable, Iterable

from ntfs.file_content_reader import FileContentError


@dataclass(frozen=True)
class NTFSLogPageEvidence:
    """A log page whose signature and update-sequence fixups are consistent."""

    page_index: int
    source_offset: int
    signature: str
    system_page_size: int | None = None
    log_page_size: int | None = None
    format_major: int | None = None
    format_minor: int | None = None
    current_lsn: int | None = None


@dataclass(frozen=True)
class NTFSLogFileScanResult:
    """Bounded page-level observations from one ``$LogFile`` stream read."""

    pages: tuple[NTFSLogPageEvidence, ...]
    bytes_examined: int
    pages_examined: int
    malformed_pages: int
    limit_reached: bool
    truncated_input: bool
    evidence_scope: str = (
        "aligned_page_signature_and_fixups; RSTR version 1.1 restart bounds; "
        "LSN values are raw"
    )

    @property
    def restart_pages(self):
        return sum(page.signature == "RSTR" for page in self.pages)

    @property
    def record_pages(self):
        return sum(page.signature == "RCRD" for page in self.pages)


class NTFSLogFileParser:
    """Validate aligned RSTR/RCRD page signatures and NTFS sector fixups.

    Restart-area/client-record interpretation is intentionally omitted. The
    parser is useful for bounded evidence gathering, but validated pages alone
    are not transaction events and cannot create recoverable file entries.
    """

    RESTART_PAGE = b"RSTR"
    RECORD_PAGE = b"RCRD"
    DEFAULT_PAGE_SIZE = 4096
    DEFAULT_SECTOR_SIZE = 512
    DEFAULT_MAX_SCAN_BYTES = 64 * 1024 * 1024
    DEFAULT_MAX_PAGES = 16_384

    def __init__(self, *, max_scan_bytes=DEFAULT_MAX_SCAN_BYTES,
                 max_pages=DEFAULT_MAX_PAGES):
        self.max_scan_bytes = max(0, int(max_scan_bytes))
        self.max_pages = max(0, int(max_pages))

    def parse(self, data, *, page_size=DEFAULT_PAGE_SIZE,
              sector_size=DEFAULT_SECTOR_SIZE) -> NTFSLogFileScanResult:
        """Inspect complete aligned pages in a bounded bytes-like input."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("NTFS $LogFile data must be a bytes-like value")
        raw = memoryview(data).cast("B")
        page_size = int(page_size)
        sector_size = int(sector_size)
        if (sector_size < 512 or sector_size > page_size
                or sector_size & (sector_size - 1)):
            raise ValueError("NTFS sector size must be a power of two from 512 to page size")
        if (page_size < sector_size or page_size % sector_size
                or page_size & (page_size - 1)):
            raise ValueError("NTFS log page size must be a sector-aligned power of two")

        byte_limit = min(len(raw), self.max_scan_bytes)
        page_limit = min(byte_limit // page_size, self.max_pages)
        bytes_examined = min(byte_limit, page_limit * page_size)
        complete_pages = bytes_examined // page_size
        pages = []
        malformed_pages = 0

        for page_index in range(complete_pages):
            source_offset = page_index * page_size
            page = raw[source_offset:source_offset + page_size]
            signature = bytes(page[:4])
            if signature not in (self.RESTART_PAGE, self.RECORD_PAGE):
                continue
            if not self._has_valid_update_sequence_array(page, page_size, sector_size):
                malformed_pages += 1
                continue
            restart_metadata = None
            if signature == self.RESTART_PAGE:
                restart_metadata = self._restart_page_metadata(
                    page, page_index, page_size, sector_size,
                )
                if restart_metadata is None:
                    malformed_pages += 1
                    continue
            pages.append(NTFSLogPageEvidence(
                page_index=page_index,
                source_offset=source_offset,
                signature=signature.decode("ascii"),
                **(restart_metadata or {}),
            ))

        limit_reached = (len(raw) > self.max_scan_bytes
                         or complete_pages < byte_limit // page_size)
        return NTFSLogFileScanResult(
            pages=tuple(pages),
            bytes_examined=bytes_examined,
            pages_examined=complete_pages,
            malformed_pages=malformed_pages,
            limit_reached=limit_reached,
            truncated_input=(len(raw) % page_size != 0),
        )

    @staticmethod
    def _has_valid_update_sequence_array(page, page_size, sector_size):
        if len(page) != page_size or page_size % sector_size:
            return False
        usa_offset = int.from_bytes(page[4:6], "little")
        usa_count = int.from_bytes(page[6:8], "little")
        expected_count = page_size // sector_size + 1
        usa_end = usa_offset + usa_count * 2
        if (usa_offset < 8 or usa_count != expected_count
                or usa_end > page_size):
            return False

        update_sequence = bytes(page[usa_offset:usa_offset + 2])
        if update_sequence == b"\x00\x00":
            return False
        for sector_index in range(1, usa_count):
            trailer = sector_index * sector_size - 2
            if bytes(page[trailer:trailer + 2]) != update_sequence:
                return False
        return True

    @staticmethod
    def _restart_page_metadata(page, page_index, page_size, sector_size):
        """Validate the supported 1.1 restart header and bounded area fields."""
        if page_index not in (0, 1) or len(page) < 0x1E:
            return None
        system_page_size = int.from_bytes(page[0x10:0x14], "little")
        log_page_size = int.from_bytes(page[0x14:0x18], "little")
        restart_offset = int.from_bytes(page[0x18:0x1A], "little")
        minor_version = int.from_bytes(page[0x1A:0x1C], "little", signed=True)
        major_version = int.from_bytes(page[0x1C:0x1E], "little", signed=True)
        chkdsk_lsn = int.from_bytes(page[0x08:0x10], "little", signed=True)
        usa_offset = int.from_bytes(page[0x04:0x06], "little")
        usa_count = int.from_bytes(page[0x06:0x08], "little")
        usa_end = usa_offset + usa_count * 2

        if (major_version != 1 or minor_version != 1 or chkdsk_lsn != 0
                or system_page_size != page_size or log_page_size != page_size
                or system_page_size < max(512, sector_size)
                or not NTFSLogFileParser._is_power_of_two(system_page_size)
                or not NTFSLogFileParser._is_power_of_two(log_page_size)
                or page_index * page_size != page_index * system_page_size
                or restart_offset % 8 != 0 or restart_offset < usa_end
                or restart_offset + 48 > system_page_size):
            return None

        area = page[restart_offset:restart_offset + 48]
        log_clients = int.from_bytes(area[8:10], "little")
        client_free_list = int.from_bytes(area[10:12], "little")
        client_in_use_list = int.from_bytes(area[12:14], "little")
        sequence_number_bits = int.from_bytes(area[16:20], "little")
        restart_area_length = int.from_bytes(area[20:22], "little")
        client_array_offset = int.from_bytes(area[22:24], "little")
        log_file_size = int.from_bytes(area[24:32], "little", signed=True)
        log_record_header_length = int.from_bytes(area[36:38], "little")
        log_page_data_offset = int.from_bytes(area[38:40], "little")
        minimum_log_size = (2 * system_page_size) + (48 * log_page_size)
        expected_sequence_bits = 67 - log_file_size.bit_length() if log_file_size > 0 else 0
        client_record_size = 160
        required_area_length = client_array_offset + log_clients * client_record_size
        indices_valid = all(
            value == 0xFFFF or value < log_clients
            for value in (client_free_list, client_in_use_list)
        )

        if (log_clients == 0 or log_clients > 256 or not indices_valid
                or log_file_size < minimum_log_size or log_file_size > 0x1_0000_0000
                or sequence_number_bits != expected_sequence_bits
                or client_array_offset % 8 != 0
                or restart_area_length < required_area_length
                or restart_offset + restart_area_length > system_page_size
                or restart_offset + client_array_offset + log_clients * client_record_size
                > system_page_size
                or log_record_header_length % 8 != 0
                or log_page_data_offset % 8 != 0
                or log_page_data_offset > log_page_size):
            return None

        return {
            "system_page_size": system_page_size,
            "log_page_size": log_page_size,
            "format_major": major_version,
            "format_minor": minor_version,
            "current_lsn": int.from_bytes(area[:8], "little"),
        }

    @staticmethod
    def _is_power_of_two(value):
        return value > 0 and (value & (value - 1)) == 0


@dataclass(frozen=True)
class NTFSLogFileEvidenceSummary:
    """Aggregate structural evidence; it never contains recoverable file data."""

    status: str
    inconclusive: bool
    log_file_count: int
    bytes_read: int
    pages_examined: int
    restart_pages: int
    record_pages: int
    malformed_pages: int
    current_lsns: tuple[str, ...]
    limit_reached: bool
    error_count: int
    reason: str | None = None

    def to_dict(self):
        return {
            "status": self.status,
            "inconclusive": self.inconclusive,
            "logFileCount": self.log_file_count,
            "bytesRead": self.bytes_read,
            "pagesExamined": self.pages_examined,
            "restartPages": self.restart_pages,
            "recordPages": self.record_pages,
            "malformedPages": self.malformed_pages,
            "currentLsns": list(self.current_lsns),
            "limitReached": self.limit_reached,
            "errorCount": self.error_count,
            "reason": self.reason,
            "recoveryClaim": "structural_evidence_only",
        }


class NTFSLogFileEvidenceScanner:
    """Read one bounded ``$LogFile`` record and aggregate structural pages."""

    MAX_READ_BYTES = 64 * 1024 * 1024
    MAX_PAGES = 16_384

    def __init__(self, parser=None):
        self.parser = parser or NTFSLogFileParser(
            max_scan_bytes=self.MAX_READ_BYTES,
            max_pages=self.MAX_PAGES,
        )

    def scan(self, nodes: Iterable, read_chunks: Callable):
        candidates = tuple(
            node for node in nodes
            if str(getattr(getattr(node, "record", None), "name", "")).casefold() == "$logfile"
            and not bool(getattr(getattr(node, "record", None), "is_dir", False))
            and not bool(getattr(node, "is_orphaned", False))
        )
        if not candidates:
            return self._empty(reason="log_file_not_found")
        if len(candidates) != 1:
            return self._empty(reason="ambiguous_log_file_records", error_count=1)

        node = candidates[0]
        data = bytearray()
        limit_reached = False
        read_failed = False
        try:
            for chunk in read_chunks(node):
                payload = memoryview(chunk).cast("B")
                remaining = self.MAX_READ_BYTES - len(data)
                if remaining <= 0:
                    limit_reached = True
                    break
                data.extend(payload[:remaining])
                if len(payload) > remaining:
                    limit_reached = True
                    break
                declared_size = int(getattr(node.record, "file_size", len(data)))
                if len(data) == self.MAX_READ_BYTES and declared_size > len(data):
                    limit_reached = True
                    break
        except (FileContentError, OSError, ValueError, TypeError):
            read_failed = True

        parsed = self.parser.parse(data)
        limit_reached = limit_reached or parsed.limit_reached or parsed.truncated_input
        current_lsns = tuple(
            f"0x{page.current_lsn:016X}"
            for page in parsed.pages
            if page.signature == "RSTR" and page.current_lsn is not None
        )[:2]
        error_count = parsed.malformed_pages + int(read_failed)
        inconclusive = (
            read_failed or limit_reached or parsed.malformed_pages > 0
            or parsed.restart_pages == 0
        )
        reason = (
            "log_file_read_error" if read_failed else
            "log_file_limit_reached" if limit_reached else
            "malformed_log_pages" if parsed.malformed_pages else
            "restart_page_not_validated" if parsed.restart_pages == 0 else None
        )
        return NTFSLogFileEvidenceSummary(
            status="inconclusive" if inconclusive else "complete",
            inconclusive=inconclusive,
            log_file_count=1,
            bytes_read=len(data),
            pages_examined=parsed.pages_examined,
            restart_pages=parsed.restart_pages,
            record_pages=parsed.record_pages,
            malformed_pages=parsed.malformed_pages,
            current_lsns=current_lsns,
            limit_reached=limit_reached,
            error_count=error_count,
            reason=reason,
        )

    @staticmethod
    def _empty(reason, error_count=0):
        return NTFSLogFileEvidenceSummary(
            status="inconclusive",
            inconclusive=True,
            log_file_count=0,
            bytes_read=0,
            pages_examined=0,
            restart_pages=0,
            record_pages=0,
            malformed_pages=0,
            current_lsns=(),
            limit_reached=False,
            error_count=error_count,
            reason=reason,
        )
