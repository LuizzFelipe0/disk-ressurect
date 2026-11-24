from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone

from infrastructure.filesystems.ntfs.discovery.orphan_mft_carver import GhostMFTCarver
from modules.storage.entities import Partition
from infrastructure.filesystems.ntfs.discovery.volume_scanner import NTFSVolumeScanner
from infrastructure.partition_tables.scanner import PartitionTableScanner
from infrastructure.filesystems.ntfs.discovery.partition_scan import NTFSBootSectorParser
from infrastructure.filesystems.ntfs.allocation.cluster_allocation import ClusterAllocationEvidence, FreeClusterRangeCollector
from infrastructure.filesystems.ntfs.mft.parser import MFTRecord


@dataclass(frozen=True)
class ReadInterval:
    start: int
    end: int

    def to_dict(self):
        return {"start": self.start, "end": self.end, "sizeBytes": self.end - self.start}


@dataclass(frozen=True)
class ReadIssue:
    start: int
    end: int
    message: str

    def to_dict(self):
        return {"start": self.start, "end": self.end, "sizeBytes": self.end - self.start, "message": self.message}


@dataclass
class _NTFSVolumeResults:
    checks: list
    orphan_records_by_partition: dict
    content_carving_ranges_by_partition: dict
    content_carving_ranges_truncated_by_partition: dict
    uncertain_content_carving_ranges_by_partition: dict
    uncertain_content_carving_ranges_truncated_by_partition: dict
    orphan_references: dict
    snapshot_mismatch: bool = False


