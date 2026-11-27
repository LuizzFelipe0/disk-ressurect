"""Bounded, read-only recovery of structurally validated contiguous files."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Iterable
import zlib

from modules.deep_scan.entities import CarvedCandidateReference, CarvingCheckpoint
from infrastructure.formats.additional import (
    COMPOUND_FILE_SIGNATURE,
    MAX_ISO_BMFF_BOXES,
    RTF_SIGNATURE,
    ZIP_END_OF_CENTRAL_DIRECTORY,
    ZIP_LOCAL_FILE_HEADER,
    is_plausible_office_local_header,
    validate_additional_candidate,
)
from infrastructure.formats.primary import (
    jpeg_header_status,
    png_decoded_size,
    valid_jpeg,
    valid_pdf,
)


@dataclass(frozen=True)
class CarvedContent:
    """A structurally validated contiguous file with no inferred original name."""

    offset: int
    extension: str
    data: bytes
    strategy: str = "contiguous_carving"
    evidence: dict | None = None

    @property
    def size_bytes(self):
        return len(self.data)


@dataclass(frozen=True)
class ContentCarveResult:
    files: tuple[CarvedContent, ...]
    bytes_scanned: int
    scan_limit_reached: bool
    candidate_bytes_read: int
    candidate_limit_reached: bool
    file_count_limit_reached: bool
    retained_bytes_limit_reached: bool
    format_stats: tuple["FormatCarveStats", ...] = ()
    candidate_read_cap_bytes: int = 0
    candidate_read_cap_bytes_per_format: int = 0
    max_file_bytes: int = 0
    max_decoded_png_bytes: int = 0
    max_scan_bytes: int = 0
    max_total_file_bytes: int = 0
    max_files: int = 0
    checkpoint: CarvingCheckpoint | None = None
    candidate_restore_bytes_read: int = 0
    cumulative_bytes_scanned: int = 0
    png_signature_offsets: tuple[int, ...] = ()
    png_signature_set_truncated: bool = False


@dataclass(frozen=True)
class FormatCarveStats:
    extension: str
    candidates_examined: int
    files_found: int
    candidate_bytes_read: int
    candidate_limit_reached: bool = False
    file_size_limit_reached: bool = False
    decoded_data_limit_reached: bool = False


class RawContentCarver:
    """Find bounded contiguous candidates for supported formats in disk ranges.

    The algorithm does not infer filenames or reconstruct fragmented files. Both
    the byte scan and retained output are bounded to keep disk reads and memory
    use predictable. The caller is responsible for choosing ranges, such as
    unallocated clusters reported by NTFS metadata.
    """

    SIGNATURE = b"\xff\xd8\xff"
    EXTENSION = ".jpg"
    FORMAT_SIGNATURES = (
        (".jpg", SIGNATURE),
        (".png", b"\x89PNG\r\n\x1a\n"),
        (".pdf", b"%PDF-"),
        (".office_zip", ZIP_LOCAL_FILE_HEADER),
        (".mp4", b"ftyp"),
        (".rtf", RTF_SIGNATURE),
        (".ole_cfb", COMPOUND_FILE_SIGNATURE),
    )
    SIGNATURE_OFFSETS = {".mp4": 4}
    EXTENSIONS_BY_FAMILY = {
        ".jpg": (".jpg",),
        ".png": (".png",),
        ".pdf": (".pdf",),
        ".office_zip": (".docx", ".docm", ".xlsx", ".xlsm"),
        ".mp4": (".mp4", ".mov"),
        ".rtf": (".rtf",),
        ".ole_cfb": (".doc", ".xls"),
    }
    SIGNATURES_BY_EXTENSION = {
        ".jpg": SIGNATURE,
        ".png": b"\x89PNG\r\n\x1a\n",
        ".pdf": b"%PDF-",
        ".docx": ZIP_LOCAL_FILE_HEADER,
        ".docm": ZIP_LOCAL_FILE_HEADER,
        ".xlsx": ZIP_LOCAL_FILE_HEADER,
        ".xlsm": ZIP_LOCAL_FILE_HEADER,
        ".mp4": b"ftyp",
        ".mov": b"ftyp",
        ".rtf": RTF_SIGNATURE,
        ".doc": COMPOUND_FILE_SIGNATURE,
        ".xls": COMPOUND_FILE_SIGNATURE,
    }
    FAMILY_BY_EXTENSION = {
        ".jpg": ".jpg",
        ".png": ".png",
        ".pdf": ".pdf",
        ".docx": ".office_zip",
        ".docm": ".office_zip",
        ".xlsx": ".office_zip",
        ".xlsm": ".office_zip",
        ".mp4": ".mp4",
        ".mov": ".mp4",
        ".rtf": ".rtf",
        ".doc": ".ole_cfb",
        ".xls": ".ole_cfb",
    }
    DEFAULT_CHUNK_SIZE = 1024 * 1024
    DEFAULT_MAX_SCAN_BYTES = 1024 * 1024 * 1024
    DEFAULT_MAX_FILE_BYTES = 32 * 1024 * 1024
    DEFAULT_MAX_TOTAL_FILE_BYTES = 128 * 1024 * 1024
    DEFAULT_MAX_CANDIDATE_READ_BYTES = 768 * 1024 * 1024
    DEFAULT_MAX_CANDIDATE_READ_BYTES_PER_FORMAT = 256 * 1024 * 1024
    DEFAULT_MAX_FILES = 256
    DEFAULT_MAX_DECODED_PNG_BYTES = 64 * 1024 * 1024
    MAX_PNG_SIGNATURE_OFFSETS = 256

    def __init__(
        self,
        disk,
        *,
        chunk_size=DEFAULT_CHUNK_SIZE,
        max_scan_bytes=DEFAULT_MAX_SCAN_BYTES,
        max_file_bytes=DEFAULT_MAX_FILE_BYTES,
        max_total_file_bytes=DEFAULT_MAX_TOTAL_FILE_BYTES,
        max_candidate_read_bytes=DEFAULT_MAX_CANDIDATE_READ_BYTES,
        max_candidate_read_bytes_per_format=DEFAULT_MAX_CANDIDATE_READ_BYTES_PER_FORMAT,
        max_decoded_png_bytes=DEFAULT_MAX_DECODED_PNG_BYTES,
        max_files=DEFAULT_MAX_FILES,
    ):
        self.disk = disk
        self.chunk_size = max(512, int(chunk_size))
        self.max_scan_bytes = max(0, int(max_scan_bytes))
        self.max_file_bytes = max(1, int(max_file_bytes))
        self.max_total_file_bytes = max(0, int(max_total_file_bytes))
        self.max_candidate_read_bytes = max(0, int(max_candidate_read_bytes))
        self.max_candidate_read_bytes_per_format = max(
            0, int(max_candidate_read_bytes_per_format),
        )
        self.max_files = max(0, int(max_files))
        self.max_decoded_png_bytes = max(0, int(max_decoded_png_bytes))

    def scan(
        self,
        ranges: Iterable[tuple[int, int]],
        *,
        progress_callback: Callable[[int, int], None] | None = None,
        resume_checkpoint: CarvingCheckpoint | None = None,
        retained_candidates: Iterable | None = None,
        retained_candidate_data: dict | None = None,
        candidate_restore_ranges: Iterable[tuple[int, int]] | None = None,
        require_all_retained_candidates: bool = False,
        checkpoint_callback: Callable[[CarvingCheckpoint | None], None] | None = None,
        ranges_truncated: bool = False,
        collect_png_signatures: bool = False,
        defer_png_signature_scan: bool = False,
    ) -> ContentCarveResult:
        """Scan half-open physical disk intervals and return validated files.

        Short reads raise ``OSError`` so callers cannot mistake an incomplete
        scan for a complete result. ``scan_limit_reached`` explicitly reports
        when the configured raw-byte budget prevented full range coverage.
        """
        merged_ranges = self._merge_ranges(ranges, int(self.disk.size))
        disk_size = int(self.disk.size)
        bytes_per_sector = int(getattr(self.disk, "bytes_per_sector", 512) or 512)
        range_fingerprint = self._range_fingerprint(merged_ranges, disk_size)
        collect_png_signatures = bool(collect_png_signatures)
        scan_profile = self._scan_profile(collect_png_signatures)
        if not self._checkpoint_matches(
            resume_checkpoint, merged_ranges, disk_size, bytes_per_sector,
            range_fingerprint, scan_profile,
        ):
            resume_checkpoint = None

        png_signature_offsets = list(
            resume_checkpoint.png_signature_offsets
            if collect_png_signatures and resume_checkpoint is not None else ()
        )
        png_signature_offsets_seen = set(png_signature_offsets)
        png_signature_set_truncated = bool(
            collect_png_signatures and resume_checkpoint is not None
            and resume_checkpoint.png_signature_set_truncated
        )

        def make_checkpoint(*args):
            return self._make_checkpoint(
                *args,
                png_signature_offsets=tuple(sorted(png_signature_offsets)),
                png_signature_set_truncated=png_signature_set_truncated,
            )

        if resume_checkpoint is not None:
            range_index, next_offset = self._resume_position(
                merged_ranges, resume_checkpoint.next_offset,
            )
        else:
            range_index = 0
            next_offset = merged_ranges[0][0] if merged_ranges else 0
        remaining_bytes = self._remaining_bytes(merged_ranges, range_index, next_offset)
        scan_target = min(remaining_bytes, self.max_scan_bytes)
        scan_limit_reached = remaining_bytes > self.max_scan_bytes
        if defer_png_signature_scan:
            scan_limit_reached = False
        completed = 0
        cumulative_bytes_scanned = resume_checkpoint.bytes_scanned if resume_checkpoint else 0
        retained_bytes = 0
        candidate_bytes_read = 0
        candidate_restore_bytes_read = 0
        candidate_limit_reached = False
        file_count_limit_reached = False
        retained_bytes_limit_reached = False
        files: list[CarvedContent] = []
        seen_content: set[bytes] = set()
        seen_offsets: set[tuple[str, int]] = set()
        if retained_candidates is not None:
            candidate_references = tuple(retained_candidates)
        elif resume_checkpoint is not None:
            candidate_references = resume_checkpoint.candidates
        else:
            candidate_references = ()
        if candidate_references:
            files, candidate_restore_bytes_read = self._restore_candidates(
                candidate_references,
                self._merge_ranges(candidate_restore_ranges, disk_size)
                if candidate_restore_ranges is not None else merged_ranges,
                retained_candidate_data,
            )
            if require_all_retained_candidates and len(files) != len(candidate_references):
                raise OSError(
                    "A committed raw candidate failed source revalidation; "
                    "the previous catalog generation was preserved."
                )
            retained_bytes = sum(len(item.data) for item in files)
            seen_content.update(hashlib.sha256(item.data).digest() for item in files)
            seen_offsets.update((item.extension, item.offset) for item in files)
        candidates_by_extension = {extension: 0 for extension, _ in self.FORMAT_SIGNATURES}
        bytes_by_extension = {extension: 0 for extension, _ in self.FORMAT_SIGNATURES}
        candidate_limits_by_extension = {extension: False for extension, _ in self.FORMAT_SIGNATURES}
        file_size_limits_by_extension = {extension: False for extension, _ in self.FORMAT_SIGNATURES}
        decoded_size_limits_by_extension = {extension: False for extension, _ in self.FORMAT_SIGNATURES}

        stop_scan = False
        cursor_checkpoint = None
        initial_carry = (
            resume_checkpoint.signature_carry
            if (resume_checkpoint is not None and range_index < len(merged_ranges)
                and merged_ranges[range_index][0] <= resume_checkpoint.next_offset
                < merged_ranges[range_index][1]
                and next_offset == resume_checkpoint.next_offset)
            else b""
        )
        if defer_png_signature_scan and resume_checkpoint is not None:
            cursor_checkpoint = make_checkpoint(
                merged_ranges,
                resume_checkpoint.range_index,
                resume_checkpoint.next_offset,
                b"",
                range_fingerprint,
                scan_profile,
                disk_size,
                bytes_per_sector,
                cumulative_bytes_scanned,
                files,
            )
        scan_range = () if defer_png_signature_scan else range(
            range_index, len(merged_ranges),
        )
        for index in scan_range:
            range_start, range_end = merged_ranges[index]
            cursor = max(range_start, next_offset) if index == range_index else range_start
            carry = initial_carry if index == range_index else b""
            if cursor >= range_end:
                continue
            while cursor < range_end and completed < self.max_scan_bytes:
                request_size = min(self.chunk_size, range_end - cursor,
                                   self.max_scan_bytes - completed)
                if request_size <= 0:
                    break
                chunk_start = cursor
                data = bytes(self.disk.read_at(cursor, request_size))
                if len(data) != request_size:
                    raise OSError(
                        f"Short content-carving read at {cursor:#x}: "
                        f"received {len(data)} of {request_size} bytes"
                    )

                combined = carry + data
                buffer_start = cursor - len(carry)
                pos = 0
                stop_offset = None
                while True:
                    if len(files) >= self.max_files:
                        file_count_limit_reached = True
                        stop_offset = buffer_start + pos
                        break
                    if retained_bytes >= self.max_total_file_bytes:
                        retained_bytes_limit_reached = True
                        stop_offset = buffer_start + pos
                        break
                    found = self._find_next_signature(combined, pos)
                    if found is None:
                        break
                    family, pos = found
                    candidate_offset = buffer_start + pos
                    pos += 1
                    if family == ".png" and collect_png_signatures:
                        if candidate_offset not in png_signature_offsets_seen:
                            if len(png_signature_offsets) < self.MAX_PNG_SIGNATURE_OFFSETS:
                                png_signature_offsets_seen.add(candidate_offset)
                                png_signature_offsets.append(candidate_offset)
                            else:
                                png_signature_set_truncated = True
                                stop_offset = candidate_offset
                                break
                    candidate_key = (family, candidate_offset)
                    if candidate_key in seen_offsets:
                        continue
                    seen_offsets.add(candidate_key)
                    if candidate_bytes_read >= self.max_candidate_read_bytes:
                        candidate_limit_reached = True
                        stop_offset = candidate_offset
                        break
                    format_remaining = min(
                        self.max_candidate_read_bytes_per_format - bytes_by_extension[family],
                        self.max_candidate_read_bytes - candidate_bytes_read,
                    )
                    if format_remaining <= 0:
                        candidate_limits_by_extension[family] = True
                        continue
                    candidates_by_extension[family] += 1
                    candidate, bytes_read, limit_reason = self._read_candidate(
                        family,
                        candidate_offset,
                        range_end,
                        format_remaining,
                    )
                    candidate_bytes_read += bytes_read
                    bytes_by_extension[family] += bytes_read
                    file_size_limits_by_extension[family] |= limit_reason == "file_size"
                    decoded_size_limits_by_extension[family] |= limit_reason == "decoded_data"
                    candidate_limits_by_extension[family] |= limit_reason == "candidate_budget"
                    if candidate is not None:
                        digest = hashlib.sha256(candidate).digest()
                        if digest in seen_content:
                            continue
                        if retained_bytes + len(candidate) > self.max_total_file_bytes:
                            retained_bytes_limit_reached = True
                            stop_offset = candidate_offset
                            break
                        if digest not in seen_content:
                            seen_content.add(digest)
                            if family in (".office_zip", ".mp4", ".rtf", ".ole_cfb"):
                                candidate_result = validate_additional_candidate(candidate)
                                if candidate_result is None:
                                    continue
                                extension = candidate_result.extension
                            else:
                                extension = family
                            files.append(CarvedContent(candidate_offset, extension, candidate))
                            retained_bytes += len(candidate)
                            pos = max(pos, candidate_offset - buffer_start + len(candidate))
                            if len(files) >= self.max_files:
                                file_count_limit_reached = True
                                signature_offset = self.SIGNATURE_OFFSETS.get(family, 0)
                                stop_offset = candidate_offset + signature_offset + len(
                                    dict(self.FORMAT_SIGNATURES)[family]
                                )
                                break
                            if retained_bytes >= self.max_total_file_bytes:
                                retained_bytes_limit_reached = True
                                break
                    if candidate_bytes_read >= self.max_candidate_read_bytes:
                        candidate_limit_reached = True
                        stop_offset = candidate_offset if candidate is None else buffer_start + pos
                        break

                max_signature_span = max(
                    self.SIGNATURE_OFFSETS.get(family, 0) + len(signature)
                    for family, signature in self.FORMAT_SIGNATURES
                )
                carry = combined[-(max_signature_span - 1):]
                cursor += request_size
                if stop_offset is None:
                    completed += request_size
                else:
                    completed += max(0, min(request_size, stop_offset - chunk_start))
                if progress_callback is not None:
                    progress_callback(completed, scan_target)
                if stop_offset is not None:
                    resume_offset = max(range_start, stop_offset)
                    cursor_checkpoint = make_checkpoint(
                        merged_ranges, index, resume_offset, b"", range_fingerprint, scan_profile,
                        disk_size, bytes_per_sector, cumulative_bytes_scanned + completed, files,
                    )
                    stop_scan = True
                    break
                if cursor < range_end and completed < self.max_scan_bytes:
                    cursor_checkpoint = make_checkpoint(
                        merged_ranges, index, cursor, carry, range_fingerprint, scan_profile,
                        disk_size, bytes_per_sector, cumulative_bytes_scanned + completed, files,
                    )
                    if checkpoint_callback is not None:
                        checkpoint_callback(cursor_checkpoint)
                if candidate_limit_reached or retained_bytes_limit_reached:
                    if cursor_checkpoint is None:
                        if cursor < range_end:
                            cursor_checkpoint = make_checkpoint(
                                merged_ranges, index, cursor, carry, range_fingerprint, scan_profile,
                                disk_size, bytes_per_sector,
                                cumulative_bytes_scanned + completed, files,
                            )
                        elif index + 1 < len(merged_ranges):
                            cursor_checkpoint = make_checkpoint(
                                merged_ranges, index + 1, merged_ranges[index + 1][0], b"",
                                range_fingerprint, scan_profile, disk_size, bytes_per_sector,
                                cumulative_bytes_scanned + completed, files,
                            )
                    stop_scan = True
                    break

            if stop_scan:
                break
            if cursor >= range_end:
                next_range_index = index + 1
                if next_range_index < len(merged_ranges):
                    cursor_checkpoint = make_checkpoint(
                        merged_ranges, next_range_index, merged_ranges[next_range_index][0], b"",
                        range_fingerprint, scan_profile, disk_size, bytes_per_sector,
                        cumulative_bytes_scanned + completed, files,
                    )
                else:
                    cursor_checkpoint = None
            if completed >= self.max_scan_bytes:
                if cursor < range_end:
                    cursor_checkpoint = make_checkpoint(
                        merged_ranges, index, cursor, carry, range_fingerprint, scan_profile,
                        disk_size, bytes_per_sector,
                        cumulative_bytes_scanned + completed, files,
                    )
                elif index + 1 < len(merged_ranges):
                    cursor_checkpoint = make_checkpoint(
                        merged_ranges, index + 1, merged_ranges[index + 1][0], b"",
                        range_fingerprint, scan_profile, disk_size, bytes_per_sector,
                        cumulative_bytes_scanned + completed, files,
                    )
                break

        if (cursor_checkpoint is None and range_index < len(merged_ranges)
                and completed == 0 and not stop_scan):
            final_index = min(range_index, len(merged_ranges) - 1)
            final_offset = max(merged_ranges[final_index][0], next_offset)
            cursor_checkpoint = make_checkpoint(
                merged_ranges, final_index, final_offset, initial_carry,
                range_fingerprint, scan_profile, disk_size, bytes_per_sector,
                cumulative_bytes_scanned, files,
            )

        if cursor_checkpoint is None and ranges_truncated and merged_ranges:
            cursor_checkpoint = make_checkpoint(
                merged_ranges, len(merged_ranges), merged_ranges[-1][1], b"",
                range_fingerprint, scan_profile, disk_size, bytes_per_sector,
                cumulative_bytes_scanned + completed, files,
            )

        if (cursor_checkpoint is None and collect_png_signatures
                and png_signature_offsets and merged_ranges):
            # Keep the bounded signature window attached to the completed raw
            # cursor while the opt-in PNG strategies consume it over later calls.
            cursor_checkpoint = make_checkpoint(
                merged_ranges, len(merged_ranges), merged_ranges[-1][1], b"",
                range_fingerprint, scan_profile, disk_size, bytes_per_sector,
                cumulative_bytes_scanned + completed, files,
            )

        if checkpoint_callback is not None:
            checkpoint_callback(cursor_checkpoint)

        return ContentCarveResult(
            tuple(files), completed, scan_limit_reached, candidate_bytes_read, candidate_limit_reached,
            file_count_limit_reached, retained_bytes_limit_reached,
            tuple(FormatCarveStats(
                family,
                candidates_by_extension[family],
                sum(item.extension in self.EXTENSIONS_BY_FAMILY[family] for item in files),
                bytes_by_extension[family],
                candidate_limits_by_extension[family],
                file_size_limits_by_extension[family],
                decoded_size_limits_by_extension[family],
            ) for family, _ in self.FORMAT_SIGNATURES),
            self.max_candidate_read_bytes,
            self.max_candidate_read_bytes_per_format,
            self.max_file_bytes,
            self.max_decoded_png_bytes,
            self.max_scan_bytes,
            self.max_total_file_bytes,
            self.max_files,
            cursor_checkpoint,
            candidate_restore_bytes_read,
            cumulative_bytes_scanned + completed,
            tuple(sorted(png_signature_offsets)),
            png_signature_set_truncated,
        )

    def _restore_candidates(self, references, ranges, retained_candidate_data=None):
        restored = []
        bytes_read_total = 0
        for reference in references:
            range_end = next((end for start, end in ranges
                              if start <= reference.offset < end), None)
            if range_end is None or reference.extension not in self.SIGNATURES_BY_EXTENSION:
                continue
            original_max_file_bytes = self.max_file_bytes
            self.max_file_bytes = max(self.max_file_bytes, reference.size_bytes + self.chunk_size)
            try:
                candidate, bytes_read, _ = self._read_candidate(
                    reference.extension,
                    reference.offset,
                    range_end,
                    max(reference.size_bytes + self.chunk_size, self.max_candidate_read_bytes),
                )
            finally:
                self.max_file_bytes = original_max_file_bytes
            bytes_read_total += bytes_read
            if (candidate is not None and len(candidate) == reference.size_bytes
                    and hashlib.sha256(candidate).hexdigest() == reference.sha256):
                retained_data = (retained_candidate_data or {}).get(
                    (reference.offset, reference.sha256),
                )
                if (retained_data is not None and len(retained_data) == reference.size_bytes
                        and hashlib.sha256(retained_data).hexdigest() == reference.sha256):
                    candidate = retained_data
                restored.append(CarvedContent(reference.offset, reference.extension, candidate))
        return restored, bytes_read_total

    @classmethod
    def _range_fingerprint(cls, ranges, disk_size):
        payload = json.dumps(
            {"diskSize": disk_size, "ranges": ranges}, separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _processed_ranges(ranges, range_index, next_offset):
        """Return only normalized intervals whose scan positions are consumed."""
        processed = list(ranges[:min(range_index, len(ranges))])
        if range_index < len(ranges):
            start, end = ranges[range_index]
            clipped_end = min(end, max(start, next_offset))
            if clipped_end > start:
                processed.append((start, clipped_end))
        return tuple(processed)

    @staticmethod
    def _prefix_ranges_through_offset(ranges, next_offset):
        """Clip a normalized range set to the physical scan cursor."""
        prefix = []
        for start, end in ranges:
            if start >= next_offset:
                break
            clipped_end = min(end, next_offset)
            if clipped_end > start:
                prefix.append((start, clipped_end))
            if end >= next_offset:
                break
        return tuple(prefix)

    @staticmethod
    def _resume_position(ranges, next_offset):
        """Map a saved physical cursor into a possibly expanded range set."""
        for index, (start, end) in enumerate(ranges):
            if start <= next_offset < end:
                return index, next_offset
            if start >= next_offset:
                return index, start
        return len(ranges), 0

    @classmethod
    def _scan_profile(cls, collect_png_signatures=False):
        payload = json.dumps(
            [(family, signature.hex(), cls.SIGNATURE_OFFSETS.get(family, 0))
             for family, signature in cls.FORMAT_SIGNATURES],
            separators=(",", ":"),
        ).encode("ascii")
        profile = b"raw-carver-structure-v1:" + payload
        if collect_png_signatures:
            profile += b":png-signatures-v2-paged"
        return hashlib.sha256(profile).hexdigest()

    @staticmethod
    def _remaining_bytes(ranges, range_index, next_offset):
        if range_index >= len(ranges):
            return 0
        first_start, first_end = ranges[range_index]
        total = max(0, first_end - max(first_start, next_offset))
        return total + sum(end - start for start, end in ranges[range_index + 1:])

    @classmethod
    def _checkpoint_matches(cls, checkpoint, ranges, disk_size, bytes_per_sector,
                            range_fingerprint, scan_profile):
        if checkpoint is None:
            return False
        if (not isinstance(checkpoint, CarvingCheckpoint)
                or checkpoint.scan_profile != scan_profile
                or checkpoint.disk_size != disk_size
                or checkpoint.bytes_per_sector != bytes_per_sector
                or checkpoint.next_offset > disk_size):
            return False
        if checkpoint.processed_range_fingerprint:
            prefix = cls._prefix_ranges_through_offset(ranges, checkpoint.next_offset)
            if cls._range_fingerprint(prefix, disk_size) != checkpoint.processed_range_fingerprint:
                return False
        else:
            if (checkpoint.range_fingerprint != range_fingerprint
                    or checkpoint.range_index > len(ranges)):
                return False
            if checkpoint.range_index < len(ranges):
                start, end = ranges[checkpoint.range_index]
                if not start <= checkpoint.next_offset <= end:
                    return False
            elif checkpoint.next_offset != 0:
                return False
        return all(
            item.extension in cls.SIGNATURES_BY_EXTENSION
            and item.offset + item.size_bytes <= disk_size
            and item.size_bytes <= cls.DEFAULT_MAX_FILE_BYTES
            and any(start <= item.offset < end for start, end in ranges)
            for item in checkpoint.candidates
        ) and len(checkpoint.png_signature_offsets) <= cls.MAX_PNG_SIGNATURE_OFFSETS and all(
            any(start <= offset < end for start, end in ranges)
            for offset in checkpoint.png_signature_offsets
        )

    @classmethod
    def _make_checkpoint(cls, ranges, range_index, next_offset, carry, range_fingerprint,
                         scan_profile, disk_size, bytes_per_sector, bytes_scanned, files,
                         *, png_signature_offsets=(), png_signature_set_truncated=False):
        references = tuple(CarvedCandidateReference(
            offset=item.offset,
            extension=item.extension,
            size_bytes=len(item.data),
            sha256=hashlib.sha256(item.data).hexdigest(),
        ) for item in files)
        return CarvingCheckpoint(
            range_fingerprint=range_fingerprint,
            range_index=range_index,
            next_offset=next_offset,
            disk_size=disk_size,
            bytes_per_sector=bytes_per_sector,
            scan_profile=scan_profile,
            candidates=references,
            bytes_scanned=bytes_scanned,
            signature_carry=carry,
            processed_range_fingerprint=cls._range_fingerprint(
                cls._processed_ranges(ranges, range_index, next_offset), disk_size,
            ),
            png_signature_offsets=tuple(png_signature_offsets),
            png_signature_set_truncated=bool(png_signature_set_truncated),
        )

    @classmethod
    def _find_next_signature(cls, data, start):
        candidates = []
        for family, signature in cls.FORMAT_SIGNATURES:
            signature_offset = cls.SIGNATURE_OFFSETS.get(family, 0)
            position = data.find(signature, start + signature_offset)
            if position >= signature_offset:
                candidate_position = position - signature_offset
                if candidate_position >= start:
                    candidates.append((candidate_position, family))
        if not candidates:
            return None
        position, family = min(candidates)
        return family, position

    def _read_candidate(self, extension, offset, range_end, byte_budget):
        family = self.FAMILY_BY_EXTENSION.get(extension, extension)
        if extension == ".jpg":
            return self._read_jpeg(offset, range_end, byte_budget)
        if extension == ".png":
            return self._read_png(offset, range_end, byte_budget)
        if extension == ".pdf":
            return self._read_pdf(offset, range_end, byte_budget)
        if family == ".office_zip":
            return self._read_office_zip(offset, range_end, byte_budget)
        if family == ".mp4":
            return self._read_mp4(offset, range_end, byte_budget)
        if family in (".rtf", ".ole_cfb"):
            return self._read_structured_additional(offset, range_end, byte_budget, family)
        return None, 0, None

    def _read_structured_additional(self, offset, range_end, byte_budget, family):
        """Read RTF or CFB until its structural parser can determine file length."""
        content = bytearray()
        cursor = offset
        bytes_read = 0
        while (cursor < range_end and len(content) < self.max_file_bytes
               and bytes_read < byte_budget):
            request_size = min(
                self.chunk_size, range_end - cursor,
                self.max_file_bytes - len(content), byte_budget - bytes_read,
            )
            if request_size <= 0:
                break
            data = bytes(self.disk.read_at(cursor, request_size))
            if len(data) != request_size:
                raise OSError(
                    f"Short {family} candidate read at {cursor:#x}: "
                    f"received {len(data)} of {request_size} bytes"
                )
            content.extend(data)
            cursor += request_size
            bytes_read += request_size
            candidate = validate_additional_candidate(content)
            if (candidate is not None
                    and candidate.extension in self.EXTENSIONS_BY_FAMILY[family]):
                return bytes(content[:candidate.size_bytes]), bytes_read, None
        if len(content) >= self.max_file_bytes:
            return None, bytes_read, "file_size"
        if bytes_read >= byte_budget:
            return None, bytes_read, "candidate_budget"
        return None, bytes_read, None

    def _read_office_zip(self, offset, range_end, byte_budget):
        """Read one bounded ZIP candidate; its family budget is shared by OOXML."""
        if byte_budget < 30:
            partial = self._read_candidate_bytes(offset, byte_budget, range_end, byte_budget)
            if partial is None:
                return None, 0, "candidate_budget"
            return None, len(partial), "candidate_budget"
        fixed_header = self._read_candidate_bytes(offset, 30, range_end, byte_budget)
        if fixed_header is None:
            return None, 0, "candidate_budget" if byte_budget < 30 else None
        name_length = int.from_bytes(fixed_header[26:28], "little")
        extra_length = int.from_bytes(fixed_header[28:30], "little")
        variable_length = name_length + extra_length
        bytes_read = len(fixed_header)
        variable_header = self._read_candidate_bytes(
            offset + bytes_read, variable_length, range_end, byte_budget - bytes_read,
        )
        if variable_header is None:
            return None, bytes_read, None
        bytes_read += len(variable_header)
        content = bytearray(fixed_header + variable_header)
        if not is_plausible_office_local_header(content):
            return None, bytes_read, None
        cursor = offset + len(content)
        while (cursor < range_end and len(content) < self.max_file_bytes
               and bytes_read < byte_budget):
            request_size = min(
                self.chunk_size, range_end - cursor,
                self.max_file_bytes - len(content), byte_budget - bytes_read,
            )
            if request_size <= 0:
                break
            data = bytes(self.disk.read_at(cursor, request_size))
            if len(data) != request_size:
                raise OSError(
                    f"Short OOXML candidate read at {cursor:#x}: {len(data)} of {request_size} bytes"
                )
            content.extend(data)
            bytes_read += request_size
            cursor += request_size
            if ZIP_END_OF_CENTRAL_DIRECTORY in content[-(22 + 65535):]:
                candidate = validate_additional_candidate(content)
                if (candidate is not None
                        and candidate.extension in self.EXTENSIONS_BY_FAMILY[".office_zip"]):
                    return bytes(content[:candidate.size_bytes]), bytes_read, None
        if len(content) >= self.max_file_bytes:
            return None, bytes_read, "file_size"
        if bytes_read >= byte_budget:
            return None, bytes_read, "candidate_budget"
        return None, bytes_read, None

    def _read_mp4(self, offset, range_end, byte_budget):
        """Read complete ISO-BMFF boxes; do not infer MP4 media decoding."""
        content = bytearray()
        cursor = offset
        bytes_read = 0
        saw_ftyp = saw_mdat = saw_movie_metadata = False
        box_count = 0
        while cursor < range_end and len(content) < self.max_file_bytes and bytes_read < byte_budget:
            if bytes_read + 8 > byte_budget:
                return None, bytes_read, "candidate_budget"
            is_first_box = bytes_read == 0
            header = self._read_candidate_bytes(cursor, 8, range_end, byte_budget - bytes_read)
            if header is None:
                return None, bytes_read, None
            content.extend(header)
            cursor += 8
            bytes_read += 8
            size32 = int.from_bytes(header[:4], "big")
            header_size = 8
            if size32 == 1:
                if bytes_read + 8 > byte_budget:
                    return None, bytes_read, "candidate_budget"
                extended_size = self._read_candidate_bytes(cursor, 8, range_end, byte_budget - bytes_read)
                if extended_size is None:
                    return None, bytes_read, None
                content.extend(extended_size)
                cursor += 8
                bytes_read += 8
                box_size = int.from_bytes(extended_size, "big")
                header_size = 16
            elif size32 == 0:
                # A zero-size box extends to an EOF the range does not encode.
                return None, bytes_read, "file_size"
            else:
                box_size = size32
            if box_size < header_size:
                return None, bytes_read, None
            box_type = header[4:8]
            if is_first_box:
                if box_type != b"ftyp" or box_size < 16 or (box_size - 16) % 4 != 0:
                    return None, bytes_read, None
                saw_ftyp = True
            saw_mdat |= box_type == b"mdat"
            saw_movie_metadata |= box_type in (b"moov", b"moof")
            box_count += 1
            if box_count > MAX_ISO_BMFF_BOXES:
                return None, bytes_read, None
            payload_size = box_size - header_size
            if len(content) + payload_size > self.max_file_bytes:
                return None, bytes_read, "file_size"
            if bytes_read + payload_size > byte_budget:
                return None, bytes_read, "candidate_budget"
            payload = self._read_candidate_bytes(cursor, payload_size, range_end, byte_budget - bytes_read)
            if payload is None:
                return None, bytes_read, None
            content.extend(payload)
            cursor += payload_size
            bytes_read += payload_size
            if saw_ftyp and saw_mdat and saw_movie_metadata:
                return bytes(content), bytes_read, None
        if len(content) >= self.max_file_bytes:
            return None, bytes_read, "file_size"
        if bytes_read >= byte_budget:
            return None, bytes_read, "candidate_budget"
        return None, bytes_read, None

    def _read_candidate_bytes(self, offset, size, range_end, byte_budget):
        if (size < 0 or offset + size > range_end or size > byte_budget
                or offset + size > int(self.disk.size)):
            return None
        data = bytes(self.disk.read_at(offset, size))
        if len(data) != size:
            raise OSError(
                f"Short candidate read at {offset:#x}: received {len(data)} of {size} bytes"
            )
        return data

    def _read_jpeg(self, offset: int, range_end: int, byte_budget: int):
        if offset < 0 or offset + len(self.SIGNATURE) > range_end:
            return None, 0, None
        content = bytearray()
        cursor = offset
        bytes_read = 0
        eoi_search_position = 0
        header_valid = False
        while (cursor < range_end and len(content) < self.max_file_bytes
               and bytes_read < byte_budget):
            request_size = min(
                min(self.chunk_size, 64 * 1024) if header_valid else 512,
                range_end - cursor,
                self.max_file_bytes - len(content),
                byte_budget - bytes_read,
            )
            if request_size <= 0:
                break
            data = bytes(self.disk.read_at(cursor, request_size))
            if len(data) != request_size:
                raise OSError(
                    f"Short candidate read at {cursor:#x}: received {len(data)} of {request_size} bytes"
                )
            content.extend(data)
            bytes_read += len(data)
            header_status = jpeg_header_status(content)
            if header_status is False:
                return None, bytes_read, None
            header_valid = header_status is True
            while True:
                marker = content.find(b"\xff\xd9", eoi_search_position)
                if marker < 0:
                    break
                end = marker + 2
                candidate = bytes(content[:end])
                if valid_jpeg(candidate):
                    return candidate, bytes_read, None
                # EOI-like bytes may occur inside a length-delimited APP or
                # other segment. Keep reading and test later marker positions.
                eoi_search_position = marker + 2
            cursor += request_size
        if len(content) >= self.max_file_bytes:
            return None, bytes_read, "file_size"
        if bytes_read >= byte_budget:
            return None, bytes_read, "candidate_budget"
        return None, bytes_read, None

    def _read_png(self, offset, range_end, byte_budget):
        content = bytearray()
        cursor = offset
        bytes_read = 0
        limit_reason = None

        def read_exact(size):
            nonlocal cursor, bytes_read, limit_reason
            if (size < 0 or len(content) + size > self.max_file_bytes
                    or bytes_read + size > byte_budget or cursor + size > range_end):
                if size >= 0 and bytes_read + size > byte_budget:
                    limit_reason = "candidate_budget"
                elif size >= 0 and len(content) + size > self.max_file_bytes:
                    limit_reason = "file_size"
                return None
            data = bytes(self.disk.read_at(cursor, size))
            if len(data) != size:
                raise OSError(
                    f"Short PNG candidate read at {cursor:#x}: {len(data)} of {size} bytes"
                )
            content.extend(data)
            cursor += size
            bytes_read += size
            return data

        signature = read_exact(8)
        if signature != b"\x89PNG\r\n\x1a\n":
            return None, bytes_read, limit_reason
        seen_ihdr = seen_idat = seen_iend = False
        seen_plte = False
        idat_ended = False
        png_decompressor = None
        expected_decoded_size = None
        decoded_size = 0
        while not seen_iend:
            header = read_exact(8)
            if header is None:
                return None, bytes_read, limit_reason
            length = int.from_bytes(header[:4], "big")
            chunk_type = header[4:]
            if length > self.max_file_bytes:
                return None, bytes_read, "file_size"
            if (len(chunk_type) != 4 or not all(
                    65 <= value <= 90 or 97 <= value <= 122 for value in chunk_type)
                    or not 65 <= chunk_type[2] <= 90):
                return None, bytes_read, limit_reason
            if not seen_ihdr:
                if chunk_type != b"IHDR" or length != 13:
                    return None, bytes_read, limit_reason
            elif chunk_type == b"IHDR":
                return None, bytes_read, limit_reason
            if chunk_type == b"PLTE":
                if (seen_plte or seen_idat or length == 0 or length > 768 or length % 3
                        or (seen_ihdr and color_type == 3
                            and length // 3 > (1 << bit_depth))):
                    return None, bytes_read, limit_reason
                seen_plte = True
            if chunk_type == b"IDAT":
                if not seen_ihdr or (color_type == 3 and not seen_plte):
                    return None, bytes_read, limit_reason
                if idat_ended:
                    return None, bytes_read, limit_reason
                seen_idat = True
            elif seen_idat and chunk_type != b"IEND":
                idat_ended = True
            if chunk_type[:1].isupper() and chunk_type not in (b"IHDR", b"PLTE", b"IDAT", b"IEND"):
                return None, bytes_read, limit_reason
            payload_and_crc = read_exact(length + 4)
            if payload_and_crc is None:
                return None, bytes_read, limit_reason
            payload, expected_crc_bytes = payload_and_crc[:-4], payload_and_crc[-4:]
            expected_crc = int.from_bytes(expected_crc_bytes, "big")
            actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
            if actual_crc != expected_crc:
                return None, bytes_read, limit_reason
            if chunk_type == b"IHDR":
                width = int.from_bytes(payload[:4], "big")
                height = int.from_bytes(payload[4:8], "big")
                bit_depth, color_type, compression, filtering, interlace = payload[8:13]
                legal_depths = {
                    0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8),
                    4: (8, 16), 6: (8, 16),
                }
                if (width == 0 or height == 0 or color_type not in legal_depths
                        or bit_depth not in legal_depths[color_type]
                        or compression != 0 or filtering != 0 or interlace not in (0, 1)):
                    return None, bytes_read, limit_reason
                if color_type in (0, 4) and seen_plte:
                    return None, bytes_read, limit_reason
                expected_decoded_size = png_decoded_size(
                    width, height, bit_depth, color_type, interlace,
                )
                if expected_decoded_size > self.max_decoded_png_bytes:
                    return None, bytes_read, "decoded_data"
                png_decompressor = zlib.decompressobj()
                seen_ihdr = True
            elif chunk_type == b"IDAT":
                try:
                    decoded = png_decompressor.decompress(
                        payload, expected_decoded_size - decoded_size + 1,
                    )
                except zlib.error:
                    return None, bytes_read, limit_reason
                decoded_size += len(decoded)
                if (decoded_size > expected_decoded_size
                        or png_decompressor.unconsumed_tail or png_decompressor.unused_data):
                    return None, bytes_read, limit_reason
            elif chunk_type == b"IEND":
                if length != 0 or not seen_idat:
                    return None, bytes_read, limit_reason
                try:
                    decoded_size += len(png_decompressor.flush(
                        expected_decoded_size - decoded_size + 1,
                    ))
                except zlib.error:
                    return None, bytes_read, limit_reason
                if (decoded_size != expected_decoded_size or not png_decompressor.eof
                        or png_decompressor.unused_data or png_decompressor.unconsumed_tail):
                    return None, bytes_read, limit_reason
                seen_iend = True
        return bytes(content), bytes_read, limit_reason

    def _read_pdf(self, offset, range_end, byte_budget):
        content = bytearray()
        cursor = offset
        bytes_read = 0
        while (cursor < range_end and len(content) < self.max_file_bytes
               and bytes_read < byte_budget):
            request_size = min(4096, self.chunk_size, range_end - cursor,
                               self.max_file_bytes - len(content), byte_budget - bytes_read)
            if request_size <= 0:
                break
            data = bytes(self.disk.read_at(cursor, request_size))
            if len(data) != request_size:
                raise OSError(
                    f"Short PDF candidate read at {cursor:#x}: {len(data)} of {request_size} bytes"
                )
            content.extend(data)
            bytes_read += len(data)
            cursor += request_size
            marker = content.rfind(b"%%EOF")
            if marker >= 0:
                candidate_end = marker + len(b"%%EOF")
                candidate = bytes(content[:candidate_end]).rstrip(b"\x00\t\n\x0c\r ")
                if valid_pdf(candidate):
                    return candidate, bytes_read, None
        if len(content) >= self.max_file_bytes:
            return None, bytes_read, "file_size"
        if bytes_read >= byte_budget:
            return None, bytes_read, "candidate_budget"
        return None, bytes_read, None

    @staticmethod
    def _merge_ranges(ranges, disk_size):
        normalized = []
        for item in ranges:
            if len(item) != 2:
                raise ValueError("Each carving range must be a (start, end) pair")
            start, end = int(item[0]), int(item[1])
            if start < 0 or end < start or end > disk_size:
                raise ValueError("Carving range is outside the physical disk")
            if end > start:
                normalized.append((start, end))
        merged = []
        for start, end in sorted(normalized):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return tuple(merged)
