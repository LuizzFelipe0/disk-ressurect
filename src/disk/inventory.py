"""Enumerate Windows physical disks and discover their NTFS partitions dynamically."""

from __future__ import annotations

import json
import os
import struct
import subprocess
from dataclasses import dataclass
from typing import Callable

from ntfs.mft_parser import MFTRecord
from disk.mft_anchor_scan import MFTAnchor, MFTAnchorScanner
from disk.partition_scan import (
    AlignedSignaturePipe,
    DiskChunkSource,
    DiskRange,
    NTFSBootSectorParser,
)


@dataclass(frozen=True)
class PhysicalDisk:
    number: int
    model: str
    size_bytes: int
    serial_number: str = ""

    @property
    def display_name(self):
        size_gib = self.size_bytes / (1024 ** 3)
        suffix = f" · {self.serial_number}" if self.serial_number else ""
        return f"Disk {self.number} · {self.model} · {size_gib:.1f} GB{suffix}"


@dataclass(frozen=True)
class PartitionEntry:
    number: int
    offset: int
    size_bytes: int
    table_type: str
    name: str = ""


@dataclass(frozen=True)
class NTFSVolume:
    disk_number: int
    partition_number: int
    partition_offset: int
    partition_size: int
    bytes_per_sector: int
    cluster_size: int
    record_size: int
    mft_offset: int
    mft_size: int
    mft_fragments: tuple[tuple[int, int, int], ...]
    partition_name: str = ""
    partition_size_is_estimated: bool = False

    def fragments_as_dicts(self):
        return [
            {"phys": physical_offset, "count": count, "base_idx": base_index}
            for physical_offset, count, base_index in self.mft_fragments
        ]

    @property
    def display_name(self):
        gib = self.partition_size / (1024 ** 3)
        name = f" · {self.partition_name}" if self.partition_name else ""
        if self.partition_number == 0:
            estimate = " · estimated end" if self.partition_size_is_estimated else ""
            return f"Lost NTFS candidate · {gib:.1f} GB{name}{estimate} · offset 0x{self.partition_offset:X}"
        return f"Partition {self.partition_number} · NTFS · {gib:.1f} GB{name} · offset 0x{self.partition_offset:X}"


class WindowsDiskEnumerator:
    """List physical disks using the Windows storage inventory provider."""

    POWERSHELL_COMMAND = (
        "$ErrorActionPreference='Stop'; "
        "Get-CimInstance Win32_DiskDrive | "
        "Select-Object @{Name='number';Expression={$_.Index}}, "
        "@{Name='model';Expression={$_.Model}}, "
        "@{Name='size';Expression={[Int64]$_.Size}}, "
        "@{Name='serial';Expression={$_.SerialNumber}} | "
        "ConvertTo-Json -Compress"
    )

    def __init__(self, runner: Callable = subprocess.run):
        self.runner = runner

    def list_disks(self):
        if os.name != "nt":
            raise OSError("Physical disk inventory is currently supported on Windows only")
        command = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", self.POWERSHELL_COMMAND]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = self.runner(command, capture_output=True, text=True, timeout=30, creationflags=flags)
        if result.returncode:
            detail = result.stderr.strip() or "Windows storage inventory query failed"
            raise OSError(detail)
        payload = json.loads(result.stdout or "[]")
        if isinstance(payload, dict):
            payload = [payload]
        disks = []
        for item in payload:
            try:
                number = int(item["number"])
                size = int(item["size"])
            except (KeyError, TypeError, ValueError):
                continue
            if number < 0 or size <= 0:
                continue
            disks.append(PhysicalDisk(number, str(item.get("model") or "Unknown disk").strip(), size,
                                      str(item.get("serial") or "").strip()))
        return sorted(disks, key=lambda disk: disk.number)