class DiskReadCoverage:
    """Tracks unique byte ranges successfully read and ranges with read errors."""

    def __init__(self, disk, chunk_size=8 * 1024 * 1024, scan_snapshot=None):
        self.disk = disk
        self.chunk_size = max(int(disk.bytes_per_sector), int(chunk_size))
        self.chunk_size -= self.chunk_size % int(disk.bytes_per_sector)
        self.intervals: list[tuple[int, int]] = []
        self.issues: list[ReadIssue] = []
        self.bytes_requested = 0
        self.bytes_read_total = 0
        self.historical_bytes_requested = 0
        self.historical_bytes_read = 0
        self.scanned_at = None
        self.cached_scan_used = False
        self.filesystem_signatures = ()
        self.gpt_header_offsets = ()
        self.ntfs_boot_offsets = ()
        if scan_snapshot is not None:
            self._restore_scan_snapshot(scan_snapshot)

    @property
    def size(self):
        return int(self.disk.size)

    @property
    def bytes_per_sector(self):
        return int(self.disk.bytes_per_sector)

    @property
    def bytes_read(self):
        return sum(end - start for start, end in self.intervals)

    def intervals_as_objects(self):
        return tuple(ReadInterval(start, end) for start, end in self.intervals)

    def read_at(self, offset, size, *, record_issue=True):
        offset, size = int(offset), int(size)
        if offset < 0 or size < 0 or offset + size > int(self.disk.size):
            raise ValueError("Validation read is outside the physical disk")
        self.bytes_requested += size
        try:
            data = self.disk.read_at(offset, size)
        except Exception as exc:
            if record_issue:
                self._add_issue(offset, offset + size, f"{type(exc).__name__}: {exc}")
            raise
        data = bytes(data)
        self.bytes_read_total += len(data)
        if len(data) > size:
            self._add_issue(offset, offset + size, "Reader returned more bytes than requested")
            raise OSError("Physical disk reader returned more bytes than requested")
        if data:
            self._add_interval(offset, offset + len(data))
        if len(data) != size:
            missing_start = offset + len(data)
            if record_issue:
                self._add_issue(missing_start, offset + size,
                    f"Short read: received {len(data)} of {size} bytes")
        return data

    def scan_full_disk(
        self, progress_callback=None, *, on_chunk=None, on_gap=None,
        combined_orphan_scan=False,
    ):
        disk_size = int(self.disk.size)
        sector_size = int(self.disk.bytes_per_sector)
        if sector_size <= 0:
            raise ValueError("Physical disk reported an invalid sector size")
        cursor = 0
        carry = b""
        ntfs_offsets = set()
        filesystem_signatures = {}
        gpt_header_offsets = set()
        marker = NTFSBootSectorParser.SIGNATURE
        other_markers = (
            (b"EFI PART", 0, "GPT"),
            (b"EXFAT   ", 3, "exFAT"),
            (b"FAT32   ", 82, "FAT32"),
            (b"FAT16   ", 54, "FAT16"),
            (b"FAT     ", 54, "FAT"),
        )

        def collect(data, data_offset, previous):
            if not data:
                return b""
            combined = previous + data
            combined_start = data_offset - len(previous)
            position = 0
            while True:
                found = combined.find(marker, position)
                if found < 0:
                    break
                signature_offset = combined_start + found
                boot_offset = signature_offset - 3
                if boot_offset >= 0 and boot_offset % sector_size == 0:
                    ntfs_offsets.add(boot_offset)
                position = found + 1
            for signature, signature_offset, filesystem in other_markers:
                position = 0
                while True:
                    found = combined.find(signature, position)
                    if found < 0:
                        break
                    boot_offset = combined_start + found - signature_offset
                    if boot_offset >= 0 and boot_offset % sector_size == 0:
                        if filesystem == "GPT":
                            gpt_header_offsets.add(boot_offset)
                        else:
                            filesystem_signatures[boot_offset] = filesystem
                    position = found + 1
            return combined[-(len(marker) + 2):]

        while cursor < disk_size:
            request = min(self.chunk_size, disk_size - cursor)
            request -= request % sector_size
            if request <= 0:
                request = disk_size - cursor
            try:
                data = self.read_at(cursor, request, record_issue=False)
            except (OSError, ValueError):
                data = b""
                carry = b""
            if data:
                carry = collect(data, cursor, carry)
                if on_chunk is not None:
                    on_chunk(cursor, data)
            if len(data) < request:
                remainder = cursor + len(data)
                while remainder < cursor + request:
                    recovery_size = min(sector_size, cursor + request - remainder)
                    try:
                        recovered = self.read_at(remainder, recovery_size)
                    except (OSError, ValueError):
                        carry = b""
                        if on_gap is not None:
                            on_gap(remainder, recovery_size)
                        remainder += recovery_size
                        continue
                    if recovered:
                        carry = collect(recovered, remainder, carry)
                        if on_chunk is not None:
                            on_chunk(remainder, recovered)
                    if len(recovered) != recovery_size:
                        carry = b""
                        if on_gap is not None:
                            on_gap(remainder + len(recovered), recovery_size - len(recovered))
                    remainder += recovery_size
                cursor += request
            else:
                cursor += request
            if progress_callback:
                label = "Reading disk and scanning deleted MFT records" if combined_orphan_scan \
                    else "Reading physical disk"
                progress_callback(cursor, disk_size, f"{label} | {cursor:,}/{disk_size:,} bytes")
        self.filesystem_signatures = tuple(
            {"offset": offset, "filesystem": filesystem, "validated": False}
            for offset, filesystem in sorted(filesystem_signatures.items())
        )
        self.gpt_header_offsets = tuple(sorted(gpt_header_offsets))
        return tuple(sorted(ntfs_offsets))

    def to_scan_snapshot(self, disk_info, ntfs_boot_offsets, scanned_at=None):
        """Return the compact, JSON-safe evidence from the sequential scan."""
        return {
            "version": 1,
            "scannedAt": scanned_at or datetime.now(timezone.utc).isoformat(),
            "identity": self._disk_identity(disk_info),
            "diskSize": int(self.disk.size),
            "bytesPerSector": self.bytes_per_sector,
            "intervals": [[start, end] for start, end in self.intervals],
            "issues": [[item.start, item.end, item.message] for item in self.issues],
            "bytesRequested": int(self.bytes_requested),
            "bytesReadTotal": int(self.bytes_read_total),
            "ntfsBootOffsets": [int(offset) for offset in ntfs_boot_offsets],
            "gptHeaderOffsets": [int(offset) for offset in self.gpt_header_offsets],
            "filesystemSignatures": [dict(item) for item in self.filesystem_signatures],
        }

    def _restore_scan_snapshot(self, snapshot):
        if (not isinstance(snapshot, dict) or snapshot.get("version") != 1
                or int(snapshot.get("diskSize", -1)) != int(self.disk.size)
                or int(snapshot.get("bytesPerSector", -1)) != self.bytes_per_sector):
            raise ValueError("Cached disk scan snapshot geometry is invalid")
        intervals = snapshot.get("intervals")
        issues = snapshot.get("issues")
        if (not isinstance(intervals, list) or len(intervals) > 100_000
                or not isinstance(issues, list) or len(issues) > 100_000):
            raise ValueError("Cached disk scan snapshot exceeds its entry limits")
        normalized_intervals = []
        previous_end = 0
        for item in intervals:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError("Cached disk scan interval is malformed")
            start, end = int(item[0]), int(item[1])
            if start < previous_end or end <= start or end > int(self.disk.size):
                raise ValueError("Cached disk scan interval is outside disk bounds")
            normalized_intervals.append((start, end))
            previous_end = end
        normalized_issues = []
        for item in issues:
            if not isinstance(item, list) or len(item) != 3:
                raise ValueError("Cached disk read issue is malformed")
            start, end = int(item[0]), int(item[1])
            if start < 0 or end <= start or end > int(self.disk.size):
                raise ValueError("Cached disk read issue is outside disk bounds")
            normalized_issues.append(ReadIssue(start, end, str(item[2])[:512]))
        ntfs_offsets = self._valid_offsets(snapshot.get("ntfsBootOffsets", []))
        gpt_offsets = self._valid_offsets(snapshot.get("gptHeaderOffsets", []))
        signatures = snapshot.get("filesystemSignatures", [])
        if not isinstance(signatures, list) or len(signatures) > 100_000:
            raise ValueError("Cached filesystem signature list is invalid")
        normalized_signatures = []
        for item in signatures:
            if not isinstance(item, dict):
                raise ValueError("Cached filesystem signature is malformed")
            offset = int(item.get("offset", -1))
            filesystem = str(item.get("filesystem", ""))
            if offset < 0 or offset >= int(self.disk.size) or not filesystem:
                raise ValueError("Cached filesystem signature is outside disk bounds")
            normalized_signatures.append({
                "offset": offset,
                "filesystem": filesystem[:32],
                "validated": False,
            })
        scanned_at = snapshot.get("scannedAt")
        if not isinstance(scanned_at, str):
            raise ValueError("Cached disk scan timestamp is missing")
        try:
            datetime.fromisoformat(scanned_at)
            bytes_requested = int(snapshot["bytesRequested"])
            bytes_read_total = int(snapshot["bytesReadTotal"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Cached disk scan counters are invalid") from exc
        if bytes_requested < 0 or bytes_read_total < 0:
            raise ValueError("Cached disk scan counters cannot be negative")
        if (normalized_intervals != [(0, int(self.disk.size))] or normalized_issues
                or bytes_requested < int(self.disk.size)
                or bytes_read_total < int(self.disk.size)):
            raise ValueError("Cached disk scan does not prove complete historical coverage")

        self.intervals = normalized_intervals
        self.issues = normalized_issues
        self.historical_bytes_requested = bytes_requested
        self.historical_bytes_read = bytes_read_total
        self.bytes_requested = bytes_requested
        self.bytes_read_total = bytes_read_total
        self.scanned_at = scanned_at
        self.cached_scan_used = True
        self.ntfs_boot_offsets = tuple(ntfs_offsets)
        self.gpt_header_offsets = tuple(gpt_offsets)
        self.filesystem_signatures = tuple(normalized_signatures)

    def _valid_offsets(self, offsets):
        if not isinstance(offsets, list) or len(offsets) > 1_000_000:
            raise ValueError("Cached disk scan offsets are invalid")
        normalized = []
        for value in offsets:
            offset = int(value)
            if offset < 0 or offset >= int(self.disk.size):
                raise ValueError("Cached disk scan offset is outside disk bounds")
            normalized.append(offset)
        return tuple(sorted(set(normalized)))

    @staticmethod
    def _disk_identity(disk_info):
        serial = str(getattr(disk_info, "serial_number", "") or "").strip().casefold()
        identity = {
            "model": str(getattr(disk_info, "model", "") or "").strip().casefold(),
            "sizeBytes": int(disk_info.size_bytes),
            "serialNumber": serial,
        }
        if not serial:
            identity["number"] = int(disk_info.number)
        return identity

    def _add_interval(self, start, end):
        if end <= start:
            return
        merged = []
        for current_start, current_end in sorted([*self.intervals, (start, end)]):
            if merged and current_start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], current_end))
            else:
                merged.append((current_start, current_end))
        self.intervals = merged

    def _add_issue(self, start, end, message):
        if end > start:
            self.issues.append(ReadIssue(start, end, str(message)))


