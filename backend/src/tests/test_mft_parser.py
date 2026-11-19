import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ntfs.attributes import AttributeParser
from ntfs.mft_parser import MFTRecord


def resident_attribute(attribute_type, content):
    length = (24 + len(content) + 7) & ~7
    attribute = bytearray(length)
    struct.pack_into("<II", attribute, 0, attribute_type, length)
    attribute[8] = 0
    struct.pack_into("<I", attribute, 16, len(content))
    struct.pack_into("<H", attribute, 20, 24)
    attribute[24:24 + len(content)] = content
    return attribute


def make_record(name="photo.jpg", payload=b"data", has_attribute_list=False,
                record_number=0, base_file_reference=0, parent_reference=5):
    raw = bytearray(1024)
    raw[:4] = b"FILE"
    struct.pack_into("<HH", raw, 4, 0x30, 3)
    raw[0x30:0x36] = b"\xAA\xBB\0\0\0\0"
    raw[510:512] = b"\xAA\xBB"
    raw[1022:1024] = b"\xAA\xBB"
    attr_offset = 0x38
    struct.pack_into("<HH", raw, 20, attr_offset, 1)
    struct.pack_into("<Q", raw, 32, base_file_reference)
    struct.pack_into("<I", raw, 44, record_number)

    file_name = bytearray(66 + len(name.encode("utf-16le")))
    struct.pack_into("<Q", file_name, 0, parent_reference)
    file_name[64] = len(name)
    file_name[65] = 1
    file_name[66:] = name.encode("utf-16le")
    attrs = resident_attribute(0x30, file_name)
    if has_attribute_list:
        attrs += resident_attribute(0x20, b"\x00")
    attrs += resident_attribute(0x80, payload)
    attrs += struct.pack("<I", 0xFFFFFFFF)
    attrs += bytes((-len(attrs)) % 8)
    raw[attr_offset:attr_offset + len(attrs)] = attrs
    struct.pack_into("<I", raw, 24, attr_offset + len(attrs))
    return bytes(raw)


class MFTParserTests(unittest.TestCase):
    def test_parses_resident_file_name_and_data(self):
        record = MFTRecord(make_record(), 42)
        self.assertTrue(record.is_valid)
        self.assertEqual(record.name, "photo.jpg")
        self.assertEqual(record.parent_index, 5)
        self.assertEqual(record.resident_data, b"data")
        self.assertEqual(record.file_size, 4)
        self.assertEqual(record.allocated_size, 4)
        self.assertTrue(record.data_is_complete)

    def test_rejects_record_with_mismatched_update_sequence(self):
        raw = bytearray(make_record())
        raw[510:512] = b"\x00\x00"
        self.assertFalse(MFTRecord(raw, 42).is_valid)

    def test_marks_records_with_attribute_lists_as_potentially_incomplete(self):
        record = MFTRecord(make_record(has_attribute_list=True), 42)
        self.assertTrue(record.is_valid)
        self.assertFalse(record.data_is_complete)

    def test_parses_parent_reference_sequence_number(self):
        parent_reference = (9 << 48) | 5
        record = MFTRecord(make_record(parent_reference=parent_reference), 42)
        self.assertTrue(record.is_valid)
        self.assertEqual(record.parent_index, 5)
        self.assertEqual(record.parent_reference, parent_reference)
        self.assertEqual(record.parent_sequence_number, 9)

    def test_marks_extension_records_incomplete_for_recovery(self):
        base_reference = (3 << 48) | 12
        record = MFTRecord(make_record(base_file_reference=base_reference), 42)
        self.assertTrue(record.is_valid)
        self.assertFalse(record.data_is_complete)
        self.assertTrue(record.is_extension_record)
        self.assertTrue(record.is_metadata_consistent)

    def test_reports_mismatched_record_number_as_metadata_warning(self):
        record = MFTRecord(make_record(record_number=7), 42)
        self.assertTrue(record.is_valid)
        self.assertFalse(record.is_metadata_consistent)
        self.assertIn("header_record_number_does_not_match_mft_index", record.metadata_warnings)

    def test_rejects_unaligned_attribute_bounds(self):
        raw = bytearray(make_record())
        struct.pack_into("<H", raw, 20, 0x39)
        self.assertFalse(MFTRecord(raw, 42).is_valid)

    def test_rejects_update_sequence_array_overlapping_attributes(self):
        raw = bytearray(make_record())
        struct.pack_into("<H", raw, 20, 0x34)
        self.assertFalse(MFTRecord(raw, 42).is_valid)

    def test_runlist_parser_rejects_truncated_entries(self):
        with self.assertRaisesRegex(ValueError, "truncated"):
            AttributeParser.parse_runlist(b"\x21\x03\x01")

    def test_runlist_parser_requires_terminator(self):
        with self.assertRaisesRegex(ValueError, "terminator"):
            AttributeParser.parse_runlist(b"\x11\x03\x01")


if __name__ == "__main__":
    unittest.main()
