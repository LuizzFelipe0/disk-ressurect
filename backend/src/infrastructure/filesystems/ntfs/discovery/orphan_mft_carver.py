from __future__ import annotations

import os
from typing import Callable, Iterable

from modules.disk.entities import NTFSVolume
from infrastructure.filesystems.ntfs.mft.parser import MFTRecord


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
        allowed_extensions: Iterable[str] | None,
        existing_records: Iterable[MFTRecord] = (),
        progress_callback: ProgressCallback | None = None,
        phase_callback: Callable[[str, int, int], None] | None = None,
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
        extensions = None if allowed_extensions is None else {
            str(value).casefold() for value in allowed_extensions
        }
        known_records = {
            bytes(record.raw_data)
            for record in existing_records
            if getattr(record, "is_valid", False)
        }
        found_records: dict[int, MFTRecord] = {}
        found_fingerprints = set(known_records)
        completed_bytes = 0
        if phase_callback is not None:
            phase_callback("orphans", 0, total_bytes)

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
                if phase_callback is not None:
                    phase_callback("orphans", completed_bytes, total_bytes)

        return found_records

    def stream(self, volume: NTFSVolume, *, allowed_extensions=None):
        """Create a collector that carves MFT records from an existing disk read."""
        return _GhostMFTStream(self, volume, allowed_extensions)

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
        if (not record.is_valid or not getattr(record, "is_metadata_consistent", True)
                or record.is_allocated or record.is_dir
                or not record.name or not record.data_is_complete or int(record.file_size) <= 0):
            return False
        if any(ord(character) < 32 for character in record.name):
            return False
        if extensions is not None and os.path.splitext(record.name)[1].casefold() not in extensions:
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


class _GhostMFTStream:
    """Consumes sequential read blocks without issuing another disk read."""

    def __init__(self, carver, volume, allowed_extensions):
        self.carver = carver
        self.start = int(volume.partition_offset)
        self.end = self.start + int(volume.partition_size)
        self.record_size = int(volume.record_size)
        self.alignment = 512
        self.cluster_size = int(volume.cluster_size)
        if (self.start < 0 or self.end <= self.start or self.end > int(carver.disk.size)
                or self.record_size < self.alignment or self.record_size % self.alignment
                or self.cluster_size <= 0):
            raise ValueError("Invalid volume bounds or NTFS record geometry for orphan MFT scan")
        self.ranges = carver._unmapped_ranges(
            volume, self.start, self.end, self.record_size, self.alignment,
        )
        self.extensions = None if allowed_extensions is None else {
            str(value).casefold() for value in allowed_extensions
        }
        self.fingerprints = set()
        self.records = {}
        self._range_index = 0
        self._carry = b""
        self._last_end = None
        self._last_consumed_end = None

    def feed(self, offset, data):
        """Consume one successfully read physical-disk segment in order."""
        offset = int(offset)
        data = bytes(data)
        if not data:
            return
        if self._last_end is not None and offset != self._last_end:
            self._carry = b""
        self._last_end = offset + len(data)
        segment_end = offset + len(data)
        while self._range_index < len(self.ranges):
            range_start, range_end = self.ranges[self._range_index]
            if range_end <= offset:
                self._range_index += 1
                self._carry = b""
                continue
            if range_start >= segment_end:
                break
            overlap_start = max(offset, range_start)
            overlap_end = min(segment_end, range_end)
            if overlap_start != offset or (
                    self._carry and overlap_start != self._last_consumed_end):
                self._carry = b""
            chunk = data[overlap_start - offset:overlap_end - offset]
            combined = self._carry + chunk
            buffer_start = overlap_start - len(self._carry)
            self.carver._collect_records(
                combined, buffer_start, range_start, range_end, self.start,
                self.record_size, self.alignment, self.cluster_size, self.end,
                self.extensions, self.fingerprints, self.records,
            )
            carry_size = min(self.record_size - 1, len(combined))
            self._carry = combined[-carry_size:] if carry_size else b""
            self._last_consumed_end = overlap_end
            if overlap_end >= range_end:
                self._range_index += 1
                self._carry = b""
            if overlap_end >= segment_end:
                break

    def gap(self, offset, size):
        """Break signature carry across an unreadable range."""
        if size > 0:
            self._carry = b""
            self._last_end = int(offset) + int(size)

    def finish(self):
        return self.records
