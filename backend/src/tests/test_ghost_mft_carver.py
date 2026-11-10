import os
import struct
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from disk.deep_scan.ghost_mft_carver import GhostMFTCarver
from disk.models import NTFSVolume
from ntfs.mft_parser import MFTRecord
from ntfs.tree_builder import TreeBuilder


def _resident_attribute(attribute_type, content):
    length = 24 + len(content)
    attribute = bytearray(length)
    struct.pack_into("<II", attribute, 0, attribute_type, length)
    struct.pack_into("<I", attribute, 16, len(content))
    struct.pack_into("<H", attribute, 20, 24)
    attribute[24:] = content
    return attribute


def make_record(name="photo.jpg", *, record_size=1024, allocated=False, payload=b"image", incomplete=False):
    raw = bytearray(record_size)
    raw[:4] = b"FILE"
    usa_offset = 0x30
    usa_count = record_size // 512 + 1
    struct.pack_into("<HH", raw, 4, usa_offset, usa_count)
    struct.pack_into("<H", raw, 16, 13)
    attr_offset = (usa_offset + usa_count * 2 + 7) & ~7
    struct.pack_into("<HH", raw, 20, attr_offset, 1 if allocated else 0)
    usa_sequence = b"\xAA\xBB"
    raw[usa_offset:usa_offset + 2] = usa_sequence
    for sector in range(1, usa_count):
        replacement_offset = usa_offset + sector * 2
        raw[replacement_offset:replacement_offset + 2] = bytes((sector, sector + 1))
        sector_end = sector * 512 - 2
        raw[sector_end:sector_end + 2] = usa_sequence

    encoded_name = name.encode("utf-16le")
    file_name = bytearray(66 + len(encoded_name))
    struct.pack_into("<Q", file_name, 0, 5)  # Parent reference deliberately may be absent.
    file_name[64] = len(name)
    file_name[65] = 1
    file_name[66:] = encoded_name
    attributes = _resident_attribute(0x30, file_name)
    if incomplete:
        attributes += _resident_attribute(0x20, b"list")
    attributes += _resident_attribute(0x80, payload)
    attributes += struct.pack("<I", 0xFFFFFFFF)
    raw[attr_offset:attr_offset + len(attributes)] = attributes
    struct.pack_into("<I", raw, 24, attr_offset + len(attributes))
    return bytes(raw)


def make_nonresident_record(name="unsafe.jpg", *, lcn=20, record_size=1024):
    raw = bytearray(make_record(name, record_size=record_size))
    attr_offset = struct.unpack_from("<H", raw, 20)[0]
    filename_length = struct.unpack_from("<I", raw, attr_offset + 4)[0]
    data_offset = attr_offset + filename_length
    end_offset = data_offset + struct.unpack_from("<I", raw, data_offset + 4)[0]
    cluster_count = 1
    runlist = bytes((0x11, cluster_count, lcn, 0))
    attribute = bytearray(64 + len(runlist))
    struct.pack_into("<II", attribute, 0, 0x80, len(attribute))
    attribute[8] = 1
    struct.pack_into("<H", attribute, 32, 64)
    struct.pack_into("<Q", attribute, 40, 512)
    struct.pack_into("<Q", attribute, 48, 512)
    attribute[64:] = runlist
    raw[data_offset:end_offset] = attribute + struct.pack("<I", 0xFFFFFFFF)
    struct.pack_into("<I", raw, 24, data_offset + len(attribute) + 4)
    usa_offset = struct.unpack_from("<H", raw, 4)[0]
    usa_count = struct.unpack_from("<H", raw, 6)[0]
    sequence = raw[usa_offset:usa_offset + 2]
    for sector in range(1, usa_count):
        raw[sector * 512 - 2:sector * 512] = sequence
    return bytes(raw)


class FakeDisk:
    def __init__(self, size=8192, short_reads=False):
        self.size = size
        self.data = bytearray(size)
        self.reads = []
        self.short_reads = short_reads

    def read_at(self, offset, size):
        self.reads.append((offset, size))
        end = min(offset + size, self.size - (1 if self.short_reads else 0))
        return bytes(self.data[offset:end])


def volume(*, record_size=1024, size=8192, fragment_offset=1024):
    return NTFSVolume(
        disk_number=0,
        partition_number=1,
        partition_offset=0,
        partition_size=size,
        bytes_per_sector=512,
        cluster_size=512,
        record_size=record_size,
        mft_offset=fragment_offset,
        mft_size=record_size,
        mft_fragments=((fragment_offset, 1, 0),),
    )


