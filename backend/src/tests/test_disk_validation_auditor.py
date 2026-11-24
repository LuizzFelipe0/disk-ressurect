import os
import sys
import unittest
import struct
import zlib
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.disk.entities import NTFSVolume, PhysicalDisk
from infrastructure.validation.disk_auditor import DiskReadCoverage, DiskValidationAuditor
from infrastructure.disk.inventory import DiskInventory
from presentation.controller import RecoveryCommandHandler
from modules.disk.dto import DiskDto
from modules.validation.dto import DiskValidationDto, DiskValidationRequestDto
from modules.disk.service import DiskService
from modules.validation.service import ValidationService
from modules.deep_scan.service import DeepScanService
from infrastructure.persistence.deep_scan_repository import JsonDeepScanRepository
from infrastructure.filesystems.ntfs.mft.parser import MFTRecord
from infrastructure.filesystems.ntfs.allocation.cluster_allocation import ClusterAllocationEvidence, FreeClusterRangeCollector


def make_ntfs_record(name, *, resident_data=None, nonresident_runlist=None, nonresident_size=0):
    align_attribute = lambda length: (length + 7) & ~7
    record = bytearray(1024)
    record[:4] = b"FILE"
    struct.pack_into("<HH", record, 4, 0x30, 3)
    record[0x30:0x36] = b"\xAA\xBB\x00\x00\x00\x00"
    record[510:512] = b"\xAA\xBB"
    record[1022:1024] = b"\xAA\xBB"
    struct.pack_into("<HH", record, 20, 0x38, 1)
    cursor = 0x38
    encoded_name = name.encode("utf-16le")
    filename = bytearray(66 + len(encoded_name))
    filename[64] = len(name)
    filename[65] = 1
    filename[66:] = encoded_name
    filename_length = align_attribute(24 + len(filename))
    struct.pack_into("<II", record, cursor, 0x30, filename_length)
    struct.pack_into("<I", record, cursor + 16, len(filename))
    struct.pack_into("<H", record, cursor + 20, 24)
    record[cursor + 24:cursor + 24 + len(filename)] = filename
    cursor += filename_length
    if nonresident_runlist is not None:
        length = align_attribute(64 + len(nonresident_runlist))
        struct.pack_into("<II", record, cursor, 0x80, length)
        record[cursor + 8] = 1
        struct.pack_into("<H", record, cursor + 32, 64)
        struct.pack_into("<QQ", record, cursor + 40, nonresident_size, nonresident_size)
        record[cursor + 64:cursor + 64 + len(nonresident_runlist)] = nonresident_runlist
        cursor += length
    elif resident_data is not None:
        length = align_attribute(24 + len(resident_data))
        struct.pack_into("<II", record, cursor, 0x80, length)
        struct.pack_into("<I", record, cursor + 16, len(resident_data))
        struct.pack_into("<H", record, cursor + 20, 24)
        record[cursor + 24:cursor + 24 + len(resident_data)] = resident_data
        cursor += length
    struct.pack_into("<I", record, cursor, 0xFFFFFFFF)
    struct.pack_into("<HH", record, 4, 0x30, 3)
    struct.pack_into("<H", record, 20, 0x38)
    struct.pack_into("<H", record, 22, 1)
    struct.pack_into("<I", record, 24, cursor + 8)
    return bytes(record)


class FakeDisk:
    def __init__(self, data, failed_ranges=()):
        self.data = bytes(data)
        self.size = len(self.data)
        self.bytes_per_sector = 512
        self.failed_ranges = tuple(failed_ranges)
        self.closed = False
        self.reads = []

    def read_at(self, offset, size):
        self.reads.append((offset, size))
        if any(offset < end and offset + size > start for start, end in self.failed_ranges):
            return b""
        return self.data[offset:offset + size]

    def close(self):
        self.closed = True


