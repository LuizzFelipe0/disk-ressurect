import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.filesystems.ntfs.artifacts.logfile import NTFSLogFileParser


PAGE_SIZE = 4096
SECTOR_SIZE = 512


def _log_page(signature):
    page = bytearray(PAGE_SIZE)
    page[:4] = signature
    usa_offset = 0x30
    usa_count = PAGE_SIZE // SECTOR_SIZE + 1
    page[4:6] = usa_offset.to_bytes(2, "little")
    page[6:8] = usa_count.to_bytes(2, "little")
    update_sequence = b"\xaa\x55"
    page[usa_offset:usa_offset + 2] = update_sequence
    for index in range(1, usa_count):
        replacement_offset = usa_offset + index * 2
        page[replacement_offset:replacement_offset + 2] = index.to_bytes(2, "little")
        trailer_offset = index * SECTOR_SIZE - 2
        page[trailer_offset:trailer_offset + 2] = update_sequence
    if signature == b"RSTR":
        page[0x10:0x14] = PAGE_SIZE.to_bytes(4, "little")
        page[0x14:0x18] = PAGE_SIZE.to_bytes(4, "little")
        restart_offset = 0x48
        page[0x18:0x1A] = restart_offset.to_bytes(2, "little")
        page[0x1A:0x1C] = (1).to_bytes(2, "little", signed=True)
        page[0x1C:0x1E] = (1).to_bytes(2, "little", signed=True)
        area = memoryview(page)[restart_offset:restart_offset + 48]
        area[0:8] = (0x10008).to_bytes(8, "little")
        area[8:10] = (1).to_bytes(2, "little")
        area[10:12] = (0xFFFF).to_bytes(2, "little")
        area[12:14] = (0xFFFF).to_bytes(2, "little")
        area[16:20] = (46).to_bytes(4, "little")
        area[20:22] = (224).to_bytes(2, "little")
        area[22:24] = (64).to_bytes(2, "little")
        area[24:32] = (1024 * 1024).to_bytes(8, "little", signed=True)
        area[36:38] = (0x70).to_bytes(2, "little")
        area[38:40] = (0x40).to_bytes(2, "little")
    return bytes(page)


class NTFSLogFileParserTests(unittest.TestCase):
    def test_recognizes_aligned_restart_and_record_pages_after_fixup_validation(self):
        result = NTFSLogFileParser().parse(
            _log_page(b"RSTR") + _log_page(b"RCRD"),
        )

        self.assertEqual(2, result.pages_examined)
        self.assertEqual(2, len(result.pages))
        self.assertEqual(1, result.restart_pages)
        self.assertEqual(1, result.record_pages)
        self.assertEqual((0, PAGE_SIZE), tuple(page.source_offset for page in result.pages))
        self.assertEqual(
            "aligned_page_signature_and_fixups; RSTR version 1.1 restart bounds; LSN values are raw",
            result.evidence_scope,
        )
        self.assertEqual((1, 1), (result.pages[0].format_major,
                                 result.pages[0].format_minor))
        self.assertEqual(0x10008, result.pages[0].current_lsn)

    def test_rejects_page_with_malformed_fixup_array_or_sector_trailer(self):
        invalid_usa_count = bytearray(_log_page(b"RSTR"))
        invalid_usa_count[6:8] = (2).to_bytes(2, "little")
        invalid_trailer = bytearray(_log_page(b"RCRD"))
        invalid_trailer[SECTOR_SIZE - 2:SECTOR_SIZE] = b"\x00\x00"

        result = NTFSLogFileParser().parse(bytes(invalid_usa_count) + bytes(invalid_trailer))

        self.assertEqual(2, result.pages_examined)
        self.assertEqual((), result.pages)
        self.assertEqual(2, result.malformed_pages)

    def test_ignores_unaligned_signature_and_reports_no_log_evidence(self):
        data = bytearray(PAGE_SIZE)
        data[37:41] = b"RSTR"

        result = NTFSLogFileParser().parse(data)

        self.assertEqual((), result.pages)
        self.assertEqual(0, result.malformed_pages)
        self.assertFalse(result.limit_reached)

    def test_rejects_restart_page_with_unknown_version_or_out_of_range_area(self):
        unknown_version = bytearray(_log_page(b"RSTR"))
        unknown_version[0x1C:0x1E] = (2).to_bytes(2, "little", signed=True)
        invalid_area = bytearray(_log_page(b"RSTR"))
        invalid_area[0x18:0x1A] = (PAGE_SIZE - 16).to_bytes(2, "little")

        result = NTFSLogFileParser().parse(bytes(unknown_version) + bytes(invalid_area))

        self.assertEqual((), result.pages)
        self.assertEqual(2, result.malformed_pages)

    def test_marks_scan_partial_when_byte_or_page_budget_is_reached(self):
        data = _log_page(b"RSTR") + _log_page(b"RCRD")

        byte_limited = NTFSLogFileParser(max_scan_bytes=PAGE_SIZE).parse(data)
        page_limited = NTFSLogFileParser(max_pages=1).parse(data)

        self.assertTrue(byte_limited.limit_reached)
        self.assertEqual(PAGE_SIZE, byte_limited.bytes_examined)
        self.assertTrue(page_limited.limit_reached)
        self.assertEqual(1, page_limited.pages_examined)

    def test_marks_truncated_partial_page_without_classifying_it_as_a_valid_record(self):
        result = NTFSLogFileParser().parse(_log_page(b"RSTR") + b"RCRD" + b"\x00" * 100)

        self.assertTrue(result.truncated_input)
        self.assertEqual(1, result.pages_examined)
        self.assertEqual(1, result.restart_pages)
        self.assertEqual(0, result.record_pages)

    def test_rejects_invalid_page_geometry(self):
        parser = NTFSLogFileParser()
        with self.assertRaises(ValueError):
            parser.parse(b"", sector_size=1000)
        with self.assertRaises(ValueError):
            parser.parse(b"", page_size=3000)


if __name__ == "__main__":
    unittest.main()
