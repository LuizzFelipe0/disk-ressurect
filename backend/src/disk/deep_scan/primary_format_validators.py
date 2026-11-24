"""Pure structural checks for the primary contiguous carving formats.

These functions do not perform disk I/O or manage scan budgets. Keeping the
format rules here lets the carver focus on bounded reads and progress while
the validators remain deterministic and easy to exercise with byte fixtures.
"""

from __future__ import annotations

import re


JPEG_FRAME_MARKERS = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}


def jpeg_header_status(data: bytes) -> bool | None:
    """Return ``None`` for incomplete headers, ``False`` if invalid, else true."""
    if len(data) < 2:
        return None
    if data[:2] != b"\xff\xd8":
        return False

    position = 2
    has_frame = False
    while position < len(data):
        if data[position] != 0xFF:
            return False
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            return None

        marker = data[position]
        position += 1
        if marker in (0xD8, 0x00, 0xD9):
            return False
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue
        if position + 2 > len(data):
            return None

        segment_length = int.from_bytes(data[position:position + 2], "big")
        if segment_length < 2:
            return False
        segment_end = position + segment_length
        if segment_end > len(data):
            return None

        if marker in JPEG_FRAME_MARKERS:
            if segment_length < 8:
                return False
            height = int.from_bytes(data[position + 3:position + 5], "big")
            width = int.from_bytes(data[position + 5:position + 7], "big")
            components = data[position + 7]
            if (height == 0 or width == 0 or components == 0
                    or segment_length != 8 + 3 * components):
                return False
            has_frame = True

        if marker == 0xDA:
            components = data[position + 2] if segment_length >= 3 else 0
            if (components == 0 or segment_length != 6 + 2 * components
                    or not has_frame):
                return False
            return True
        position = segment_end
    return None


def png_decoded_size(width: int, height: int, bit_depth: int,
                     color_type: int, interlace: int) -> int:
    """Calculate the bounded decompressed scanline size, including Adam7."""
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


def valid_pdf(data: bytes) -> bool:
    """Accept PDFs with a bounded classic xref table and required trailer refs."""
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
    return valid_classic_xref(data[xref_offset:eof], xref_offset)


def valid_classic_xref(data: bytes, xref_offset: int) -> bool:
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
            if (not size_match or not root_match or b"<<" not in dictionary
                    or b">>" not in dictionary):
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


def valid_jpeg(data: bytes) -> bool:
    """Validate JPEG marker lengths, at least one frame/scan, and EOI."""
    if len(data) < 12 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        return False
    position = 2
    has_frame = False
    has_scan = False
    length = len(data)
    while position < length:
        if data[position] != 0xFF:
            return False
        while position < length and data[position] == 0xFF:
            position += 1
        if position >= length:
            return False
        marker = data[position]
        position += 1
        if marker == 0xD9:
            return has_frame and has_scan and position == length
        if marker in (0xD8, 0x00):
            return False
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue
        if position + 2 > length:
            return False
        segment_length = int.from_bytes(data[position:position + 2], "big")
        if segment_length < 2 or position + segment_length > length:
            return False
        segment_end = position + segment_length
        if marker in JPEG_FRAME_MARKERS:
            if segment_length < 8:
                return False
            height = int.from_bytes(data[position + 3:position + 5], "big")
            width = int.from_bytes(data[position + 5:position + 7], "big")
            components = data[position + 7]
            if (height == 0 or width == 0 or components == 0
                    or segment_length != 8 + 3 * components):
                return False
            has_frame = True
        if marker == 0xDA:
            components = data[position + 2] if segment_length >= 3 else 0
            if components == 0 or segment_length != 6 + 2 * components:
                return False
            has_scan = True
            position = segment_end
            while position < length:
                if data[position] != 0xFF:
                    position += 1
                    continue
                marker_start = position
                while position < length and data[position] == 0xFF:
                    position += 1
                if position >= length:
                    return False
                entropy_marker = data[position]
                if entropy_marker == 0x00 or 0xD0 <= entropy_marker <= 0xD7:
                    position += 1
                    continue
                position = marker_start
                break
            continue
        position = segment_end
    return False
