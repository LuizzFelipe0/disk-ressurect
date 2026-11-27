"""Bounded decoding of complete rows from non-interlaced PNG IDAT streams."""

from __future__ import annotations

from dataclasses import dataclass
import struct
import time
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_DECODED_BYTES = 8 * 1024 * 1024
MAX_RETAINED_BYTES = 16 * 1024 * 1024
TIME_LIMIT_SECONDS = 2.0
RETAINED_OVERHEAD_RESERVE = 64 * 1024
MAX_CHUNKS = 1024


@dataclass(frozen=True)
class PngPartialDecode:
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


def decode_png_partial_rows(data, *, source_offset=0, max_input_bytes=MAX_INPUT_BYTES,
                              max_decoded_bytes=MAX_DECODED_BYTES,
                              max_retained_bytes=MAX_RETAINED_BYTES,
                              time_limit_seconds=TIME_LIMIT_SECONDS,
                              clock=time.monotonic):
    """Decode only complete non-interlaced 8-bit RGB/RGBA rows from IDAT bytes."""
    if len(data) > max_input_bytes:
        return PngPartialDecode("rejected", "input_limit", None, None, None, (), (),
                              0, False, False, False, False, 0, 0, 0)
    started = clock()
    data = bytes(data)
    if not data.startswith(PNG_SIGNATURE):
        return PngPartialDecode("rejected", "signature_invalid", None, None, None, (), (),
                              0, False, False, False, False, len(data), 0, 0)

    remaining_retained = max_retained_bytes - len(data) - RETAINED_OVERHEAD_RESERVE
    if remaining_retained < 0:
        return PngPartialDecode("rejected", "retained_memory_limit", None, None, None, (), (),
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
            ranges.append((source_offset + payload_start, source_offset + payload_end))
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
        return PngPartialDecode("rejected", stop_reason, width, height, channels, (),
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
    return PngPartialDecode(
        status, stop_reason, width, height, channels, tuple(rows), tuple(ranges),
        crc_valid, crc_unknown, crc_invalid, decompressor.eof, iend_valid,
        len(data), len(decoded), partial_row_bytes,
    )
