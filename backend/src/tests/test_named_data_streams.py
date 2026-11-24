import os
import struct
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from infrastructure.filesystems.ntfs.artifacts.sources import UsnJournalEvidenceScanner
from infrastructure.filesystems.ntfs.readers.file_content_reader import FileContentError, NTFSFileContentReader
from infrastructure.filesystems.ntfs.mft.parser import MFTRecord


def _align(value, boundary=8):
    return (value + boundary - 1) & ~(boundary - 1)


def resident_data_attribute(payload, name=None):
    name_bytes = (name or "").encode("utf-16le")
    name_offset = 24 if name else 0
    content_offset = _align(24 + len(name_bytes)) if name else 24
    length = _align(content_offset + len(payload))
    attribute = bytearray(length)
    struct.pack_into("<II", attribute, 0, 0x80, length)
    attribute[8] = 0
    attribute[9] = len(name or "")
    struct.pack_into("<H", attribute, 10, name_offset)
    struct.pack_into("<I", attribute, 16, len(payload))
    struct.pack_into("<H", attribute, 20, content_offset)
    if name:
        attribute[name_offset:name_offset + len(name_bytes)] = name_bytes
    attribute[content_offset:content_offset + len(payload)] = payload
    return bytes(attribute)


def nonresident_data_attribute(name, *, lowest_vcn=0, highest_vcn=2,
                               file_size=10, allocated_size=12, runlist=b"\x11\x03\x01\x00"):
    name_bytes = name.encode("utf-16le")
    runlist_offset = _align(64 + len(name_bytes))
    length = _align(runlist_offset + len(runlist))
    attribute = bytearray(length)
    struct.pack_into("<II", attribute, 0, 0x80, length)
    attribute[8] = 1
    attribute[9] = len(name)
    struct.pack_into("<H", attribute, 10, 64)
    struct.pack_into("<Q Q", attribute, 16, lowest_vcn, highest_vcn)
    struct.pack_into("<H", attribute, 32, runlist_offset)
    struct.pack_into("<Q Q", attribute, 40, allocated_size, file_size)
    attribute[64:64 + len(name_bytes)] = name_bytes
    attribute[runlist_offset:runlist_offset + len(runlist)] = runlist
    return bytes(attribute)


def make_record(attributes, *, name="$UsnJrnl", base_file_reference=0):
    raw = bytearray(1024)
    raw[:4] = b"FILE"
    struct.pack_into("<HH", raw, 4, 0x30, 3)
    raw[0x30:0x36] = b"\xaa\xbb\x00\x00\x00\x00"
    raw[510:512] = b"\xaa\xbb"
    raw[1022:1024] = b"\xaa\xbb"
    offset = 0x38
    struct.pack_into("<HH", raw, 20, offset, 1)
    struct.pack_into("<Q", raw, 32, base_file_reference)
    for attribute in attributes:
        raw[offset:offset + len(attribute)] = attribute
        offset += len(attribute)
    struct.pack_into("<I", raw, offset, 0xFFFFFFFF)
    offset += 4
    offset = _align(offset)
    struct.pack_into("<I", raw, 24, offset)
    record = MFTRecord(raw, 42)
    record.name = name
    return record


class FakeDisk:
    def __init__(self, data):
        self.data = data
        self.reads = []

    def read_at(self, offset, size):
        self.reads.append((offset, size))
        return self.data[offset:offset + size]


def usn_record(name="old.txt", reason=0x200):
    encoded = name.encode("utf-16le")
    length = _align(60 + len(encoded))
    record = bytearray(length)
    struct.pack_into("<IHH", record, 0, length, 2, 0)
    struct.pack_into("<Q Q q q I I I I H H", record, 8,
                     (3 << 48) | 88, (2 << 48) | 5, 44, 0,
                     reason, 0, 0, 0, len(encoded), 60)
    record[60:60 + len(encoded)] = encoded
    return bytes(record)


