"""Test-only extraction of complete PNG rows from a surviving IDAT prefix."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
import random
import struct
import sys
import time
import unittest
import zlib

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.carving.content_carver import RawContentCarver


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_DECODED_BYTES = 8 * 1024 * 1024
MAX_RETAINED_BYTES = 16 * 1024 * 1024
TIME_LIMIT_SECONDS = 2.0
RETAINED_OVERHEAD_RESERVE = 64 * 1024
MAX_CHUNKS = 1024


@dataclass(frozen=True)
class PartialPngRows:
    status: str
    stop_reason: str
    width: int | None
    height: int | None
    channels: int | None
    rows: tuple[bytes, ...]
    source_ranges: tuple[tuple[int, int], ...]
    valid_idat_crc_count: int
    idat_crc_unknown: bool
    idat_crc_invalid: bool
    zlib_complete: bool
    iend_valid: bool
    input_bytes: int
    decoded_bytes: int
    partial_row_bytes: int


def _paeth(left, up, upper_left):
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    if up_distance <= upper_left_distance:
        return up
    return upper_left


def _unfilter_row(filter_type, filtered, previous, bytes_per_pixel):
    output = bytearray(len(filtered))
    for index, value in enumerate(filtered):
        left = output[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        up = previous[index] if previous is not None else 0
        upper_left = previous[index - bytes_per_pixel] if previous is not None and index >= bytes_per_pixel else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        elif filter_type == 4:
            predictor = _paeth(left, up, upper_left)
        else:
            raise ValueError("unsupported PNG filter")
        output[index] = (value + predictor) & 0xFF
    return bytes(output)


def recover_complete_png_rows(data, *, max_input_bytes=MAX_INPUT_BYTES,
                              max_decoded_bytes=MAX_DECODED_BYTES,
                              max_retained_bytes=MAX_RETAINED_BYTES,
                              time_limit_seconds=TIME_LIMIT_SECONDS,
                              clock=time.monotonic):
    """Decode only complete non-interlaced 8-bit RGB/RGBA rows from IDAT bytes."""
    if len(data) > max_input_bytes:
        return PartialPngRows("rejected", "input_limit", None, None, None, (), (),
                              0, False, False, False, False, 0, 0, 0)
    started = clock()
    data = bytes(data)
    if not data.startswith(PNG_SIGNATURE):
        return PartialPngRows("rejected", "signature_invalid", None, None, None, (), (),
                              0, False, False, False, False, len(data), 0, 0)

    remaining_retained = max_retained_bytes - len(data) - RETAINED_OVERHEAD_RESERVE
    if remaining_retained < 0:
        return PartialPngRows("rejected", "retained_memory_limit", None, None, None, (), (),
                              0, False, False, False, False, len(data), 0, 0)
    decoded_limit = min(max_decoded_bytes, remaining_retained // 2)

    cursor = len(PNG_SIGNATURE)
    width = height = channels = None
    interlace = None
    decompressor = zlib.decompressobj()
    decoded = bytearray()
    ranges = []
    crc_valid = 0
    crc_unknown = False
    crc_invalid = False
    iend_valid = False
    stop_reason = "incomplete_png"
    seen_ihdr = seen_idat = idat_ended = False
    chunk_count = 0

    while cursor < len(data):
        if clock() - started >= time_limit_seconds:
            stop_reason = "time_limit"
            break
        chunk_count += 1
        if chunk_count > MAX_CHUNKS:
            stop_reason = "chunk_limit"
            break
        if cursor + 8 > len(data):
            stop_reason = "truncated_chunk_header"
            break
        length = int.from_bytes(data[cursor:cursor + 4], "big")
        kind = data[cursor + 4:cursor + 8]
        payload_start = cursor + 8
        if length > max_input_bytes:
            stop_reason = "chunk_length_limit"
            break
        available = min(length, max(0, len(data) - payload_start))
        payload_end = payload_start + available
        complete_payload = available == length
        crc_end = payload_end + 4
        complete_chunk = complete_payload and crc_end <= len(data)
        payload = data[payload_start:payload_end]

        if not seen_ihdr:
            if kind != b"IHDR" or length != 13 or not complete_chunk:
                stop_reason = "ihdr_missing_or_truncated"
                break
            expected_crc = int.from_bytes(data[payload_end:crc_end], "big")
            if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
                stop_reason = "ihdr_crc_invalid"
                break
            width, height = struct.unpack(">II", payload[:8])
            bit_depth, color_type, compression, filtering, interlace = payload[8:13]
            channels = {2: 3, 6: 4}.get(color_type)
            if (not width or not height or bit_depth != 8 or channels is None
                    or compression != 0 or filtering != 0):
                stop_reason = "unsupported_ihdr"
                break
            if interlace != 0:
                stop_reason = "interlaced_png_unsupported"
                break
            expected_decoded = height * (width * channels + 1)
            if expected_decoded > max_decoded_bytes:
                stop_reason = "decoded_limit"
                break
            if expected_decoded > decoded_limit:
                stop_reason = "retained_memory_limit"
                break
            seen_ihdr = True
            cursor = crc_end
            continue

        if kind == b"IDAT":
            if idat_ended:
                stop_reason = "nonconsecutive_idat"
                break
            seen_idat = True
            ranges.append((payload_start, payload_end))
            try:
                remaining = decoded_limit - len(decoded)
                decoded.extend(decompressor.decompress(payload, max(1, remaining + 1)))
            except zlib.error:
                stop_reason = "zlib_error"
                break
            if len(decoded) > max_decoded_bytes or decompressor.unconsumed_tail:
                stop_reason = "decoded_limit"
                break
            if complete_chunk:
                expected_crc = int.from_bytes(data[payload_end:crc_end], "big")
                if zlib.crc32(kind + payload) & 0xFFFFFFFF == expected_crc:
                    crc_valid += 1
                else:
                    crc_invalid = True
                cursor = crc_end
                continue
            crc_unknown = True
            stop_reason = "truncated_idat"
            break

        if seen_idat:
            idat_ended = True
        if not complete_chunk:
            stop_reason = "truncated_chunk"
            break
        expected_crc = int.from_bytes(data[payload_end:crc_end], "big")
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
            stop_reason = "chunk_crc_invalid"
            break
        cursor = crc_end
        if kind == b"IEND":
            if length != 0 or not decompressor.eof:
                stop_reason = "iend_or_zlib_incomplete"
                break
            iend_valid = True
            stop_reason = "complete"
            break
        if kind[:1].isupper() and kind not in (b"PLTE",):
            stop_reason = "unsupported_critical_chunk"
            break

    if not seen_idat and stop_reason in ("incomplete_png", "iend_or_zlib_incomplete"):
        stop_reason = "idat_missing"

    if width is None or height is None or channels is None:
        return PartialPngRows("rejected", stop_reason, width, height, channels, (),
                              tuple(ranges), crc_valid, crc_unknown, crc_invalid,
                              False, iend_valid, len(data), len(decoded), 0)

    row_bytes = width * channels
    stride = row_bytes + 1
    complete_row_count = min(height, len(decoded) // stride)
    partial_row_bytes = len(decoded) - complete_row_count * stride
    rows = []
    previous = None
    for index in range(complete_row_count):
        if clock() - started >= time_limit_seconds:
            stop_reason = "time_limit"
            break
        start = index * stride
        filter_type = decoded[start]
        filtered = decoded[start + 1:start + stride]
        try:
            row = _unfilter_row(filter_type, filtered, previous, channels)
        except ValueError:
            stop_reason = "filter_invalid"
            rows = []
            break
        rows.append(row)
        previous = row

    complete_file = (
        stop_reason == "complete" and len(rows) == height and decompressor.eof
        and not crc_unknown and not crc_invalid and iend_valid
    )
    status = "complete" if complete_file else ("partial" if rows else "rejected")
    if complete_file:
        stop_reason = "complete"
    elif crc_invalid and stop_reason == "complete":
        stop_reason = "crc_invalid"
    elif rows and stop_reason == "incomplete_png":
        stop_reason = "incomplete_stream"
    return PartialPngRows(
        status, stop_reason, width, height, channels, tuple(rows), tuple(ranges),
        crc_valid, crc_unknown, crc_invalid, decompressor.eof, iend_valid,
        len(data), len(decoded), partial_row_bytes,
    )


def _chunk(kind, payload):
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def _filtered_rows(pixels, width, height, channels, filters):
    row_bytes = width * channels
    rows = [pixels[i * row_bytes:(i + 1) * row_bytes] for i in range(height)]
    result = bytearray()
    previous = None
    for row_index, row in enumerate(rows):
        filter_type = filters[row_index % len(filters)]
        encoded = bytearray(row_bytes)
        for index, value in enumerate(row):
            left = row[index - channels] if index >= channels else 0
            up = previous[index] if previous is not None else 0
            upper_left = previous[index - channels] if previous is not None and index >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            else:
                predictor = _paeth(left, up, upper_left)
            encoded[index] = (value - predictor) & 0xFF
        result.append(filter_type)
        result.extend(encoded)
        previous = row
    return bytes(result), tuple(rows)


def _png_fixture(width=32, height=12, channels=3, seed=610, level=0,
                 interlace=0):
    rng = random.Random(seed)
    pixels = bytes(rng.randrange(256) for _ in range(width * height * channels))
    filtered, rows = _filtered_rows(pixels, width, height, channels, (0, 1, 2, 3, 4))
    compressed = zlib.compress(filtered, level)
    color_type = 2 if channels == 3 else 6
    ihdr_payload = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, interlace)
    ihdr = _chunk(b"IHDR", ihdr_payload)
    split = len(compressed) // 3
    complete = PNG_SIGNATURE + ihdr + _chunk(b"IDAT", compressed[:split])
    complete += _chunk(b"IDAT", compressed[split:]) + _chunk(b"IEND", b"")
    row_stride = width * channels + 1
    cut = None
    for prefix_length in range(split + 1, len(compressed)):
        partial_output = zlib.decompressobj().decompress(compressed[:prefix_length])
        complete_rows = len(partial_output) // row_stride
        if 2 <= complete_rows < height and len(partial_output) % row_stride:
            cut = prefix_length
            break
    if cut is None:
        raise AssertionError("fixture could not produce a partial scanline prefix")
    damaged = PNG_SIGNATURE + ihdr
    second = compressed[split:]
    damaged += struct.pack(">I4s", len(compressed[:split]), b"IDAT")
    damaged += compressed[:split]
    damaged += struct.pack(">I", zlib.crc32(b"IDAT" + compressed[:split]) & 0xFFFFFFFF)
    damaged += struct.pack(">I4s", len(second), b"IDAT") + second[:cut - split]
    return complete, damaged, rows, cut, split


class _MemoryDisk:
    def __init__(self, data):
        self.data = bytes(data)
        self.size = len(self.data)
        self.bytes_read = 0

    def read_at(self, offset, size):
        self.bytes_read += size
        return self.data[offset:offset + size]


class PNGPartialRecoveryExperimentTests(unittest.TestCase):
    def test_complete_control_matches_existing_carver_and_recovers_all_rows(self):
        complete, _damaged, original_rows, _cut, _split = _png_fixture()
        with Image.open(BytesIO(complete)) as image:
            image.load()
            self.assertEqual((32, 12), image.size)
        result = recover_complete_png_rows(complete)
        carver = RawContentCarver(_MemoryDisk(complete)).scan(((0, len(complete)),))

        self.assertEqual("complete", result.status)
        self.assertEqual(original_rows, result.rows)
        self.assertTrue(result.zlib_complete)
        self.assertTrue(result.iend_valid)
        self.assertEqual([complete], [item.data for item in carver.files if item.extension == ".png"])

    def test_truncated_idat_recovers_only_complete_original_rows(self):
        complete, damaged, original_rows, cut, split = _png_fixture()
        result = recover_complete_png_rows(damaged)
        carver = RawContentCarver(_MemoryDisk(damaged)).scan(((0, len(damaged)),))

        self.assertEqual("partial", result.status)
        self.assertEqual("truncated_idat", result.stop_reason)
        self.assertFalse(result.zlib_complete)
        self.assertFalse(result.iend_valid)
        self.assertEqual(1, result.valid_idat_crc_count)
        self.assertTrue(result.idat_crc_unknown)
        self.assertGreater(result.partial_row_bytes, 0)
        self.assertLess(len(result.rows), len(original_rows))
        self.assertEqual(original_rows[:len(result.rows)], result.rows)
        self.assertEqual((), tuple(item.data for item in carver.files if item.extension == ".png"))
        self.assertGreater(cut, split)
        self.assertLess(len(damaged), len(complete))

    def test_rgba_and_multiple_compression_levels_preserve_rows_exactly(self):
        for channels, level, width, height in ((4, 6, 19, 11), (3, 1, 47, 8)):
            with self.subTest(channels=channels, level=level):
                _complete, damaged, original_rows, _cut, _split = _png_fixture(
                    width, height, channels, seed=level + channels, level=level,
                )
                result = recover_complete_png_rows(damaged)
                self.assertEqual("partial", result.status)
                self.assertEqual(original_rows[:len(result.rows)], result.rows)

    def test_corrupt_crc_is_preserved_as_unverified_evidence(self):
        complete, _damaged, original_rows, _cut, _split = _png_fixture()
        corrupted = bytearray(complete)
        first_idat = corrupted.index(b"IDAT")
        chunk_length = int.from_bytes(corrupted[first_idat - 4:first_idat], "big")
        crc_offset = first_idat + 4 + chunk_length
        corrupted[crc_offset] ^= 0xFF

        result = recover_complete_png_rows(bytes(corrupted))

        self.assertEqual("partial", result.status)
        self.assertTrue(result.idat_crc_invalid)
        self.assertEqual(original_rows, result.rows)
        self.assertEqual("crc_invalid", result.stop_reason)

    def test_overwritten_zlib_tail_preserves_only_rows_decoded_before_stream_error(self):
        complete, _damaged, original_rows, _cut, _split = _png_fixture()
        first_idat = complete.index(b"IDAT")
        second_idat = complete.index(b"IDAT", first_idat + 4)
        second_length = int.from_bytes(complete[second_idat - 4:second_idat], "big")
        payload_last_byte = second_idat + 4 + second_length - 1
        overwritten = bytearray(complete)
        overwritten[payload_last_byte] ^= 0xA5

        result = recover_complete_png_rows(bytes(overwritten))

        self.assertEqual("partial", result.status)
        self.assertEqual("zlib_error", result.stop_reason)
        self.assertFalse(result.zlib_complete)
        self.assertEqual(original_rows[:len(result.rows)], result.rows)
        self.assertLess(len(result.rows), len(original_rows))

    def test_interlaced_png_is_rejected_instead_of_inventing_scanline_positions(self):
        width, height, channels = 32, 12, 3
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 1)
        interlaced = PNG_SIGNATURE + _chunk(b"IHDR", ihdr)
        interlaced += _chunk(b"IDAT", zlib.compress(bytes((width * channels + 1) * height)))
        interlaced += _chunk(b"IEND", b"")
        result = recover_complete_png_rows(interlaced)

        self.assertEqual("rejected", result.status)
        self.assertEqual("interlaced_png_unsupported", result.stop_reason)
        self.assertEqual((), result.rows)

    def test_missing_idat_bad_signature_and_decompression_limit_are_explicit(self):
        complete, _damaged, _rows, _cut, _split = _png_fixture()
        ihdr_start = len(PNG_SIGNATURE)
        ihdr_length = int.from_bytes(complete[ihdr_start:ihdr_start + 4], "big")
        ihdr_end = ihdr_start + ihdr_length + 12
        missing_idat = complete[:ihdr_end] + _chunk(b"IEND", b"")

        self.assertEqual("idat_missing", recover_complete_png_rows(missing_idat).stop_reason)
        self.assertEqual("signature_invalid", recover_complete_png_rows(b"not png").stop_reason)
        self.assertEqual("decoded_limit",
                         recover_complete_png_rows(complete, max_decoded_bytes=64).stop_reason)

    def test_retained_memory_and_injected_monotonic_time_limits_stop_explicitly(self):
        complete, _damaged, _rows, _cut, _split = _png_fixture()
        self.assertEqual("retained_memory_limit", recover_complete_png_rows(
            complete, max_retained_bytes=64 * 1024,
        ).stop_reason)
        times = iter((0.0, 2.0))
        timed = recover_complete_png_rows(complete, time_limit_seconds=1.0,
                                          clock=lambda: next(times))
        self.assertEqual("time_limit", timed.stop_reason)


if __name__ == "__main__":
    unittest.main()
