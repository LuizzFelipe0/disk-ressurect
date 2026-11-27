"""Test-only extraction of an intact JPEG thumbnail from a damaged JPEG."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import hashlib
import os
import struct
import sys
import time
import unittest

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.carving.content_carver import RawContentCarver
from infrastructure.formats.primary import valid_jpeg


MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_THUMBNAIL_BYTES = 256 * 1024
MAX_RETAINED_BYTES = 16 * 1024 * 1024
TIME_LIMIT_SECONDS = 2.0


@dataclass(frozen=True)
class ThumbnailResult:
    status: str
    stop_reason: str
    data: bytes
    source_range: tuple[int, int] | None
    bytes_read: int
    elapsed_seconds: float
    retained_bytes: int


class _BytesSource:
    def __init__(self, data: bytes, fail: bool = False):
        self.data = data
        self.size = len(data)
        self.fail = fail
        self.bytes_read = 0

    def read_at(self, offset: int, size: int) -> bytes:
        if self.fail:
            raise OSError("synthetic read failure")
        if offset < 0 or size < 0 or offset + size > self.size:
            raise OSError("out-of-range read")
        self.bytes_read += size
        return self.data[offset:offset + size]


def _jpeg_bytes(size: tuple[int, int], seed: int, *, progressive: bool = False) -> bytes:
    width, height = size
    pixels = bytes((index * 37 + seed * 19) & 0xFF for index in range(width * height * 3))
    image = Image.frombytes("RGB", size, pixels)
    output = BytesIO()
    image.save(output, format="JPEG", quality=83, progressive=progressive,
               optimize=False, subsampling=0)
    return output.getvalue()


def _exif_app1_with_thumbnail(thumbnail: bytes) -> bytes:
    """Build an EXIF APP1 with IFD0 and an IFD1 JPEG interchange thumbnail."""
    tiff_offset = 8  # APP1's six-byte Exif preamble followed by the TIFF header.
    ifd0_offset = 8
    ifd0_size = 2 + 4
    ifd1_offset = ifd0_offset + ifd0_size
    ifd1_size = 2 + 2 * 12 + 4
    thumbnail_offset = ifd1_offset + ifd1_size
    tiff = bytearray(b"MM\x00*" + struct.pack(">I", ifd0_offset))
    tiff.extend(struct.pack(">H", 0))
    tiff.extend(struct.pack(">I", ifd1_offset))
    tiff.extend(struct.pack(">H", 2))
    tiff.extend(struct.pack(">HHI4s", 0x0201, 4, 1, struct.pack(">I", thumbnail_offset)))
    tiff.extend(struct.pack(">HHI4s", 0x0202, 4, 1, struct.pack(">I", len(thumbnail))))
    tiff.extend(struct.pack(">I", 0))
    tiff.extend(thumbnail)
    payload = b"Exif\x00\x00" + bytes(tiff)
    segment_length = len(payload) + 2
    return b"\xff\xe1" + struct.pack(">H", segment_length) + payload


def _damaged_jpeg_with_exif_thumbnail(*, progressive: bool = False):
    main = _jpeg_bytes((180, 120), 3, progressive=progressive)
    thumbnail = _jpeg_bytes((32, 24), 91)
    app1 = _exif_app1_with_thumbnail(thumbnail)
    original = main[:2] + app1 + main[2:]
    # The cut point is fixture-oracle data. The extractor receives only these
    # surviving bytes and has no access to the original or cut offset.
    sos = original.index(b"\xff\xda")
    scan_start = sos + 2 + int.from_bytes(original[sos + 2:sos + 4], "big")
    damaged = original[:scan_start + max(1, (len(original) - scan_start) // 3)]
    return original, damaged, thumbnail


def extract_exif_thumbnail(source: _BytesSource, *, max_input_bytes: int = MAX_INPUT_BYTES,
                           max_thumbnail_bytes: int = MAX_THUMBNAIL_BYTES,
                           max_retained_bytes: int = MAX_RETAINED_BYTES,
                           time_limit_seconds: float = TIME_LIMIT_SECONDS,
                           clock=time.monotonic) -> ThumbnailResult:
    started = time.perf_counter()
    monotonic_started = clock()
    if source.size > max_input_bytes:
        return ThumbnailResult("rejected", "input_limit", b"", None, 0,
                               time.perf_counter() - started, 0)
    if source.size + max_thumbnail_bytes > max_retained_bytes:
        return ThumbnailResult("rejected", "retained_memory_limit", b"", None, 0,
                               time.perf_counter() - started, 0)
    try:
        data = source.read_at(0, source.size)
    except OSError:
        return ThumbnailResult("error", "source_read_error", b"", None,
                               source.bytes_read, time.perf_counter() - started, 0)
    if clock() - monotonic_started >= time_limit_seconds:
        return ThumbnailResult("inconclusive", "time_limit", b"", None,
                               source.bytes_read, time.perf_counter() - started, len(data))

    if not data.startswith(b"\xff\xd8"):
        return ThumbnailResult("rejected", "jpeg_signature_invalid", b"", None,
                               source.bytes_read, time.perf_counter() - started, len(data))
    position = 2
    while position + 4 <= len(data) and data[position] == 0xFF:
        if clock() - monotonic_started >= time_limit_seconds:
            return ThumbnailResult("inconclusive", "time_limit", b"", None,
                                   source.bytes_read, time.perf_counter() - started, len(data))
        marker_start = position
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            return ThumbnailResult("rejected", "exif_not_found", b"", None,
                                   source.bytes_read, time.perf_counter() - started, len(data))
        if position + 2 > len(data):
            break
        segment_length = int.from_bytes(data[position:position + 2], "big")
        if segment_length < 2 or position + segment_length > len(data):
            return ThumbnailResult("rejected", "truncated_segment", b"", None,
                                   source.bytes_read, time.perf_counter() - started, len(data))
        segment_end = position + segment_length
        if marker == 0xDA:
            break
        if marker == 0xE1 and data[position + 2:position + 8] == b"Exif\x00\x00":
            tiff_start = position + 8
            tiff_end = segment_end
            tiff = data[tiff_start:tiff_end]
            if len(tiff) < 8:
                return ThumbnailResult("rejected", "tiff_header_truncated", b"", None,
                                       source.bytes_read, time.perf_counter() - started, len(data))
            byte_order = tiff[:2]
            endian = ">" if byte_order == b"MM" else "<" if byte_order == b"II" else None
            if endian is None or struct.unpack(endian + "H", tiff[2:4])[0] != 42:
                return ThumbnailResult("rejected", "tiff_header_invalid", b"", None,
                                       source.bytes_read, time.perf_counter() - started, len(data))
            ifd0_offset = struct.unpack(endian + "I", tiff[4:8])[0]
            if ifd0_offset + 2 > len(tiff):
                return ThumbnailResult("rejected", "ifd0_out_of_bounds", b"", None,
                                       source.bytes_read, time.perf_counter() - started, len(data))
            ifd0_count = struct.unpack(endian + "H", tiff[ifd0_offset:ifd0_offset + 2])[0]
            next_offset_pos = ifd0_offset + 2 + ifd0_count * 12
            if next_offset_pos + 4 > len(tiff):
                return ThumbnailResult("rejected", "ifd0_truncated", b"", None,
                                       source.bytes_read, time.perf_counter() - started, len(data))
            ifd1_offset = struct.unpack(endian + "I", tiff[next_offset_pos:next_offset_pos + 4])[0]
            if not ifd1_offset:
                return ThumbnailResult("rejected", "thumbnail_missing", b"", None,
                                       source.bytes_read, time.perf_counter() - started, len(data))
            if ifd1_offset + 2 > len(tiff):
                return ThumbnailResult("rejected", "ifd1_out_of_bounds", b"", None,
                                       source.bytes_read, time.perf_counter() - started, len(data))
            entry_count = struct.unpack(endian + "H", tiff[ifd1_offset:ifd1_offset + 2])[0]
            entries_end = ifd1_offset + 2 + entry_count * 12
            if entries_end + 4 > len(tiff):
                return ThumbnailResult("rejected", "ifd1_truncated", b"", None,
                                       source.bytes_read, time.perf_counter() - started, len(data))
            values = {}
            for index in range(entry_count):
                entry = tiff[ifd1_offset + 2 + index * 12:ifd1_offset + 14 + index * 12]
                tag, value_type, count = struct.unpack(endian + "HHI", entry[:8])
                if tag in (0x0201, 0x0202) and value_type == 4 and count == 1:
                    values[tag] = struct.unpack(endian + "I", entry[8:12])[0]
            if 0x0201 not in values or 0x0202 not in values:
                return ThumbnailResult("rejected", "thumbnail_tags_missing", b"", None,
                                       source.bytes_read, time.perf_counter() - started, len(data))
            thumb_start, thumb_length = values[0x0201], values[0x0202]
            if not thumb_length or thumb_length > max_thumbnail_bytes:
                return ThumbnailResult("rejected", "thumbnail_size_limit", b"", None,
                                       source.bytes_read, time.perf_counter() - started, len(data))
            thumb_end = thumb_start + thumb_length
            if thumb_start < entries_end + 4 or thumb_end > len(tiff):
                return ThumbnailResult("rejected", "thumbnail_out_of_bounds", b"", None,
                                       source.bytes_read, time.perf_counter() - started, len(data))
            absolute_start = tiff_start + thumb_start
            thumbnail = tiff[thumb_start:thumb_end]
            if not valid_jpeg(thumbnail):
                return ThumbnailResult("rejected", "thumbnail_jpeg_invalid", b"", None,
                                       source.bytes_read, time.perf_counter() - started, len(data))
            return ThumbnailResult("partial_content", "embedded_thumbnail_extracted", thumbnail,
                                   (absolute_start, absolute_start + len(thumbnail)),
                                   source.bytes_read, time.perf_counter() - started,
                                   len(data) + len(thumbnail))
        position = segment_end
        if position <= marker_start:
            break
    return ThumbnailResult("rejected", "exif_thumbnail_not_found", b"", None,
                           source.bytes_read, time.perf_counter() - started, len(data))


class JpegPartialRecoveryExperimentTests(unittest.TestCase):
    def test_damaged_baseline_and_progressive_sources_yield_decodable_original_thumbnail(self):
        for progressive in (False, True):
            with self.subTest(progressive=progressive):
                original, damaged, expected_thumbnail = _damaged_jpeg_with_exif_thumbnail(
                    progressive=progressive,
                )
                with Image.open(BytesIO(original)) as original_image:
                    original_image.load()
                result = extract_exif_thumbnail(_BytesSource(damaged))
                with Image.open(BytesIO(result.data)) as thumbnail_image:
                    thumbnail_image.load()
                    self.assertEqual((32, 24), thumbnail_image.size)
                # The oracle hash is consulted only after extraction and decode.
                self.assertEqual(hashlib.sha256(expected_thumbnail).digest(),
                                 hashlib.sha256(result.data).digest())
                self.assertEqual("partial_content", result.status)
                self.assertEqual("embedded_thumbnail_extracted", result.stop_reason)
                self.assertIsNotNone(result.source_range)
                self.assertGreater(result.bytes_read, len(result.data))
                self.assertGreater(len(original), len(damaged))

    def test_existing_contiguous_carver_already_finds_the_embedded_thumbnail(self):
        _original, damaged, _expected_thumbnail = _damaged_jpeg_with_exif_thumbnail()
        result = extract_exif_thumbnail(_BytesSource(damaged))

        class Reader:
            size = len(damaged)

            def read_at(self, offset, size):
                return damaged[offset:offset + size]

        carved = RawContentCarver(Reader(), max_file_bytes=len(damaged)).scan(((0, len(damaged)),))
        carved_jpegs = [item.data for item in carved.files if item.extension == ".jpg"]
        # This experiment extracts proven embedded content, but does not claim
        # additional recovery over carving when the thumbnail is already found.
        self.assertIn(result.data, carved_jpegs)

    def test_missing_thumbnail_malformed_offsets_and_read_failure_are_explicit(self):
        _original, damaged, _expected_thumbnail = _damaged_jpeg_with_exif_thumbnail()
        self.assertEqual("error", extract_exif_thumbnail(_BytesSource(damaged, fail=True)).status)
        self.assertEqual("input_limit", extract_exif_thumbnail(
            _BytesSource(damaged), max_input_bytes=32,
        ).stop_reason)
        self.assertEqual("retained_memory_limit", extract_exif_thumbnail(
            _BytesSource(damaged), max_retained_bytes=len(damaged),
        ).stop_reason)
        times = iter((0.0, 0.0, 2.0))
        self.assertEqual("time_limit", extract_exif_thumbnail(
            _BytesSource(damaged), time_limit_seconds=1.0,
            clock=lambda: next(times),
        ).stop_reason)
        no_exif = b"\xff\xd8\xff\xd9"
        self.assertEqual("exif_thumbnail_not_found",
                         extract_exif_thumbnail(_BytesSource(no_exif)).stop_reason)

        original, _damaged, _thumb = _damaged_jpeg_with_exif_thumbnail()
        malformed = bytearray(original)
        app1 = malformed.index(b"Exif\x00\x00")
        tiff = app1 + 6
        # IFD0 next-IFD offset is the final 4 bytes of its zero-entry table.
        malformed[tiff + 10:tiff + 14] = struct.pack(">I", len(malformed) + 1)
        self.assertEqual("ifd1_out_of_bounds",
                         extract_exif_thumbnail(_BytesSource(bytes(malformed))).stop_reason)


if __name__ == "__main__":
    unittest.main()
