"""Conservatively resolve fragmented unnamed NTFS $DATA extents."""

from dataclasses import dataclass
from collections.abc import Mapping
import struct

from ntfs.attributes import AttributeParser


@dataclass(frozen=True)
class DataExtentResolution:
    """Evidence returned when an MFT $DATA runlist is resolved or refused."""

    status: str
    reason: str | None = None
    data_runs: tuple[tuple[int | None, int], ...] = ()
    file_size: int = 0
    extent_count: int = 0


@dataclass(frozen=True)
class _DataAttribute:
    attribute_id: int
    lowest_vcn: int
    highest_vcn: int
    data_runs: tuple[tuple[int | None, int], ...]
    file_size: int
    flags: int
    is_resident: bool


@dataclass(frozen=True)
class _AttributeListEntry:
    attribute_type: int
    lowest_vcn: int
    record_number: int
    sequence_number: int
    attribute_id: int
    name: str


class MFTDataExtentResolver:
    """Join only MFT extents authorized by a resident ``$ATTRIBUTE_LIST``.

    This resolver performs no disk reads. The caller supplies all validated MFT
    records plus the selected volume geometry, then applies ``data_runs`` only
    when ``status == "resolved"``. Non-resident attribute lists and ambiguous,
    stale or incomplete extent chains remain inconclusive.
    """

    ATTRIBUTE_LIST_TYPE = 0x20
    DATA_TYPE = 0x80
    MAX_DATA_EXTENTS = 128
    MAX_ATTRIBUTE_LIST_ENTRIES = 4096
    MAX_MFT_RECORD_BYTES = 64 * 1024
    MAX_FILE_SIZE_BYTES = 16 * 1024**3

    def resolve(self, base_record, records, *, cluster_size, volume_size_bytes):
        """Return bounded contiguous logical runs for one base MFT record."""
        if getattr(base_record, "is_extension_record", False):
            return self._inconclusive("extension_record_is_not_a_base_record")
        if not bool(getattr(base_record, "is_valid", False)):
            return self._inconclusive("invalid_base_record")
        if not bool(getattr(base_record, "has_attribute_list", False)):
            return DataExtentResolution("not_required", file_size=int(base_record.file_size))

        try:
            cluster_size = int(cluster_size)
            volume_size_bytes = int(volume_size_bytes)
            file_size = int(base_record.file_size)
            record_number = int(base_record.index)
            sequence_number = int(base_record.sequence_number)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return self._inconclusive("invalid_volume_or_record_geometry")
        if cluster_size <= 0 or volume_size_bytes <= 0:
            return self._inconclusive("invalid_volume_or_record_geometry")
        if file_size <= 0 or file_size > self.MAX_FILE_SIZE_BYTES:
            return self._inconclusive("file_size_outside_supported_bounds")
        if not bool(getattr(base_record, "is_metadata_consistent", False)):
            return self._inconclusive("base_record_metadata_is_inconsistent")

        try:
            base_attributes = self._parse_record_attributes(base_record)
            list_entries = self._parse_attribute_list(base_record)
        except (ValueError, struct.error, UnicodeError, OverflowError):
            return self._inconclusive("attribute_list_is_malformed_or_unsupported")
        data_entries = [entry for entry in list_entries if entry.attribute_type == self.DATA_TYPE
                        and not entry.name]
        if not data_entries or len(data_entries) > self.MAX_DATA_EXTENTS:
            return self._inconclusive("data_extent_count_outside_supported_bounds")

        if isinstance(records, Mapping):
            by_record_number = records
        else:
            by_record_number = {}
            for record in records:
                try:
                    index = int(record.index)
                except (AttributeError, TypeError, ValueError, OverflowError):
                    continue
                by_record_number.setdefault(index, []).append(record)

        attributes = []
        seen_references = set()
        for entry in data_entries:
            reference_key = (entry.record_number, entry.sequence_number, entry.attribute_id)
            if reference_key in seen_references:
                return self._inconclusive("duplicate_data_extent_reference")
            seen_references.add(reference_key)
            candidates = by_record_number.get(entry.record_number, ())
            if not isinstance(candidates, (tuple, list)):
                candidates = (candidates,)
            matching = [record for record in candidates
                        if int(getattr(record, "sequence_number", -1)) == entry.sequence_number]
            if len(matching) != 1:
                return self._inconclusive("missing_or_ambiguous_extent_record_generation")

            extent_record = matching[0]
            if not bool(getattr(extent_record, "is_valid", False)):
                return self._inconclusive("extent_record_is_invalid")
            if not bool(getattr(extent_record, "is_metadata_consistent", False)):
                return self._inconclusive("extent_record_metadata_is_inconsistent")
            if not self._record_number_matches_header(extent_record):
                return self._inconclusive("extent_record_number_does_not_match_header")
            if entry.record_number == record_number:
                if entry.sequence_number != sequence_number:
                    return self._inconclusive("base_record_generation_mismatch")
            elif not self._references_base(extent_record, record_number, sequence_number):
                return self._inconclusive("extent_record_references_a_different_base_generation")
            elif bool(getattr(extent_record, "is_allocated", True)) != bool(
                    getattr(base_record, "is_allocated", True)):
                return self._inconclusive("base_and_extent_allocation_states_differ")

            if extent_record is base_record:
                descriptors = base_attributes
            else:
                try:
                    descriptors = self._parse_record_attributes(extent_record)
                except (ValueError, struct.error, UnicodeError, OverflowError):
                    return self._inconclusive("extent_record_attributes_are_malformed")
            matching_attributes = [attribute for attribute in descriptors
                                   if attribute.attribute_id == entry.attribute_id
                                   and attribute.lowest_vcn == entry.lowest_vcn]
            if len(matching_attributes) != 1:
                return self._inconclusive("attribute_list_entry_does_not_match_data_attribute")
            attribute = matching_attributes[0]
            if attribute.is_resident or attribute.highest_vcn < attribute.lowest_vcn:
                return self._inconclusive("resident_or_invalid_nonresident_extent")
            if attribute.flags & (0x0001 | 0x4000):
                return self._inconclusive("compressed_or_encrypted_data_is_unsupported")
            described_clusters = sum(count for _lcn, count in attribute.data_runs)
            if described_clusters != attribute.highest_vcn - attribute.lowest_vcn + 1:
                return self._inconclusive("runlist_cluster_count_does_not_match_vcn_range")
            attributes.append(attribute)

        attributes.sort(key=lambda attribute: attribute.lowest_vcn)
        next_vcn = 0
        combined_runs = []
        physical_ranges = []
        for attribute in attributes:
            if attribute.lowest_vcn != next_vcn:
                return self._inconclusive("data_extent_vcn_gap_or_overlap")
            next_vcn = attribute.highest_vcn + 1
            for lcn, count in attribute.data_runs:
                if count <= 0:
                    return self._inconclusive("non_positive_cluster_run")
                if lcn is not None:
                    start = int(lcn) * cluster_size
                    end = start + int(count) * cluster_size
                    if start < 0 or end > volume_size_bytes:
                        return self._inconclusive("data_extent_outside_selected_volume")
                    physical_ranges.append((start, end))
                combined_runs.append((lcn, int(count)))
                if len(combined_runs) > self.MAX_DATA_EXTENTS * 256:
                    return self._inconclusive("run_count_outside_supported_bounds")

        required_clusters = (file_size + cluster_size - 1) // cluster_size
        if next_vcn != required_clusters:
            return self._inconclusive("data_extents_do_not_cover_declared_file_size")
        if self._ranges_overlap(physical_ranges):
            return self._inconclusive("physical_data_extents_overlap")
        if int(getattr(base_record, "file_size", -1)) != file_size:
            return self._inconclusive("file_size_changed_during_resolution")

        return DataExtentResolution(
            status="resolved",
            data_runs=tuple(combined_runs),
            file_size=file_size,
            extent_count=len(attributes),
        )

    @classmethod
    def _parse_record_attributes(cls, record):
        raw = bytes(getattr(record, "raw_data", b""))
        if len(raw) < 48 or len(raw) > cls.MAX_MFT_RECORD_BYTES or raw[:4] != b"FILE":
            raise ValueError("MFT record size or signature is invalid")
        attribute_offset = struct.unpack_from("<H", raw, 20)[0]
        bytes_in_use = struct.unpack_from("<I", raw, 24)[0]
        if attribute_offset < 48 or attribute_offset % 8 or not attribute_offset < bytes_in_use <= len(raw):
            raise ValueError("MFT attribute bounds are invalid")
        attributes = []
        cursor = attribute_offset
        terminated = False
        while cursor + 4 <= bytes_in_use:
            attribute_type = struct.unpack_from("<I", raw, cursor)[0]
            if attribute_type == 0xFFFFFFFF:
                terminated = True
                break
            if cursor + 8 > bytes_in_use:
                raise ValueError("Truncated MFT attribute header")
            attribute_length = struct.unpack_from("<I", raw, cursor + 4)[0]
            if (attribute_length < 16 or attribute_length % 8
                    or cursor + attribute_length > bytes_in_use):
                raise ValueError("MFT attribute length is invalid")
            attribute_id = struct.unpack_from("<H", raw, cursor + 14)[0]
            if attribute_type == cls.DATA_TYPE:
                attribute = cls._parse_data_attribute(raw, cursor, attribute_length, attribute_id)
                if not attribute.is_resident and not cls._attribute_name(raw, cursor, attribute_length):
                    attributes.append(attribute)
            cursor += attribute_length
        if not terminated:
            raise ValueError("MFT attribute terminator is missing")
        return tuple(attributes)

    @classmethod
    def _parse_data_attribute(cls, raw, cursor, length, attribute_id):
        residency = raw[cursor + 8]
        flags = struct.unpack_from("<H", raw, cursor + 12)[0]
        if residency == 0:
            if length < 24:
                raise ValueError("Resident data attribute is truncated")
            size = struct.unpack_from("<I", raw, cursor + 16)[0]
            return _DataAttribute(attribute_id, 0, 0, (), size, flags, True)
        if residency != 1 or length < 64:
            raise ValueError("Non-resident data attribute is invalid")
        lowest_vcn, highest_vcn = struct.unpack_from("<QQ", raw, cursor + 16)
        runlist_offset = struct.unpack_from("<H", raw, cursor + 32)[0]
        file_size = struct.unpack_from("<Q", raw, cursor + 48)[0]
        if runlist_offset < 64 or runlist_offset >= length:
            raise ValueError("Non-resident runlist bounds are invalid")
        runs = tuple(AttributeParser.parse_runlist(raw[cursor + runlist_offset:cursor + length]))
        return _DataAttribute(
            attribute_id, lowest_vcn, highest_vcn, runs, file_size, flags, False,
        )

    @classmethod
    def _parse_attribute_list(cls, record):
        raw = bytes(getattr(record, "raw_data", b""))
        attribute_offset = struct.unpack_from("<H", raw, 20)[0]
        bytes_in_use = struct.unpack_from("<I", raw, 24)[0]
        cursor = attribute_offset
        values = []
        while cursor + 8 <= bytes_in_use:
            attribute_type = struct.unpack_from("<I", raw, cursor)[0]
            if attribute_type == 0xFFFFFFFF:
                break
            length = struct.unpack_from("<I", raw, cursor + 4)[0]
            if length < 16 or cursor + length > bytes_in_use:
                raise ValueError("MFT attribute list bounds are invalid")
            if attribute_type == cls.ATTRIBUTE_LIST_TYPE:
                if raw[cursor + 8] != 0:
                    raise ValueError("Non-resident attribute lists are unsupported")
                if length < 24:
                    raise ValueError("Resident attribute list header is truncated")
                value_size = struct.unpack_from("<I", raw, cursor + 16)[0]
                value_offset = struct.unpack_from("<H", raw, cursor + 20)[0]
                value_end = value_offset + value_size
                if value_offset < 24 or value_end > length:
                    raise ValueError("Resident attribute list value is out of bounds")
                values.append(bytes(raw[cursor + value_offset:cursor + value_end]))
            cursor += length
        if len(values) != 1:
            raise ValueError("Exactly one resident attribute list is required")
        entries = []
        data = values[0]
        position = 0
        while position < len(data):
            if len(data) - position < 26:
                raise ValueError("Attribute list entry is truncated")
            attribute_type = struct.unpack_from("<I", data, position)[0]
            length = struct.unpack_from("<H", data, position + 4)[0]
            name_length = data[position + 6]
            name_offset = data[position + 7]
            if (length < 26 or length % 8 or position + length > len(data)):
                raise ValueError("Attribute list entry length is invalid")
            lowest_vcn = struct.unpack_from("<Q", data, position + 8)[0]
            file_reference = struct.unpack_from("<Q", data, position + 16)[0]
            attribute_id = struct.unpack_from("<H", data, position + 24)[0]
            name = ""
            if name_length:
                name_end = name_offset + name_length * 2
                if name_offset < 26 or name_end > length:
                    raise ValueError("Attribute list entry name is out of bounds")
                name = data[position + name_offset:position + name_end].decode(
                    "utf-16le", errors="strict",
                )
            entries.append(_AttributeListEntry(
                attribute_type=attribute_type,
                lowest_vcn=lowest_vcn,
                record_number=file_reference & 0xFFFFFFFFFFFF,
                sequence_number=(file_reference >> 48) & 0xFFFF,
                attribute_id=attribute_id,
                name=name,
            ))
            if len(entries) > cls.MAX_ATTRIBUTE_LIST_ENTRIES:
                raise ValueError("Attribute list entry count exceeds limit")
            position += length
        return tuple(entries)

    @classmethod
    def _attribute_name(cls, raw, cursor, length):
        name_length = raw[cursor + 9]
        if not name_length:
            return ""
        name_offset = struct.unpack_from("<H", raw, cursor + 10)[0]
        end = name_offset + name_length * 2
        if name_offset < 64 or end > length:
            raise ValueError("Named data attribute name is out of bounds")
        return raw[cursor + name_offset:cursor + end].decode("utf-16le", errors="strict")

    @staticmethod
    def _references_base(record, base_index, base_sequence):
        reference = int(getattr(record, "base_file_reference", 0) or 0)
        return ((reference & 0xFFFFFFFFFFFF) == base_index
                and ((reference >> 48) & 0xFFFF) == base_sequence)

    @staticmethod
    def _record_number_matches_header(record):
        header_number = getattr(record, "record_number", None)
        if header_number in (None, 0):
            return True
        return int(header_number) == int(record.index)

    @staticmethod
    def _ranges_overlap(ranges):
        ordered = sorted(ranges)
        return any(current[0] < previous[1]
                   for previous, current in zip(ordered, ordered[1:]))

    @staticmethod
    def _inconclusive(reason):
        return DataExtentResolution(status="inconclusive", reason=reason)
