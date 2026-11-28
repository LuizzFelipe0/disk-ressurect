import struct
from dataclasses import dataclass, replace

from infrastructure.filesystems.ntfs.attributes.attributes import AttributeParser

NTFS_DATA_FLAG_COMPRESSED = 0x0001
NTFS_DATA_FLAG_ENCRYPTED = 0x4000
NTFS_DATA_FLAG_SPARSE = 0x8000
NTFS_DATA_KNOWN_FLAGS = (
    NTFS_DATA_FLAG_COMPRESSED | NTFS_DATA_FLAG_ENCRYPTED | NTFS_DATA_FLAG_SPARSE
)


def unsupported_data_attribute_reason(flags):
    flags = int(flags)
    if flags & NTFS_DATA_FLAG_COMPRESSED:
        return "compressed_data_is_unsupported"
    if flags & NTFS_DATA_FLAG_ENCRYPTED:
        return "encrypted_data_is_unsupported"
    unknown_flags = flags & ~NTFS_DATA_KNOWN_FLAGS
    if unknown_flags:
        return f"unknown_data_attribute_flags:0x{unknown_flags:04x}"
    return None


@dataclass(frozen=True)
class NTFSDataStream:
    """One named ``$DATA`` stream parsed from this MFT record only."""

    name: str
    file_size: int
    allocated_size: int
    resident_data: bytes | None
    data_runs: tuple[tuple[int | None, int], ...]
    is_resident: bool
    is_complete: bool
    incomplete_reasons: tuple[str, ...] = ()
    flags: int = 0
    unsupported_reason: str | None = None


