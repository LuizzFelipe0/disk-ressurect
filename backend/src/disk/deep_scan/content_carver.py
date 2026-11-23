"""Bounded, read-only recovery of structurally validated contiguous files."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
import re
from typing import Callable, Iterable
import zlib

from disk.deep_scan.carving_checkpoint import CarvedCandidateReference, CarvingCheckpoint
from disk.deep_scan.additional_format_validators import (
    ZIP_END_OF_CENTRAL_DIRECTORY,
    ZIP_LOCAL_FILE_HEADER,
    validate_additional_candidate,
)


@dataclass(frozen=True)
class CarvedContent:
    """A structurally validated contiguous file with no inferred original name."""

    offset: int
    extension: str
    data: bytes

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
    )
    SIGNATURE_OFFSETS = {".mp4": 4}
    EXTENSIONS_BY_FAMILY = {
        ".jpg": (".jpg",),
        ".png": (".png",),
        ".pdf": (".pdf",),
        ".office_zip": (".docx", ".docm", ".xlsx", ".xlsm"),
        ".mp4": (".mp4",),
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
    }
    DEFAULT_CHUNK_SIZE = 1024 * 1024
    DEFAULT_MAX_SCAN_BYTES = 1024 * 1024 * 1024
    DEFAULT_MAX_FILE_BYTES = 32 * 1024 * 1024
    DEFAULT_MAX_TOTAL_FILE_BYTES = 128 * 1024 * 1024
    DEFAULT_MAX_CANDIDATE_READ_BYTES = 768 * 1024 * 1024
    DEFAULT_MAX_CANDIDATE_READ_BYTES_PER_FORMAT = 256 * 1024 * 1024
    DEFAULT_MAX_FILES = 256
    DEFAULT_MAX_DECODED_PNG_BYTES = 64 * 1024 * 1024

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
        checkpoint_callback: Callable[[CarvingCheckpoint | None], None] | None = None,
        ranges_truncated: bool = False,
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
        scan_profile = self._scan_profile()
        if not self._checkpoint_matches(
            resume_checkpoint, merged_ranges, disk_size, bytes_per_sector,
            range_fingerprint, scan_profile,
        ):
            resume_checkpoint = None

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
        if resume_checkpoint is not None:
            files, candidate_restore_bytes_read = self._restore_candidates(
                resume_checkpoint.candidates, merged_ranges,
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
        for index in range(range_index, len(merged_ranges)):
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
                            if family in (".office_zip", ".mp4"):
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
                    cursor_checkpoint = self._make_checkpoint(
                        merged_ranges, index, resume_offset, b"", range_fingerprint, scan_profile,
                        disk_size, bytes_per_sector, cumulative_bytes_scanned + completed, files,
                    )
                    stop_scan = True
                    break
                if cursor < range_end and completed < self.max_scan_bytes:
                    cursor_checkpoint = self._make_checkpoint(
                        merged_ranges, index, cursor, carry, range_fingerprint, scan_profile,
                        disk_size, bytes_per_sector, cumulative_bytes_scanned + completed, files,
                    )
                    if checkpoint_callback is not None:
                        checkpoint_callback(cursor_checkpoint)
                if candidate_limit_reached or retained_bytes_limit_reached:
                    if cursor_checkpoint is None:
                        if cursor < range_end:
                            cursor_checkpoint = self._make_checkpoint(
                                merged_ranges, index, cursor, carry, range_fingerprint, scan_profile,
                                disk_size, bytes_per_sector,
                                cumulative_bytes_scanned + completed, files,
                            )
                        elif index + 1 < len(merged_ranges):
                            cursor_checkpoint = self._make_checkpoint(
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
                    cursor_checkpoint = self._make_checkpoint(
                        merged_ranges, next_range_index, merged_ranges[next_range_index][0], b"",
                        range_fingerprint, scan_profile, disk_size, bytes_per_sector,
                        cumulative_bytes_scanned + completed, files,
                    )
                else:
                    cursor_checkpoint = None
            if completed >= self.max_scan_bytes:
                if cursor < range_end:
                    cursor_checkpoint = self._make_checkpoint(
                        merged_ranges, index, cursor, carry, range_fingerprint, scan_profile,
                        disk_size, bytes_per_sector,
                        cumulative_bytes_scanned + completed, files,
                    )
                elif index + 1 < len(merged_ranges):
                    cursor_checkpoint = self._make_checkpoint(
                        merged_ranges, index + 1, merged_ranges[index + 1][0], b"",
                        range_fingerprint, scan_profile, disk_size, bytes_per_sector,
                        cumulative_bytes_scanned + completed, files,
                    )
                break

        if (cursor_checkpoint is None and range_index < len(merged_ranges)
                and completed == 0 and not stop_scan):
            final_index = min(range_index, len(merged_ranges) - 1)
            final_offset = max(merged_ranges[final_index][0], next_offset)
            cursor_checkpoint = self._make_checkpoint(
                merged_ranges, final_index, final_offset, initial_carry,
                range_fingerprint, scan_profile, disk_size, bytes_per_sector,
                cumulative_bytes_scanned, files,
            )

        if cursor_checkpoint is None and ranges_truncated and merged_ranges:
            cursor_checkpoint = self._make_checkpoint(
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
        )

    def _restore_candidates(self, references, ranges):
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
    def _scan_profile(cls):
        payload = json.dumps(
            [(family, signature.hex(), cls.SIGNATURE_OFFSETS.get(family, 0))
             for family, signature in cls.FORMAT_SIGNATURES],
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(b"raw-carver-structure-v1:" + payload).hexdigest()

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
        )

    @classmethod
    def _make_checkpoint(cls, ranges, range_index, next_offset, carry, range_fingerprint,
                         scan_profile, disk_size, bytes_per_sector, bytes_scanned, files):
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
        return None, 0, None

    def _read_office_zip(self, offset, range_end, byte_budget):
        """Read one bounded ZIP candidate; its family budget is shared by OOXML."""
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
                saw_ftyp = box_type == b"ftyp"
            saw_mdat |= box_type == b"mdat"
            saw_movie_metadata |= box_type in (b"moov", b"moof")
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
                candidate = validate_additional_candidate(content)
                if candidate is not None and candidate.extension == ".mp4":
                    return bytes(content[:candidate.size_bytes]), bytes_read, None
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
            header_status = self._jpeg_header_status(content)
            if header_status is False:
                return None, bytes_read, None
            header_valid = header_status is True
            while True:
                marker = content.find(b"\xff\xd9", eoi_search_position)
                if marker < 0:
                    break
                end = marker + 2
                candidate = bytes(content[:end])
                if self._valid_jpeg(candidate):
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

    @classmethod
    def _jpeg_header_status(cls, data):
        """Return None for incomplete headers, False for invalid, True after SOS."""
        if len(data) < 2:
            return None
        if data[:2] != b"\xff\xd8":
            return False
        pos = 2
        has_frame = False
        while pos < len(data):
            if data[pos] != 0xFF:
                return False
            while pos < len(data) and data[pos] == 0xFF:
                pos += 1
            if pos >= len(data):
                return None
            marker = data[pos]
            pos += 1
            if marker in (0xD8, 0x00, 0xD9):
                return False
            if 0xD0 <= marker <= 0xD7 or marker == 0x01:
                continue
            if pos + 2 > len(data):
                return None
            segment_length = int.from_bytes(data[pos:pos + 2], "big")
            if segment_length < 2:
                return False
            segment_end = pos + segment_length
            if segment_end > len(data):
                return None
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if segment_length < 8:
                    return False
                height = int.from_bytes(data[pos + 3:pos + 5], "big")
                width = int.from_bytes(data[pos + 5:pos + 7], "big")
                components = data[pos + 7]
                if (height == 0 or width == 0 or components == 0
                        or segment_length != 8 + 3 * components):
                    return False
                has_frame = True
            if marker == 0xDA:
                components = data[pos + 2] if segment_length >= 3 else 0
                if (components == 0 or segment_length != 6 + 2 * components
                        or not has_frame):
                    return False
                return True
            pos = segment_end
        return None

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
                expected_decoded_size = self._png_decoded_size(
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

    @staticmethod
    def _png_decoded_size(width, height, bit_depth, color_type, interlace):
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
        bits_per_pixel = channels * bit_depth
        if not interlace:
            return ((width * bits_per_pixel + 7) // 8 + 1) * height
        passes = (
            (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
            (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2),
        )
        total = 0
        for x_start, y_start, x_step, y_step in passes:
            pass_width = max(0, (width - x_start + x_step - 1) // x_step)
            pass_height = max(0, (height - y_start + y_step - 1) // y_step)
            if pass_width and pass_height:
                row_bytes = (pass_width * bits_per_pixel + 7) // 8
                total += (row_bytes + 1) * pass_height
        return total

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
                if self._valid_pdf(candidate):
                    return candidate, bytes_read, None
        if len(content) >= self.max_file_bytes:
            return None, bytes_read, "file_size"
        if bytes_read >= byte_budget:
            return None, bytes_read, "candidate_budget"
        return None, bytes_read, None

    @staticmethod
    def _valid_pdf(data):
        if not data.startswith(b"%PDF-") or not re.search(rb"%PDF-[0-9]\.[0-9]", data[:16]):
            return False
        eof = data.rfind(b"%%EOF")
        if eof < 0:
            return False
        startxref = list(re.finditer(rb"startxref\s+(\d+)\s*$", data[:eof]))
        if not startxref:
            return False
        xref_offset = int(startxref[-1].group(1))
        if xref_offset < 0 or xref_offset >= eof:
            return False
        return RawContentCarver._valid_classic_xref(data[xref_offset:eof], xref_offset)

    @staticmethod
    def _valid_classic_xref(data, xref_offset):
        """Validate classic xref subsections and the trailer's required references.

        Xref streams are conservatively rejected because validating their
        compressed entry table requires a separate bounded decoder.
        """
        lines = data.splitlines()
        if not lines or lines[0].strip() != b"xref":
            return False
        index = 1
        maximum_object_number = 0
        while index < len(lines):
            line = lines[index].strip()
            index += 1
            if not line:
                continue
            if line == b"trailer":
                dictionary_lines = []
                while index < len(lines):
                    dictionary_lines.append(lines[index])
                    index += 1
                    if b">>" in lines[index - 1]:
                        break
                dictionary = b"\n".join(dictionary_lines)
                size_match = re.search(rb"/Size\s+(\d+)\b", dictionary)
                root_match = re.search(rb"/Root\s+(\d+)\s+(\d+)\s+R\b", dictionary)
                if not size_match or not root_match or b"<<" not in dictionary or b">>" not in dictionary:
                    return False
                size = int(size_match.group(1))
                root_number, root_generation = map(int, root_match.groups())
                return (size > maximum_object_number and 0 < root_number < size
                        and root_generation <= 65535)

            subsection = re.fullmatch(rb"(\d+)\s+(\d+)", line)
            if not subsection:
                return False
            first, count = map(int, subsection.groups())
            if count <= 0 or first + count > 10_000_000:
                return False
            maximum_object_number = max(maximum_object_number, first + count - 1)
            for _ in range(count):
                if index >= len(lines):
                    return False
                entry = re.fullmatch(rb"\s*(\d{10})\s+(\d{5})\s+([nf])\s*", lines[index])
                index += 1
                if not entry:
                    return False
                offset, generation = int(entry.group(1)), int(entry.group(2))
                if generation > 65535 or (entry.group(3) == b"n" and offset >= xref_offset):
                    return False
        return False

    @staticmethod
    def _valid_jpeg(data: bytes) -> bool:
        """Validate JPEG marker lengths, at least one frame/scan, and EOI."""
        if len(data) < 12 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
            return False
        pos = 2
        has_frame = False
        has_scan = False
        length = len(data)
        while pos < length:
            if data[pos] != 0xFF:
                return False
            while pos < length and data[pos] == 0xFF:
                pos += 1
            if pos >= length:
                return False
            marker = data[pos]
            pos += 1
            if marker == 0xD9:
                return has_frame and has_scan and pos == length
            if marker in (0xD8, 0x00):
                return False
            if 0xD0 <= marker <= 0xD7 or marker == 0x01:
                continue
            if pos + 2 > length:
                return False
            segment_length = int.from_bytes(data[pos:pos + 2], "big")
            if segment_length < 2 or pos + segment_length > length:
                return False
            segment_end = pos + segment_length
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if segment_length < 8:
                    return False
                height = int.from_bytes(data[pos + 3:pos + 5], "big")
                width = int.from_bytes(data[pos + 5:pos + 7], "big")
                components = data[pos + 7]
                if height == 0 or width == 0 or components == 0 or segment_length != 8 + 3 * components:
                    return False
                has_frame = True
            if marker == 0xDA:
                components = data[pos + 2] if segment_length >= 3 else 0
                if components == 0 or segment_length != 6 + 2 * components:
                    return False
                has_scan = True
                pos = segment_end
                while pos < length:
                    if data[pos] != 0xFF:
                        pos += 1
                        continue
                    marker_start = pos
                    while pos < length and data[pos] == 0xFF:
                        pos += 1
                    if pos >= length:
                        return False
                    entropy_marker = data[pos]
                    if entropy_marker == 0x00 or 0xD0 <= entropy_marker <= 0xD7:
                        pos += 1
                        continue
                    pos = marker_start
                    break
                continue
            pos = segment_end
        return False

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
