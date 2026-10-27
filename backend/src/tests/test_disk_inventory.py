import os
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from disk.inventory import DiskInventory
from disk.deep_scan.lost_partition_scanner import LostPartitionScanner
from disk.ntfs_discovery.anchor_resolver import MFTAnchorVolumeResolver
from disk.ntfs_discovery.volume_scanner import NTFSVolumeScanner
from disk.partition_table.scanner import PartitionTableScanner
from disk.models import PhysicalDisk
from disk.enumeration.windows import WindowsDiskEnumerator
from disk.scanning.mft_anchor_scan import MFTAnchor, MFTAnchorScanner
from ntfs.mft_parser import MFTRecord


class MemoryDisk:
    def __init__(self, data, disk_number=0, sector_size=512):
        self.data = data
        self.disk_number = disk_number
        self.bytes_per_sector = sector_size
        self.size = len(data)
        self.closed = False
        self.reads = []

    def read_at(self, offset, size):
        if offset < 0 or size < 0:
            raise ValueError("negative read")
        self.reads.append((offset, size))
        return self.data[offset:offset + size]

    def close(self):
        self.closed = True


def mbr_entry(table, slot, partition_type, first_lba, sectors):
    offset = 446 + slot * 16
    table[offset + 4] = partition_type
    struct.pack_into("<II", table, offset + 8, first_lba, sectors)


