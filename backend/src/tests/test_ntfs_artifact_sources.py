import struct
import unittest

from infrastructure.filesystems.ntfs.artifacts.sources import RecycleBinIndexParser, UsnJournalParser


def _usn_v2(*, name="deleted.txt", reason=0x00000200, file_number=42,
            file_sequence=7, parent_number=5, parent_sequence=3, ticks=0):
    encoded_name = name.encode("utf-16le")
    record_length = (60 + len(encoded_name) + 7) & ~7
    record = bytearray(record_length)
    struct.pack_into("<IHH", record, 0, record_length, 2, 0)
    file_reference = (file_sequence << 48) | file_number
    parent_reference = (parent_sequence << 48) | parent_number
    struct.pack_into("<Q Q q q I I I I H H", record, 8,
                     file_reference, parent_reference, 123, ticks, reason,
                     0, 0, 0, len(encoded_name), 60)
    record[60:60 + len(encoded_name)] = encoded_name
    return bytes(record)


def _usn_v3(*, name="video.mp4", reason=0x100, ticks=0):
    encoded_name = name.encode("utf-16le")
    record_length = (76 + len(encoded_name) + 7) & ~7
    record = bytearray(record_length)
    struct.pack_into("<IHH", record, 0, record_length, 3, 0)
    record[8:24] = bytes(range(16))
    record[24:40] = bytes(range(16, 32))
    struct.pack_into("<q q I I I I H H", record, 40,
                     900, ticks, reason, 0, 0, 0, len(encoded_name), 76)
    record[76:76 + len(encoded_name)] = encoded_name
    return bytes(record)


class UsnJournalParserTests(unittest.TestCase):
    def test_parses_v2_file_delete_with_mft_references_and_timestamp(self):
        ticks = 134_000_000_000_000_000
        result = UsnJournalParser().parse(_usn_v2(ticks=ticks), source_offset=4096)

        self.assertEqual(1, len(result.artifacts))
        artifact = result.artifacts[0]
        self.assertEqual("usn_journal", artifact.source)
        self.assertEqual(4096, artifact.source_offset)
        self.assertEqual("deleted.txt", artifact.name)
        self.assertEqual((42, 7), (artifact.file_reference.record_number,
                                   artifact.file_reference.sequence_number))
        self.assertEqual((5, 3), (artifact.parent_reference.record_number,
                                  artifact.parent_reference.sequence_number))
        self.assertEqual(123, artifact.usn)
        self.assertIn("FILE_DELETE", artifact.reason_flags)
        self.assertTrue(artifact.indicates_delete)
        self.assertIsNotNone(artifact.timestamp_utc)

    def test_parses_v3_preserving_opaque_128_bit_file_ids(self):
        artifact = UsnJournalParser().parse(_usn_v3()).artifacts[0]

        self.assertEqual("video.mp4", artifact.name)
        self.assertEqual(bytes(range(16)).hex(), artifact.file_reference.raw_hex)
        self.assertIsNone(artifact.file_reference.record_number)
        self.assertFalse(artifact.indicates_delete)

    def test_skips_sparse_padding_and_reports_malformed_records(self):
        valid = _usn_v2(name="kept.txt", reason=0x100)
        malformed = bytearray(_usn_v2())
        struct.pack_into("<H", malformed, 58, 1)  # Name overlaps fixed header.
        data = bytes(malformed) + bytes(16) + valid

        result = UsnJournalParser().parse(data)

        self.assertEqual(["kept.txt"], [item.name for item in result.artifacts])
        self.assertGreaterEqual(result.malformed_records, 1)

    def test_byte_budget_stops_before_a_partial_record_and_returns_resume_offset(self):
        record = _usn_v2()
        result = UsnJournalParser(max_bytes=64).parse(record, source_offset=1000)

        self.assertTrue(result.limit_reached)
        self.assertEqual("byte_budget", result.limit_reason)
        self.assertEqual(1000, result.next_offset)
        self.assertEqual(1, result.records_examined)

    def test_record_budget_is_reported(self):
        data = _usn_v2(name="one.txt") + _usn_v2(name="two.txt")
        result = UsnJournalParser(max_records=1).parse(data)

        self.assertEqual(["one.txt"], [item.name for item in result.artifacts])
        self.assertTrue(result.limit_reached)
        self.assertEqual("record_budget", result.limit_reason)


class RecycleBinIndexParserTests(unittest.TestCase):
    @staticmethod
    def _header(version, size, ticks):
        return struct.pack("<Q Q Q", version, size, ticks)

    def test_parses_v1_path_and_pairs_dollar_r_name(self):
        path = "C:\\Users\\Ada\\report.txt"
        data = self._header(1, 1234, 134_000_000_000_000_000) + path.encode("utf-16le") + b"\x00\x00"

        artifact = RecycleBinIndexParser().parse(
            data, artifact_name="$Iabc123.txt", source_offset=77,
        )

        self.assertEqual("C:\\Users\\Ada\\report.txt", artifact.original_path)
        self.assertEqual("report.txt", artifact.name)
        self.assertEqual("$Rabc123.txt", artifact.companion_content_name)
        self.assertEqual(1234, artifact.size_bytes)
        self.assertTrue(artifact.indicates_delete)
        self.assertEqual(77, artifact.source_offset)

    def test_parses_v2_path_length_in_utf16_code_units(self):
        path = "D:\\Photos\\lost.jpg"
        encoded_path = path.encode("utf-16le")
        data = (self._header(2, 9000, 0)
                + struct.pack("<I", len(path))
                + encoded_path)

        artifact = RecycleBinIndexParser().parse(data)

        self.assertEqual(2, artifact.format_version)
        self.assertEqual(path, artifact.original_path)
        self.assertEqual("lost.jpg", artifact.name)
        self.assertIsNone(artifact.timestamp_utc)

    def test_rejects_truncated_and_oversized_v2_paths(self):
        truncated = self._header(2, 10, 0) + struct.pack("<I", 100) + b"x\x00"
        too_long = self._header(2, 10, 0) + struct.pack("<I", 9) + b"x\x00" * 9

        with self.assertRaisesRegex(ValueError, "Truncated"):
            RecycleBinIndexParser().parse(truncated)
        with self.assertRaisesRegex(ValueError, "configured limit"):
            RecycleBinIndexParser(max_path_code_units=8).parse(too_long)


if __name__ == "__main__":
    unittest.main()
