import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from disk.models import NTFSVolume
from ntfs.file_content_reader import NTFSFileContentReader
from ntfs.mft_data_extent_resolver import MFTDataExtentResolver
from ntfs.mft_parser import MFTRecord
from modules.catalog.service import CatalogService
from modules.catalog.mapper import CatalogMapper
from modules.recovery.service import RecoveryWorkflow


def resident_attribute(attribute_type, content, attribute_id):
    length = (24 + len(content) + 7) & ~7
    attribute = bytearray(length)
    struct.pack_into("<II", attribute, 0, attribute_type, length)
    struct.pack_into("<H", attribute, 14, attribute_id)
    struct.pack_into("<I", attribute, 16, len(content))
    struct.pack_into("<H", attribute, 20, 24)
    attribute[24:24 + len(content)] = content
    return attribute


def nonresident_data_attribute(lowest_vcn, highest_vcn, lcn, file_size, attribute_id):
    runlist = bytes((0x11, highest_vcn - lowest_vcn + 1, lcn, 0))
    length = (64 + len(runlist) + 7) & ~7
    attribute = bytearray(length)
    struct.pack_into("<II", attribute, 0, 0x80, length)
    attribute[8] = 1
    struct.pack_into("<H", attribute, 14, attribute_id)
    struct.pack_into("<QQ", attribute, 16, lowest_vcn, highest_vcn)
    struct.pack_into("<H", attribute, 32, 64)
    struct.pack_into("<Q", attribute, 40, (highest_vcn - lowest_vcn + 1) * 4)
    struct.pack_into("<Q", attribute, 48, file_size)
    attribute[64:64 + len(runlist)] = runlist
    return attribute


def attribute_list_entry(record_number, sequence_number, lowest_vcn, attribute_id=3):
    entry = bytearray(32)
    struct.pack_into("<I H B B Q Q H", entry, 0, 0x80, 32, 0, 26, lowest_vcn,
                     (sequence_number << 48) | record_number, attribute_id)
    return entry


def make_record(index, sequence, attrs, *, base_reference=0, name="photo.jpg"):
    raw = bytearray(1024)
    raw[:4] = b"FILE"
    struct.pack_into("<HH", raw, 4, 0x30, 3)
    struct.pack_into("<H", raw, 16, sequence)
    raw[0x30:0x36] = b"\xAA\xBB\0\0\0\0"
    raw[510:512] = b"\xAA\xBB"
    raw[1022:1024] = b"\xAA\xBB"
    attr_offset = 0x38
    struct.pack_into("<HH", raw, 20, attr_offset, 1)
    struct.pack_into("<Q", raw, 32, base_reference)
    struct.pack_into("<I", raw, 44, index)

    file_name = bytearray(66 + len(name.encode("utf-16le")))
    struct.pack_into("<Q", file_name, 0, 5)
    file_name[64] = len(name)
    file_name[65] = 1
    file_name[66:] = name.encode("utf-16le")
    attributes = resident_attribute(0x30, file_name, 1) + b"".join(attrs)
    attributes += struct.pack("<I", 0xFFFFFFFF)
    attributes += bytes((-len(attributes)) % 8)
    raw[attr_offset:attr_offset + len(attributes)] = attributes
    struct.pack_into("<I", raw, 24, attr_offset + len(attributes))
    return MFTRecord(raw, index, record_size=1024)


def make_fragmented_records(
    *, extension_sequence=9, listed_extension_sequence=None,
    extension_vcns=(1, 1), extension_lcn=20,
):
    base_index, base_sequence = 42, 7
    extension_index = 43
    entries = (
        attribute_list_entry(base_index, base_sequence, 0),
        attribute_list_entry(
            extension_index,
            extension_sequence if listed_extension_sequence is None else listed_extension_sequence,
            extension_vcns[0],
        ),
    )
    base_reference = (base_sequence << 48) | base_index
    base = make_record(
        base_index,
        base_sequence,
        [resident_attribute(0x20, b"".join(entries), 2),
         nonresident_data_attribute(0, 0, 10, 8, 3)],
    )
    extension = make_record(
        extension_index,
        extension_sequence,
        [nonresident_data_attribute(
            extension_vcns[0], extension_vcns[1], extension_lcn, 8, 3,
        )],
        base_reference=base_reference,
        name="extension",
    )
    return base, extension