def mft_record(record_size=1024, lcn=8, clusters=2):
    raw = bytearray(record_size)
    raw[:4] = b"FILE"
    struct.pack_into("<HH", raw, 4, 0x30, record_size // 512 + 1)
    raw[0x30:0x36] = b"\xAA\xBB\0\0\0\0"
    usa_count = record_size // 512 + 1
    for index in range(1, usa_count):
        raw[index * 512 - 2:index * 512] = b"\xAA\xBB"
    attr_offset = 0x38
    struct.pack_into("<H", raw, 20, attr_offset)
    attr_length = 72
    struct.pack_into("<II", raw, attr_offset, 0x80, attr_length)
    raw[attr_offset + 8] = 1
    struct.pack_into("<H", raw, attr_offset + 32, 64)
    struct.pack_into("<Q", raw, attr_offset + 48, clusters * 4096)
    run = bytes([0x11, clusters, lcn, 0])
    raw[attr_offset + 64:attr_offset + 64 + len(run)] = run
    struct.pack_into("<I", raw, 24, attr_offset + attr_length + 4)
    struct.pack_into("<I", raw, attr_offset + attr_length, 0xFFFFFFFF)
    return bytes(raw)


def mft_root_record(record_size=1024, lcn=2, clusters=2):
    """Build a minimal, USA-protected $MFT record zero for scanner tests."""
    raw = bytearray(record_size)
    raw[:4] = b"FILE"
    usa_count = record_size // 512 + 1
    struct.pack_into("<HH", raw, 4, 0x30, usa_count)
    raw[0x30:0x32] = b"\xAA\xBB"
    for index in range(1, usa_count):
        raw[index * 512 - 2:index * 512] = b"\xAA\xBB"

    cursor = 0x38
    filename = bytearray(66 + len("$MFT") * 2)
    filename[64] = len("$MFT")
    filename[66:] = "$MFT".encode("utf-16le")
    filename_length = 24 + len(filename)
    struct.pack_into("<II", raw, cursor, 0x30, filename_length)
    struct.pack_into("<I", raw, cursor + 16, len(filename))
    struct.pack_into("<H", raw, cursor + 20, 24)
    raw[cursor + 24:cursor + filename_length] = filename
    cursor += filename_length

    data_length = 72
    struct.pack_into("<II", raw, cursor, 0x80, data_length)
    raw[cursor + 8] = 1
    struct.pack_into("<H", raw, cursor + 32, 64)
    allocated = clusters * 4096
    struct.pack_into("<QQ", raw, cursor + 40, allocated, allocated)
    run = bytes([0x11, clusters, lcn, 0])
    raw[cursor + 64:cursor + 64 + len(run)] = run
    cursor += data_length
    struct.pack_into("<I", raw, cursor, 0xFFFFFFFF)
    struct.pack_into("<H", raw, 20, 0x38)
    struct.pack_into("<I", raw, 24, cursor + 4)
    return bytes(raw)


def ntfs_disk(disk_number, partition_lba=4, partition_sectors=3000):
    data = bytearray(2 * 1024 * 1024)
    mbr = memoryview(data)[:512]
    mbr[510:512] = b"\x55\xAA"
    mbr_entry(mbr, 0, 0x07, partition_lba, partition_sectors)
    partition_offset = partition_lba * 512
    boot = memoryview(data)[partition_offset:partition_offset + 512]
    boot[3:11] = b"NTFS    "
    struct.pack_into("<H", boot, 11, 512)
    boot[13] = 8
    struct.pack_into("<Q", boot, 40, 2800)
    struct.pack_into("<Q", boot, 48, 4)
    struct.pack_into("<b", boot, 64, -10)
    boot[510:512] = b"\x55\xAA"
    mft_offset = partition_offset + 4 * 4096
    data[mft_offset:mft_offset + 1024] = mft_record()
    return MemoryDisk(data, disk_number)


class DiskInventoryTests(unittest.TestCase):
    def test_enumerator_parses_singleton_and_list_json_and_sorts_disks(self):
        class Result:
            returncode = 0
            stderr = ""
            stdout = '[{"number":2,"model":"Archive","size":2000},{"number":0,"model":"Boot","size":1000}]'

        enumerator = WindowsDiskEnumerator(runner=lambda *args, **kwargs: Result())
        with patch("disk.enumeration.windows.os.name", "nt"):
            disks = enumerator.list_disks()
        self.assertEqual([disk.number for disk in disks], [0, 2])
        self.assertEqual(disks[0].model, "Boot")

    def test_reads_mbr_partition_and_discovers_ntfs_mft_extent(self):
        disk = ntfs_disk(4)
        partitions = PartitionTableScanner(disk).partitions()
        self.assertEqual(len(partitions), 1)
        self.assertEqual(partitions[0].offset, 4 * 512)

        volumes = NTFSVolumeScanner(disk, 4).scan()

        self.assertEqual(len(volumes), 1)
        volume = volumes[0]
        self.assertEqual(volume.disk_number, 4)
        self.assertEqual(volume.partition_number, 1)
        self.assertEqual(volume.record_size, 1024)
        self.assertEqual(volume.mft_fragments, ((4 * 512 + 8 * 4096, 8, 0),))

    def test_catalog_discovery_keeps_disk_identity_for_multiple_drives(self):
        disks = {0: ntfs_disk(0), 3: ntfs_disk(3, partition_lba=8)}
        inventory = DiskInventory(
            enumerator=type("Enumerator", (), {"list_disks": lambda _self: [
                PhysicalDisk(number, f"Disk {number}", disk.size) for number, disk in disks.items()
            ]})(),
            disk_factory=lambda number: disks[number],
        )

        self.assertEqual([disk.number for disk in inventory.list_disks()], [0, 3])
        volume = inventory.list_ntfs_volumes(3)[0]
        self.assertEqual(volume.disk_number, 3)
        self.assertEqual(volume.partition_offset, 8 * 512)
        self.assertTrue(disks[3].closed)

    def test_gpt_partitions_are_read_from_entries_not_protective_mbr(self):
        data = bytearray(2 * 1024 * 1024)
        mbr = memoryview(data)[:512]
        mbr[510:512] = b"\x55\xAA"
        mbr_entry(mbr, 0, 0xEE, 1, len(data) // 512 - 1)
        header = memoryview(data)[512:1024]
        header[:8] = b"EFI PART"
        struct.pack_into("<I", header, 12, 92)
        struct.pack_into("<QII", header, 72, 2, 1, 128)
        table = memoryview(data)[1024:1152]
        table[:16] = b"{NTFS-GPT-GUID!!"[:16]
        struct.pack_into("<QQ", table, 32, 16, 100)
        table[56:72] = "Recovery".encode("utf-16le")

        partitions = PartitionTableScanner(MemoryDisk(data)).partitions()

        self.assertEqual(len(partitions), 1)
        self.assertEqual(partitions[0].table_type, "GPT")
        self.assertEqual(partitions[0].name, "Recovery")
        self.assertEqual(partitions[0].offset, 16 * 512)

    def test_rejects_partition_outside_physical_disk(self):
        data = bytearray(4096)
        data[510:512] = b"\x55\xAA"
        mbr_entry(memoryview(data), 0, 0x07, 4, 10)
        self.assertEqual(PartitionTableScanner(MemoryDisk(data)).partitions(), [])

    def test_deep_scan_finds_ntfs_volume_when_partition_table_is_missing(self):
        disk = ntfs_disk(2)
        disk.data[446:510] = bytes(64)

        checkpoints = []
        volumes = LostPartitionScanner(disk, 2, chunk_size=1024 * 1024).scan(
            candidate_callback=checkpoints.append,
        )

        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0].partition_number, 0)
        self.assertEqual(volumes[0].partition_offset, 4 * 512)
        self.assertEqual(volumes[0].disk_number, 2)
        self.assertEqual(checkpoints, [(volumes[0],)])

    def test_deep_scan_prioritizes_disk_tail_then_covers_the_rest_once(self):
        disk = ntfs_disk(2)
        scanner = LostPartitionScanner(
            disk,
            2,
            chunk_size=1024 * 1024,
            priority_tail_bytes=1024 * 1024,
        )

        ranges = scanner._scan_ranges()

        self.assertEqual(ranges[0].name, "Priority disk-tail scan")
        self.assertEqual(ranges[0].end, disk.size)
        self.assertEqual(ranges[1].name, "Full-disk scan")
        self.assertEqual(ranges[1].start, 0)
        self.assertEqual(ranges[0].start, ranges[1].end)

    def test_deep_scan_can_reconstruct_partition_start_from_backup_boot_sector(self):
        disk = ntfs_disk(2)
        partition_offset = 4 * 512
        boot = bytes(disk.data[partition_offset:partition_offset + 512])
        disk.data[partition_offset:partition_offset + 512] = bytes(512)
        disk.data[446:510] = bytes(64)
        backup_offset = partition_offset + 2800 * 512 - 512
        disk.data[backup_offset:backup_offset + 512] = boot

        checkpoints = []
        volumes = LostPartitionScanner(disk, 2, chunk_size=1024 * 1024).scan(
            candidate_callback=checkpoints.append,
        )

        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0].partition_offset, partition_offset)
        self.assertEqual(volumes[0].mft_offset, partition_offset + 4 * 4096)
        self.assertEqual(checkpoints, [(volumes[0],)])

    def test_mft_anchor_scan_finds_root_record_and_resolves_estimated_volume(self):
        partition_offset = 4096
        mft_offset = partition_offset + 2 * 4096
        data = bytearray(128 * 1024)
        data[mft_offset:mft_offset + 1024] = mft_root_record()
        disk = MemoryDisk(data, disk_number=7)

        # The record crosses a source chunk boundary to exercise overlap handling.
        anchor = MFTAnchorScanner(disk, scan_limit=len(data), chunk_size=12_800).scan()
        self.assertIsNotNone(anchor)
        self.assertEqual(anchor.physical_offset, mft_offset)
        self.assertEqual(anchor.record.name, "$MFT")
        self.assertEqual(anchor.record.allocated_size, 8192)
        self.assertEqual(len(disk.reads), 2)

        volume = MFTAnchorVolumeResolver(disk, 7).resolve(anchor)
        self.assertIsNotNone(volume)
        self.assertEqual(volume.partition_offset, partition_offset)
        self.assertEqual(volume.partition_size, len(data) - partition_offset)
        self.assertEqual(volume.cluster_size, 4096)
        self.assertTrue(volume.partition_size_is_estimated)
        self.assertEqual(volume.mft_fragments, ((mft_offset, 8, 0),))

    def test_mft_anchor_resolver_rejects_inconsistent_cluster_geometry(self):
        partition_offset = 4096
        mft_offset = partition_offset + 2 * 4096
        record = MFTRecord(mft_root_record(), 0, mft_offset=mft_offset)
        record.allocated_size += 512
        disk = MemoryDisk(bytes(128 * 1024))

        self.assertIsNone(MFTAnchorVolumeResolver(disk, 0).resolve(
            MFTAnchor(mft_offset, record)
        ))

    def test_deep_scan_uses_mft_anchor_before_boot_sector_full_scan(self):
        partition_offset = 4096
        mft_offset = partition_offset + 2 * 4096
        data = bytearray(128 * 1024)
        data[mft_offset:mft_offset + 1024] = mft_root_record()
        disk = MemoryDisk(data, disk_number=5)
        inventory = DiskInventory(disk_factory=lambda _number: disk)
        checkpoints = []

        volumes = inventory.deep_scan_ntfs_volumes(5, candidate_callback=checkpoints.append)

        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0].partition_offset, partition_offset)
        self.assertTrue(volumes[0].partition_size_is_estimated)
        self.assertEqual(checkpoints, [(volumes[0],)])
        self.assertTrue(disk.closed)


if __name__ == "__main__":
    unittest.main()