class FakeEnumerator:
    def __init__(self, disks):
        self.disks = disks

    def list_disks(self):
        return self.disks


class FakeRepository:
    def load(self, _disk):
        return None


class DiskReadCoverageTests(unittest.TestCase):
    def test_uncertain_ranges_include_only_unobserved_tail_of_a_straddling_run(self):
        evidence = ClusterAllocationEvidence(
            {7: SimpleNamespace(data_runs=((4, 8),))}, cluster_count=32,
        )
        evidence.consume(b"\x10", 0)

        ranges = evidence.uncertain_content_ranges(1000, 512)

        self.assertEqual(ranges["bitmapUnobserved"], ((1000 + 8 * 512, 1000 + 12 * 512),))
        self.assertEqual(ranges["possiblyReused"], ((1000 + 4 * 512, 1000 + 12 * 512),))

    def test_merges_overlapping_reads_and_reports_unique_coverage(self):
        disk = FakeDisk(bytes(4096))
        coverage = DiskReadCoverage(disk, chunk_size=512)

        coverage.read_at(0, 1024)
        coverage.read_at(512, 1024)

        self.assertEqual(coverage.bytes_read, 1536)
        self.assertEqual(coverage.bytes_read_total, 2048)
        self.assertEqual(coverage.intervals, [(0, 1536)])

    def test_records_short_read_as_an_explicit_gap(self):
        disk = FakeDisk(bytes(4096), failed_ranges=((1024, 1536),))
        coverage = DiskReadCoverage(disk, chunk_size=1024)

        offsets = coverage.scan_full_disk()

        self.assertEqual(offsets, ())
        self.assertEqual(coverage.bytes_read, 3584)
        self.assertEqual([(issue.start, issue.end) for issue in coverage.issues], [(1024, 1536)])

    def test_free_cluster_ranges_merge_across_bitmap_chunks_and_respect_budget(self):
        collector = FreeClusterRangeCollector(
            volume_start=4096, cluster_size=512, cluster_count=32,
        )
        collector.consume(b"\x00", 0)
        collector.consume(b"\x01\x00", 1)

        result = collector.finish()

        self.assertEqual(result["ranges"], ((4096, 8192), (8704, 16384)))
        self.assertEqual(result["retainedBytes"], 11776)
        self.assertFalse(result["truncated"])

        limited = FreeClusterRangeCollector(
            volume_start=0, cluster_size=512, cluster_count=32, max_bytes=1024,
        )
        limited.consume(bytes(4), 0)
        limited_result = limited.finish()
        self.assertEqual(limited_result["ranges"], ((0, 1024),))
        self.assertTrue(limited_result["truncated"])

    def test_finds_ntfs_and_fat_boot_signatures_across_the_entire_disk(self):
        data = bytearray(4096)
        data[1027:1035] = b"NTFS    "
        data[2048 + 82:2048 + 90] = b"FAT32   "
        coverage = DiskReadCoverage(FakeDisk(data), chunk_size=1024)

        offsets = coverage.scan_full_disk()

        self.assertEqual(offsets, (1024,))
        self.assertEqual(coverage.filesystem_signatures, ({
            "offset": 2048, "filesystem": "FAT32", "validated": False,
        },))

    def test_bitmap_scan_counts_clusters_and_checks_system_cluster_bits(self):
        volume = SimpleNamespace(partition_offset=0, cluster_size=512)
        bitmap = SimpleNamespace(file_size=2, resident_data=b"\x25\x00", data_runs=())

        result = DiskValidationAuditor._scan_bitmap(
            FakeDisk(bytes(4096)), volume, bitmap, expected_bytes=2,
            cluster_count=16, target_clusters={0, 2, 3, 5},
        )

        self.assertEqual(result["allocatedClusters"], 3)
        self.assertEqual(result["freeClusters"], 13)
        self.assertEqual(result["systemClustersAllocated"], {"0": True, "2": True, "3": False, "5": True})

    def test_bitmap_scan_uses_requested_trusted_carving_range_budget(self):
        volume = SimpleNamespace(partition_offset=0, cluster_size=512)
        bitmap = SimpleNamespace(file_size=1, resident_data=b"\x00", data_runs=())

        result = DiskValidationAuditor._scan_bitmap(
            FakeDisk(bytes(4096)), volume, bitmap, expected_bytes=1,
            cluster_count=8, target_clusters=(), collect_carving_ranges=True,
            carving_range_max_bytes=1024,
        )

        self.assertEqual(result["_contentCarvingRanges"], ((0, 1024),))
        self.assertEqual(result["_contentCarvingRangeCapBytes"], 1024)
        self.assertTrue(result["_contentCarvingRangesTruncated"])

    def test_bitmap_scan_classifies_orphan_runs_without_rejecting_allocated_clusters(self):
        volume = SimpleNamespace(partition_offset=0, cluster_size=512)
        bitmap = SimpleNamespace(file_size=2, resident_data=b"\x25\x00", data_runs=())
        orphan = SimpleNamespace(data_runs=((2, 3), (None, 2)))

        result = DiskValidationAuditor._scan_bitmap(
            FakeDisk(bytes(4096)), volume, bitmap, expected_bytes=2,
            cluster_count=16, target_clusters=(), orphan_records={-123: orphan},
        )

        self.assertEqual(result["orphanDataAllocation"], [{
            "recordId": -123,
            "status": "mixed",
            "allocatedClusters": 1,
            "freeClusters": 2,
            "unknownClusters": 0,
            "sparseClusters": 2,
            "bitmapObservedClusters": 3,
        }])

    def test_bitmap_scan_marks_unread_or_out_of_range_orphan_clusters_unknown(self):
        volume = SimpleNamespace(partition_offset=0, cluster_size=512)
        bitmap = SimpleNamespace(file_size=1, resident_data=b"\x01", data_runs=())
        orphan = SimpleNamespace(data_runs=((0, 2), (15, 3)))

        result = DiskValidationAuditor._scan_bitmap(
            FakeDisk(bytes(4096)), volume, bitmap, expected_bytes=2,
            cluster_count=16, target_clusters=(), orphan_records={-7: orphan},
        )

        self.assertEqual(result["orphanDataAllocation"], [{
            "recordId": -7,
            "status": "partially_observed",
            "allocatedClusters": 1,
            "freeClusters": 1,
            "unknownClusters": 3,
            "sparseClusters": 0,
            "bitmapObservedClusters": 2,
        }])