class MFTRecord:
    """Parses a single NTFS MFT Record."""
    def __init__(self, data, index, disk=None, mft_offset=None, record_size=None):
        self.raw_data = bytearray(data)
        self.record_size = int(record_size or len(self.raw_data))
        self.index = index
        self.disk = disk
        self.mft_offset = mft_offset
        self.sequence_number = 0
        self.link_count = 0
        self.record_number = None
        self.base_file_reference = 0
        self.base_file_reference_index = 0
        self.base_file_reference_sequence = 0
        self.is_extension_record = False
        self.is_valid = False
        self.metadata_warnings = []
        self.is_metadata_consistent = False
        self.is_allocated = False # Tells if file was deleted (Recycle Bin/Format)
        self.is_dir = False
        self.name = ""
        self.parent_index = None
        self.parent_reference = None
        self.parent_sequence_number = None
        self.data_runs = []
        self.file_size = 0
        self.allocated_size = 0
        self.resident_data = None
        self.data_is_complete = True
        self.data_attribute_flags = 0
        self.data_unsupported_reason = None
        self.data_extent_resolution = "not_checked"
        self.data_extent_resolution_reason = None
        self.data_extent_count = 0
        # Keys are case-folded stream names. These descriptors never merge
        # extension-record attributes; ambiguous/incomplete streams remain
        # explicitly unusable until an ATTRIBUTE_LIST resolver exists.
        self.named_data_streams: dict[str, NTFSDataStream] = {}
        self.has_attribute_list = False
        self._filename_priority = -1

        if (
            self.record_size < 512
            or self.record_size % 512
            or len(self.raw_data) != self.record_size
            or self.raw_data[:4] != b"FILE"
        ):
            return
        try:
            usa_off, usa_count = struct.unpack_from("<HH", self.raw_data, 4)
            attr_off = struct.unpack_from("<H", self.raw_data, 20)[0]
            if usa_off + usa_count * 2 > attr_off:
                return
            if not self._apply_usa():
                return
            self._parse()
            self.is_valid = True
        except (IndexError, struct.error, ValueError, OverflowError):
            self.is_valid = False

    def _apply_usa(self):
        usa_off, usa_count = struct.unpack_from("<HH", self.raw_data, 4)
        if len(self.raw_data) % 512:
            return False
        sectors = len(self.raw_data) // 512
        if usa_count != sectors + 1 or usa_off < 8 or usa_off + usa_count * 2 > len(self.raw_data):
            return False
        usa_seq = bytes(self.raw_data[usa_off:usa_off + 2])
        for i in range(1, usa_count):
            sector_end = i * 512 - 2
            if self.raw_data[sector_end:sector_end + 2] != usa_seq:
                return False
        for i in range(1, usa_count):
            sector_end = i * 512 - 2
            replacement = usa_off + i * 2
            self.raw_data[sector_end:sector_end + 2] = self.raw_data[replacement:replacement + 2]
        return True

    def _parse(self):
        attr_off = struct.unpack_from("<H", self.raw_data, 20)[0]
        flags = struct.unpack_from("<H", self.raw_data, 22)[0]
        self.sequence_number = struct.unpack_from("<H", self.raw_data, 16)[0]
        self.link_count = struct.unpack_from("<H", self.raw_data, 18)[0]
        bytes_in_use = struct.unpack_from("<I", self.raw_data, 24)[0]
        self.base_file_reference = struct.unpack_from("<Q", self.raw_data, 32)[0]
        self.base_file_reference_index = self.base_file_reference & 0xFFFFFFFFFFFF
        self.base_file_reference_sequence = (self.base_file_reference >> 48) & 0xFFFF
        # NTFS 3.x stores the MFT record number at offset 44. A zero value is
        # accepted because older record layouts and synthetic fixtures omit it.
        if len(self.raw_data) >= 48:
            self.record_number = struct.unpack_from("<I", self.raw_data, 44)[0]
        if (attr_off < 48 or attr_off % 8 or bytes_in_use > len(self.raw_data)
                or bytes_in_use % 8 or attr_off >= bytes_in_use):
            raise ValueError("Invalid MFT attribute bounds")

        usa_off, usa_count = struct.unpack_from("<HH", self.raw_data, 4)
        if usa_off < 8 or usa_off % 2 or usa_off + usa_count * 2 > attr_off:
            raise ValueError("MFT update sequence array overlaps its attributes")
        
        # 0x01 = In Use. If 0, file is deleted. 0x02 = Directory.
        self.is_allocated = bool(flags & 0x01)
        self.is_dir = bool(flags & 0x02)
        if self.base_file_reference:
            self.is_extension_record = True
            # Extension records may carry only part of a file's attributes.
            self.data_is_complete = False
        if (self.record_number not in (None, 0) and self.index >= 0
                and self.record_number != self.index):
            self.metadata_warnings.append("header_record_number_does_not_match_mft_index")
        
        curr = attr_off
        data_attributes = 0
        terminated = False
        while curr + 4 <= bytes_in_use:
            atype = struct.unpack_from("<I", self.raw_data, curr)[0]
            if atype == 0xFFFFFFFF:
                terminated = True
                break
            if curr + 8 > bytes_in_use:
                raise ValueError("Truncated MFT attribute header")
            alen = struct.unpack_from("<I", self.raw_data, curr + 4)[0]
            if alen < 16 or curr + alen > bytes_in_use:
                raise ValueError("Invalid MFT attribute length")
            if curr % 8 or alen % 8:
                raise ValueError("MFT attributes must be 8-byte aligned")

            if atype == 0x30: # $FILE_NAME
                self._parse_file_name(curr, alen)
            elif atype == 0x20: # $ATTRIBUTE_LIST may point to additional data extents.
                self.has_attribute_list = True
                self.data_is_complete = False
            elif atype == 0x80: # $DATA
                attribute_name = self._parse_attribute_name(curr, alen)
                if not attribute_name:
                    data_attributes += 1
                    if data_attributes > 1:
                        self.data_is_complete = False
                    self._parse_data(curr, alen)
                else:
                    self._parse_named_data(curr, alen, attribute_name)
            curr += alen
        if not terminated:
            raise ValueError("MFT record has no attribute terminator")
        self._finalize_named_data_streams()
        self.is_metadata_consistent = not self.metadata_warnings

    def _parse_attribute_name(self, curr, attr_len):
        name_length = self.raw_data[curr + 9]
        if name_length == 0:
            return ""
        name_offset = struct.unpack_from("<H", self.raw_data, curr + 10)[0]
        non_resident = self.raw_data[curr + 8]
        minimum_name_offset = 64 if non_resident else 24
        name_end = name_offset + name_length * 2
        if name_offset < minimum_name_offset or name_end > attr_len:
            raise ValueError("Invalid named MFT attribute bounds")
        try:
            name = bytes(self.raw_data[curr + name_offset:curr + name_end]).decode(
                "utf-16le", errors="strict",
            )
        except UnicodeDecodeError as exc:
            raise ValueError("MFT attribute name is not valid UTF-16LE") from exc
        if not name or "\x00" in name:
            raise ValueError("MFT attribute name is empty or contains a NUL")
        return name

    def _parse_named_data(self, curr, attr_len, name):
        """Keep one attribute descriptor; duplicate names are conservative."""
        key = name.casefold()
        if key in self.named_data_streams:
            previous = self.named_data_streams[key]
            reasons = tuple(dict.fromkeys(
                (*previous.incomplete_reasons, "duplicate_named_data_attributes")
            ))
            self.named_data_streams[key] = replace(
                previous, is_complete=False, incomplete_reasons=reasons,
            )
            return

        non_resident = self.raw_data[curr + 8]
        flags = struct.unpack_from("<H", self.raw_data, curr + 12)[0]
        unsupported_reason = unsupported_data_attribute_reason(flags)
        if non_resident not in (0, 1):
            raise ValueError("Invalid named $DATA residency flag")
        if non_resident:
            if attr_len < 64:
                raise ValueError("Truncated named non-resident $DATA attribute")
            lowest_vcn = struct.unpack_from("<Q", self.raw_data, curr + 16)[0]
            highest_vcn = struct.unpack_from("<Q", self.raw_data, curr + 24)[0]
            allocated_size = struct.unpack_from("<Q", self.raw_data, curr + 40)[0]
            file_size = struct.unpack_from("<Q", self.raw_data, curr + 48)[0]
            runlist_offset = struct.unpack_from("<H", self.raw_data, curr + 32)[0]
            if runlist_offset < 64 or runlist_offset >= attr_len:
                raise ValueError("Invalid named $DATA runlist offset")
            runs = tuple(AttributeParser.parse_runlist(
                self.raw_data[curr + runlist_offset:curr + attr_len]
            ))
            described_clusters = sum(cluster_count for _lcn, cluster_count in runs)
            reasons = []
            if lowest_vcn != 0:
                reasons.append("stream_starts_after_first_vcn")
            if highest_vcn < lowest_vcn or described_clusters != highest_vcn - lowest_vcn + 1:
                reasons.append("runlist_does_not_cover_declared_vcn_range")
            self.named_data_streams[key] = NTFSDataStream(
                name=name,
                file_size=file_size,
                allocated_size=allocated_size,
                resident_data=None,
                data_runs=runs,
                is_resident=False,
                is_complete=not reasons,
                incomplete_reasons=tuple(reasons),
                flags=flags,
                unsupported_reason=unsupported_reason,
            )
            return

        if attr_len < 24:
            raise ValueError("Truncated named resident $DATA attribute")
        file_size = struct.unpack_from("<I", self.raw_data, curr + 16)[0]
        content_offset = struct.unpack_from("<H", self.raw_data, curr + 20)[0]
        content_end = content_offset + file_size
        if content_offset < 24 or content_end > attr_len:
            raise ValueError("Invalid named resident $DATA content bounds")
        content = bytes(self.raw_data[curr + content_offset:curr + content_end])
        self.named_data_streams[key] = NTFSDataStream(
            name=name,
            file_size=file_size,
            allocated_size=file_size,
            resident_data=content,
            data_runs=(),
            is_resident=True,
            is_complete=True,
            flags=flags,
            unsupported_reason=unsupported_reason,
        )

    def _finalize_named_data_streams(self):
        if not self.named_data_streams:
            return
        reasons = []
        if self.has_attribute_list:
            reasons.append("attribute_list_may_reference_missing_stream_extents")
        if self.is_extension_record:
            reasons.append("extension_record_requires_base_record_resolution")
        if not reasons:
            return
        for key, stream in tuple(self.named_data_streams.items()):
            self.named_data_streams[key] = replace(
                stream,
                is_complete=False,
                incomplete_reasons=tuple(dict.fromkeys(
                    (*stream.incomplete_reasons, *reasons)
                )),
            )

    def get_named_data_stream(self, name):
        """Return a named stream descriptor using NTFS case-insensitive lookup."""
        return self.named_data_streams.get(str(name).casefold())

    def _parse_file_name(self, curr, attr_len):
        if attr_len < 0x18:
            raise ValueError("Truncated $FILE_NAME attribute")
        content_offset = struct.unpack_from("<H", self.raw_data, curr + 20)[0]
        content_length = struct.unpack_from("<I", self.raw_data, curr + 16)[0]
        start = curr + content_offset
        end = start + content_length
        if content_offset < 24 or end > curr + attr_len or content_length < 66:
            raise ValueError("Invalid $FILE_NAME content bounds")
        content = self.raw_data[start:end]
        parent_reference = struct.unpack_from("<Q", content, 0)[0]
        name, parent_index = AttributeParser.get_file_name(content)
        namespace = content[65]
        if namespace not in (0, 1, 2, 3):
            raise ValueError("Unknown $FILE_NAME namespace")
        priority = {0: 2, 1: 3, 2: 1, 3: 3}.get(namespace, 0)
        if priority >= self._filename_priority:
            self.parent_index = parent_index
            self.parent_reference = parent_reference
            self.parent_sequence_number = (parent_reference >> 48) & 0xFFFF
            self.name = name
            self._filename_priority = priority

    def _parse_data(self, curr, attr_len):
        non_resident = self.raw_data[curr+8]
        self.data_attribute_flags = struct.unpack_from("<H", self.raw_data, curr + 12)[0]
        self.data_unsupported_reason = unsupported_data_attribute_reason(
            self.data_attribute_flags,
        )
        if non_resident not in (0, 1):
            raise ValueError("Invalid $DATA residency flag")
        if non_resident:
            if attr_len < 64:
                raise ValueError("Truncated non-resident $DATA attribute")
            lowest_vcn = struct.unpack_from("<Q", self.raw_data, curr + 16)[0]
            if lowest_vcn != 0:
                self.data_is_complete = False
            self.allocated_size = struct.unpack_from("<Q", self.raw_data, curr + 40)[0]
            self.file_size = struct.unpack_from("<Q", self.raw_data, curr + 48)[0]
            runlist_offset = struct.unpack_from("<H", self.raw_data, curr + 32)[0]
            if runlist_offset < 64 or runlist_offset >= attr_len:
                raise ValueError("Invalid $DATA runlist offset")
            self.data_runs = AttributeParser.parse_runlist(
                self.raw_data[curr + runlist_offset:curr + attr_len]
            )
        else:
            if attr_len < 24:
                raise ValueError("Truncated resident $DATA attribute")
            self.file_size = struct.unpack_from("<I", self.raw_data, curr + 16)[0]
            self.allocated_size = self.file_size
            content_offset = struct.unpack_from("<H", self.raw_data, curr + 20)[0]
            if content_offset < 24 or content_offset + self.file_size > attr_len:
                raise ValueError("Invalid resident $DATA content bounds")
            self.resident_data = bytes(
                self.raw_data[curr + content_offset:curr + content_offset + self.file_size]
            )