class DiskValidationAuditor:
    """Audits full-disk read coverage, partition structures and NTFS metadata."""

    def __init__(self, disk_enumerator, disk_factory, chunk_size=8 * 1024 * 1024):
        self.disk_enumerator = disk_enumerator
        self.disk_factory = disk_factory
        self.chunk_size = chunk_size

    def validate(
        self, disk_number, progress_callback=None, retain_orphans_for_offset=None,
        orphan_scan_volume=None, content_carving_range_budget_bytes=None,
        validation_snapshot=None,
    ):
        physical_disk = self._find_physical_disk(disk_number)
        if physical_disk is None:
            raise ValueError(f"Physical disk {disk_number} is no longer available")

        disk = self.disk_factory(int(disk_number))
        can_reuse_snapshot = self._snapshot_matches_disk(validation_snapshot, physical_disk)
        try:
            coverage = self._create_coverage(
                disk, validation_snapshot if can_reuse_snapshot else None,
            )
            orphan_stream = self._create_orphan_stream(
                disk, orphan_scan_volume, retain_orphans_for_offset,
            )
            offsets = self._scan_disk(coverage, progress_callback, orphan_stream)
            partition_entries, partition_checks, volumes = self._discover_volumes(
                coverage, disk, int(disk_number), offsets,
            )
            volume_results = self._validate_volumes(
                coverage,
                disk,
                volumes,
                offsets,
                retain_orphans_for_offset,
                orphan_stream,
                progress_callback,
                validation_snapshot,
                content_carving_range_budget_bytes,
            )
            partitions = self._partition_report(
                coverage, partition_entries, volumes, offsets,
            )
            mbr_signature_found = self._mbr_signature_found(coverage)
            report = self._build_report(
                physical_disk, disk, coverage, partitions, partition_checks,
                volumes, volume_results, mbr_signature_found,
            )
            return self._attach_snapshot(
                report,
                physical_disk,
                coverage,
                offsets,
                partitions,
                volumes,
                volume_results,
                mbr_signature_found,
                validation_snapshot,
            )
        finally:
            disk.close()

    def validate_source(
        self, source, source_reader_factory, progress_callback=None,
        retain_orphans_for_offset=None, orphan_scan_volume=None,
        content_carving_range_budget_bytes=None,
    ):
        """Run the same full-disk audit against a registered non-physical source."""
        from modules.storage.entities import PhysicalDisk

        synthetic_disk = PhysicalDisk(
            -1, source.display_name, source.size_bytes, source.source_id,
        )

        class SourceEnumerator:
            @staticmethod
            def list_disks():
                return [synthetic_disk]

        return DiskValidationAuditor(
            SourceEnumerator(), lambda _number: source_reader_factory(source), self.chunk_size,
        ).validate(
            -1, progress_callback, retain_orphans_for_offset, orphan_scan_volume,
            content_carving_range_budget_bytes,
        )

    def _find_physical_disk(self, disk_number):
        disk_number = int(disk_number)
        return next((item for item in self.disk_enumerator.list_disks()
                     if item.number == disk_number), None)

    def _create_coverage(self, disk, validation_snapshot):
        try:
            return DiskReadCoverage(disk, self.chunk_size, scan_snapshot=validation_snapshot)
        except (TypeError, ValueError, OverflowError):
            return DiskReadCoverage(disk, self.chunk_size)

    @staticmethod
    def _create_orphan_stream(disk, volume, retain_offset):
        if volume is None or int(volume.partition_offset) != retain_offset:
            return None
        return GhostMFTCarver(disk).stream(volume)

    @staticmethod
    def _scan_disk(coverage, progress_callback, orphan_stream):
        if coverage.cached_scan_used:
            return coverage.ntfs_boot_offsets
        return coverage.scan_full_disk(
            progress_callback,
            on_chunk=orphan_stream.feed if orphan_stream is not None else None,
            on_gap=orphan_stream.gap if orphan_stream is not None else None,
            combined_orphan_scan=orphan_stream is not None,
        )

    def _discover_volumes(self, coverage, disk, disk_number, offsets):
        try:
            partition_entries = PartitionTableScanner(coverage).partitions()
        except (OSError, ValueError, struct.error):
            partition_entries = []

        partition_checks, gpt_partitions = self._discover_gpt_partitions(coverage)
        known_offsets = {entry.offset for entry in partition_entries}
        partition_entries.extend(
            entry for offset, entry in gpt_partitions.items() if offset not in known_offsets
        )
        volume_scanner = NTFSVolumeScanner(coverage, disk_number)
        volumes_by_offset = {}
        for partition in partition_entries:
            try:
                volume = volume_scanner._probe_partition(partition)
            except (OSError, ValueError, struct.error):
                volume = None
            if volume:
                volumes_by_offset[volume.partition_offset] = volume

        self._discover_signature_volumes(
            coverage, disk, offsets, volume_scanner, volumes_by_offset,
        )
        return partition_entries, partition_checks, volumes_by_offset

    def _discover_gpt_partitions(self, coverage):
        checks = []
        partitions = {}
        for header_offset in coverage.gpt_header_offsets:
            try:
                check, entries = self._validate_gpt_header(coverage, header_offset)
            except (OSError, ValueError, struct.error) as exc:
                check, entries = ({
                    "offset": header_offset,
                    "valid": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }, ())
            checks.append(check)
            for entry in entries:
                partitions.setdefault(entry.offset, entry)
        return checks, partitions

    @staticmethod
    def _discover_signature_volumes(coverage, disk, offsets, volume_scanner, volumes_by_offset):
        # Full-disk boot-sector hits include volumes whose partition table was lost.
        for boot_offset in offsets:
            try:
                boot = coverage.read_at(boot_offset, max(512, disk.bytes_per_sector))
                geometry = NTFSBootSectorParser.parse(boot)
                if geometry is None:
                    continue
                starts = {boot_offset}
                estimated_start = boot_offset + geometry.bytes_per_sector - geometry.volume_size
                if 0 <= estimated_start < boot_offset:
                    starts.add(estimated_start)
                for start in starts:
                    size = min(geometry.volume_size, int(disk.size) - start)
                    if size <= 0:
                        continue
                    candidate = Partition(
                        0, start, size, "NTFS signature", "Full-disk NTFS signature",
                    )
                    volume = volume_scanner._probe_partition(candidate)
                    if volume:
                        volumes_by_offset[volume.partition_offset] = volume
            except (OSError, ValueError, struct.error):
                continue

    def _validate_volumes(
        self, coverage, disk, volumes, offsets, retain_offset, orphan_stream,
        progress_callback, validation_snapshot, content_carving_range_budget_bytes,
    ):
        results = _NTFSVolumeResults(
            checks=[],
            orphan_records_by_partition={},
            content_carving_ranges_by_partition={},
            content_carving_ranges_truncated_by_partition={},
            uncertain_content_carving_ranges_by_partition={},
            uncertain_content_carving_ranges_truncated_by_partition={},
            orphan_references=dict(
                (validation_snapshot or {}).get("orphanRecordRefsByPartition", {})
            ),
        )
        for volume in sorted(volumes.values(), key=lambda item: item.partition_offset):
            try:
                self._validate_volume(
                    coverage, disk, volume, offsets, retain_offset, orphan_stream,
                    progress_callback, results, content_carving_range_budget_bytes,
                )
            except (OSError, ValueError, struct.error) as exc:
                results.checks.append({
                    "partitionOffset": int(volume.partition_offset),
                    "validationError": f"{type(exc).__name__}: {exc}",
                })
        return results

    def _validate_volume(
        self, coverage, disk, volume, offsets, retain_offset, orphan_stream,
        progress_callback, results, content_carving_range_budget_bytes,
    ):
        partition_offset = int(volume.partition_offset)
        retain_orphans = partition_offset == retain_offset
        cached_orphans = self._cached_orphans(
            coverage, disk, volume, retain_orphans, results,
        )
        checked = self._validate_ntfs_volume(
            coverage,
            volume,
            offsets,
            retain_orphans=retain_orphans,
            progress_callback=progress_callback,
            precomputed_orphans=(
                orphan_stream.finish() if retain_orphans and orphan_stream is not None
                else cached_orphans
            ),
            content_carving_range_budget_bytes=content_carving_range_budget_bytes,
        )
        if not retain_orphans:
            results.checks.append(checked)
            return

        check, orphan_records, carving_ranges, uncertain_ranges = checked
        key = str(partition_offset)
        results.orphan_references[key] = self._orphan_record_references(orphan_records)
        results.orphan_records_by_partition[partition_offset] = orphan_records
        results.content_carving_ranges_by_partition[partition_offset] = carving_ranges
        results.content_carving_ranges_truncated_by_partition[partition_offset] = bool(
            check.get("contentCarvingRangesTruncated", False)
        )
        results.uncertain_content_carving_ranges_by_partition[partition_offset] = {
            "bitmapUnobserved": uncertain_ranges["bitmapUnobserved"],
            "possiblyReused": uncertain_ranges["possiblyReused"],
        }
        results.uncertain_content_carving_ranges_truncated_by_partition[partition_offset] = {
            "bitmapUnobserved": uncertain_ranges["bitmapUnobservedTruncated"],
            "possiblyReused": uncertain_ranges["possiblyReusedTruncated"],
        }
        results.checks.append(check)

    def _cached_orphans(self, coverage, disk, volume, retain_orphans, results):
        if not retain_orphans or not coverage.cached_scan_used:
            return None
        key = str(int(volume.partition_offset))
        references = results.orphan_references.get(key)
        if references is None:
            return None
        cached_orphans = self._revalidate_cached_orphans(coverage, disk, volume, references)
        if cached_orphans is None:
            results.snapshot_mismatch = True
            return {}
        return cached_orphans

    @staticmethod
    def _partition_report(coverage, entries, volumes, offsets):
        filesystem_by_offset = {
            int(item["offset"]): item["filesystem"]
            for item in coverage.filesystem_signatures
        }
        filesystem_by_offset.update({offset: "NTFS" for offset in offsets})
        partitions = [
            {
                "partitionNumber": entry.number,
                "offset": entry.offset,
                "sizeBytes": entry.size_bytes,
                "tableType": str(entry.table_type),
                "name": entry.name,
                "filesystem": "NTFS" if entry.offset in volumes
                    else filesystem_by_offset.get(entry.offset, "unvalidated"),
                "source": "partition_table",
            }
            for entry in entries
        ]
        listed_offsets = {entry["offset"] for entry in partitions}
        for volume in volumes.values():
            if volume.partition_offset in listed_offsets:
                continue
            partitions.append({
                "partitionNumber": volume.partition_number,
                "offset": volume.partition_offset,
                "sizeBytes": volume.partition_size,
                "tableType": "discovered_ntfs",
                "name": volume.partition_name,
                "filesystem": "NTFS",
                "source": "full_disk_signature",
                "estimatedSize": bool(volume.partition_size_is_estimated),
            })
        return partitions

    @staticmethod
    def _mbr_signature_found(coverage):
        try:
            mbr_data = coverage.read_at(0, 512)
            return len(mbr_data) == 512 and mbr_data[510:512] == b"\x55\xAA"
        except (OSError, ValueError):
            return False

    @staticmethod
    def _build_report(
        physical_disk, disk, coverage, partitions, partition_checks, volumes,
        results, mbr_signature_found,
    ):
        unsupported_filesystems = {
            item["filesystem"] for item in coverage.filesystem_signatures
            if item["filesystem"] != "NTFS"
        }
        unsupported_filesystems.update(
            item["filesystem"] for item in partitions if item["filesystem"] != "NTFS"
        )
        return {
            "disk": physical_disk,
            "coverage": coverage,
            "partitions": partitions,
            "partition_table_checks": partition_checks,
            "mbr_signature_found": mbr_signature_found,
            "ntfs_checks": results.checks,
            "unsupported_filesystems": sorted(unsupported_filesystems),
            "filesystem_signatures": coverage.filesystem_signatures,
            "capacity_mismatch": int(disk.size) != int(physical_disk.size_bytes),
            "orphan_records_by_partition": results.orphan_records_by_partition,
            "content_carving_ranges_by_partition": results.content_carving_ranges_by_partition,
            "content_carving_ranges_truncated_by_partition":
                results.content_carving_ranges_truncated_by_partition,
            "uncertain_content_carving_ranges_by_partition":
                results.uncertain_content_carving_ranges_by_partition,
            "uncertain_content_carving_ranges_truncated_by_partition":
                results.uncertain_content_carving_ranges_truncated_by_partition,
            "validation_snapshot_used": coverage.cached_scan_used,
            "validation_snapshot_scanned_at": coverage.scanned_at,
        }

    def _attach_snapshot(
        self, report, physical_disk, coverage, offsets, partitions, volumes,
        results, mbr_signature_found, validation_snapshot,
    ):
        if coverage.cached_scan_used:
            return self._attach_cached_snapshot(
                report, coverage, partitions, volumes, results,
                mbr_signature_found, validation_snapshot,
            )
        if coverage.bytes_read == int(physical_disk.size_bytes) and not coverage.issues:
            snapshot = coverage.to_scan_snapshot(physical_disk, offsets)
            snapshot.update(self._snapshot_metadata(
                partitions, volumes, results.checks, mbr_signature_found,
            ))
            snapshot["orphanRecordRefsByPartition"] = results.orphan_references
            report["validation_scan_snapshot"] = snapshot
        report["validation_snapshot_mismatch"] = False
        return report

    def _attach_cached_snapshot(
        self, report, coverage, partitions, volumes, results,
        mbr_signature_found, validation_snapshot,
    ):
        metadata_matches = self._snapshot_metadata_matches(
            validation_snapshot, partitions, volumes, results.checks, mbr_signature_found,
        )
        old_issues = len((validation_snapshot or {}).get("issues", ()))
        mismatch = results.snapshot_mismatch or not metadata_matches or len(coverage.issues) > old_issues
        report["validation_snapshot_mismatch"] = mismatch
        if not mismatch:
            report["validation_scan_snapshot"] = dict(validation_snapshot)
            report["validation_scan_snapshot"]["orphanRecordRefsByPartition"] = (
                results.orphan_references
            )
        return report

    @staticmethod
    def _snapshot_matches_disk(snapshot, disk_info):
        if not isinstance(snapshot, dict) or snapshot.get("version") != 1:
            return False
        if snapshot.get("identity") != DiskReadCoverage._disk_identity(disk_info):
            return False
        try:
            scanned_at = datetime.fromisoformat(snapshot["scannedAt"])
            age_seconds = (datetime.now(timezone.utc) - scanned_at.astimezone(timezone.utc)).total_seconds()
            return (0 <= age_seconds <= 24 * 60 * 60
                    and int(snapshot["diskSize"]) == int(disk_info.size_bytes)
                    and int(snapshot["bytesPerSector"]) in (512, 1024, 2048, 4096))
        except (KeyError, TypeError, ValueError):
            return False

    @staticmethod
    def _orphan_record_references(records):
        references = []
        for record in records.values():
            offset = getattr(record, "mft_offset", None)
            if offset is None:
                return []
            references.append({
                "offset": int(offset),
                "recordIndex": int(record.index),
                "recordSize": int(record.record_size),
                "sha256": hashlib.sha256(bytes(record.raw_data)).hexdigest(),
            })
        references.sort(key=lambda item: item["offset"])
        return references

    @staticmethod
    def _revalidate_cached_orphans(reader, disk, volume, references):
        if not isinstance(references, list) or len(references) > 100_000:
            return None
        volume_start = int(volume.partition_offset)
        volume_end = volume_start + int(volume.partition_size)
        unmapped_ranges = GhostMFTCarver._unmapped_ranges(
            volume, volume_start, volume_end, int(volume.record_size), 512,
        )
        restored = {}
        seen_offsets = set()
        try:
            for item in references:
                if not isinstance(item, dict):
                    return None
                offset = int(item["offset"])
                record_size = int(item["recordSize"])
                record_index = int(item["recordIndex"])
                digest = str(item["sha256"])
                if (record_size != int(volume.record_size) or record_index != -(offset + 1)
                        or len(digest) != 64 or offset in seen_offsets
                        or not any(start <= offset and offset + record_size <= end
                                   for start, end in unmapped_ranges)):
                    return None
                raw = reader.read_at(offset, record_size)
                if len(raw) != record_size:
                    return None
                record = MFTRecord(raw, record_index, disk, offset, record_size)
                if (not record.is_valid
                        or hashlib.sha256(bytes(record.raw_data)).hexdigest() != digest
                        or not GhostMFTCarver._is_recoverable(
                            record, None, int(volume.cluster_size), volume_start, volume_end,
                        )):
                    return None
                restored[record_index] = record
                seen_offsets.add(offset)
        except (KeyError, TypeError, ValueError, OSError, OverflowError):
            return None
        return restored

    @staticmethod
    def _snapshot_metadata(partitions, volumes, ntfs_checks, mbr_signature_found):
        partition_manifest = sorted([
            int(item["offset"]), int(item["sizeBytes"]), str(item["tableType"]),
            str(item["filesystem"]), str(item["name"]),
        ] for item in partitions)
        volume_manifest = sorted([
            int(item.partition_offset), int(item.partition_size), int(item.bytes_per_sector),
            int(item.cluster_size), int(item.record_size), int(item.mft_offset),
            int(item.mft_size), [list(int(value) for value in fragment)
                                 for fragment in item.mft_fragments],
        ] for item in volumes.values())
        metadata = {
            "mbrSignatureFound": bool(mbr_signature_found),
            "partitions": partition_manifest,
            "volumes": volume_manifest,
            "ntfsChecks": [{
                key: check.get(key)
                for key in (
                    "partitionOffset", "partitionSizeBytes", "primaryAndBackupBootMatch",
                    "mftRecordZeroValid", "mftMirrorMatchesFirstRecords", "mftMirrorOffset",
                    "mftRecords", "mftBytesRead", "mftReadComplete", "mftSha256",
                    "bitmapRecordValid", "expectedBitmapBytes", "bitmapSha256",
                    "bitmapAllocation", "orphanedFileRecordCount",
                )
            } for check in ntfs_checks],
        }
        encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return {
            "partitionManifest": partition_manifest,
            "volumeManifest": volume_manifest,
            "metadataFingerprint": hashlib.sha256(encoded).hexdigest(),
        }

    @staticmethod
    def _snapshot_metadata_matches(snapshot, partitions, volumes, ntfs_checks, mbr_signature_found):
        current = DiskValidationAuditor._snapshot_metadata(
            partitions, volumes, ntfs_checks, mbr_signature_found,
        )
        return all(snapshot.get(key) == value for key, value in current.items())

    @staticmethod
    def _validate_gpt_header(disk, offset):
        sector_size = int(disk.bytes_per_sector)
        header = disk.read_at(offset, sector_size)
        check = {"offset": offset, "signatureFound": header[:8] == b"EFI PART", "valid": False}
        if not check["signatureFound"] or len(header) < 92:
            check["error"] = "GPT header signature or minimum length is invalid"
            return check, ()
        header_size = struct.unpack_from("<I", header, 12)[0]
        stored_header_crc = struct.unpack_from("<I", header, 16)[0]
        if not 92 <= header_size <= sector_size:
            check["error"] = "GPT header size is outside the logical sector"
            return check, ()
        header_copy = bytearray(header[:header_size])
        header_copy[16:20] = bytes(4)
        header_crc_valid = zlib.crc32(header_copy) & 0xFFFFFFFF == stored_header_crc
        current_lba = struct.unpack_from("<Q", header, 24)[0]
        backup_lba = struct.unpack_from("<Q", header, 32)[0]
        first_usable_lba, last_usable_lba = struct.unpack_from("<QQ", header, 40)
        entries_lba = struct.unpack_from("<Q", header, 72)[0]
        entry_count, entry_size = struct.unpack_from("<II", header, 80)
        stored_entries_crc = struct.unpack_from("<I", header, 88)[0]
        table_size = entry_count * entry_size
        table_offset = entries_lba * sector_size
        header_lbas_valid = (
            current_lba == offset // sector_size
            and backup_lba < int(disk.size) // sector_size
            and first_usable_lba <= last_usable_lba < int(disk.size) // sector_size
        )
        table_bounds_valid = (
            0 < entry_count <= 4096 and 128 <= entry_size <= 4096
            and table_offset <= int(disk.size) and table_size <= int(disk.size) - table_offset
        )
        entries = ()
        entries_crc_valid = False
        if table_bounds_valid:
            raw_table = disk.read_at(table_offset, table_size)
            entries_crc_valid = len(raw_table) == table_size and (zlib.crc32(raw_table) & 0xFFFFFFFF) == stored_entries_crc
            if entries_crc_valid:
                parsed = []
                for index in range(entry_count):
                    start = index * entry_size
                    entry = raw_table[start:start + entry_size]
                    if entry[:16] == bytes(16):
                        continue
                    first_lba, last_lba = struct.unpack_from("<QQ", entry, 32)
                    if last_lba < first_lba:
                        continue
                    name = entry[56:min(entry_size, 128)].decode("utf-16le", errors="ignore").rstrip("\x00")
                    partition_offset = first_lba * sector_size
                    partition_size = (last_lba - first_lba + 1) * sector_size
                    if partition_offset >= 0 and partition_size > 0 and partition_offset + partition_size <= int(disk.size):
                        parsed.append(Partition(index + 1, partition_offset, partition_size, "GPT", name))
                entries = tuple(parsed)
        check.update({
            "currentLba": current_lba,
            "backupLba": backup_lba,
            "headerLbasValid": header_lbas_valid,
            "headerCrcValid": header_crc_valid,
            "entriesTableBoundsValid": table_bounds_valid,
            "entriesCrcValid": entries_crc_valid,
            "valid": header_crc_valid and header_lbas_valid and table_bounds_valid and entries_crc_valid,
        })
        return check, entries

    @staticmethod
    def _validate_ntfs_volume(
        disk, volume, boot_offsets, retain_orphans=False, progress_callback=None,
        precomputed_orphans=None, content_carving_range_budget_bytes=None,
    ):
        sector_size = int(volume.bytes_per_sector)
        cluster_size = int(volume.cluster_size)
        boot_offset = int(volume.partition_offset)
        primary_boot = disk.read_at(boot_offset, sector_size)
        boot_geometry = NTFSBootSectorParser.parse(primary_boot)
        checked_volume_size = boot_geometry.volume_size if boot_geometry else int(volume.partition_size)
        backup_offset = boot_offset + checked_volume_size - sector_size
        backup_boot = disk.read_at(backup_offset, sector_size) if backup_offset >= boot_offset else b""

        mft = disk.read_at(int(volume.mft_offset), int(volume.record_size))
        mft_record = MFTRecord(mft, 0, disk, int(volume.mft_offset), int(volume.record_size))
        mft_digest = hashlib.sha256()
        mirror_lcn = boot_geometry.mftmirr_lcn if boot_geometry else -1
        mirror_offset = boot_offset + mirror_lcn * cluster_size
        mirror_size = 4 * int(volume.record_size)
        primary_mft_prefix = disk.read_at(int(volume.mft_offset), mirror_size)
        mirror = disk.read_at(mirror_offset, mirror_size) if mirror_offset >= boot_offset else b""
        mirror_matches = bool(mirror and len(mirror) == len(primary_mft_prefix)
            and mirror == primary_mft_prefix)

        record_counts = {
            "valid": 0,
            "allocated": 0,
            "deleted": 0,
            "invalidFileRecords": 0,
            "metadataInconsistent": 0,
        }
        mft_bytes_read = 0
        for physical_offset, record_count, _base_index in volume.mft_fragments:
            records_per_batch = max(1, (4 * 1024 * 1024) // int(volume.record_size))
            cursor = 0
            while cursor < record_count:
                count = min(records_per_batch, record_count - cursor)
                request_size = count * int(volume.record_size)
                raw = disk.read_at(physical_offset + cursor * int(volume.record_size), request_size)
                if len(raw) != request_size:
                    break
                mft_bytes_read += len(raw)
                mft_digest.update(raw)
                for index in range(count):
                    begin = index * int(volume.record_size)
                    record_bytes = raw[begin:begin + int(volume.record_size)]
                    if record_bytes[:4] != b"FILE":
                        continue
                    record = MFTRecord(record_bytes, cursor + index, disk,
                        physical_offset + begin, int(volume.record_size))
                    if record.is_valid:
                        record_counts["valid"] += 1
                        record_counts["allocated" if record.is_allocated else "deleted"] += 1
                        if not record.is_metadata_consistent:
                            record_counts["metadataInconsistent"] += 1
                    else:
                        record_counts["invalidFileRecords"] += 1
                cursor += count

        def report_orphan_progress(completed, total):
            if progress_callback is not None:
                progress_callback(
                    completed,
                    total,
                    f"Searching deleted MFT records | {completed:,}/{total:,} bytes",
                )

        if precomputed_orphans is None:
            orphans = GhostMFTCarver(disk).hunt(
                volume,
                allowed_extensions=None,
                existing_records=(),
                progress_callback=report_orphan_progress if progress_callback is not None else None,
            )
        else:
            orphans = precomputed_orphans

        bitmap_record, bitmap_offset = DiskValidationAuditor._read_mft_record(
            disk, volume, mft_record, 6,
        )
        expected_bitmap_bytes = math.ceil(
            (checked_volume_size // cluster_size) / 8
        )
        cluster_count = checked_volume_size // cluster_size
        bitmap_runs_valid, bitmap_storage_clusters = DiskValidationAuditor._bitmap_storage_clusters(
            bitmap_record, cluster_size, cluster_count,
        )
        target_clusters = set()
        for physical_offset, record_count, _base_index in volume.mft_fragments:
            first_cluster = (int(physical_offset) - boot_offset) // cluster_size
            byte_count = int(record_count) * int(volume.record_size)
            target_clusters.update(range(first_cluster, first_cluster + math.ceil(byte_count / cluster_size)))
        if mirror_lcn >= 0:
            mirror_cluster_count = math.ceil((4 * int(volume.record_size)) / cluster_size)
            target_clusters.update(range(mirror_lcn, mirror_lcn + mirror_cluster_count))
        target_clusters.update(bitmap_storage_clusters)
        bitmap_stats = DiskValidationAuditor._scan_bitmap(
            disk, volume, bitmap_record if bitmap_runs_valid else None,
            expected_bitmap_bytes, cluster_count, target_clusters,
            orphan_records=orphans,
            collect_carving_ranges=retain_orphans,
            carving_range_max_bytes=content_carving_range_budget_bytes,
        )
        for item in bitmap_stats.get("orphanDataAllocation", ()):
            record = orphans.get(int(item["recordId"]))
            if record is not None:
                record.cluster_allocation_evidence = item
        content_carving_ranges = bitmap_stats.pop("_contentCarvingRanges", ())
        carving_ranges_truncated = bool(bitmap_stats.pop("_contentCarvingRangesTruncated", False))
        uncertain_ranges = bitmap_stats.pop("_uncertainContentCarvingRanges", {
            "bitmapUnobserved": (), "possiblyReused": (),
            "bitmapUnobservedTruncated": False, "possiblyReusedTruncated": False,
        })
        bitmap_valid = bool(bitmap_runs_valid and bitmap_record and bitmap_record.is_valid
            and bitmap_record.name == "$Bitmap" and bitmap_record.data_is_complete
            and bitmap_record.file_size == expected_bitmap_bytes
            and bitmap_stats["bytesRead"] == expected_bitmap_bytes
            and all(bitmap_stats["systemClustersAllocated"].values()))
        # Content carving is restricted to ranges proved free by a complete,
        # structurally valid bitmap; partial maps are evidence only.
        content_carving_ranges = DiskValidationAuditor._trusted_content_carving_ranges(
            bitmap_valid, content_carving_ranges,
        )
        if not bitmap_valid:
            carving_ranges_truncated = False

        check = {
            "partitionOffset": boot_offset,
            "partitionSizeBytes": int(volume.partition_size),
            "partitionEndEstimated": bool(volume.partition_size_is_estimated),
            "primaryAndBackupBootMatch": bool(backup_boot and primary_boot == backup_boot),
            "backupBootFoundInFullScan": backup_offset in boot_offsets,
            "mftRecordZeroValid": bool(mft_record.is_valid and mft_record.name == "$MFT"),
            "mftMirrorMatchesFirstRecords": mirror_matches,
            "mftMirrorOffset": mirror_offset,
            "mftRecords": record_counts,
            "mftBytesRead": mft_bytes_read,
            "mftSha256": mft_digest.hexdigest(),
            "mftReadComplete": mft_bytes_read >= int(volume.mft_size),
            "bitmapRecordValid": bitmap_valid,
            "bitmapRecordOffset": bitmap_offset,
            "expectedBitmapBytes": expected_bitmap_bytes,
            "bitmapAllocation": bitmap_stats,
            "contentCarvingRangesTruncated": carving_ranges_truncated,
            "contentCarvingRangeCapBytes": int(content_carving_range_budget_bytes
                if content_carving_range_budget_bytes is not None
                else FreeClusterRangeCollector.DEFAULT_MAX_BYTES),
            "orphanedFileRecordCount": len(orphans),
        }
        return (check, orphans, content_carving_ranges, uncertain_ranges) if retain_orphans else check

    @staticmethod
    def _scan_bitmap(
        disk, volume, bitmap_record, expected_bytes, cluster_count, target_clusters,
        orphan_records=None, collect_carving_ranges=False, carving_range_max_bytes=None,
    ):
        selected = {cluster for cluster in target_clusters if 0 <= cluster < cluster_count}
        selected_ordered = sorted(selected)
        observed = {}
        allocated = 0
        bytes_read = 0
        bitmap_digest = hashlib.sha256()
        orphan_evidence = ClusterAllocationEvidence(orphan_records, cluster_count)
        free_range_collector = FreeClusterRangeCollector(
            int(volume.partition_offset), int(volume.cluster_size), cluster_count,
            max_bytes=(FreeClusterRangeCollector.DEFAULT_MAX_BYTES
                if carving_range_max_bytes is None else int(carving_range_max_bytes)),
        ) if collect_carving_ranges else None
        remaining = int(getattr(bitmap_record, "file_size", 0)) if bitmap_record else 0
        if bitmap_record and bitmap_record.resident_data is not None:
            chunks = (bytes(bitmap_record.resident_data),)
        elif bitmap_record and bitmap_record.data_runs:
            def read_runs():
                nonlocal remaining
                for lcn, cluster_total in bitmap_record.data_runs:
                    run_remaining = min(int(cluster_total) * int(volume.cluster_size), remaining)
                    run_offset = 0
                    while run_remaining:
                        size = min(4 * 1024 * 1024, run_remaining)
                        if lcn is None:
                            data = bytes(size)
                        else:
                            offset = (int(volume.partition_offset) + int(lcn) * int(volume.cluster_size)
                                + run_offset)
                            data = disk.read_at(offset, size)
                            if len(data) != size:
                                return
                        yield data
                        run_remaining -= size
                        run_offset += size
                        remaining -= size
                    if remaining <= 0:
                        break
            chunks = read_runs()
        else:
            chunks = ()

        bitmap_byte_offset = 0
        target_index = 0
        for chunk in chunks:
            if bytes_read >= expected_bytes:
                break
            chunk = bytes(chunk[:expected_bytes - bytes_read])
            bitmap_digest.update(chunk)
            orphan_evidence.consume(chunk, bytes_read)
            if free_range_collector is not None:
                free_range_collector.consume(chunk, bytes_read)
            for index, value in enumerate(chunk):
                byte_offset = bitmap_byte_offset + index
                valid_bits = min(8, max(0, cluster_count - byte_offset * 8))
                if valid_bits <= 0:
                    break
                masked = value & ((1 << valid_bits) - 1)
                allocated += masked.bit_count()
                first_cluster = byte_offset * 8
                while (target_index < len(selected_ordered)
                        and selected_ordered[target_index] < first_cluster + valid_bits):
                    cluster = selected_ordered[target_index]
                    observed[cluster] = bool(masked & (1 << (cluster - first_cluster)))
                    target_index += 1
            bytes_read += len(chunk)
            bitmap_byte_offset += len(chunk)
        result = {
            "bytesRead": bytes_read,
            "expectedBytes": expected_bytes,
            "bitmapSha256": bitmap_digest.hexdigest(),
            "clusterCount": cluster_count,
            "allocatedClusters": allocated,
            "freeClusters": max(0, cluster_count - allocated),
            "systemClustersAllocated": {str(cluster): observed.get(cluster, False) for cluster in sorted(selected)},
            "orphanDataAllocation": orphan_evidence.to_dict(),
            "orphanDataAllocationInterpretation": (
                "Allocation bits are evidence only: an allocated cluster may have been reused, "
                "and bitmap metadata may be stale or inconsistent."
            ),
        }
        if free_range_collector is not None:
            carving = free_range_collector.finish()
            result["_contentCarvingRanges"] = carving["ranges"]
            result["_contentCarvingRangesTruncated"] = carving["truncated"]
            result["_contentCarvingRangeCapBytes"] = carving["rangeCapBytes"]
            result["_uncertainContentCarvingRanges"] = orphan_evidence.uncertain_content_ranges(
                int(volume.partition_offset), int(volume.cluster_size),
            )
        return result

    @staticmethod
    def _bitmap_storage_clusters(bitmap_record, cluster_size, cluster_count):
        """Validate $Bitmap's own runlist before reading or trusting its contents."""
        if bitmap_record is None or not getattr(bitmap_record, "is_valid", True):
            return False, ()
        if getattr(bitmap_record, "resident_data", None) is not None:
            return True, ()
        if cluster_size <= 0 or cluster_count <= 0:
            return False, ()
        runs = tuple(getattr(bitmap_record, "data_runs", ()))
        if not runs:
            return False, ()
        storage_clusters = []
        capacity = 0
        for lcn, cluster_total in runs:
            cluster_total = int(cluster_total)
            if lcn is None or cluster_total <= 0:
                return False, ()
            lcn = int(lcn)
            run_end = lcn + cluster_total
            if lcn < 0 or run_end > cluster_count:
                return False, ()
            capacity += cluster_total * int(cluster_size)
            if len(storage_clusters) + cluster_total > 1_000_000:
                return False, ()
            storage_clusters.extend(range(lcn, run_end))
        if capacity < int(getattr(bitmap_record, "file_size", 0)):
            return False, ()
        return True, tuple(storage_clusters)

    @staticmethod
    def _trusted_content_carving_ranges(bitmap_valid, ranges):
        return tuple(ranges) if bitmap_valid else ()

    @staticmethod
    def _read_mft_record(disk, volume, mft_record_zero, record_index):
        if not mft_record_zero.is_valid or not mft_record_zero.data_runs:
            return None, None
        target = int(record_index) * int(volume.record_size)
        position = 0
        for lcn, cluster_count in mft_record_zero.data_runs:
            run_size = int(cluster_count) * int(volume.cluster_size)
            if position <= target < position + run_size:
                if lcn is None:
                    return None, None
                physical_offset = (int(volume.partition_offset) + int(lcn) * int(volume.cluster_size)
                    + target - position)
                data = disk.read_at(physical_offset, int(volume.record_size))
                if len(data) != int(volume.record_size):
                    return None, physical_offset
                return MFTRecord(data, record_index, disk, physical_offset, int(volume.record_size)), physical_offset
            position += run_size
        return None, None
