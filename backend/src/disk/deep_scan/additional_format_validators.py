"""Bounded structural screens for additional contiguous carving formats.

This module is deliberately independent from the range scanner so it can be
used by the carver without coupling format parsing to disk I/O. It recognizes
OOXML Office ZIP containers and ISO-BMFF/MP4 files. It does not decompress ZIP
members or decode media payloads; a positive result is structural evidence,
not proof that an application can open the recovered file.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct


ZIP_LOCAL_FILE_HEADER = b"PK\x03\x04"
ZIP_END_OF_CENTRAL_DIRECTORY = b"PK\x05\x06"
ISO_BMFF_FILE_TYPE = b"ftyp"

# The range scanner can use these offset-aware signatures to seed a candidate.
# ZIP local headers are ambiguous until their central directory is inspected.
ADDITIONAL_SIGNATURES = (
    ("ooxml", ZIP_LOCAL_FILE_HEADER, 0),
    ("iso_bmff", ISO_BMFF_FILE_TYPE, 4),
)

MAX_ZIP_ENTRIES = 4096
MAX_ISO_BMFF_BOXES = 65536

_OOXML_REQUIRED_MEMBERS = {
    "word/document.xml": ".docx",
    "xl/workbook.xml": ".xlsx",
}
_OOXML_MACRO_MEMBERS = {
    "word/vbaProject.bin": ".docm",
    "xl/vbaProject.bin": ".xlsm",
}
_OOXML_SHARED_REQUIRED = {"[Content_Types].xml", "_rels/.rels"}


@dataclass(frozen=True)
class AdditionalFormatCandidate:
    """Detected type and exact contiguous size of a structurally screened file."""

    extension: str
    size_bytes: int
    validation_scope: str


def find_additional_signatures(data: bytes, start: int = 0) -> tuple[tuple[str, int], ...]:
    """Return (format hint, candidate start) pairs found in a scan buffer.

    ISO-BMFF's ``ftyp`` box signature is four bytes into its first box, so the
    returned candidate offset points to the box header, not to the signature.
    """
    data = bytes(data)
    cursor = max(0, int(start))
    found: list[tuple[str, int]] = []
    while True:
        offset = data.find(ZIP_LOCAL_FILE_HEADER, cursor)
        if offset < 0:
            break
        found.append(("ooxml", offset))
        cursor = offset + len(ZIP_LOCAL_FILE_HEADER)

    cursor = max(4, int(start) + 4)
    while True:
        marker = data.find(ISO_BMFF_FILE_TYPE, cursor)
        if marker < 0:
            break
        candidate_offset = marker - 4
        if candidate_offset >= start and candidate_offset + 8 <= len(data):
            box_size = int.from_bytes(data[candidate_offset:marker], "big")
            if box_size == 0 or box_size >= 16:
                found.append(("iso_bmff", candidate_offset))
        cursor = marker + len(ISO_BMFF_FILE_TYPE)
    return tuple(sorted(found, key=lambda item: item[1]))


def validate_additional_candidate(data: bytes) -> AdditionalFormatCandidate | None:
    """Validate a complete candidate prefix and return its type and byte size.

    Extra bytes after the recognized archive/container are ignored and are not
    included in ``size_bytes``. Candidates exceeding limits set by the caller's
    input buffer or the ZIP entry/MP4 box ceilings are rejected.
    """
    data = bytes(data)
    office = _validate_ooxml(data)
    if office is not None:
        return office
    return _validate_iso_bmff(data)


def _validate_ooxml(data: bytes) -> AdditionalFormatCandidate | None:
    if not data.startswith(ZIP_LOCAL_FILE_HEADER):
        return None
    # The EOCD can have a 16-bit comment. Search only this bounded tail.
    tail_start = max(0, len(data) - (22 + 65535))
    eocd = data.rfind(ZIP_END_OF_CENTRAL_DIRECTORY, tail_start)
    while eocd >= 0:
        if eocd + 22 <= len(data):
            disk_number, central_disk, disk_entries, entry_count, central_size, central_offset, comment_size = (
                struct.unpack_from("<HHHHIIH", data, eocd + 4)
            )
            archive_end = eocd + 22 + comment_size
            if (archive_end <= len(data) and disk_number == central_disk == 0
                    and disk_entries == entry_count and entry_count <= MAX_ZIP_ENTRIES
                    and entry_count not in (0xFFFF,) and central_size != 0xFFFFFFFF
                    and central_offset != 0xFFFFFFFF
                    and central_offset + central_size == eocd):
                extension = _validate_central_directory(
                    data[:archive_end], central_offset, central_size, entry_count, eocd,
                )
                if extension:
                    return AdditionalFormatCandidate(
                        extension, archive_end,
                        "ZIP central directory, local headers and OOXML member names",
                    )
        eocd = data.rfind(ZIP_END_OF_CENTRAL_DIRECTORY, tail_start, eocd)
    return None


def _validate_central_directory(data, central_offset, central_size, entry_count, eocd_offset):
    cursor = central_offset
    central_end = central_offset + central_size
    names: set[str] = set()
    office_extension = None
    if central_end != eocd_offset or central_end > len(data):
        return None
    for _ in range(entry_count):
        if cursor + 46 > central_end or data[cursor:cursor + 4] != b"PK\x01\x02":
            return None
        flags = int.from_bytes(data[cursor + 8:cursor + 10], "little")
        compression = int.from_bytes(data[cursor + 10:cursor + 12], "little")
        compressed_size = int.from_bytes(data[cursor + 20:cursor + 24], "little")
        name_length = int.from_bytes(data[cursor + 28:cursor + 30], "little")
        extra_length = int.from_bytes(data[cursor + 30:cursor + 32], "little")
        comment_length = int.from_bytes(data[cursor + 32:cursor + 34], "little")
        disk_start = int.from_bytes(data[cursor + 34:cursor + 36], "little")
        local_offset = int.from_bytes(data[cursor + 42:cursor + 46], "little")
        record_end = cursor + 46 + name_length + extra_length + comment_length
        if (record_end > central_end or name_length == 0 or disk_start != 0
                or flags & 0x1 or compressed_size == 0xFFFFFFFF
                or local_offset == 0xFFFFFFFF or compression not in (0, 8)):
            return None
        name_bytes = data[cursor + 46:cursor + 46 + name_length]
        try:
            name = name_bytes.decode("utf-8" if flags & 0x800 else "cp437")
        except UnicodeDecodeError:
            return None
        if name in names:
            return None
        names.add(name)
        if name in _OOXML_REQUIRED_MEMBERS:
            office_extension = _OOXML_REQUIRED_MEMBERS[name]
        elif name in _OOXML_MACRO_MEMBERS:
            office_extension = _OOXML_MACRO_MEMBERS[name]

        if local_offset + 30 > central_offset or data[local_offset:local_offset + 4] != ZIP_LOCAL_FILE_HEADER:
            return None
        local_flags = int.from_bytes(data[local_offset + 6:local_offset + 8], "little")
        local_method = int.from_bytes(data[local_offset + 8:local_offset + 10], "little")
        local_name_length = int.from_bytes(data[local_offset + 26:local_offset + 28], "little")
        local_extra_length = int.from_bytes(data[local_offset + 28:local_offset + 30], "little")
        local_name_start = local_offset + 30
        local_data_start = local_name_start + local_name_length + local_extra_length
        if (local_data_start + compressed_size > central_offset
                or local_data_start > central_offset
                or local_flags != flags or local_method != compression
                or data[local_name_start:local_name_start + local_name_length] != name_bytes):
            return None
        cursor = record_end
    if cursor != central_end or not _OOXML_SHARED_REQUIRED.issubset(names) or not office_extension:
        return None
    return office_extension


def _validate_iso_bmff(data: bytes) -> AdditionalFormatCandidate | None:
    if len(data) < 16 or data[4:8] != ISO_BMFF_FILE_TYPE:
        return None
    cursor = 0
    box_count = 0
    saw_ftyp = saw_mdat = saw_movie_metadata = False
    while cursor < len(data):
        if cursor + 8 > len(data):
            return None
        size32 = int.from_bytes(data[cursor:cursor + 4], "big")
        box_type = data[cursor + 4:cursor + 8]
        header_size = 8
        if size32 == 1:
            if cursor + 16 > len(data):
                return None
            box_size = int.from_bytes(data[cursor + 8:cursor + 16], "big")
            header_size = 16
        elif size32 == 0:
            box_size = len(data) - cursor
        else:
            box_size = size32
        if box_size < header_size or cursor + box_size > len(data):
            return None
        if cursor == 0 and box_type == ISO_BMFF_FILE_TYPE:
            if box_size < 16 or (box_size - 16) % 4 != 0:
                return None
            saw_ftyp = True
        elif box_type == b"mdat":
            saw_mdat = True
        elif box_type in (b"moov", b"moof"):
            saw_movie_metadata = True
        cursor += box_size
        box_count += 1
        if box_count > MAX_ISO_BMFF_BOXES:
            return None
        if size32 == 0:
            break
    if cursor == len(data) and saw_ftyp and saw_mdat and saw_movie_metadata:
        return AdditionalFormatCandidate(
            ".mp4", len(data), "ISO-BMFF top-level box bounds and ftyp/mdat/movie metadata",
        )
    return None