class NamedDataStreamMFTTests(unittest.TestCase):
    def test_resident_named_stream_is_exposed_without_changing_unnamed_data(self):
        record = make_record([
            resident_data_attribute(b"base-content"),
            resident_data_attribute(b"journal-bytes", "$J"),
        ])

        self.assertTrue(record.is_valid)
        self.assertEqual(b"base-content", record.resident_data)
        stream = record.get_named_data_stream("$j")
        self.assertEqual("$J", stream.name)
        self.assertEqual(b"journal-bytes", stream.resident_data)
        self.assertTrue(stream.is_resident)
        self.assertTrue(stream.is_complete)

    def test_nonresident_named_stream_tracks_runlist_and_vcn_coverage(self):
        record = make_record([nonresident_data_attribute("$J")])

        self.assertTrue(record.is_valid)
        stream = record.named_data_streams["$j"]
        self.assertEqual(((1, 3),), stream.data_runs)
        self.assertEqual(10, stream.file_size)
        self.assertTrue(stream.is_complete)

    def test_complete_sparse_named_stream_reads_zero_filled_ranges(self):
        runlist = b"\x01\x01\x11\x01\x01\x00"  # one sparse cluster, then LCN 1
        record = make_record([nonresident_data_attribute(
            "$J", highest_vcn=1, file_size=8, allocated_size=4, runlist=runlist,
        )])
        disk = FakeDisk(bytes(4) + b"DATA")
        reader = NTFSFileContentReader(disk, 0, 4, volume_size_bytes=len(disk.data))

        content = reader.read_named_stream(SimpleNamespace(record=record), "$J")

        self.assertEqual(b"\x00\x00\x00\x00DATA", content)
        self.assertEqual([(4, 4)], disk.reads)

    def test_duplicate_named_streams_are_marked_incomplete(self):
        record = make_record([
            resident_data_attribute(b"first", "$J"),
            resident_data_attribute(b"second", "$J"),
        ])

        self.assertTrue(record.is_valid)
        stream = record.get_named_data_stream("$J")
        self.assertFalse(stream.is_complete)
        self.assertIn("duplicate_named_data_attributes", stream.incomplete_reasons)

    def test_attribute_list_and_extension_records_never_claim_named_stream_complete(self):
        attribute_list = bytearray(24)
        struct.pack_into("<II", attribute_list, 0, 0x20, 24)
        attribute_list[8] = 0
        struct.pack_into("<I", attribute_list, 16, 0)
        struct.pack_into("<H", attribute_list, 20, 24)
        for attributes, base_ref, reason in (
            ([resident_data_attribute(b"journal", "$J"), bytes(attribute_list)], 0,
             "attribute_list_may_reference_missing_stream_extents"),
            ([resident_data_attribute(b"journal", "$J")], (2 << 48) | 41,
             "extension_record_requires_base_record_resolution"),
        ):
            with self.subTest(reason=reason):
                record = make_record(attributes, base_file_reference=base_ref)
                stream = record.get_named_data_stream("$J")
                self.assertTrue(record.is_valid)
                self.assertFalse(stream.is_complete)
                self.assertIn(reason, stream.incomplete_reasons)

    def test_nonresident_stream_with_incomplete_declared_vcn_range_is_not_complete(self):
        record = make_record([nonresident_data_attribute("$J", highest_vcn=4)])

        self.assertTrue(record.is_valid)
        stream = record.get_named_data_stream("$J")
        self.assertFalse(stream.is_complete)
        self.assertIn("runlist_does_not_cover_declared_vcn_range", stream.incomplete_reasons)


class NamedDataStreamReaderTests(unittest.TestCase):
    def test_reads_resident_named_stream_with_prefix_limit(self):
        record = make_record([resident_data_attribute(b"journal-data", "$J")])
        reader = NTFSFileContentReader(FakeDisk(b""), 0, 4)

        self.assertEqual(b"journ", reader.read_named_stream(SimpleNamespace(record=record), "$J", 5))

    def test_reads_nonresident_named_stream_from_synthetic_media_with_limit(self):
        payload = b"0123456789AB"
        disk = FakeDisk(bytes(4) + payload)
        record = make_record([nonresident_data_attribute(
            "$J", file_size=len(payload), allocated_size=len(payload), highest_vcn=2,
        )])
        reader = NTFSFileContentReader(
            disk, 0, 4, chunk_size=3, volume_size_bytes=len(disk.data),
        )

        content = reader.read_named_stream(SimpleNamespace(record=record), "$J", 7)

        self.assertEqual(b"0123456", content)
        self.assertEqual(7, sum(size for _offset, size in disk.reads))
        self.assertTrue(all(size <= 3 for _offset, size in disk.reads))

    def test_refuses_duplicate_or_attribute_list_incomplete_streams(self):
        record = make_record([
            resident_data_attribute(b"one", "$J"),
            resident_data_attribute(b"two", "$J"),
        ])
        reader = NTFSFileContentReader(FakeDisk(b""), 0, 4)

        with self.assertRaisesRegex(FileContentError, "incomplete"):
            reader.read_named_stream(SimpleNamespace(record=record), "$J")

    def test_refuses_nonresident_named_stream_without_volume_bounds(self):
        record = make_record([nonresident_data_attribute("$J")])
        reader = NTFSFileContentReader(FakeDisk(bytes(32)), 0, 4)

        with self.assertRaisesRegex(FileContentError, "volume size is required"):
            reader.read_named_stream(SimpleNamespace(record=record), "$J")

    def test_refuses_nonresident_run_that_crosses_volume_boundary(self):
        record = make_record([nonresident_data_attribute("$J")])
        disk = FakeDisk(bytes(32))
        reader = NTFSFileContentReader(disk, 0, 4, volume_size_bytes=8)

        with self.assertRaisesRegex(FileContentError, "beyond the selected NTFS volume"):
            reader.read_named_stream(SimpleNamespace(record=record), "$J")
        self.assertEqual([], disk.reads)

    def test_volume_bound_is_also_applied_to_unnamed_index_reads(self):
        record = make_record([nonresident_data_attribute(
            "", file_size=10, allocated_size=12,
        )])
        disk = FakeDisk(bytes(32))
        reader = NTFSFileContentReader(disk, 0, 4, volume_size_bytes=8)

        with self.assertRaisesRegex(FileContentError, "beyond the selected NTFS volume"):
            b"".join(reader.iter_chunks(SimpleNamespace(record=record)))
        self.assertEqual([], disk.reads)

    def test_named_stream_read_has_hard_64_mib_ceiling(self):
        record = make_record([resident_data_attribute(b"x" * 32, "$J")])
        reader = NTFSFileContentReader(FakeDisk(b""), 0, 4)

        content = reader.read_named_stream(SimpleNamespace(record=record), "$J", 128 * 1024 * 1024)

        self.assertEqual(32, len(content))