def serialize_record(record):
    """Restore the update-sequence words expected at on-disk sector tails."""
    raw = bytearray(record.raw_data)
    usa_offset, usa_count = struct.unpack_from("<HH", raw, 4)
    for index in range(1, usa_count):
        sector_end = index * 512 - 2
        raw[sector_end:sector_end + 2] = raw[usa_offset:usa_offset + 2]
    return bytes(raw)


class FakeDisk:
    def __init__(self, data):
        self.data = bytearray(data)

    def read_at(self, offset, size):
        return bytes(self.data[offset:offset + size])

    @property
    def size(self):
        return len(self.data)

    def close(self):
        pass


class MFTDataExtentResolverTests(unittest.TestCase):
    def test_resolves_exact_base_and_extension_generations_into_ordered_runs(self):
        base, extension = make_fragmented_records()

        result = MFTDataExtentResolver().resolve(
            base, (base, extension), cluster_size=4, volume_size_bytes=128,
        )

        self.assertEqual("resolved", result.status)
        self.assertEqual(((10, 1), (20, 1)), result.data_runs)
        self.assertEqual(2, result.extent_count)
        self.assertEqual(8, result.file_size)

    def test_resolved_runs_stream_fragmented_file_in_logical_order(self):
        base, extension = make_fragmented_records()
        result = MFTDataExtentResolver().resolve(
            base, (base, extension), cluster_size=4, volume_size_bytes=128,
        )
        disk = FakeDisk(bytes(128))
        disk.data[40:44] = b"head"
        disk.data[80:84] = b"tail"
        base.data_runs = result.data_runs
        base.data_is_complete = result.status == "resolved"

        content = b"".join(NTFSFileContentReader(
            disk, 0, 4, volume_size_bytes=128,
        ).iter_chunks(type("Node", (), {"record": base})()))

        self.assertEqual(b"headtail", content)

    def test_stale_extension_sequence_is_inconclusive(self):
        base, extension = make_fragmented_records(
            extension_sequence=10, listed_extension_sequence=9,
        )

        result = MFTDataExtentResolver().resolve(
            base, (base, extension), cluster_size=4, volume_size_bytes=128,
        )

        self.assertEqual("inconclusive", result.status)
        self.assertEqual("missing_or_ambiguous_extent_record_generation", result.reason)
        self.assertFalse(base.data_is_complete)

    def test_vcn_gap_is_not_promoted_to_a_complete_runlist(self):
        base, extension = make_fragmented_records(extension_vcns=(2, 2))

        result = MFTDataExtentResolver().resolve(
            base, (base, extension), cluster_size=4, volume_size_bytes=128,
        )

        self.assertEqual("inconclusive", result.status)
        self.assertEqual("data_extent_vcn_gap_or_overlap", result.reason)

    def test_extent_outside_volume_is_rejected(self):
        base, extension = make_fragmented_records(extension_lcn=32)

        result = MFTDataExtentResolver().resolve(
            base, (base, extension), cluster_size=4, volume_size_bytes=128,
        )

        self.assertEqual("inconclusive", result.status)
        self.assertEqual("data_extent_outside_selected_volume", result.reason)

    def test_extent_count_limit_is_enforced(self):
        base, extension = make_fragmented_records()

        class OneExtentResolver(MFTDataExtentResolver):
            MAX_DATA_EXTENTS = 1

        result = OneExtentResolver().resolve(
            base, (base, extension), cluster_size=4, volume_size_bytes=128,
        )

        self.assertEqual("inconclusive", result.status)
        self.assertEqual("data_extent_count_outside_supported_bounds", result.reason)

    def test_catalog_and_extractor_recover_fragmented_deleted_file_without_listing_extension(self):
        base, extension = make_fragmented_records()
        disk_image = bytearray(16_384)
        disk_image[4096:5120] = serialize_record(base)
        disk_image[5120:6144] = serialize_record(extension)
        expected_content = b"\xff\xd8\xff\xe0\x00\x04\x00\x00"
        disk_image[4096 + 40:4096 + 44] = expected_content[:4]
        disk_image[4096 + 80:4096 + 84] = expected_content[4:]
        volume = NTFSVolume(
            3, 1, 4096, 8192, 512, 4, 1024, 4096, 2048, ((4096, 2, 42),),
        )

        snapshot = CatalogService(
            lambda _disk_number: FakeDisk(disk_image),
        ).build(volume)

        self.assertEqual((42,), tuple(snapshot.catalog.nodes))
        node = snapshot.catalog.nodes[42]
        self.assertEqual(((10, 1), (20, 1)), tuple(node.record.data_runs))
        self.assertTrue(node.record.data_is_complete)
        self.assertTrue(node.record.is_metadata_consistent)
        self.assertEqual("resolved", node.record.data_extent_resolution)
        self.assertEqual(2, node.record.data_extent_count)
        mapped = CatalogMapper.node(node, {id(node): "file-42"}).to_dict()
        self.assertEqual("resolved", mapped["dataExtentResolution"])
        self.assertEqual(2, mapped["dataExtentCount"])

        class SafeDestination:
            def validate(self, _path, _disk_number):
                return None

        with tempfile.TemporaryDirectory() as output_directory:
            result = RecoveryWorkflow(
                disk_factory=lambda _disk_number: FakeDisk(disk_image),
                output_guard=SafeDestination(),
            ).extract_selection(
                snapshot, (node,), output_directory, (".jpg",),
            )

            self.assertEqual(1, result.recovered_count)
            recovered_files = list(Path(output_directory).rglob("*.jpg"))
            self.assertEqual(1, len(recovered_files))
            self.assertEqual(expected_content, recovered_files[0].read_bytes())

    def test_catalog_keeps_stale_extent_inconclusive_and_not_recoverable(self):
        base, extension = make_fragmented_records(
            extension_sequence=10, listed_extension_sequence=9,
        )
        disk_image = bytearray(16_384)
        disk_image[4096:5120] = serialize_record(base)
        disk_image[5120:6144] = serialize_record(extension)
        volume = NTFSVolume(
            3, 1, 4096, 8192, 512, 4, 1024, 4096, 2048, ((4096, 2, 42),),
        )

        snapshot = CatalogService(
            lambda _disk_number: FakeDisk(disk_image),
        ).build(volume)

        self.assertEqual((42,), tuple(snapshot.catalog.nodes))
        record = snapshot.catalog.nodes[42].record
        self.assertFalse(record.data_is_complete)
        self.assertTrue(record.is_metadata_consistent)
        self.assertEqual("inconclusive", record.data_extent_resolution)
        self.assertEqual("missing_or_ambiguous_extent_record_generation",
                         record.data_extent_resolution_reason)
        mapped = CatalogMapper.node(
            snapshot.catalog.nodes[42], {id(snapshot.catalog.nodes[42]): "file-42"},
        ).to_dict()
        self.assertEqual("inconclusive", mapped["dataExtentResolution"])
        self.assertEqual("missing_or_ambiguous_extent_record_generation",
                         mapped["dataExtentResolutionReason"])

        class SafeDestination:
            def validate(self, _path, _disk_number):
                return None

        with tempfile.TemporaryDirectory() as output_directory:
            result = RecoveryWorkflow(
                disk_factory=lambda _disk_number: FakeDisk(disk_image),
                output_guard=SafeDestination(),
            ).extract_selection(
                snapshot, (snapshot.catalog.nodes[42],), output_directory, (".jpg",),
            )

        self.assertEqual(0, result.recovered_count)
        self.assertEqual("incomplete_mft", result.results[0].status)


if __name__ == "__main__":
    unittest.main()
