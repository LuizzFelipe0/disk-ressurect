from __future__ import annotations

import os
from typing import Callable, Iterable

from disk.models import NTFSVolume
from ntfs.mft_parser import MFTRecord


ProgressCallback = Callable[[int, int], None]


class GhostMFTCarver:
    """Carve deleted MFT records outside the volume's mapped MFT extents."""

    SIGNATURE = b"FILE"
    DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024

    def __init__(self, disk, chunk_size=DEFAULT_CHUNK_SIZE):
        self.disk = disk
        self.chunk_size = max(512, int(chunk_size))

    def hunt(
        self,
        volume: NTFSVolume,
        *,
        allowed_extensions: Iterable[str],
        existing_records: Iterable[MFTRecord] = (),
        progress_callback: ProgressCallback | None = None,
    ) -> dict[int, MFTRecord]:
        start = int(volume.partition_offset)
        end = start + int(volume.partition_size)
        record_size = int(volume.record_size)
        sector_size = int(volume.bytes_per_sector)
        cluster_size = int(volume.cluster_size)
        # MFTRecord applies USA fixups on 512-byte units; scan that alignment
        # even on volumes whose reported logical sector size is larger.
        record_alignment = 512
        if (start < 0 or end <= start or end > int(self.disk.size)
                or sector_size not in (512, 1024, 2048, 4096)
                or record_size < record_alignment or record_size % record_alignment or cluster_size <= 0):
            raise ValueError("Invalid volume bounds or NTFS record geometry for orphan MFT scan")

        ranges = self._unmapped_ranges(volume, start, end, record_size, record_alignment)
        total_bytes = sum(range_end - range_start for range_start, range_end in ranges)
        extensions = {str(value).casefold() for value in allowed_extensions}
        known_records = {
            bytes(record.raw_data)
            for record in existing_records
            if getattr(record, "is_valid", False)
        }
        found_records: dict[int, MFTRecord] = {}
        found_fingerprints = set(known_records)
        completed_bytes = 0

        for range_start, range_end in ranges:
            carry = b""
            cursor = range_start
            while cursor < range_end:
                request_size = min(self.chunk_size, range_end - cursor)
                data = self.disk.read_at(cursor, request_size)
                if len(data) != request_size:
                    raise OSError(
                        f"Short orphan MFT scan read at {cursor:#x}: "
                        f"received {len(data)} of {request_size} bytes"
                    )

                combined = carry + data
                buffer_start = cursor - len(carry)
                self._collect_records(
                    combined,
                    buffer_start,
                    range_start,
                    range_end,
                    start,
                    record_size,
                    record_alignment,
                    cluster_size,
                    end,
                    extensions,
                    found_fingerprints,
                    found_records,
                )
                carry_size = min(record_size - 1, len(combined))
                carry = combined[-carry_size:] if carry_size else b""
                cursor += request_size
                completed_bytes += request_size
                if progress_callback is not None:
                    progress_callback(completed_bytes, total_bytes)

        return found_records

    @staticmethod
    def _unmapped_ranges(volume, volume_start, volume_end, record_size, alignment):
        extents = []
        for physical_offset, record_count, _base_index in volume.mft_fragments:
            extent_start = int(physical_offset)
            extent_end = extent_start + int(record_count) * record_size
            if (record_count <= 0 or extent_start < volume_start or extent_end > volume_end
                    or (extent_start - volume_start) % alignment):
                raise ValueError("MFT fragment is outside the selected volume or misaligned")
            extents.append((extent_start, extent_end))

        merged = []
        for extent_start, extent_end in sorted(extents):
            if merged and extent_start < merged[-1][1]:
                raise ValueError("MFT fragments overlap")
            if merged and extent_start == merged[-1][1]:
                merged[-1] = (merged[-1][0], extent_end)
            else:
                merged.append((extent_start, extent_end))

        ranges = []
        cursor = volume_start
        for extent_start, extent_end in merged:
            if cursor < extent_start:
                ranges.append((cursor, extent_start))
            cursor = extent_end
        if cursor < volume_end:
            ranges.append((cursor, volume_end))
        return ranges

    @classmethod
    def _collect_records(
        cls,
        data,
        buffer_start,
        range_start,
        range_end,
        volume_start,
        record_size,
        alignment,
        cluster_size,
        volume_end,
        extensions,
        fingerprints,
        records,
    ):
        pos = 0
        while True:
            pos = data.find(cls.SIGNATURE, pos)
            if pos < 0:
                return

            physical_offset = buffer_start + pos
            record_end = physical_offset + record_size
            aligned = (physical_offset - volume_start) % alignment == 0
            within_unmapped_range = range_start <= physical_offset and record_end <= range_end
            if aligned and within_unmapped_range and pos + record_size <= len(data):
                raw_record = data[pos:pos + record_size]
                # The physical offset gives every carved record a stable ID in a
                # disjoint namespace from the non-negative MFT record numbers.
                synthetic_id = -(physical_offset + 1)
                record = MFTRecord(raw_record, synthetic_id, mft_offset=physical_offset, record_size=record_size)
                if cls._is_recoverable(record, extensions, cluster_size, volume_start, volume_end):
                    fingerprint = bytes(record.raw_data)
                    if fingerprint not in fingerprints:
                        fingerprints.add(fingerprint)
                        records[synthetic_id] = record
            pos += len(cls.SIGNATURE)

    @staticmethod
    def _is_recoverable(record, extensions, cluster_size, volume_start, volume_end):
        if (not record.is_valid or record.is_allocated or record.is_dir
                or not record.name or not record.data_is_complete):
            return False
        if any(ord(character) < 32 for character in record.name):
            return False
        if os.path.splitext(record.name)[1].casefold() not in extensions:
            return False

        if record.resident_data is not None:
            return len(record.resident_data) == record.file_size
        if not record.data_runs:
            return False

        total_capacity = 0
        for lcn, cluster_count in record.data_runs:
            if cluster_count <= 0:
                return False
            run_capacity = int(cluster_count) * cluster_size
            total_capacity += run_capacity
            if lcn is not None:
                run_start = volume_start + int(lcn) * cluster_size
                if run_start < volume_start or run_start + run_capacity > volume_end:
                    return False
        return total_capacity >= int(record.file_size)
