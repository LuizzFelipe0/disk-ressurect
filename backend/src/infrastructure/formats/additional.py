"""Bounded structural screens for additional contiguous carving formats.

This module is deliberately independent from the range scanner so it can be
used by the carver without coupling format parsing to disk I/O. It recognizes
OOXML Office ZIP containers and bounded ISO-BMFF containers. It does not decompress ZIP
members or decode media payloads; a positive result is structural evidence,
not proof that an application can open the recovered file.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct


ZIP_LOCAL_FILE_HEADER = b"PK\x03\x04"
ZIP_END_OF_CENTRAL_DIRECTORY = b"PK\x05\x06"
ISO_BMFF_FILE_TYPE = b"ftyp"
RTF_SIGNATURE = b"{\\rtf"
COMPOUND_FILE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")

# The range scanner can use these offset-aware signatures to seed a candidate.
# ZIP local headers are ambiguous until their central directory is inspected.
ADDITIONAL_SIGNATURES = (
    ("ooxml", ZIP_LOCAL_FILE_HEADER, 0),
    ("iso_bmff", ISO_BMFF_FILE_TYPE, 4),
    ("rtf", RTF_SIGNATURE, 0),
    ("ole_compound", COMPOUND_FILE_SIGNATURE, 0),
)

MAX_ZIP_ENTRIES = 4096
MAX_ISO_BMFF_BOXES = 65536
MAX_RTF_NESTING = 1024
MAX_COMPOUND_FILE_BYTES = 32 * 1024 * 1024

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
    for family, signature, signature_offset in ADDITIONAL_SIGNATURES:
        search_from = max(cursor + signature_offset, signature_offset)
        while True:
            marker = data.find(signature, search_from)
            if marker < 0:
                break
            candidate_offset = marker - signature_offset
            if candidate_offset >= start:
                if family != "iso_bmff" or candidate_offset + 8 <= len(data):
                    if family != "iso_bmff" or int.from_bytes(
                        data[candidate_offset:marker], "big",
                    ) == 0 or int.from_bytes(data[candidate_offset:marker], "big") >= 16:
                        found.append((family, candidate_offset))
            search_from = marker + 1
    return tuple(sorted(found, key=lambda item: item[1]))


def validate_additional_candidate(data: bytes) -> AdditionalFormatCandidate | None:
    """Validate a complete candidate prefix and return its type and byte size.

    Extra bytes after the recognized archive/container are ignored and are not
    included in ``size_bytes``. Candidates exceeding limits set by the caller's
    input buffer or the ZIP entry/MP4 box ceilings are rejected.
    """
    data = bytes(data)
    rtf = _validate_rtf(data)
    if rtf is not None:
        return rtf
    compound = _validate_compound_office(data)
    if compound is not None:
        return compound
    office = _validate_ooxml(data)
    if office is not None:
        return office
    return _validate_iso_bmff(data)


def _validate_rtf(data: bytes) -> AdditionalFormatCandidate | None:
    """Return a complete, balanced RTF group without interpreting document text."""
    if (len(data) < 7 or not data.startswith(RTF_SIGNATURE)
            or not 48 <= data[5] <= 57 or len(data) > MAX_COMPOUND_FILE_BYTES):
        return None

    depth = 1
    index = 1
    recognized_header_control = False
    while index < len(data):
        value = data[index]
        if value == ord("\\"):
            index += 1
            if index >= len(data):
                return None
            if data[index] == ord("'"):
                if index + 2 >= len(data) or any(
                    digit not in b"0123456789abcdefABCDEF" for digit in data[index + 1:index + 3]
                ):
                    return None
                index += 3
                continue
            if 65 <= data[index] <= 90 or 97 <= data[index] <= 122:
                word_start = index
                while index < len(data) and (65 <= data[index] <= 90 or 97 <= data[index] <= 122):
                    index += 1
                    if index - word_start > 32:
                        return None
                word = data[word_start:index].lower()
                if word in (b"ansi", b"mac", b"pc", b"pca", b"deff", b"pard", b"fonttbl"):
                    recognized_header_control = True
                sign = 1
                if index < len(data) and data[index] == ord("-"):
                    sign = -1
                    index += 1
                number_start = index
                number = 0
                while index < len(data) and 48 <= data[index] <= 57:
                    number = number * 10 + data[index] - 48
                    if number > MAX_COMPOUND_FILE_BYTES:
                        return None
                    index += 1
                has_parameter = index > number_start
                if word == b"bin":
                    if not has_parameter or sign < 0 or index + number > len(data):
                        return None
                    index += number
                    continue
                if index < len(data) and data[index] == ord(" "):
                    index += 1
                continue
            index += 1
            continue
        if value == ord("{"):
            depth += 1
            if depth > MAX_RTF_NESTING:
                return None
        elif value == ord("}"):
            depth -= 1
            if depth == 0:
                if not recognized_header_control:
                    return None
                return AdditionalFormatCandidate(
                    ".rtf", index + 1, "RTF header, escaped controls, binary spans and balanced groups",
                )
            if depth < 0:
                return None
        index += 1
    return None


def _validate_compound_office(data: bytes) -> AdditionalFormatCandidate | None:
    """Validate a version-3 CFB file and distinguish legacy Word from Excel streams.

    The parser follows bounded FAT, directory and mini-FAT chains. It does not
    interpret OLE streams; DOC/XLS classification requires their well-known
    stream names to be reachable from the root directory entry.
    """
    if len(data) < 512 or not data.startswith(COMPOUND_FILE_SIGNATURE):
        return None
    if len(data) > MAX_COMPOUND_FILE_BYTES:
        return None
    header = data[:512]
    minor_version = int.from_bytes(header[24:26], "little")
    major_version = int.from_bytes(header[26:28], "little")
    sector_shift = int.from_bytes(header[30:32], "little")
    mini_sector_shift = int.from_bytes(header[32:34], "little")
    if (minor_version not in (0x003E, 0x003B) or major_version != 3
            or header[28:30] != b"\xfe\xff" or sector_shift != 9
            or mini_sector_shift != 6 or any(header[34:40])):
        return None

    sector_size = 1 << sector_shift
    available_sectors = (len(data) - 512) // sector_size
    if available_sectors < 3:
        return None
    num_fat_sectors = int.from_bytes(header[44:48], "little")
    first_directory_sector = int.from_bytes(header[48:52], "little")
    mini_stream_cutoff = int.from_bytes(header[56:60], "little")
    first_mini_fat_sector = int.from_bytes(header[60:64], "little")
    num_mini_fat_sectors = int.from_bytes(header[64:68], "little")
    first_difat_sector = int.from_bytes(header[68:72], "little")
    num_difat_sectors = int.from_bytes(header[72:76], "little")
    if (int.from_bytes(header[40:44], "little") != 0
            or mini_stream_cutoff != 4096 or not 1 <= num_fat_sectors <= 512
            or first_directory_sector >= available_sectors
            or num_mini_fat_sectors > 512):
        return None

    free_sector = 0xFFFFFFFF
    end_of_chain = 0xFFFFFFFE
    fat_sector_marker = 0xFFFFFFFD
    difat_sector_marker = 0xFFFFFFFC
    fat_sector_ids = [
        int.from_bytes(header[offset:offset + 4], "little")
        for offset in range(76, 512, 4)
    ]
    fat_sector_ids = [sector for sector in fat_sector_ids if sector != free_sector]
    difat_sector_ids = []
    if num_fat_sectors > len(fat_sector_ids):
        if (num_difat_sectors == 0 or first_difat_sector >= available_sectors
                or num_difat_sectors > 256):
            return None
        current = first_difat_sector
        visited_difat = set()
        for _ in range(num_difat_sectors):
            if current >= available_sectors or current in visited_difat:
                return None
            visited_difat.add(current)
            difat_sector_ids.append(current)
            sector_data = _compound_sector(data, current, sector_size)
            entries = [int.from_bytes(sector_data[i:i + 4], "little")
                       for i in range(0, sector_size, 4)]
            fat_sector_ids.extend(value for value in entries[:-1] if value != free_sector)
            current = entries[-1]
        if current != end_of_chain:
            return None
    elif num_difat_sectors != 0 or first_difat_sector != end_of_chain:
        return None
    if (len(fat_sector_ids) != num_fat_sectors
            or len(set(fat_sector_ids)) != len(fat_sector_ids)
            or any(sector >= available_sectors for sector in fat_sector_ids)
            or set(fat_sector_ids) & set(difat_sector_ids)):
        return None

    fat_entries = []
    for sector_id in fat_sector_ids:
        sector_data = _compound_sector(data, sector_id, sector_size)
        fat_entries.extend(
            int.from_bytes(sector_data[i:i + 4], "little")
            for i in range(0, sector_size, 4)
        )
    if len(fat_entries) < available_sectors:
        return None
    if any(fat_entries[sector] != fat_sector_marker for sector in fat_sector_ids):
        return None
    if any(fat_entries[sector] != difat_sector_marker for sector in difat_sector_ids):
        return None

    def follow_chain(first_sector, expected_count=None, table=fat_entries, sector_limit=available_sectors):
        if first_sector == end_of_chain:
            return () if expected_count in (None, 0) else None
        chain = []
        visited = set()
        current = first_sector
        while current != end_of_chain and len(chain) <= sector_limit:
            if current >= sector_limit or current in visited or current >= len(table):
                return None
            visited.add(current)
            chain.append(current)
            current = table[current]
            if current in (free_sector, fat_sector_marker, difat_sector_marker):
                return None
        if current != end_of_chain or (expected_count is not None and len(chain) != expected_count):
            return None
        return tuple(chain)

    directory_chain = follow_chain(first_directory_sector)
    if not directory_chain:
        return None
    directory_bytes = b"".join(
        _compound_sector(data, sector, sector_size) for sector in directory_chain
    )
    directory_entries = []
    for offset in range(0, len(directory_bytes), 128):
        entry = directory_bytes[offset:offset + 128]
        if len(entry) != 128:
            return None
        object_type = entry[66]
        if object_type == 0:
            directory_entries.append(None)
            continue
        name_length = int.from_bytes(entry[64:66], "little")
        if name_length < 2 or name_length > 64 or name_length % 2:
            return None
        try:
            name = entry[:name_length - 2].decode("utf-16le")
        except UnicodeDecodeError:
            return None
        directory_entries.append({
            "name": name,
            "type": object_type,
            "left": int.from_bytes(entry[68:72], "little"),
            "right": int.from_bytes(entry[72:76], "little"),
            "child": int.from_bytes(entry[76:80], "little"),
            "start": int.from_bytes(entry[116:120], "little"),
            "size": int.from_bytes(entry[120:128], "little"),
        })
    if not directory_entries or not directory_entries[0] or directory_entries[0]["type"] != 5:
        return None

    no_stream = free_sector
    reachable = set()
    stream_indexes = set()

    def visit_tree(index, depth=0):
        if index == no_stream:
            return True
        if index >= len(directory_entries) or depth > 128 or index in reachable:
            return False
        entry = directory_entries[index]
        if entry is None:
            return False
        reachable.add(index)
        if not visit_tree(entry["left"], depth + 1):
            return False
        if entry["type"] == 2:
            stream_indexes.add(index)
        elif entry["type"] in (1, 5):
            if entry["child"] != no_stream and not visit_tree(entry["child"], depth + 1):
                return False
        else:
            return False
        return visit_tree(entry["right"], depth + 1)

    root_child = directory_entries[0]["child"]
    if root_child == no_stream or not visit_tree(root_child):
        return None
    streams = {directory_entries[index]["name"]: directory_entries[index]
               for index in stream_indexes}
    is_word = "WordDocument" in streams and ("0Table" in streams or "1Table" in streams)
    is_excel = "Workbook" in streams or "Book" in streams
    if is_word == is_excel:
        return None

    def validate_stream(entry):
        size = entry["size"]
        if size == 0:
            return entry["start"] == end_of_chain
        if size >= mini_stream_cutoff:
            required_sectors = (size + sector_size - 1) // sector_size
            return follow_chain(entry["start"], required_sectors) is not None
        return validate_mini_stream(entry, size)

    root = directory_entries[0]
    root_size = root["size"]
    if root_size:
        root_chain = follow_chain(root["start"], (root_size + sector_size - 1) // sector_size)
        if root_chain is None:
            return None
    else:
        root_chain = ()

    mini_fat_chain = follow_chain(
        first_mini_fat_sector, num_mini_fat_sectors if num_mini_fat_sectors else 0,
    )
    if mini_fat_chain is None:
        return None
    mini_fat_entries = []
    for sector in mini_fat_chain:
        sector_data = _compound_sector(data, sector, sector_size)
        mini_fat_entries.extend(
            int.from_bytes(sector_data[i:i + 4], "little")
            for i in range(0, sector_size, 4)
        )

    def validate_mini_stream(entry, size):
        if not root_chain or not mini_fat_entries:
            return False
        needed = (size + 63) // 64
        current = entry["start"]
        visited = set()
        for _ in range(needed):
            if (current >= len(mini_fat_entries) or current in visited
                    or current * 64 >= root_size):
                return False
            visited.add(current)
            current = mini_fat_entries[current]
        return current == end_of_chain

    required_stream_names = ("WordDocument", "0Table" if "0Table" in streams else "1Table") if is_word else (
        "Workbook" if "Workbook" in streams else "Book",
    )
    if not all(validate_stream(streams[name]) for name in required_stream_names):
        return None

    allocated_sectors = [
        index for index, next_sector in enumerate(fat_entries)
        if next_sector != free_sector
    ]
    if not allocated_sectors:
        return None
    candidate_size = (max(allocated_sectors) + 2) * sector_size
    if candidate_size > len(data) or candidate_size > MAX_COMPOUND_FILE_BYTES:
        return None
    extension = ".doc" if is_word else ".xls"
    return AdditionalFormatCandidate(
        extension, candidate_size,
        "CFB v3 header, FAT/DIFAT bounds, directory tree and Word/Excel stream chains",
    )


def _compound_sector(data: bytes, sector_id: int, sector_size: int) -> bytes:
    offset = 512 + sector_id * sector_size
    end = offset + sector_size
    if sector_id < 0 or end > len(data):
        return b""
    return data[offset:end]


def is_plausible_office_local_header(data: bytes) -> bool:
    """Reject obvious ZIP false positives before reading a full candidate.

    This checks only the bounded local header. The central directory remains
    the authority for accepting an OOXML file.
    """
    data = bytes(data)
    if len(data) < 30 or not data.startswith(ZIP_LOCAL_FILE_HEADER):
        return False
    version_needed = int.from_bytes(data[4:6], "little")
    flags = int.from_bytes(data[6:8], "little")
    compression = int.from_bytes(data[8:10], "little")
    compressed_size = int.from_bytes(data[18:22], "little")
    uncompressed_size = int.from_bytes(data[22:26], "little")
    name_length = int.from_bytes(data[26:28], "little")
    extra_length = int.from_bytes(data[28:30], "little")
    name_end = 30 + name_length
    header_end = name_end + extra_length
    if (version_needed < 10 or version_needed > 63 or flags & (0x1 | 0x40)
            or compression not in (0, 8) or compressed_size == 0xFFFFFFFF
            or uncompressed_size == 0xFFFFFFFF or not 1 <= name_length <= 1024
            or extra_length > 4096 or header_end > len(data)):
        return False
    try:
        name = data[30:name_end].decode("utf-8" if flags & 0x800 else "cp437")
    except UnicodeDecodeError:
        return False
    normalized = name.replace("\\", "/")
    if (not normalized or normalized.startswith("/") or "\x00" in normalized
            or any(part == ".." for part in normalized.split("/"))):
        return False
    return normalized in _OOXML_SHARED_REQUIRED or normalized.startswith((
        "_rels/", "docProps/", "word/", "xl/", "ppt/", "customXml/", "customUI/",
    ))


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
    movie_extension = ".mp4"
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
            ftyp_payload = data[cursor + header_size:cursor + box_size]
            if len(ftyp_payload) < 8 or (len(ftyp_payload) - 8) % 4 != 0:
                return None
            brands = (ftyp_payload[:4],) + tuple(
                ftyp_payload[position:position + 4]
                for position in range(8, len(ftyp_payload), 4)
            )
            if b"qt  " in brands:
                movie_extension = ".mov"
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
            movie_extension, len(data),
            "ISO-BMFF top-level box bounds and ftyp/mdat/movie metadata; "
            "QuickTime brand required for MOV classification",
        )
    return None