class UsnJournalEvidenceScannerTests(unittest.TestCase):
    @staticmethod
    def _journal_node(record):
        parent = SimpleNamespace(record=SimpleNamespace(name="$Extend"), parent=None)
        return SimpleNamespace(record=record, children=[], parent=parent)

    def test_locates_j_stream_and_returns_events_only(self):
        journal = usn_record()
        record = make_record([resident_data_attribute(journal, "$J")])
        node = self._journal_node(record)
        reader = NTFSFileContentReader(FakeDisk(b""), 0, 4)

        result = UsnJournalEvidenceScanner().scan([node], reader.read_named_stream)

        self.assertEqual(1, len(result))
        self.assertEqual("complete", result[0].status)
        self.assertEqual(["old.txt"], [event.name for event in result[0].events])
        self.assertTrue(result[0].events[0].indicates_delete)
        self.assertFalse(hasattr(result[0], "content"))

    def test_does_not_treat_unrelated_usnjrnl_name_as_ntfs_journal(self):
        record = make_record([resident_data_attribute(usn_record(), "$J")])
        node = SimpleNamespace(record=record, children=[], parent=None)
        calls = []

        result = UsnJournalEvidenceScanner().scan(
            [node], lambda *args: calls.append(args) or usn_record(),
        )

        self.assertEqual("incomplete_stream", result[0].status)
        self.assertEqual("journal_parent_path_not_verified", result[0].reason)
        self.assertEqual([], calls)

    def test_scans_nonresident_j_stream_from_synthetic_disk_bytes(self):
        journal = usn_record(name="deleted-from-disk.txt")
        cluster_count = (len(journal) + 3) // 4
        runlist = b"\x11" + bytes([cluster_count]) + b"\x01\x00"
        attribute = nonresident_data_attribute(
            "$J", highest_vcn=cluster_count - 1, file_size=len(journal),
            allocated_size=cluster_count * 4, runlist=runlist,
        )
        record = make_record([attribute])
        disk_data = bytes(4) + journal + bytes(cluster_count * 4 - len(journal))
        reader = NTFSFileContentReader(
            FakeDisk(disk_data), 0, 4, chunk_size=13, volume_size_bytes=len(disk_data),
        )
        node = self._journal_node(record)

        result = UsnJournalEvidenceScanner().scan([node], reader.read_named_stream)

        self.assertEqual("complete", result[0].status)
        self.assertEqual(["deleted-from-disk.txt"], [event.name for event in result[0].events])

    def test_skips_journal_if_attribute_list_makes_stream_incomplete(self):
        attr_list = bytearray(24)
        struct.pack_into("<II", attr_list, 0, 0x20, 24)
        attr_list[8] = 0
        struct.pack_into("<H", attr_list, 20, 24)
        record = make_record([
            resident_data_attribute(usn_record(), "$J"),
            bytes(attr_list),
        ])
        node = self._journal_node(record)
        calls = []

        result = UsnJournalEvidenceScanner().scan(
            [node], lambda *args: calls.append(args) or b"",
        )

        self.assertEqual("incomplete_stream", result[0].status)
        self.assertEqual([], calls)

    def test_bounds_journal_read_and_reports_partial_stream(self):
        record = make_record([resident_data_attribute(b"12345678", "$J")])
        stream = record.get_named_data_stream("$J")
        stream = stream.__class__(
            name=stream.name, file_size=100, allocated_size=100,
            resident_data=b"12345678", data_runs=(), is_resident=True,
            is_complete=True,
        )
        record.named_data_streams["$j"] = stream
        node = self._journal_node(record)
        calls = []

        result = UsnJournalEvidenceScanner(max_bytes=6).scan(
            [node], lambda _node, name, limit: calls.append((name, limit)) or b"123456",
        )

        self.assertEqual([("$J", 6)], calls)
        self.assertEqual("partial", result[0].status)
        self.assertEqual("journal_stream_exceeds_scan_budget", result[0].reason)
        self.assertEqual(6, result[0].bytes_read)


if __name__ == "__main__":
    unittest.main()
