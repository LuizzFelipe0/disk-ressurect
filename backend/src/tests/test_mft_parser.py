import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from infrastructure.filesystems.ntfs.attributes.attributes import AttributeParser
from infrastructure.filesystems.ntfs.mft.parser import MFTRecord
from helpers import make_record, resident_attribute


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