class DiskValidationAuditorTests(unittest.TestCase):
    def test_bitmap_own_runs_must_be_inside_volume_and_cover_its_file_size(self):
        valid_record = SimpleNamespace(
            is_valid=True, resident_data=None, file_size=600, data_runs=((3, 2),),
        )
        invalid_record = SimpleNamespace(
            is_valid=True, resident_data=None, file_size=600, data_runs=((15, 2),),
        )

        valid, clusters = DiskValidationAuditor._bitmap_storage_clusters(
            valid_record, cluster_size=512, cluster_count=16,
        )
        invalid, invalid_clusters = DiskValidationAuditor._bitmap_storage_clusters(
            invalid_record, cluster_size=512, cluster_count=16,
        )

        self.assertTrue(valid)
        self.assertEqual(clusters, (3, 4))
        self.assertFalse(invalid)
        self.assertEqual(invalid_clusters, ())

    def test_unallocated_bitmap_storage_cluster_is_not_trusted_for_carving(self):
        volume = SimpleNamespace(partition_offset=0, cluster_size=512)
        bitmap_record = SimpleNamespace(
            is_valid=True, resident_data=None, file_size=2, data_runs=((3, 1),),
        )
        bitmap_valid, bitmap_storage_clusters = DiskValidationAuditor._bitmap_storage_clusters(
            bitmap_record, cluster_size=512, cluster_count=16,
        )
        bitmap_data = SimpleNamespace(file_size=2, resident_data=b"\x00\x00", data_runs=())
        bitmap_stats = DiskValidationAuditor._scan_bitmap(
            FakeDisk(bytes(4096)), volume, bitmap_data, expected_bytes=2,
            cluster_count=16, target_clusters=set(bitmap_storage_clusters),
            collect_carving_ranges=True,
        )

        self.assertTrue(bitmap_valid)
        self.assertEqual(bitmap_stats["systemClustersAllocated"], {"3": False})
        validated_map = all(bitmap_stats["systemClustersAllocated"].values())
        carving_ranges = DiskValidationAuditor._trusted_content_carving_ranges(
            validated_map, bitmap_stats["_contentCarvingRanges"],
        )
        self.assertEqual(carving_ranges, ())

    def test_inconsistent_mft_record_numbers_keep_the_audit_inconclusive(self):
        disk = PhysicalDisk(0, "Metadata test", 512, "metadata-test")
        report = {
            "disk": disk,
            "coverage": SimpleNamespace(bytes_read=512, bytes_requested=512,
                bytes_read_total=512, issues=(), intervals_as_objects=lambda: ()),
            "capacity_mismatch": False,
            "unsupported_filesystems": (),
            "ntfs_checks": ({
                "mftRecordZeroValid": True,
                "mftMirrorMatchesFirstRecords": True,
                "bitmapRecordValid": True,
                "primaryAndBackupBootMatch": True,
                "mftReadComplete": True,
                "mftRecords": {"metadataInconsistent": 1, "invalidFileRecords": 0},
                "orphanedFileRecordCount": 0,
            },),
            "partition_table_checks": ({"valid": True},),
            "mbr_signature_found": True,
            "partitions": (),
            "filesystem_signatures": (),
        }

        validation = DiskValidationDto.from_report(report).to_dict()
        summary = ValidationService.summary(report)

        self.assertEqual(validation["assessment"], "inconclusive")
        self.assertEqual(summary["inconsistentMftRecordCount"], 1)

    def test_audits_full_disk_and_returns_identity_and_partition_evidence(self):
        disk_info = PhysicalDisk(2, "Test disk", 4096, "serial-2")
        opened = []

        def disk_factory(_number):
            disk = FakeDisk(bytes(4096))
            opened.append(disk)
            return disk

        auditor = DiskValidationAuditor(FakeEnumerator([disk_info]), disk_factory, chunk_size=1024)
        report = auditor.validate(2)
        dto = DiskValidationDto.from_report(report).to_dict()

        self.assertTrue(issubclass(type(DiskValidationDto.from_report(report)), DiskDto))
        self.assertEqual(dto["serialNumber"], "serial-2")
        self.assertEqual(dto["sizeBytes"], 4096)
        self.assertEqual(dto["coverageStatus"], "complete")
        self.assertEqual(dto["bytesRead"], 4096)
        self.assertEqual(dto["readIntervals"], [{"start": 0, "end": 4096, "sizeBytes": 4096}])
        self.assertEqual(dto["assessment"], "inconclusive")
        self.assertIn("does not prove", dto["interpretation"])
        self.assertTrue(opened[0].closed)

    def test_reuses_cached_coverage_but_labels_it_historical_and_inconclusive(self):
        disk_info = PhysicalDisk(0, "Cache test", 4096, "cache-serial")
        opened = []

        def disk_factory(_number):
            disk = FakeDisk(bytes(4096))
            opened.append(disk)
            return disk

        inventory = DiskInventory(FakeEnumerator([disk_info]), disk_factory)
        repository = JsonDeepScanRepository()
        service = ValidationService(inventory, DiskService(inventory, repository), repository)
        first = service.validate_disk(0)
        first_read_count = len(opened[-1].reads)
        second = service.validate_disk(0)
        second_read_count = len(opened[-1].reads)
        forced = service.validate_disk(0, force_fresh=True)
        forced_read_count = len(opened[-1].reads)
        dto = DiskValidationDto.from_report(second).to_dict()

        self.assertFalse(first["validation_snapshot_used"])
        self.assertTrue(second["validation_snapshot_used"])
        self.assertFalse(forced["validation_snapshot_used"])
        self.assertLess(second_read_count, first_read_count)
        self.assertEqual(forced_read_count, first_read_count)
        self.assertEqual(dto["coverageStatus"], "cached_snapshot")
        self.assertEqual(dto["evidenceFreshness"], "cached_snapshot")
        self.assertEqual(dto["assessment"], "inconclusive")
        self.assertIn(first["validation_scan_snapshot"]["scannedAt"], dto["interpretation"])

    def test_partition_metadata_change_invalidates_snapshot_and_repeats_full_scan(self):
        disk_info = PhysicalDisk(0, "Cache test", 4096, "cache-serial")
        data = [bytes(4096)]
        opened = []

        def disk_factory(_number):
            disk = FakeDisk(data[0])
            opened.append(disk)
            return disk

        inventory = DiskInventory(FakeEnumerator([disk_info]), disk_factory)
        repository = JsonDeepScanRepository()
        service = ValidationService(inventory, DiskService(inventory, repository), repository)
        service.validate_disk(0)
        changed = bytearray(4096)
        changed[510:512] = b"\x55\xAA"
        data[0] = bytes(changed)

        report = service.validate_disk(0)

        self.assertFalse(report["validation_snapshot_used"])
        self.assertEqual(len(opened[-1].reads), 3)
        self.assertEqual(report["coverage"].bytes_read, len(data[0]))

    def test_incomplete_cached_scan_snapshot_is_rejected_and_read_again(self):
        disk_info = PhysicalDisk(0, "Cache test", 4096, "cache-serial")
        enumerator = FakeEnumerator([disk_info])
        fresh = DiskValidationAuditor(
            enumerator, lambda _number: FakeDisk(bytes(4096)), chunk_size=1024,
        ).validate(0)
        incomplete = dict(fresh["validation_scan_snapshot"])
        incomplete["intervals"] = [[0, 4095]]
        opened = []

        def disk_factory(_number):
            disk = FakeDisk(bytes(4096))
            opened.append(disk)
            return disk

        report = DiskValidationAuditor(
            enumerator, disk_factory, chunk_size=1024,
        ).validate(0, validation_snapshot=incomplete)

        self.assertFalse(report["validation_snapshot_used"])
        self.assertEqual(report["coverage"].bytes_read, 4096)
        self.assertEqual(opened[0].reads[0], (0, 1024))

    def test_cached_orphan_reference_rejects_changed_record_bytes(self):
        volume = NTFSVolume(
            0, 1, 0, 4096, 512, 512, 1024, 512, 1024, ((512, 1, 0),),
        )
        raw = bytearray(make_ntfs_record("orphan.jpg", resident_data=b"jpg"))
        struct.pack_into("<H", raw, 22, 0)
        data = bytearray(4096)
        data[1536:1536 + 1024] = raw
        disk = FakeDisk(data)
        record = MFTRecord(raw, -1537, disk, 1536, 1024)
        reference = DiskValidationAuditor._orphan_record_references({record.index: record})

        restored = DiskValidationAuditor._revalidate_cached_orphans(
            DiskReadCoverage(disk), disk, volume, reference,
        )
        data[1536 + 100] ^= 0xFF
        changed_disk = FakeDisk(data)
        rejected = DiskValidationAuditor._revalidate_cached_orphans(
            DiskReadCoverage(changed_disk), changed_disk, volume, reference,
        )

        self.assertEqual(tuple(restored), (record.index,))
        self.assertIsNone(rejected)

    def test_marks_a_disk_inconclusive_when_any_physical_range_cannot_be_read(self):
        disk_info = PhysicalDisk(0, "Unreadable disk", 4096, "")

        def disk_factory(_number):
            return FakeDisk(bytes(4096), failed_ranges=((1024, 1536),))

        report = DiskValidationAuditor(
            FakeEnumerator([disk_info]), disk_factory, chunk_size=1024,
        ).validate(0)
        dto = DiskValidationDto.from_report(report).to_dict()

        self.assertEqual(dto["coverageStatus"], "incomplete")
        self.assertEqual(dto["assessment"], "inconclusive")
        self.assertEqual(dto["readErrors"][0]["start"], 1024)
        self.assertEqual(dto["readErrors"][0]["end"], 1536)
        self.assertEqual(dto["bytesRead"], 3584)

    def test_rejects_unknown_or_negative_disk_numbers(self):
        self.assertEqual(DiskValidationRequestDto.from_payload({"diskNumber": "3"}).disk_number, 3)
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            DiskValidationRequestDto.from_payload({"diskNumber": -1})
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            DiskValidationRequestDto.from_payload({"diskNumber": True})

    def test_validates_gpt_header_and_partition_array_checksums(self):
        data = bytearray(4096)
        entry = bytearray(128)
        entry[:16] = bytes.fromhex("A2A0D0EBE5B9334487C068B6B72699C7")
        struct.pack_into("<QQ", entry, 32, 3, 4)
        data[2 * 512:2 * 512 + 128] = entry
        header = memoryview(data)[512:1024]
        header[:8] = b"EFI PART"
        struct.pack_into("<I", header, 12, 92)
        struct.pack_into("<QQ", header, 24, 1, 7)
        struct.pack_into("<QII", header, 72, 2, 1, 128)
        struct.pack_into("<I", header, 88, zlib.crc32(entry) & 0xFFFFFFFF)
        header_copy = bytearray(header[:92])
        header_copy[16:20] = bytes(4)
        struct.pack_into("<I", header, 16, zlib.crc32(header_copy) & 0xFFFFFFFF)
        coverage = DiskReadCoverage(FakeDisk(data))

        check, partitions = DiskValidationAuditor._validate_gpt_header(coverage, 512)

        self.assertTrue(check["valid"])
        self.assertEqual(len(partitions), 1)
        self.assertEqual(partitions[0].offset, 3 * 512)
        self.assertEqual(partitions[0].size_bytes, 2 * 512)

    def test_checks_ntfs_boot_backup_mft_mirror_and_bitmap_contents(self):
        data = bytearray(2 * 1024 * 1024)
        data[510:512] = b"\x55\xAA"
        data[450] = 0x07
        struct.pack_into("<II", data, 454, 4, 2800)
        start = 4 * 512
        boot = bytearray(512)
        boot[3:11] = b"NTFS    "
        struct.pack_into("<H", boot, 11, 512)
        boot[13] = 8
        struct.pack_into("<Q", boot, 40, 2800)
        struct.pack_into("<QQ", boot, 48, 4, 2)
        boot[64] = (-10) & 0xFF
        boot[510:512] = b"\x55\xAA"
        data[start:start + 512] = boot
        bitmap = bytearray(44)
        for cluster in (2, 4, 5, 6, 7):
            bitmap[cluster // 8] |= 1 << (cluster % 8)
        records = [bytes(1024) for _ in range(16)]
        records[0] = make_ntfs_record(
            "$MFT", nonresident_runlist=b"\x11\x04\x04\x00", nonresident_size=16384,
        )
        records[6] = make_ntfs_record("$Bitmap", resident_data=bytes(bitmap))
        mft_offset = start + 4 * 4096
        data[mft_offset:mft_offset + 16 * 1024] = b"".join(records)
        mirror_offset = start + 2 * 4096
        data[mirror_offset:mirror_offset + 4 * 1024] = b"".join(records[:4])
        orphan_offset = start + 10 * 4096
        orphan_record = bytearray(make_ntfs_record("orphan.jpg", resident_data=b"ok"))
        struct.pack_into("<H", orphan_record, 22, 0)
        data[orphan_offset:orphan_offset + 1024] = orphan_record
        backup_offset = start + 2800 * 512 - 512
        data[backup_offset:backup_offset + 512] = boot
        fake_disk = FakeDisk(data)
        disk_info = PhysicalDisk(0, "NTFS test", len(data), "ntfs-0")
        progress = []
        selected_volume = NTFSVolume(
            disk_number=0, partition_number=1, partition_offset=start,
            partition_size=2800 * 512, bytes_per_sector=512, cluster_size=4096,
            record_size=1024, mft_offset=mft_offset, mft_size=16 * 1024,
            mft_fragments=((mft_offset, 16, 0),),
        )

        report = DiskValidationAuditor(
            FakeEnumerator([disk_info]), lambda _number: fake_disk, chunk_size=64 * 1024,
        ).validate(0, lambda completed, total, message: progress.append(message),
            retain_orphans_for_offset=start, orphan_scan_volume=selected_volume)
        dto = DiskValidationDto.from_report(report).to_dict()

        self.assertEqual(len(dto["ntfsChecks"]), 1)
        check = dto["ntfsChecks"][0]
        self.assertTrue(check["primaryAndBackupBootMatch"])
        self.assertTrue(check["backupBootFoundInFullScan"])
        self.assertTrue(check["mftRecordZeroValid"])
        self.assertTrue(check["mftMirrorMatchesFirstRecords"])
        self.assertTrue(check["bitmapRecordValid"])
        self.assertIn(start, report["content_carving_ranges_by_partition"])
        self.assertTrue(report["content_carving_ranges_by_partition"][start])
        self.assertTrue(all(
            start <= range_start < range_end <= start + 2800 * 512
            for range_start, range_end in report["content_carving_ranges_by_partition"][start]
        ))
        self.assertEqual(check["bitmapAllocation"]["allocatedClusters"], 5)
        self.assertEqual(check["mftRecords"]["allocated"], 2)
        self.assertEqual(dto["assessment"], "inconclusive")
        self.assertIn(check["partitionOffset"], report["orphan_records_by_partition"],
            (start, check["partitionOffset"], report["orphan_records_by_partition"]))
        carved_orphans = report["orphan_records_by_partition"][check["partitionOffset"]]
        self.assertEqual([record.name for record in carved_orphans.values()], ["orphan.jpg"])
        self.assertTrue(any(message.startswith("Reading disk and scanning deleted MFT records")
            for message in progress))
        self.assertFalse(any(message.startswith("Searching deleted MFT records") for message in progress))

    def test_validate_disk_command_returns_audit_contract_and_progress(self):
        disk_info = PhysicalDisk(2, "Command test", 4096, "command-2")

        class Inventory:
            def validate_disk(self, disk_number, progress_callback):
                progress_callback(4096, 4096, "Disk read complete")
                return DiskValidationAuditor(
                    FakeEnumerator([disk_info]), lambda _number: FakeDisk(bytes(4096)),
                    chunk_size=1024,
                ).validate(disk_number)

        repository = FakeRepository()
        inventory = Inventory()
        disk_service = DiskService(inventory, repository)
        handler = RecoveryCommandHandler(
            disk_service,
            DeepScanService(inventory, disk_service, repository, repository),
            ValidationService(inventory, disk_service, repository),
            None,
            None,
            None,
        )
        events = []

        result = handler.dispatch("validate_disk", {"diskNumber": 2}, events.append)

        self.assertEqual(result["number"], 2)
        self.assertIn("partitionTableChecks", result)
        self.assertEqual(events[0]["payload"]["stage"], "disk-validation")


if __name__ == "__main__":
    unittest.main()