class GhostMFTCarverTests(unittest.TestCase):
    def test_carves_deleted_records_across_chunks_and_deduplicates_exact_copies(self):
        disk = FakeDisk()
        candidate = make_record()
        disk.data[2048:3072] = candidate
        disk.data[3072:4096] = candidate
        disk.data[4096:5120] = make_record("active.jpg", allocated=True)
        disk.data[5120:6144] = make_record("incomplete.jpg", incomplete=True)
        corrupt = bytearray(make_record("corrupt.jpg"))
        corrupt[510:512] = b"\x00\x00"  # Invalid USA fixup.
        disk.data[6144:7168] = corrupt
        progress = []

        records = GhostMFTCarver(disk, chunk_size=512).hunt(
            volume(), allowed_extensions={".jpg"}, progress_callback=lambda done, total: progress.append((done, total)),
        )

        self.assertEqual(len(records), 1)
        record = next(iter(records.values()))
        self.assertEqual(record.name, "photo.jpg")
        self.assertEqual(record.mft_offset, 2048)
        self.assertLess(record.index, 0)
        self.assertIsNotNone(record.resident_data)
        self.assertEqual(progress[-1][0], progress[-1][1])
        self.assertTrue(disk.reads)

    def test_uses_configured_record_size_and_usa_on_larger_mft_records(self):
        disk = FakeDisk()
        raw = make_record(record_size=2048)
        disk.data[4608:6656] = raw

        records = GhostMFTCarver(disk, chunk_size=512).hunt(
            volume(record_size=2048, fragment_offset=2048), allowed_extensions={".jpg"},
        )

        self.assertEqual([record.name for record in records.values()], ["photo.jpg"])

    def test_deduplicates_a_stale_copy_of_an_existing_canonical_record(self):
        disk = FakeDisk()
        raw = make_record()
        disk.data[2048:3072] = raw
        canonical = MFTRecord(raw, 10, record_size=1024)

        records = GhostMFTCarver(disk).hunt(
            volume(), allowed_extensions={".jpg"}, existing_records=[canonical],
        )

        self.assertEqual(records, {})

    def test_rejects_out_of_volume_data_runs_and_unsupported_extensions(self):
        disk = FakeDisk()
        disk.data[2048:3072] = make_record("notes.txt")
        disk.data[3072:4096] = make_nonresident_record()
        records = GhostMFTCarver(disk).hunt(
            volume(), allowed_extensions={".jpg"},
        )
        self.assertEqual(records, {})

    def test_accepts_a_complete_nonresident_runlist_inside_the_selected_volume(self):
        disk = FakeDisk()
        disk.data[2048:3072] = make_nonresident_record("safe.jpg", lcn=5)

        records = GhostMFTCarver(disk).hunt(volume(), allowed_extensions={".jpg"})

        self.assertEqual([record.name for record in records.values()], ["safe.jpg"])

    def test_supports_512_byte_records_and_ignores_unaligned_signature_hits(self):
        disk = FakeDisk()
        disk.data[2048:2560] = make_record("small.jpg", record_size=512)
        misaligned = make_record("misaligned.jpg")
        disk.data[3073:4097] = misaligned

        records = GhostMFTCarver(disk, chunk_size=512).hunt(
            volume(record_size=512, fragment_offset=512), allowed_extensions={".jpg"},
        )

        self.assertEqual([record.name for record in records.values()], ["small.jpg"])

    def test_raises_on_truncated_disk_reads_instead_of_silently_skipping_bytes(self):
        disk = FakeDisk(short_reads=True)
        with self.assertRaisesRegex(OSError, "Short orphan MFT scan read"):
            GhostMFTCarver(disk, chunk_size=512).hunt(volume(), allowed_extensions={".jpg"})

    def test_orphan_nodes_stay_isolated_from_untrusted_parent_references(self):
        record = MFTRecord(make_record(), -2049, mft_offset=2048, record_size=1024)
        builder = TreeBuilder(disk=None, fragments=[], base_offset=0, record_size=1024)
        builder.nodes = {0: SimpleNamespace(record=SimpleNamespace(index=0))}

        builder.inject_ghosts({record.index: record})

        orphan = builder.nodes[record.index]
        self.assertTrue(orphan.is_orphaned)
        self.assertIsNone(orphan.parent)
        self.assertIn("Lost_Files_DeepScan", orphan.full_path)
        self.assertIn("[DELETED]_photo.jpg", orphan.full_path)

    def test_rejects_synthetic_id_collisions(self):
        record = MFTRecord(make_record(), -2049, mft_offset=2048, record_size=1024)
        builder = TreeBuilder(disk=None, fragments=[], base_offset=0, record_size=1024)
        builder.nodes = {record.index: SimpleNamespace(record=SimpleNamespace(index=record.index))}

        with self.assertRaisesRegex(ValueError, "collides"):
            builder.inject_ghosts({record.index: record})


if __name__ == "__main__":
    unittest.main()