class PartitionTableScanner:
    """Read MBR, extended MBR and GPT layouts from a physical disk."""

    MAX_GPT_ENTRIES = 4096
    MAX_EBR_ENTRIES = 128
    EXTENDED_MBR_TYPES = {0x05, 0x0F, 0x85}
    MBR_SECTOR_BYTES = 512

    def __init__(self, disk, sector_size=None):
        self.disk = disk
        self.sector_size = int(sector_size or disk.bytes_per_sector)
        if self.sector_size < self.MBR_SECTOR_BYTES:
            raise ValueError("Unsupported logical sector size")

    def partitions(self):
        mbr = self.disk.read_at(0, self.MBR_SECTOR_BYTES)
        if len(mbr) != self.MBR_SECTOR_BYTES or mbr[510:512] != b"\x55\xAA":
            return []
        entries = [self._mbr_entry(mbr, 446 + slot * 16, slot + 1) for slot in range(4)]
        if any(entry and entry.table_type == "GPT protective" for entry in entries):
            gpt = self._gpt_partitions()
            return gpt
        regular = [
            entry for entry in entries
            if entry and entry.table_type not in self.EXTENDED_MBR_TYPES
            and entry.offset < self.disk.size
            and entry.offset + entry.size_bytes <= self.disk.size
        ]
        extended = [entry for entry in entries if entry and entry.table_type in self.EXTENDED_MBR_TYPES]
        logical = []
        next_number = 5
        for container in extended:
            found = self._logical_partitions(container, next_number)
            logical.extend(found)
            next_number += len(found)
        result = regular + logical
        result = [
            entry for entry in result
            if entry.offset >= 0 and entry.size_bytes > 0
            and entry.offset + entry.size_bytes <= self.disk.size
        ]
        return sorted(result, key=lambda entry: (entry.offset, entry.number))

    def _mbr_entry(self, sector, offset, number):
        partition_type = sector[offset + 4]
        first_lba, sector_count = struct.unpack_from("<II", sector, offset + 8)
        if partition_type == 0 or sector_count == 0:
            return None
        name = f"MBR type 0x{partition_type:02X}"
        table_type = "GPT protective" if partition_type == 0xEE else partition_type
        return PartitionEntry(number, first_lba * self.sector_size,
                              sector_count * self.sector_size, table_type, name)

    def _logical_partitions(self, extended, first_number):
        base_lba = extended.offset // self.sector_size
        current_lba = base_lba
        result = []
        visited = set()
        for _ in range(self.MAX_EBR_ENTRIES):
            if current_lba in visited:
                break
            visited.add(current_lba)
            ebr = self.disk.read_at(current_lba * self.sector_size, self.MBR_SECTOR_BYTES)
            if len(ebr) != self.MBR_SECTOR_BYTES or ebr[510:512] != b"\x55\xAA":
                break
            data_entry = self._mbr_entry(ebr, 446, first_number + len(result))
            if data_entry and data_entry.table_type not in self.EXTENDED_MBR_TYPES:
                relative_lba, sector_count = struct.unpack_from("<II", ebr, 454)
                result.append(PartitionEntry(
                    first_number + len(result),
                    (current_lba + relative_lba) * self.sector_size,
                    sector_count * self.sector_size,
                    data_entry.table_type,
                    data_entry.name,
                ))
            link = self._mbr_entry(ebr, 462, 0)
            if link is None or link.table_type not in self.EXTENDED_MBR_TYPES:
                break
            relative_next = struct.unpack_from("<I", ebr, 470)[0]
            current_lba = base_lba + relative_next
        return result

    def _gpt_partitions(self):
        header = self.disk.read_at(self.sector_size, self.sector_size)
        if len(header) < 92 or header[:8] != b"EFI PART":
            return []
        header_size = struct.unpack_from("<I", header, 12)[0]
        if header_size < 92 or header_size > self.sector_size:
            return []
        entries_lba = struct.unpack_from("<Q", header, 72)[0]
        entry_count, entry_size = struct.unpack_from("<II", header, 80)
        if not 0 < entry_count <= self.MAX_GPT_ENTRIES or not 128 <= entry_size <= 4096:
            return []
        table_size = entry_count * entry_size
        table_offset = entries_lba * self.sector_size
        if table_offset > self.disk.size or table_size > self.disk.size - table_offset:
            return []
        table = self.disk.read_at(table_offset, table_size)
        if len(table) != table_size:
            return []
        result = []
        for index in range(entry_count):
            offset = index * entry_size
            entry = table[offset:offset + entry_size]
            if entry[:16] == bytes(16):
                continue
            first_lba, last_lba = struct.unpack_from("<QQ", entry, 32)
            if last_lba < first_lba:
                continue
            name = entry[56:min(entry_size, 128)].decode("utf-16le", errors="ignore").rstrip("\x00")
            partition = PartitionEntry(index + 1, first_lba * self.sector_size,
                                       (last_lba - first_lba + 1) * self.sector_size,
                                       "GPT", name)
            if partition.offset >= 0 and partition.size_bytes > 0 and partition.offset + partition.size_bytes <= self.disk.size:
                result.append(partition)
        return result


class NTFSVolumeScanner:
    """Find NTFS volumes and map their MFT runlists into physical disk extents."""

    def __init__(self, disk, disk_number, partition_scanner=None):
        self.disk = disk
        self.disk_number = int(disk_number)
        self.partition_scanner = partition_scanner or PartitionTableScanner(disk)

    def scan(self, progress_callback=None):
        partitions = self.partition_scanner.partitions()
        volumes = []
        total = len(partitions)
        for position, partition in enumerate(partitions, 1):
            if progress_callback:
                progress_callback(position - 1, total, f"Checking partition {partition.number}")
            volume = self._probe_partition(partition)
            if volume is not None:
                volumes.append(volume)
            if progress_callback:
                progress_callback(position, total, f"Checked partition {partition.number}")
        return volumes

    def _probe_partition(self, partition, boot_sector=None):
        boot = boot_sector or self.disk.read_at(partition.offset, max(512, self.disk.bytes_per_sector))
        geometry = NTFSBootSectorParser.parse(boot)
        if geometry is None or geometry.volume_size > partition.size_bytes:
            return None
        if partition.offset < 0 or partition.offset + geometry.volume_size > self.disk.size:
            return None
        mft_offset = partition.offset + geometry.mft_lcn * geometry.cluster_size
        raw_record = self.disk.read_at(mft_offset, geometry.record_size)
        if len(raw_record) != geometry.record_size:
            return None
        record = MFTRecord(raw_record, 0, self.disk, mft_offset, geometry.record_size)
        if not record.is_valid or not record.data_runs or record.file_size <= 0 or not record.data_is_complete:
            return None
        fragments = self._mft_fragments(partition, geometry.cluster_size, geometry.record_size, record)
        if not fragments:
            return None
        return NTFSVolume(
            disk_number=self.disk_number,
            partition_number=partition.number,
            partition_offset=partition.offset,
            partition_size=partition.size_bytes,
            bytes_per_sector=geometry.bytes_per_sector,
            cluster_size=geometry.cluster_size,
            record_size=geometry.record_size,
            mft_offset=mft_offset,
            mft_size=record.file_size,
            mft_fragments=tuple(fragments),
            partition_name=partition.name,
        )

    @staticmethod
    def _mft_fragments(partition, cluster_size, record_size, mft_record):
        records_needed = (mft_record.file_size + record_size - 1) // record_size
        base_index = 0
        fragments = []
        for lcn, cluster_count in mft_record.data_runs:
            byte_count = cluster_count * cluster_size
            record_count = byte_count // record_size
            if record_count <= 0:
                continue
            record_count = min(record_count, records_needed - base_index)
            if record_count <= 0:
                break
            if lcn is not None:
                fragments.append({
                    "phys": partition.offset + lcn * cluster_size,
                    "count": record_count,
                    "base_idx": base_index,
                })
            base_index += record_count
            if base_index >= records_needed:
                break
        if base_index < records_needed:
            return []
        return [
            (fragment["phys"], fragment["count"], fragment["base_idx"])
            for fragment in fragments
        ]


class DiskInventory:
    """Application-facing disk and NTFS volume inventory."""

    def __init__(self, enumerator=None, disk_factory=None):
        from disk.raw_disk import RawDisk

        self.enumerator = enumerator or WindowsDiskEnumerator()
        self.disk_factory = disk_factory or RawDisk

    def list_disks(self):
        return self.enumerator.list_disks()

    def list_ntfs_volumes(self, disk_number, progress_callback=None):
        disk = self.disk_factory(int(disk_number))
        try:
            return NTFSVolumeScanner(disk, int(disk_number)).scan(progress_callback)
        finally:
            disk.close()

    def deep_scan_ntfs_volumes(self, disk_number, progress_callback=None):
        disk = self.disk_factory(int(disk_number))
        try:
            # A surviving $MFT record zero can locate an NTFS volume even when
            # both partition-table entries and boot sectors were overwritten.
            anchor = MFTAnchorScanner(disk).scan(progress_callback)
            if anchor is not None:
                volume = MFTAnchorVolumeResolver(disk, int(disk_number)).resolve(anchor)
                if volume is not None:
                    return [volume]
            return LostPartitionScanner(disk, int(disk_number)).scan(progress_callback)
        finally:
            disk.close()


class MFTAnchorVolumeResolver:
    """Infer a volume start and MFT mapping from a validated $MFT record zero."""

    MIN_CLUSTER_SIZE = 512
    MAX_CLUSTER_SIZE = 2 * 1024 * 1024

    def __init__(self, disk, disk_number):
        self.disk = disk
        self.disk_number = int(disk_number)

    def resolve(self, anchor: MFTAnchor):
        record = anchor.record
        if (not record.is_valid or record.name != "$MFT" or not record.data_runs
                or not record.data_is_complete or record.file_size <= 0
                or record.allocated_size <= 0):
            return None
        physical_runs = [(lcn, count) for lcn, count in record.data_runs
                         if lcn is not None and count > 0]
        if len(physical_runs) != len(record.data_runs) or not physical_runs:
            return None
        total_clusters = sum(count for _, count in physical_runs)
        if total_clusters <= 0 or record.allocated_size % total_clusters:
            return None
        cluster_size = record.allocated_size // total_clusters
        sector_size = int(self.disk.bytes_per_sector)
        if (cluster_size < max(self.MIN_CLUSTER_SIZE, sector_size)
                or cluster_size > self.MAX_CLUSTER_SIZE
                or cluster_size & (cluster_size - 1)
                or cluster_size % sector_size):
            return None

        first_lcn = physical_runs[0][0]
        mft_offset = int(anchor.physical_offset)
        partition_offset = mft_offset - first_lcn * cluster_size
        if (partition_offset < 0 or partition_offset % cluster_size
                or partition_offset + record.file_size > self.disk.size):
            return None
        for lcn, count in physical_runs:
            run_start = partition_offset + lcn * cluster_size
            run_end = run_start + count * cluster_size
            if run_start < partition_offset or run_end > self.disk.size:
                return None
        if partition_offset + first_lcn * cluster_size != mft_offset:
            return None

        partition = PartitionEntry(0, partition_offset, self.disk.size - partition_offset,
                                   "MFT-derived", "$MFT anchor; partition end estimated")
        fragments = NTFSVolumeScanner._mft_fragments(
            partition, cluster_size, record.record_size, record
        )
        if not fragments or fragments[0][0] != mft_offset:
            return None
        return NTFSVolume(
            disk_number=self.disk_number,
            partition_number=0,
            partition_offset=partition_offset,
            partition_size=partition.size_bytes,
            bytes_per_sector=sector_size,
            cluster_size=cluster_size,
            record_size=record.record_size,
            mft_offset=mft_offset,
            mft_size=record.file_size,
            mft_fragments=tuple(fragments),
            partition_name=partition.name,
            partition_size_is_estimated=True,
        )


class LostPartitionScanner:
    """Find lost NTFS partition boot sectors without writing to the source disk."""

    DEFAULT_CHUNK_SIZE = 64 * 1024 * 1024
    PRIORITY_TAIL_BYTES = 1024 * 1024 * 1024

    def __init__(self, disk, disk_number, chunk_size=DEFAULT_CHUNK_SIZE,
                 priority_tail_bytes=PRIORITY_TAIL_BYTES):
        self.disk = disk
        self.disk_number = int(disk_number)
        self.chunk_source = DiskChunkSource(disk, chunk_size)
        self.priority_tail_bytes = max(0, int(priority_tail_bytes))
        self.signature_pipe = AlignedSignaturePipe(
            NTFSBootSectorParser.SIGNATURE,
            disk.bytes_per_sector,
            signature_offset=3,
        )
        self.volume_scanner = NTFSVolumeScanner(disk, disk_number)
        self.candidate_validator = LostPartitionCandidateValidator(
            disk,
            self.volume_scanner,
        )

    def scan(self, progress_callback=None):
        return self.scan_ranges(self._scan_ranges(), progress_callback)

    def scan_ranges(self, ranges, progress_callback=None):
        """Run the same discovery pipeline against selected byte ranges."""
        volumes_by_offset = {}
        chunks = self.chunk_source(ranges, progress_callback)
        for boot_offset in self.signature_pipe(chunks):
            for volume in self.candidate_validator(boot_offset):
                volumes_by_offset.setdefault(volume.partition_offset, volume)
        return sorted(volumes_by_offset.values(), key=lambda volume: volume.partition_offset)

    def _scan_ranges(self):
        disk_size = int(self.disk.size)
        tail_size = min(self.priority_tail_bytes, disk_size // 8)
        tail_size -= tail_size % int(self.disk.bytes_per_sector)
        tail_start = disk_size - tail_size
        ranges = []
        if tail_start < disk_size:
            ranges.append(DiskRange("Priority disk-tail scan", tail_start, disk_size))
        if tail_start > 0:
            ranges.append(DiskRange("Full-disk scan", 0, tail_start))
        return tuple(ranges)


class LostPartitionCandidateValidator:
    """Pipe that validates a boot signature by checking geometry and its MFT."""

    def __init__(self, disk, volume_scanner):
        self.disk = disk
        self.volume_scanner = volume_scanner

    def __call__(self, boot_offset):
        boot = self.disk.read_at(boot_offset, max(512, self.disk.bytes_per_sector))
        geometry = NTFSBootSectorParser.parse(boot)
        if geometry is None or boot_offset % geometry.bytes_per_sector:
            return ()
        starts = (boot_offset, boot_offset - geometry.volume_size + geometry.bytes_per_sector)
        found = []
        seen = set()
        for start in starts:
            if (start < 0 or start + geometry.volume_size > self.disk.size
                    or start in seen):
                continue
            seen.add(start)
            if boot_offset not in (start, start + geometry.volume_size - geometry.bytes_per_sector):
                continue
            partition = PartitionEntry(0, start, geometry.volume_size, "Lost NTFS", "Deep scan")
            volume = self.volume_scanner._probe_partition(partition, boot_sector=boot)
            if volume is not None:
                found.append(volume)
        return tuple(found)
